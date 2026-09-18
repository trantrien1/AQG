"""Writer của pipeline, dùng mô hình đã fine-tune (chỉ đọc chữ).

Writer gốc của Direct_PDF_Mode đọc ảnh từng trang PDF; Qwen3-8B/14B chỉ đọc
chữ, nên ở đây tài liệu được model thị giác chép thành chữ trước (xem
``mcqft.pipeline_ft prepare``) rồi đưa vào prompt đúng như tác vụ ``gen_ctx``
lúc huấn luyện.

Lớp ``FineTunedWriter`` thay thẳng ``orchestrator.writer``: cùng giao diện
``run(PdfWriteRequest) -> PdfWriteResponse``. Các tác nhân sau (phương án nhiễu,
giải độc lập, kiểm chứng, chấm, đóng gói) chạy nguyên trạng.

Hai nguồn câu nháp:

- ``drafts``: kho câu đã sinh sẵn theo mức độ (soạn trước bằng vLLM offline nên
  không phải giữ mô hình trong bộ nhớ cùng lúc với model thị giác);
- ``drafter``: gọi một máy chủ OpenAI-compatible đang phục vụ base + adapter.
"""
from __future__ import annotations

import re
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .metrics import parse_generated
from .prompts import LETTERS, gen_ctx_messages, strip_letter

MAX_EXPLANATION = 1400   # rule_validator: explanation_too_long
MAX_QUOTE = 250
MIN_QUOTE = 15

_RE_MATH = re.compile(r'\$[^$]*\$')
_RE_SENT_SPLIT = re.compile(r'(?<=[.;:])\s+')
_RE_ARROW = re.compile(r'\s*(?:\\Rightarrow|\\Leftrightarrow|⇒|⇔)\s*')
_RE_WORD = re.compile(r'[0-9a-zA-ZÀ-ỹ\\]+')
_STEPS_BY_LEVEL = {'Nhận biết': 2, 'Thông hiểu': 3, 'Vận dụng': 4, 'Vận dụng cao': 5}


def _mask_math(text: str) -> Tuple[str, List[str]]:
    spans: List[str] = []

    def repl(m: re.Match) -> str:
        spans.append(m.group(0))
        return f'\x00{len(spans) - 1}\x00'

    return _RE_MATH.sub(repl, text), spans


def _unmask(text: str, spans: List[str]) -> str:
    return re.sub(r'\x00(\d+)\x00', lambda m: spans[int(m.group(1))], text)


def split_steps(solution: str, minimum: int) -> List[Dict[str, str]]:
    """Cắt lời giải thành các bước; chỉ cắt nhỏ thêm khi chưa đủ ``minimum`` bước.

    Cắt ở ngoài công thức (``$...$`` được che trước) nên không làm hỏng LaTeX.
    """
    masked, spans = _mask_math(solution.strip())
    parts = [p.strip() for p in masked.split('\n') if p.strip()]
    for splitter in (_RE_ARROW, _RE_SENT_SPLIT):
        if len(parts) >= minimum:
            break
        out: List[str] = []
        for p in parts:
            out.extend(x.strip() for x in splitter.split(p) if x.strip())
        parts = out
    return [{'title': f'Bước {i + 1}', 'content': _unmask(p, spans)}
            for i, p in enumerate(parts)]


def trim_explanation(solution: str, limit: int = MAX_EXPLANATION) -> str:
    """Cắt lời giải cho vừa trần của pipeline, ưu tiên cắt ở hết dòng."""
    text = solution.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    idx = max(cut.rfind('\n'), cut.rfind('. '))
    return (cut[:idx] if idx > 0 else cut).strip()


def _tokens(text: str) -> set:
    return {w.lower() for w in _RE_WORD.findall(text or '') if len(w) > 1}


def quote_spans(doc_text: str) -> List[str]:
    """Các đoạn có thể dùng làm trích dẫn nguồn (dòng và câu trong tài liệu)."""
    spans: List[str] = []
    for line in (l.strip() for l in doc_text.splitlines()):
        if not line:
            continue
        if MIN_QUOTE <= len(line) <= MAX_QUOTE:
            spans.append(line)
        elif len(line) > MAX_QUOTE:
            masked, marks = _mask_math(line)
            for sent in _RE_SENT_SPLIT.split(masked):
                sent = _unmask(sent.strip(), marks)
                if MIN_QUOTE <= len(sent) <= MAX_QUOTE:
                    spans.append(sent)
    return spans


def pick_source_quote(candidate: Dict[str, Any], doc_text: str,
                      slot: Dict[str, Any]) -> str:
    """Đoạn trong tài liệu khớp nhất với câu hỏi và qua được luật trích dẫn.

    Mô hình fine-tune không tự trích dẫn tài liệu (nó không được huấn luyện để
    làm việc đó), nên trích dẫn được CHỌN LẠI từ bản chép của tài liệu. Đây là
    trích dẫn có thật, nhưng là do máy dò chứ không phải do mô hình chỉ ra —
    ``Critic`` vẫn chấm lại độ bám nguồn trên ảnh trang gốc.
    """
    from pipeline.rule_validator import source_quote_issues

    target = _tokens(candidate.get('question_text', '')) | _tokens(
        candidate.get('answer_explanation_text', ''))
    best, best_score = '', (0, 0.0)
    for span in quote_spans(doc_text):
        toks = _tokens(span)
        shared = len(toks & target)
        if shared < 2:
            continue
        # Đoạn có công thức được ưu tiên hơn tiêu đề mục (vốn cũng trùng vài từ
        # với đề nhưng không chứng minh được gì về phương pháp).
        score = (1 if '$' in span else 0, shared / len(toks) ** 0.5)
        if score <= best_score:
            continue
        if source_quote_issues(dict(candidate, source_quote_text=span), slot):
            continue
        best, best_score = span, score
    return best


def to_candidate(record: Dict[str, Any], slot: Dict[str, Any], doc_text: str,
                 own_distractors: bool = False) -> Dict[str, Any]:
    """Câu do mô hình soạn -> candidate đúng khuôn Writer của pipeline."""
    choices = [strip_letter(c) for c in record['choices']]
    answer_index = LETTERS.index(record['answer'])
    answer_text = choices[answer_index]
    solution = record['solution'].strip()
    level = str(slot.get('cognitive_level') or 'Thông hiểu')
    candidate: Dict[str, Any] = {
        'question_text': record['question'].strip(),
        'answer_text': answer_text,
        'answer_explanation_text': trim_explanation(solution),
        'source_quote_text': '',
        'visual': {'type': 'none', 'spec': {}, 'alt_text': ''},
        'verifier_hint': {'type': 'none', 'payload': {}},
        'distractors': [],
        'why_correct': '',
        'why_others_wrong': {},
        '_writer_kind': 'finetuned',
    }
    if not slot.get('_no_explanation'):
        candidate['detailed_solution'] = {
            'steps': split_steps(solution, _STEPS_BY_LEVEL.get(level, 3)),
            'final_answer': answer_text,
        }
    if own_distractors:
        candidate['distractors'] = [
            {'distractor_text': c,
             'distractor_category_text': 'finetuned_model',
             'distractor_explanation_text': (
                 'Phương án do mô hình fine-tune soạn cùng câu hỏi; mô hình không '
                 'mô tả cách ra giá trị này.')}
            for i, c in enumerate(choices) if i != answer_index
        ]
    candidate['source_quote_text'] = pick_source_quote(candidate, doc_text, slot)
    return candidate


#: Phương án nhiễu giả, chỉ để chạy bộ luật của pipeline lúc lọc câu nháp.
_DUMMY_DISTRACTORS = [
    {'distractor_text': '$1+\\sqrt{2}$', 'distractor_category_text': 'placeholder',
     'distractor_explanation_text': 'Chỗ giữ: $1+\\sqrt{2}$ do tính sai bước 2.'},
    {'distractor_text': '$2+\\sqrt{3}$', 'distractor_category_text': 'placeholder',
     'distractor_explanation_text': 'Chỗ giữ: $2+\\sqrt{3}$ do đổi cận sai.'},
    {'distractor_text': '$3+\\sqrt{5}$', 'distractor_category_text': 'placeholder',
     'distractor_explanation_text': 'Chỗ giữ: $3+\\sqrt{5}$ do quên hệ số $\\frac{1}{2}$.'},
]


def rule_issues(record: Dict[str, Any], slot: Dict[str, Any], doc_text: str,
                own_distractors: bool = False) -> List[str]:
    """Các lỗi mà bộ luật của pipeline sẽ bắt — dùng để lọc kho câu nháp trước.

    Lọc ở bước soạn nháp rẻ hơn nhiều so với để câu chạy hết Distractor + Critic
    (mỗi bước một lời gọi model thị giác) rồi mới bị loại.
    """
    from pipeline.rule_validator import validate_candidate

    candidate = to_candidate(record, slot, doc_text, own_distractors)
    if len(candidate['distractors']) != 3:
        candidate = dict(candidate, distractors=_DUMMY_DISTRACTORS)
    return validate_candidate(candidate, slot)


class OnlineDrafter:
    """Gọi máy chủ OpenAI-compatible đang phục vụ base + adapter.

    Dùng ``/v1/completions`` với prompt đã dựng sẵn bằng chat template
    (``enable_thinking=False``) — giống hệt lúc huấn luyện. Qua ``/v1/chat/...``
    thì vLLM tự bật chế độ suy nghĩ của Qwen3 nên đầu ra lệch khuôn đã học.
    """

    def __init__(self, base_url: str, model: str, api_key: str = 'none',
                 tokenizer: Any = None, max_tokens: int = 2048,
                 temperature: float = 0.7, top_p: float = 0.8, top_k: int = 20):
        from openai import OpenAI
        self.client = OpenAI(base_url=base_url, api_key=api_key or 'none')
        self.model = model
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.sampling = dict(temperature=temperature, top_p=top_p)
        self.top_k = top_k

    def render(self, messages: Sequence[Dict]) -> str:
        from .infer import render
        return render(self.tokenizer, messages)

    def __call__(self, context: str, level: str, topic: str) -> str:
        prompt = self.render(gen_ctx_messages(context, level, topic))
        resp = self.client.completions.create(
            model=self.model, prompt=prompt, max_tokens=self.max_tokens,
            extra_body={'top_k': self.top_k}, **self.sampling)
        return resp.choices[0].text


class FineTunedWriter:
    """Thay ``orchestrator.writer``; sinh câu bằng mô hình đã fine-tune."""

    def __init__(self, doc_text: str, drafts: Optional[Dict[str, List[Dict]]] = None,
                 drafter: Optional[Callable[[str, str, str], str]] = None,
                 context_for_slot: Optional[Callable[[Dict], Tuple[str, str]]] = None,
                 own_distractors: bool = False, tries: int = 3,
                 model: str = 'finetuned'):
        if drafts is None and drafter is None:
            raise ValueError('cần kho câu nháp (drafts) hoặc hàm sinh (drafter)')
        self.doc_text = doc_text
        self.drafts = {k: list(v) for k, v in (drafts or {}).items()}
        self.drafter = drafter
        self.context_for_slot = context_for_slot
        self.own_distractors = own_distractors
        self.tries = max(1, int(tries))
        self.model = model
        self.stats = {'used': 0, 'parse_failed': 0, 'invalid': 0, 'no_draft': 0,
                      'no_quote': 0}
        self._lock = threading.Lock()

    # ---- nguồn câu nháp ----
    def _next_raw(self, slot: Dict[str, Any]) -> Optional[str]:
        level = str(slot.get('cognitive_level') or 'Thông hiểu')
        if self.drafter is not None:
            context, topic = (self.context_for_slot(slot) if self.context_for_slot
                              else (self.doc_text, ''))
            return self.drafter(context, level, topic)
        with self._lock:
            queue = self.drafts.get(level) or []
            if not queue:
                return None
            return queue.pop(0)['text']

    def run(self, request: Any) -> Any:
        from pipeline.agents.writer_agent import _validate_writer_candidate
        from pipeline.direct_pdf.agents.messages import PdfWriteResponse

        slot = request.slot
        errors: List[str] = []
        for _ in range(self.tries):
            raw = self._next_raw(slot)
            if raw is None:
                with self._lock:
                    self.stats['no_draft'] += 1
                errors.append(f"hết câu nháp cho mức {slot.get('cognitive_level')}")
                break
            with self._lock:
                self.stats['used'] += 1
            record, problems = parse_generated(raw)
            if problems or record['answer'] is None:
                with self._lock:
                    self.stats['parse_failed'] += 1
                errors.append(f'đầu ra sai khuôn: {problems}')
                continue
            candidate = to_candidate(record, slot, self.doc_text, self.own_distractors)
            if not candidate['source_quote_text']:
                with self._lock:
                    self.stats['no_quote'] += 1
                errors.append('không tìm được trích dẫn nguồn hợp lệ trong tài liệu')
                continue
            try:
                _validate_writer_candidate(candidate)
            except Exception as exc:
                with self._lock:
                    self.stats['invalid'] += 1
                errors.append(str(exc))
                continue
            candidate['_slot_id'] = slot.get('slot_id')
            candidate['_writer_stage'] = True
            return PdfWriteResponse(slot_id=slot.get('slot_id', ''),
                                    candidates=[candidate], errors=errors)
        return PdfWriteResponse(slot_id=slot.get('slot_id', ''), candidates=[],
                                errors=errors)

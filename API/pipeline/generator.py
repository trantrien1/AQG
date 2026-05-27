"""Question generator (mục 10): nhận slot blueprint + context pack → câu hỏi.

Khác với pipeline cũ ở 2 điểm:
1. Mỗi slot có topic + question_pattern + cognitive_level + skill cụ thể.
2. Output có thêm `verifier_hint` để verifier kiểm tra symbolic.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from . import config as cfg
from . import distractor_bank
from .context_utils import trim_context_for_generation
from .llm_client import BudgetExceeded, call_llm
from .parsing import loads_json_maybe_repair, normalize_display_math


# ==== Parse helpers ====

def _extract(text: str, start: str, end: Optional[str]) -> str:
    s = text.find(start)
    if s < 0:
        return ''
    s += len(start)
    e = text.find(end, s) if end else len(text)
    if e < 0:
        e = len(text)
    return text[s:e].strip()


def _parse_verifier_hint(block: str) -> Dict[str, Any]:
    """Block có dạng:
        type: <type>
        payload: <json>
    """
    m_type = re.search(r'type\s*:\s*(\S+)', block)
    m_payload = re.search(r'payload\s*:\s*(\{.*?\}|\[.*?\]|none|None|null)\s*$', block, re.DOTALL | re.MULTILINE)
    if not m_payload:
        m_payload = re.search(r'payload\s*:\s*(\{.*\})', block, re.DOTALL)
    t = m_type.group(1).strip() if m_type else 'none'
    payload_raw = m_payload.group(1).strip() if m_payload else '{}'
    try:
        payload = json.loads(payload_raw) if payload_raw not in ('none', 'None', 'null') else {}
    except Exception:
        payload = {}
    return {'type': t, 'payload': payload}


def _parse_visual_block(block: str) -> Dict[str, Any]:
    """Block:
        type: <type>
        spec: <json>
        alt_text: <text>
    """
    m_type = re.search(r'type\s*:\s*(\S+)', block)
    m_spec = re.search(r'spec\s*:\s*(\{.*?\}|\[.*?\])\s*$', block, re.DOTALL | re.MULTILINE)
    if not m_spec:
        m_spec = re.search(r'spec\s*:\s*(\{.*\})', block, re.DOTALL)
    m_alt = re.search(r'alt_text\s*:\s*(.+)', block)
    t = m_type.group(1).strip() if m_type else 'none'
    spec_raw = m_spec.group(1).strip() if m_spec else '{}'
    try:
        spec = json.loads(spec_raw)
    except Exception:
        spec = {}
    alt = m_alt.group(1).strip() if m_alt else ''
    if t == 'none':
        return None  # type:ignore[return-value]
    return {'type': t, 'spec': spec, 'alt_text': alt}


def _strip_json_fence(text: str) -> str:
    return re.sub(r'^```(?:json)?\s*|\s*```$', '', (text or '').strip())

def _first_json_object(text: str) -> Optional[Dict[str, Any]]:
    raw = _strip_json_fence(text)
    try:
        obj = loads_json_maybe_repair(raw)
    except Exception:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            return None
        try:
            obj = loads_json_maybe_repair(m.group(0))
        except Exception:
            return None
    if isinstance(obj, list):
        return {'questions': obj}
    return obj if isinstance(obj, dict) else None

def _normalize_solution_steps(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        steps_raw = raw.get('steps') or []
        final_answer = raw.get('final_answer') or ''
    elif isinstance(raw, list):
        steps_raw = raw
        final_answer = ''
    else:
        return {'steps': [], 'final_answer': ''}

    steps: List[Dict[str, str]] = []
    for i, step in enumerate(steps_raw, start=1):
        if isinstance(step, dict):
            title = str(step.get('title') or f'Buoc {i}').strip()
            content = str(step.get('content') or step.get('text') or '').strip()
        else:
            title = f'Buoc {i}'
            content = str(step or '').strip()
        if content:
            steps.append({'title': title, 'content': content})
    return {'steps': steps[:6], 'final_answer': str(final_answer or '').strip()}

def _why_wrong_lookup(raw: Any) -> Dict[str, str]:
    if isinstance(raw, dict):
        return {str(k).strip().upper(): str(v or '').strip() for k, v in raw.items()}
    out: Dict[str, str] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get('option') or item.get('key') or '').strip().upper()
            reason = str(item.get('reason') or item.get('rationale') or '').strip()
            if key and reason:
                out[key] = reason
    return out

def _source_quote_candidates(context: str, limit: int = 4) -> List[str]:
    """Short exact spans the batch prompt can copy as source quotes."""
    text = re.sub(r'\s+', ' ', context or '').strip()
    if not text:
        return []
    raw_parts = re.split(r'(?<=[.!?])\s+|(?<=\))\s+(?=[A-ZÀ-ỸĐ])|\n+', text)
    candidates: List[str] = []
    seen = set()
    for raw in raw_parts:
        part = raw.strip(' "\'“”')
        if not (20 <= len(part) <= 260):
            continue
        if re.match(r'(?i)^\s*(topic|chunk type|context type|title)\s*:', part):
            continue
        if re.search(r'(?i)\b(?:cau|bai|question|exercise)\s*\d+[\.:)]?', part):
            continue
        has_math_or_concept = bool(
            re.search(
                r'\\int|∫|nguyên hàm|nguyen ham|tích phân|tich phan|diện tích|dien tich|'
                r'vận tốc|van toc|lưu lượng|luu luong|điện lượng|dien luong|[=<>]',
                part,
                re.I,
            )
        )
        if not has_math_or_concept:
            continue
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(part)
        if len(candidates) >= limit:
            break
    if candidates:
        return candidates
    fallback = text[:240].strip()
    return [fallback] if len(fallback) >= 20 else []

def _parse_json_response(text: str) -> Optional[Dict[str, Any]]:
    obj = _first_json_object(text)
    if not obj:
        return None

    question = obj.get('question_text') or obj.get('question') or obj.get('stem') or ''
    explanation = (
        obj.get('answer_explanation_text')
        or obj.get('explanation')
        or obj.get('short_explanation')
        or ''
    )
    source_quote = obj.get('source_quote_text') or obj.get('source_quote') or ''
    verifier = obj.get('verifier_payload') or obj.get('verifier_hint') or {}
    if not isinstance(verifier, dict):
        verifier = {'type': 'none', 'payload': {}}
    verifier.setdefault('type', 'none')
    if not isinstance(verifier.get('payload'), dict):
        verifier['payload'] = {}

    options = obj.get('options') or []
    answer_key = str(obj.get('answer_key') or '').strip().upper()
    answer_text = obj.get('answer_text') or obj.get('answer') or ''
    distractors: List[Dict[str, str]] = []
    why_wrong = {
        key: _sympy_to_natural(value)
        for key, value in _why_wrong_lookup(obj.get('why_others_wrong')).items()
    }

    if isinstance(options, list) and options:
        by_key: Dict[str, Dict[str, str]] = {}
        for i, opt in enumerate(options):
            if isinstance(opt, dict):
                key = str(opt.get('key') or opt.get('label') or chr(ord('A') + i)).strip().upper()
                val = str(opt.get('text') or opt.get('option') or '').strip()
            else:
                key = chr(ord('A') + i)
                val = str(opt or '').strip()
            if key and val:
                by_key[key] = {'key': key, 'text': val}
        if answer_key and answer_key in by_key:
            answer_text = by_key[answer_key]['text']
            for key in sorted(by_key):
                if key == answer_key:
                    continue
                distractors.append({
                    'distractor_category_text': None,
                    'distractor_explanation_text': why_wrong.get(key, ''),
                    'distractor_text': by_key[key]['text'],
                })

    if not distractors:
        raw_ds = obj.get('distractors') or []
        if isinstance(raw_ds, list):
            for d in raw_ds:
                if isinstance(d, dict):
                    text_val = d.get('distractor_text') or d.get('text') or d.get('option') or ''
                    category = d.get('distractor_category_text') or d.get('category')
                    reason = d.get('distractor_explanation_text') or d.get('explanation') or d.get('reason') or ''
                else:
                    text_val = str(d or '')
                    category = None
                    reason = ''
                if text_val:
                    distractors.append({
                        'distractor_category_text': category,
                        'distractor_explanation_text': str(reason or ''),
                        'distractor_text': str(text_val),
                    })

    detailed_solution = _normalize_solution_steps(obj.get('detailed_solution'))
    for step in detailed_solution.get('steps') or []:
        step['content'] = _sympy_to_natural(step.get('content', ''))
    detailed_solution['final_answer'] = _sympy_to_natural(detailed_solution.get('final_answer', ''))

    response = {
        'question_text': _sympy_to_natural(str(question or '')),
        'answer_explanation_text': _sympy_to_natural(str(explanation or '').strip()),
        'answer_text': _sympy_to_natural(str(answer_text or '')),
        'source_quote_text': _clean_source_quote(str(source_quote or '')),
        'visual': obj.get('visual') if isinstance(obj.get('visual'), dict) else None,
        'verifier_hint': verifier,
        'distractors': distractors[:3],
        'answer_key': answer_key or None,
        'detailed_solution': detailed_solution,
        'why_correct': _sympy_to_natural(str(obj.get('why_correct') or '').strip()),
        'why_others_wrong': why_wrong,
    }
    for d in response['distractors']:
        d['distractor_text'] = _sympy_to_natural(d['distractor_text'])
        d['distractor_explanation_text'] = _sympy_to_natural(
            d.get('distractor_explanation_text', '')
        )
    return response

def _clean_source_quote(quote: str) -> str:
    quote = (quote or '').strip()
    quote = quote.strip('"“”')
    return quote.strip()


def _sympy_to_natural(text: str) -> str:
    """Backward-compatible name; display text is normalized toward LaTeX."""
    return normalize_display_math(text)


def _extract_prompt_glossary(context: str, max_items: int = 10) -> str:
    """Build a small glossary from source context for prompt grounding."""
    if not context:
        return '- Không phát hiện glossary; dùng thuật ngữ đúng theo ngữ cảnh.'

    items: List[str] = []
    seen = set()

    for m in re.finditer(r'\b[A-Z]{2,}(?:[A-Z0-9_/-]{0,12})\b', context):
        term = m.group(0)
        if term not in seen:
            seen.add(term)
            items.append(f'- {term}: ký hiệu/thuật ngữ xuất hiện trong ngữ cảnh')
        if len(items) >= max_items:
            return '\n'.join(items)

    definition_markers = (
        ' là ', ' được gọi là ', ' ký hiệu ', ' định nghĩa ',
        ' nghĩa là ', ' tức là ',
    )
    sentences = re.split(r'(?<=[.!?])\s+|\n+', context)
    for sent in sentences:
        s = re.sub(r'\s+', ' ', sent).strip()
        if not (25 <= len(s) <= 220):
            continue
        low = s.lower()
        if any(marker in low for marker in definition_markers) and s not in seen:
            seen.add(s)
            items.append(f'- {s}')
        if len(items) >= max_items:
            break

    if not items:
        return '- Không phát hiện glossary; dùng thuật ngữ đúng theo ngữ cảnh.'
    return '\n'.join(items)


def parse_response(text: str) -> Dict[str, Any]:
    """Parse LLM output theo định dạng OUTPUT_FORMAT_INSTRUCTION."""
    json_response = _parse_json_response(text)
    if json_response:
        return json_response

    response = {
        'question_text': _extract(text, 'Question:', 'Answer explanation:'),
        'answer_explanation_text': _extract(text, 'Answer explanation:', 'Answer:'),
        'answer_text': _extract(text, 'Answer:', 'Source quote:'),
        'source_quote_text': _extract(text, 'Source quote:', 'Visual:'),
    }
    # Backward compat: nếu LLM bỏ qua "Source quote:", parse answer cũ
    if not response['answer_text']:
        response['answer_text'] = _extract(text, 'Answer:', 'Verifier hint:')
    if not response['source_quote_text']:
        response['source_quote_text'] = _extract(text, 'Source quote:', 'Verifier hint:')
    response['source_quote_text'] = _clean_source_quote(response.get('source_quote_text', ''))

    # Visual block (mới Tier 2)
    visual_block = _extract(text, 'Visual:', 'Verifier hint:')
    response['visual'] = _parse_visual_block(visual_block) if visual_block else None

    verifier_block = _extract(text, 'Verifier hint:', 'Distractors:')
    response['verifier_hint'] = _parse_verifier_hint(verifier_block)

    distractors_block = _extract(text, 'Distractors:', None)
    blocks = re.split(r'\n\s*\n', distractors_block.strip())
    distractors = []
    for b in blocks:
        if not b.strip():
            continue
        d = {
            'distractor_category_text': _extract(b, 'Distractor category:', 'Distractor explanation:'),
            'distractor_explanation_text': _extract(b, 'Distractor explanation:', 'Distractor:'),
            'distractor_text': _extract(b, 'Distractor:', None),
        }
        if d['distractor_text']:
            distractors.append(d)
    response['distractors'] = distractors[:3]

    # Post-process display text. Verifier still receives the machine-readable
    # `verifier_hint.payload` (không bị normalize bởi bước này).
    response['question_text'] = _sympy_to_natural(response['question_text'])
    response['answer_explanation_text'] = _sympy_to_natural(response['answer_explanation_text'])
    response['answer_text'] = _sympy_to_natural(response['answer_text'])
    for d in response['distractors']:
        d['distractor_text'] = _sympy_to_natural(d['distractor_text'])
        d['distractor_explanation_text'] = _sympy_to_natural(
            d.get('distractor_explanation_text', '')
        )
    return response


def is_valid(response: Dict[str, Any]) -> bool:
    if not response['question_text'] or not response['answer_text']:
        return False
    if len(response['distractors']) != 3:
        return False
    return True

def _conceptual_self_contained_guidance(slot: Dict[str, Any]) -> str:
    pattern = str(slot.get('question_pattern', '')).lower()
    meta_pattern = str(slot.get('meta_pattern', '')).lower()
    cognitive = str(slot.get('cognitive_level', '')).lower()
    if not (
        'concept' in pattern
        or meta_pattern == 'conceptual'
        or 'nhận biết' in cognitive
        or 'nhan biet' in cognitive
    ):
        return ''
    return (
        '\n\nYêu cầu riêng cho câu khái niệm/nhận biết:\n'
        '- Stem phải self-contained: nêu rõ tên hoặc nội dung ngắn của định lý/khái niệm; '
        'không chỉ viết "Định lý 1", "Định lý 2", "Ví dụ trên".\n'
        '- Nếu hỏi điều kiện áp dụng/không áp dụng, nhắc lại đối tượng chính trong stem.\n'
    )


# ==== Generator ====

_FULL_MCQ_JSON_FORMAT = '''\

Trả về DUY NHẤT một JSON object hợp lệ, không markdown/code fence. Schema:
{
  "question": "stem tự đầy đủ, không liệt kê A/B/C/D trong stem",
  "options": [
    {"key": "A", "text": "một phương án"},
    {"key": "B", "text": "một phương án"},
    {"key": "C", "text": "một phương án"},
    {"key": "D", "text": "một phương án"}
  ],
  "answer_key": "A|B|C|D",
  "explanation": "giải thích ngắn vì sao đáp án đúng, bám clean context",
  "detailed_solution": {
    "steps": [
      {"title": "Bước 1", "content": "nêu dữ kiện/công thức"},
      {"title": "Bước 2", "content": "tính toán hoặc suy luận"},
      {"title": "Kết luận", "content": "chọn đáp án đúng"}
    ],
    "final_answer": "nội dung đáp án đúng"
  },
  "why_correct": "vì sao đáp án đúng là duy nhất",
  "why_others_wrong": {
    "A": "để trống hoặc nêu lý do nếu A sai",
    "B": "để trống hoặc nêu lý do nếu B sai",
    "C": "để trống hoặc nêu lý do nếu C sai",
    "D": "để trống hoặc nêu lý do nếu D sai"
  },
  "source_quote": "trích nguyên văn 15-250 ký tự từ clean context",
  "visual": {"type": "none", "spec": {}, "alt_text": ""},
  "verifier_payload": {"type": "none", "payload": {}}
}

Quy tắc bắt buộc:
- options có đúng 4 phương án, chỉ 1 đáp án đúng, không trùng text.
- answer_key phải trỏ tới option đúng; why_others_wrong chỉ cần lý do cho 3 option sai.
- Distractors: choose the misconception first, compute the wrong result from that misconception, then write the option. Do not invent a vague reason after choosing a random wrong value.
- why_others_wrong must match the exact distractor value; avoid generic phrases like "calculation mistake" unless the erroneous calculation is shown.
- Các field hiển thị cho học sinh (question/options/explanation/detailed_solution/why_correct/why_others_wrong) phải dùng LaTeX inline cho công thức Toán.
- Vì output là JSON, mọi backslash LaTeX phải escape đúng: viết "\\\\(x^2+1\\\\)", "\\\\frac{a}{b}", "\\\\sqrt{x}", "\\\\int_a^b f(x)\\\\,dx". Không viết "\\(x^2+1\\)" trong JSON string.
- Không dùng plaintext kiểu sqrt(x), int_a^b, binomial(n,k), x**2 trong phần hiển thị; verifier_payload mới dùng cú pháp máy đọc/SymPy.
- NGHIEM CAM paraphrase/viet lai cau hoi, bai tap, vi du da co trong context. Cau moi phai co so lieu/tinh huong moi.
- Prefer conceptual/property/application questions with a meaningful stem; avoid bare one-step warm-up items when a better item is possible.
- source_quote must support the concept/formula/theorem, not quote an old exercise stem beginning "Cau", "Bai", "Question", or "Exercise".
- If the source is mostly exercises, use the underlying method only: change surface story, names, values, and wording.
- detailed_solution toi thieu: Nhan biet >=2 steps; Thong hieu >=3; Van dung >=4; Van dung cao >=5.
- Step dau tien khong duoc la "Ket luan"; voi cau tinh toan, cac step chinh nen co cong thuc hoac phep tinh cu the.
- verifier_payload chỉ dùng type hỗ trợ khi payload chắc chắn đúng schema; nếu không chắc, dùng {"type":"none","payload":{}}.
- Nếu đáp án đúng là một số/phân số cụ thể trong câu computation/application, bắt buộc tạo verifier_payload numeric_eval đúng schema; thiếu verifier sẽ bị loại.
- Với bài chuyển động hỏi quãng đường từ vận tốc, phải đảm bảo vận tốc không âm trên cả khoảng hoặc tích phân trị tuyệt đối; nếu tích phân trực tiếp vận tốc có dấu thì hỏi độ dời/vị trí.
- source_quote phải là đoạn xuất hiện trong clean context, không tự diễn đạt lại.
'''

class QuestionGenerator:
    def __init__(self, model_name: Optional[str] = None):
        self.model = model_name or cfg.GENERATOR_MODEL
        self.system_prompt = cfg.SYSTEM_PROMPT

    def _build_user_prompt(self, slot: Dict[str, Any], context: str) -> str:
        topic = slot.get('topic', '')
        prompt_context = trim_context_for_generation(
            context,
            slot,
            max_chars=cfg.GENERATION_CONTEXT_MAX_CHARS,
        )
        glossary = _extract_prompt_glossary(prompt_context)

        # Ưu tiên misconception do PlannerAgent (LLM) suy luận từ context;
        # fallback về distractor_bank khi inference rỗng.
        inferred = slot.get('inferred_misconceptions') or []
        if inferred:
            lines = [
                f"- [{m.get('id', 'm_' + str(i))}] {m.get('wrong_form', '')} — {m.get('rationale', '')}"
                for i, m in enumerate(inferred)
            ]
            misc_block = '\n'.join(lines) if lines else '(không có)'
        else:
            misconceptions = distractor_bank.get_misconceptions(
                topic=topic, k=5, seed=hash(slot['slot_id']) & 0xffff,
            )
            misc_block = distractor_bank.format_for_prompt(misconceptions)

        base = cfg.USER_PROMPT_TEMPLATE.format(
            topic=topic,
            cognitive_level=slot['cognitive_level'],
            difficulty_target=slot['difficulty_target'],
            pattern=slot['question_pattern'],
            misconceptions=misc_block,
            context=prompt_context,
        )
        prompt_guidance = (
            '\n\nGlossary / thuật ngữ cần giữ đúng:\n'
            f'{glossary}\n\n'
            f'Context type: {slot.get("source_chunk_type", "unknown")}. '
            f'Risk warning: {slot.get("risk_warning", "") or "none"}.\n'
            'ANTI-PARAPHRASE: If the context contains examples or existing exercises, do not rewrite them. '
            'Create a new stem with new numbers/situation; use only the underlying concept/formula.\n\n'
            f'Gợi ý verifier_type nội bộ: {slot.get("verifier_type", "none")}. '
            'Chỉ dùng verifier_payload theo gợi ý này khi payload chắc chắn đúng schema.\n\n'
            f'{cfg.PROMPT_ENGINEERING_GUIDE}\n\n'
            f'{_conceptual_self_contained_guidance(slot)}\n\n'
            f'{cfg.ONE_SHOT_FORMAT_EXAMPLE}\n\n'
            f'{cfg.SELF_REVIEW_CRITERIA}'
        )
        return base + prompt_guidance + '\n\n' + _FULL_MCQ_JSON_FORMAT

    def generate_for_slot(self, slot: Dict[str, Any], context: str,
                          num_samples: int = cfg.NUM_SAMPLES_PER_SLOT
                          ) -> List[Dict[str, Any]]:
        prompt = self._build_user_prompt(slot, context)
        results = []
        for i in range(num_samples):
            try:
                raw = call_llm(self.system_prompt, prompt, model=self.model)
                parsed = parse_response(raw)
                if is_valid(parsed):
                    parsed['_slot_id'] = slot['slot_id']
                    parsed['_fast_full_mcq'] = True
                    results.append(parsed)
            except BudgetExceeded:
                raise
            except Exception as e:
                print(f'  [slot {slot["slot_id"]} sample {i}] error: {e}')
                continue
        return results

_BATCH_MCQ_JSON_FORMAT = '''\
Return one valid JSON object, no markdown:
{
  "questions": [
    {
      "slot_id": "same slot_id from input",
      "question": "self-contained stem, no A/B/C/D labels",
      "options": [
        {"key":"A","text":"..."},
        {"key":"B","text":"..."},
        {"key":"C","text":"..."},
        {"key":"D","text":"..."}
      ],
      "answer_key": "A|B|C|D",
      "explanation": "brief explanation",
      "detailed_solution": {
        "steps": [
          {"title":"Buoc 1","content":"..."},
          {"title":"Buoc 2","content":"..."},
          {"title":"Ket luan","content":"..."}
        ],
        "final_answer": "correct option text"
      },
      "why_correct": "...",
      "why_others_wrong": {"A":"...","B":"...","C":"...","D":"..."},
      "source_quote": "15-250 chars copied from that slot context, not an old exercise stem",
      "visual": {"type":"none","spec":{},"alt_text":""},
      "verifier_payload": {"type":"none","payload":{}}
    }
  ]
}

Rules:
- Generate exactly one question for each input slot_id. Do not skip slots.
- Each question has exactly 4 options and exactly 1 correct answer.
- Student-facing math uses inline LaTeX. Escape backslashes correctly in JSON.
- Detailed solution minimum: Nhan biet 2 steps, Thong hieu 3, Van dung 4, Van dung cao 5.
- Distractors: choose the misconception first, compute the wrong result from that misconception, then write the option; why_others_wrong must match the exact option value.
- Do not use vague distractor reasons such as "calculation mistake" unless the wrong calculation is shown.
- Avoid bare one-step warm-up items such as "Tinh \\int_a^b kx dx"; prefer conceptual/property/application questions with a meaningful stem.
- Do not paraphrase any existing exercise/example from context. Create a new item from the concept/formula.
- source_quote must be copied exactly from that slot's source_quote_candidates when the list is non-empty; otherwise copy an exact 15-250 char span from context that supports the concept/formula.
- source_quote must NOT be metadata such as "Topic:", "Title:", "Chunk type:", and must NOT quote "Cau/Bai/Question/Exercise".
- Default to {"type":"none","payload":{}}. Use a verifier_payload only for direct numeric/algebraic calculations where the machine-readable expression and expected answer are explicit and simple.
- If the correct answer is a concrete number/fraction and question_pattern is computation or application, verifier_payload is REQUIRED; missing verifier will be rejected.
- For numeric_eval, the schema is exactly {"type":"numeric_eval","payload":{"expr":"machine-readable arithmetic expression","expected_numeric":number}}.
- For numeric_eval, the correct option text, detailed_solution.final_answer, answer_key, and expected_numeric must all represent the same value. If they disagree, fix the answer/options before output.
- For conceptual, interpretation, or OCR-noisy context, keep verifier_payload as {"type":"none","payload":{}} even if verifier_type_hint suggests a math engine.
- For motion questions about distance from velocity, ensure velocity is nonnegative on the whole interval or integrate absolute velocity. If integrating signed velocity directly, ask for displacement/position instead of distance.
'''

class BatchQuestionGenerator:
    """Generate multiple full MCQs in one LLM call for Fast Mode."""

    def __init__(self, model_name: Optional[str] = None):
        self.model = model_name or cfg.GENERATOR_MODEL
        self.system_prompt = (
            'Ban la chuyen gia ra de Toan. Sinh MCQ chat luong cao tu clean context. '
            'Uu tien dung Toan, mot dap an dung duy nhat, distractor hop ly, JSON dung schema.'
        )

    def _slot_payload(self, slot: Dict[str, Any], context: str) -> Dict[str, Any]:
        prompt_context = trim_context_for_generation(
            context,
            slot,
            max_chars=cfg.FAST_BATCH_CONTEXT_CHARS,
        )
        misconceptions = []
        for m in slot.get('inferred_misconceptions') or []:
            if isinstance(m, dict):
                misconceptions.append({
                    'id': m.get('id', ''),
                    'wrong_form': m.get('wrong_form', ''),
                })
        return {
            'slot_id': slot.get('slot_id', ''),
            'topic': slot.get('topic', ''),
            'skill': slot.get('skill', ''),
            'cognitive_level': slot.get('cognitive_level', ''),
            'difficulty_target': slot.get('difficulty_target', 0.5),
            'question_pattern': slot.get('question_pattern', ''),
            'verifier_type_hint': slot.get('verifier_type', 'none'),
            'context_type': slot.get('source_chunk_type', 'unknown'),
            'risk_warning': slot.get('risk_warning', ''),
            'misconceptions': misconceptions[:3],
            'source_quote_candidates': _source_quote_candidates(prompt_context),
            'context': prompt_context,
        }

    def _build_user_prompt(self, slots_contexts: List[tuple[Dict[str, Any], str]]) -> str:
        payload = [
            self._slot_payload(slot, context)
            for slot, context in slots_contexts
        ]
        return (
            'Generate MCQs for these slots. Keep each output item mapped by slot_id.\n'
            'Use each slot context and skill as the primary source. Do not reuse the same stem, answer formula, story, or source_quote across slots in the same batch.\n'
            'Prefer diverse core operations; the validator will handle any unavoidable duplicates.\n'
            'If a slot context is an exercise or worked solution, create a new scenario with different surface details while preserving the underlying method.\n'
            f'Input slots JSON:\n{json.dumps(payload, ensure_ascii=False)}\n\n'
            f'{_BATCH_MCQ_JSON_FORMAT}'
        )

    def generate_batch(
        self,
        slots_contexts: List[tuple[Dict[str, Any], str]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not slots_contexts:
            return {}
        expected_ids = [str(slot.get('slot_id') or '').strip() for slot, _ in slots_contexts]
        expected_set = {sid for sid in expected_ids if sid}
        base_to_expected = {}
        for sid in expected_ids:
            base = re.sub(r'_r\d{2}$', '', sid)
            base_to_expected.setdefault(base, sid)
        prompt = self._build_user_prompt(slots_contexts)
        raw = call_llm(
            self.system_prompt,
            prompt,
            model=self.model,
            max_tokens=cfg.FAST_BATCH_MAX_TOKENS,
        )
        obj = _first_json_object(raw)
        if not obj:
            return {}
        items = []
        for key in ('questions', 'items', 'mcqs', 'data', 'outputs'):
            if isinstance(obj.get(key), list):
                items = obj.get(key) or []
                break
        out: Dict[str, List[Dict[str, Any]]] = {}
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            raw_slot_id = str(item.get('slot_id') or item.get('_slot_id') or '').strip()
            slot_id = raw_slot_id
            if slot_id not in expected_set:
                slot_id = base_to_expected.get(raw_slot_id, slot_id)
            if slot_id not in expected_set and idx < len(expected_ids):
                slot_id = expected_ids[idx]
            if not slot_id:
                continue
            item['slot_id'] = slot_id
            parsed = _parse_json_response(json.dumps(item, ensure_ascii=False))
            if not parsed or not is_valid(parsed):
                continue
            parsed['_slot_id'] = slot_id
            parsed['_fast_full_mcq'] = True
            parsed['_batch_generated'] = True
            out.setdefault(slot_id, []).append(parsed)
        return out

"""PdfCriticAgent — chấm chất lượng MCQ trên chính các trang PDF (vision).

Thay cho critic text (`grounding.judge_grounding`/`judge_multi_trait`) vốn cần
context dạng text. Ở Direct_PDF, "context" là ảnh trang tài liệu, nên critic tự
hỏi model vision (rationale-before-score, RMTS) hai chiều:

  1. grounding  — mọi dữ kiện trong stem/answer/explanation + source_quote có
                  THẬT trong tài liệu đính kèm không? (0..1)
  2. multi-trait — clarity / cognitive_depth / bloom_alignment /
                   distractor_plausibility / answer_uniqueness /
                   error_distractor_consistency (mỗi trait 0..1)

`error_distractor_consistency` (theo hướng eval của LookAlike): làm theo đúng
chuỗi lỗi trong distractor_explanation_text có ra đúng distractor_text không,
và why_correct/explanation có nhất quán với answer_text không — bắt lớp lỗi
giải thích tham chiếu sai đáp án.

Điền annotations đúng KEY mà FormatterAgent đọc: `_grounding`, `_quality`
(mean traits), `_quality_traits`, `_bloom_alignment`. LUÔN điền các key này —
kể cả khi model lỗi/parse hỏng (default trung tính) — để FormatterAgent không
ép mọi record thành `needs_revision`.

Reject khi grounding < GROUNDING_THRESHOLD hoặc answer_uniqueness < 0.5 (nghi
đa đáp án). Không có Refiner nên KHÔNG set `_refinable`; candidate bị reject sẽ
để orchestrator retry slot mới.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .pdf_base import PdfAwareAgent
from .messages import PdfCriticRequest, PdfCriticResponse
from ... import config as cfg
from ...llm_client import BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError
from ...parsing import (
    drop_orphan_math_closers,
    normalize_latex_escapes,
    trim_unclosed_math,
)

_TRAIT_KEYS = (
    'clarity', 'cognitive_depth', 'bloom_alignment',
    'distractor_plausibility', 'answer_uniqueness',
    'error_distractor_consistency',
)


class PdfCriticAgent(PdfAwareAgent):
    """Grounding + multi-trait rubric bằng model vision trên trang tài liệu."""

    def __init__(self, use_skills: bool = True, model: str = None):
        super().__init__(
            'critic',
            skills=['source-grounding', 'rubric-critique', 'curriculum-alignment'],
            use_skills=use_skills,
            model=model,
        )
        self._skill_instructions = self.skill_instructions()

    def run(self, request: PdfCriticRequest) -> PdfCriticResponse:
        annotations: Dict[str, Any] = {}
        try:
            raw = self._call_pdf(
                self._user_prompt(request),
                request.attachment_parts,
                # 7 khối rationale+score (grounding + 6 traits); 700 từng gây
                # JSON cụt ~40% lượt chấm -> traits rơi hết về trung tính.
                max_tokens=cfg.CRITIC_MAX_TOKENS,
            )
            grounding, grounding_rationale, traits, quality = _parse_critic(raw)
        except (BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError):
            raise
        except Exception as exc:
            # Critic lỗi -> KHÔNG chặn record: điền trung tính để Formatter xử lý.
            annotations['_grounding'] = 0.6
            annotations['_quality'] = 0.6
            annotations['_quality_traits'] = _neutral_traits()
            annotations['_bloom_alignment'] = 0.7
            annotations['_critic_errored'] = str(exc)
            return PdfCriticResponse(annotations=annotations, rejected=False)

        annotations['_grounding'] = grounding
        annotations['_grounding_rationale'] = grounding_rationale
        annotations['_quality'] = quality
        annotations['_quality_traits'] = traits
        annotations['_bloom_alignment'] = traits.get(
            'bloom_alignment', {}).get('score', 1.0)

        if grounding < cfg.GROUNDING_THRESHOLD:
            detail = grounding_rationale[:160]
            suffix = f' ({detail})' if detail else ''
            return PdfCriticResponse(
                annotations=annotations, rejected=True,
                reject_reason=f'grounding={grounding:.2f} < {cfg.GROUNDING_THRESHOLD}{suffix}',
            )
        uniq = traits.get('answer_uniqueness', {}).get('score', 1.0)
        if uniq < cfg.ANSWER_UNIQUENESS_THRESHOLD:
            return PdfCriticResponse(
                annotations=annotations, rejected=True,
                reject_reason=f'answer_uniqueness={uniq:.2f} (nghi đa đáp án)',
            )
        cons = traits.get('error_distractor_consistency', {}).get('score', 1.0)
        if cons < cfg.ERROR_VALUE_CONSISTENCY_THRESHOLD:
            detail = traits.get('error_distractor_consistency', {}).get('rationale', '')[:160]
            suffix = f' ({detail})' if detail else ''
            return PdfCriticResponse(
                annotations=annotations, rejected=True,
                reject_reason=(
                    f'error_distractor_consistency={cons:.2f} '
                    f'(lỗi mô tả không khớp giá trị distractor/đáp án){suffix}'),
            )
        return PdfCriticResponse(annotations=annotations, rejected=False)

    def _user_prompt(self, request: PdfCriticRequest) -> str:
        c = request.candidate
        distractors = '\n'.join(
            f"- {d.get('distractor_text', '')} (lỗi: {d.get('distractor_category_text', '')}) "
            f"— cách ra giá trị này: {d.get('distractor_explanation_text', '')}"
            for d in c.get('distractors', [])
        )
        payload = {
            'question_text': c.get('question_text', ''),
            'answer_text': c.get('answer_text', ''),
            'answer_explanation_text': c.get('answer_explanation_text', ''),
            'why_correct': c.get('why_correct', ''),
            'source_quote_text': c.get('source_quote_text', ''),
            'cognitive_level': request.slot.get('cognitive_level', ''),
            'generation_policy': (
                'Direct_PDF_Mode may create a NEW exercise by changing numbers, '
                'names, units, or story details, as long as the underlying '
                'formula, theorem, method, notation, or worked-example pattern '
                'is supported by the attached PDF. Do not require every newly '
                'chosen number to appear verbatim in the source.'
            ),
        }
        return f"""
Tài liệu Toán được đính kèm ở trên (các trang ảnh/PDF). Hãy ĐỌC tài liệu rồi CHẤM
một câu hỏi trắc nghiệm dưới đây. Với MỖI tiêu chí: viết `rationale` (1 câu ngắn)
TRƯỚC, rồi `score` trong [0,1] SAU (rationale-before-score).

Direct_PDF grounding policy:
- The question may be a NEW exercise derived from the PDF. Changed numbers,
  names, units, and story details are allowed when the underlying formula,
  theorem, method, notation, or worked-example pattern is supported by the PDF.
- Give high grounding (0.70-0.95) when the source_quote is present or strongly
  matches a formula/theorem/example in the PDF and the question correctly applies
  that same method, even if the final numeric answer is newly computed.
- Give medium grounding (0.45-0.70) when the method appears supported but exact
  quote matching is uncertain from page images.
- Give low grounding (<0.40) only when the quote is irrelevant/not visible, the
  main concept is outside the PDF, or the solution contradicts the PDF method.
- Do not reject a valid symbolic or numeric inference solely because the final
  computed value does not appear verbatim in the PDF.

Additional skill instructions:
{self._skill_instructions}

Câu hỏi cần chấm:
{json.dumps(payload, ensure_ascii=False)}
Các distractor:
{distractors or '(chưa có)'}

Tiêu chí:
- grounding: source_quote và phương pháp/công thức/khái niệm chính có được PDF hỗ trợ
  không? Cho phép số liệu/tình huống mới nếu chúng chỉ là bài tập phát sinh hợp lệ từ
  phương pháp trong PDF.
- clarity: đề rõ ràng, không mơ hồ.
- cognitive_depth: độ sâu tư duy phù hợp mức nhận thức yêu cầu.
- bloom_alignment: có đúng mức Bloom "{request.slot.get('cognitive_level', '')}" không.
- distractor_plausibility: 3 phương án sai có hợp lý, gắn lỗi thường gặp không.
- answer_uniqueness: CHỈ có đúng một đáp án đúng; không distractor nào cũng đúng.
- error_distractor_consistency: với MỖI distractor, nếu làm theo đúng chuỗi lỗi
  trong phần "cách ra giá trị này" thì có ra ĐÚNG giá trị distractor đó không?
  Đồng thời why_correct/answer_explanation_text có nhất quán với answer_text
  không (không tham chiếu nhầm sang phương án khác)? Chấm thấp (<0.4) nếu mô tả
  lỗi không dẫn tới giá trị distractor hoặc giải thích mâu thuẫn với đáp án.

Chỉ trả về DUY NHẤT một JSON, KHÔNG kèm markdown/chữ ngoài JSON:
{{
  "grounding": {{"rationale":"...", "score":0.0}},
  "clarity": {{"rationale":"...", "score":0.0}},
  "cognitive_depth": {{"rationale":"...", "score":0.0}},
  "bloom_alignment": {{"rationale":"...", "score":0.0}},
  "distractor_plausibility": {{"rationale":"...", "score":0.0}},
  "answer_uniqueness": {{"rationale":"...", "score":0.0}},
  "error_distractor_consistency": {{"rationale":"...", "score":0.0}}
}}
""".strip()


def _clean_rationale(text: Any) -> str:
    """Rationale hiển thị ở màn chi tiết câu hỏi: khử escape thừa + cắt 300
    ký tự có thể rơi giữa công thức -> chuẩn hoá để KaTeX render được."""
    s = str(text or '').strip()[:300]
    return drop_orphan_math_closers(trim_unclosed_math(normalize_latex_escapes(s)))


def _coerce_score(info: Any) -> float:
    if isinstance(info, dict):
        val = info.get('score', 0.5)
    else:
        val = info
    try:
        val = float(val)
    except Exception:
        return 0.5
    return max(0.0, min(1.0, val))


def _neutral_traits() -> Dict[str, Dict[str, Any]]:
    return {k: {'score': 0.6, 'rationale': ''} for k in _TRAIT_KEYS}


def _salvage_trait_blocks(text: str) -> Dict[str, Any]:
    """Vớt các khối trait hoàn chỉnh từ JSON bị cụt (model hết token giữa chừng).

    Cắt text theo vị trí xuất hiện của từng key rồi tìm score/rationale trong
    đoạn của key đó — các trait đã chấm xong vẫn giữ được điểm thật thay vì
    toàn bộ rơi về trung tính.
    """
    keys = ('grounding',) + _TRAIT_KEYS
    positions = []
    for key in keys:
        m = re.search(r'"' + key + r'"\s*:', text)
        if m:
            positions.append((m.start(), key))
    positions.sort()
    obj: Dict[str, Any] = {}
    for idx, (start, key) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
        block = text[start:end]
        sm = re.search(r'"score"\s*:\s*(-?[0-9]*\.?[0-9]+)', block)
        if not sm:
            continue
        rm = re.search(r'"rationale"\s*:\s*"((?:[^"\\]|\\.)*)"', block)
        obj[key] = {
            'score': float(sm.group(1)),
            'rationale': rm.group(1) if rm else '',
        }
    return obj


def _parse_critic(raw: str):
    """Trả về (grounding, grounding_rationale, traits, quality).

    Không raise với JSON cụt: thử json.loads, rồi khối {...} lớn nhất, cuối
    cùng vớt từng trait bằng _salvage_trait_blocks. Trait không vớt được sẽ
    nhận 0.5 trung tính ở vòng lặp phía dưới.
    """
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', (raw or '').strip())
    obj = None
    try:
        obj = json.loads(text)
    except Exception:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group(0))
            except Exception:
                obj = None
    if not isinstance(obj, dict):
        obj = _salvage_trait_blocks(text)

    grounding_info = obj.get('grounding')
    grounding = _coerce_score(grounding_info)
    grounding_rationale = ''
    if isinstance(grounding_info, dict):
        grounding_rationale = _clean_rationale(grounding_info.get('rationale', ''))
    traits: Dict[str, Any] = {}
    scores: List[float] = []
    for key in _TRAIT_KEYS:
        info = obj.get(key)
        score = _coerce_score(info)
        rationale = ''
        if isinstance(info, dict):
            rationale = _clean_rationale(info.get('rationale', ''))
        traits[key] = {'score': score, 'rationale': rationale}
        scores.append(score)
    quality = sum(scores) / len(scores) if scores else 0.5
    return grounding, grounding_rationale, traits, quality

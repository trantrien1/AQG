"""PdfDistractorAgent — Stage 2: sinh 3 distractor gắn misconception (vision).

Error-first (theo hướng DiVERT/LookAlike, không cần train): chọn misconception
TRƯỚC (lấy từ `distractor_bank` match theo nội dung câu hỏi), áp dụng lỗi vào
chính bài toán để suy ra giá trị sai, rồi mới ghi distractor. Nhờ đó
`distractor_explanation_text` mô tả đúng chuỗi lỗi tạo ra `distractor_text`
— liên kết mà PdfCriticAgent chấm ở trait `error_distractor_consistency`.

Nhìn thấy các trang PDF nên ký hiệu/kết quả sai vẫn khớp phong cách tài liệu.
Tái dùng parser stateless `_parse_distractors` của distractor chunk.
"""
from __future__ import annotations

import json
import zlib
from typing import Any, Dict, List

from .pdf_base import PdfAwareAgent
from .messages import PdfDistractorRequest, PdfDistractorResponse
from .pdf_writer_agent import _feedback_block
from ... import ablation
from ... import config as cfg
from ... import distractor_bank
from ...agents.distractor_agent import _parse_distractors
from ...llm_client import BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError


def _missing_error_fields(distractors: List[Dict[str, Any]]) -> List[int]:
    """Chỉ số các distractor thiếu mô tả lỗi — điều kiện cốt lõi của error-first.

    Không có `distractor_explanation_text` thì critic không thể kiểm tra tính
    nhất quán lỗi↔giá trị, nên coi là candidate hỏng để orchestrator retry.
    """
    return [i for i, d in enumerate(distractors)
            if not str(d.get('distractor_explanation_text') or '').strip()]


def _misconception_block(candidate: Dict[str, Any], slot: Dict[str, Any]) -> str:
    """Chọn k misconception khớp nội dung câu hỏi, format cho prompt.

    Seed theo CRC32 của text để cùng một candidate luôn nhận cùng danh sách
    (tái lập được khi debug/benchmark).
    """
    if not ablation.is_enabled(ablation.MISCONCEPTION_CATALOGUE):
        # Ablation: bỏ danh mục sai lầm, agent phải tự nghĩ ra lỗi.
        return ''
    match_text = ' '.join(str(x or '') for x in (
        slot.get('topic'),
        candidate.get('question_text'),
        candidate.get('answer_explanation_text'),
    )).strip()
    seed = zlib.crc32(match_text.encode('utf-8'))
    items = distractor_bank.get_misconceptions(match_text, k=6, seed=seed)
    return distractor_bank.format_for_prompt(items)


class PdfDistractorAgent(PdfAwareAgent):
    """Tạo đúng 3 phương án sai hợp lý cho một MCQ core từ Writer."""

    def __init__(self, use_skills: bool = True, model: str = None):
        super().__init__(
            'distractor',
            skills=['distractor-generation'],
            use_skills=use_skills,
            model=model,
        )
        self._skill_instructions = self.skill_instructions()

    def run(self, request: PdfDistractorRequest) -> PdfDistractorResponse:
        try:
            raw = self._call_pdf(
                self._user_prompt(request),
                request.attachment_parts,
                max_tokens=cfg.DISTRACTOR_MAX_TOKENS,
            )
            distractors = _parse_distractors(raw)
            if len(distractors) != 3:
                return PdfDistractorResponse(
                    distractors=[], error=f'distractor_count={len(distractors)}')
            missing = _missing_error_fields(distractors)
            if missing:
                return PdfDistractorResponse(
                    distractors=[],
                    error=f'distractor_missing_error_explanation={missing}')
            for d in distractors:
                if not str(d.get('distractor_category_text') or '').strip():
                    d['distractor_category_text'] = 'unlisted_error'
            return PdfDistractorResponse(distractors=distractors)
        except (BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError):
            raise
        except Exception as exc:
            return PdfDistractorResponse(distractors=[], error=str(exc))

    def _user_prompt(self, request: PdfDistractorRequest) -> str:
        candidate = request.candidate
        core = {k: candidate.get(k) for k in (
            'question_text', 'answer_text', 'answer_explanation_text', 'why_correct')}
        misconceptions = _misconception_block(candidate, request.slot)
        feedback = _feedback_block(request.slot.get('_feedback_guidance'))
        return f"""{feedback}
Tài liệu Toán đính kèm ở trên (các trang ảnh/PDF). Dựa vào nội dung tài liệu và
phần lõi MCQ dưới đây, tạo ĐÚNG 3 phương án SAI (distractor) theo quy trình
ERROR-FIRST: chọn lỗi trước, suy ra giá trị sai sau.

Sai lầm thường gặp (misconception bank — ưu tiên chọn từ đây):
{misconceptions}

Quy trình BẮT BUỘC cho MỖI distractor:
1. CHỌN một misconception phù hợp với bài toán này; ghi id của nó vào
   distractor_category_text. Nếu không id nào khớp, tự nêu một lỗi cụ thể khác
   và đặt id ngắn dạng snake_case.
2. ÁP DỤNG đúng lỗi đó vào chính bài toán, tính/suy luận ra kết quả sai.
3. Ghi kết quả vào distractor_text. distractor_explanation_text phải mô tả các
   bước làm sai SAO CHO ai làm theo sẽ ra ĐÚNG distractor_text (nêu rõ phép
   tính khi là câu số).

Quy tắc:
- 3 distractor phải dùng 3 misconception KHÁC nhau.
- Mỗi distractor phải SAI so với đáp án đúng nhưng HỢP LÝ với học sinh.
- Giữ cùng DẠNG/đơn vị với đáp án đúng. Dùng LaTeX inline, escape \\\\ trong JSON.
- KHÔNG trùng đáp án đúng hoặc một giá trị tương đương.

Phần lõi MCQ (đáp án đúng KHÔNG được lặp lại làm distractor):
{json.dumps(core, ensure_ascii=False)}

Chỉ trả về JSON:
{{
  "distractors": [
    {{"distractor_text":"...", "distractor_category_text":"<misconception id>", "distractor_explanation_text":"các bước làm sai dẫn tới ĐÚNG giá trị này & vì sao sai"}}
  ]
}}
""".strip()

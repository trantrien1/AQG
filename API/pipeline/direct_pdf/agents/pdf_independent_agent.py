"""IndependentVerifierAgent — dựng mục tiêu kiểm chứng ĐỘC LẬP cho một câu hỏi.

Agent này giải lại bài toán từ đầu và nộp về một biểu thức máy đọc được; SymPy
tính lại giá trị đó (trong `pipeline.independent_target`) rồi tầng phân xử so
với đáp án key.

Điều kiện độc lập được ép ở ĐẦU VÀO: agent chỉ nhận `question_text`. Nó không
nhận `answer_text`, `answer_explanation_text`, `detailed_solution`,
`verifier_payload` hay danh sách phương án — nếu nhận, nó sẽ neo theo đáp án
đang cần kiểm và cơ chế mất hết giá trị. :func:`_blinded_stem` là chỗ duy nhất
đọc candidate, và nó chỉ lấy đúng một trường.

Mặc định chạy bằng `cfg.INDEPENDENT_VERIFIER_MODEL` (mặc định = JUDGE_MODEL) ở
nhiệt độ 0, và KHÔNG gửi kèm trang tài liệu (đề bài vốn tự chứa) để không nhân
đôi chi phí token; đặt AQG_INDEPENDENT_VERIFIER_SEES_DOCUMENT=1 nếu muốn nó đọc
tài liệu gốc.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .pdf_base import PdfAwareAgent
from ... import ablation
from ... import config as cfg
from ...independent_target import (
    IndependentTarget, build_independent_target, disabled_target,
)
from ...llm_client import (
    BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError, call_llm,
)


def _blinded_stem(candidate: Dict[str, Any]) -> str:
    """Chỉ lấy đề bài. Mọi trường khác của candidate đến từ Writer nên bị bịt."""
    return str(candidate.get('question_text') or '').strip()


class PdfIndependentVerifierAgent(PdfAwareAgent):
    """Giải lại bài toán một cách độc lập để lấy mục tiêu đối chiếu."""

    def __init__(self, use_skills: bool = False, model: Optional[str] = None):
        # use_skills=False có chủ đích: skill của pipeline mô tả cách RA ĐỀ, còn
        # agent này chỉ làm một việc là giải toán.
        super().__init__(
            'independent_verifier',
            skills=[],
            use_skills=False,
            model=model or cfg.INDEPENDENT_VERIFIER_MODEL,
        )

    def run(
        self,
        candidate: Dict[str, Any],
        attachment_parts: Optional[List[Dict[str, Any]]] = None,
    ) -> IndependentTarget:
        if not ablation.is_enabled(ablation.INDEPENDENT_VERIFICATION):
            return disabled_target('tắt qua ablation')
        if not cfg.INDEPENDENT_VERIFICATION:
            return disabled_target('tắt qua AQG_INDEPENDENT_VERIFICATION=0')

        stem = _blinded_stem(candidate)
        if not stem:
            return disabled_target('candidate không có đề bài')

        sees_doc = bool(
            getattr(cfg, 'INDEPENDENT_VERIFIER_SEES_DOCUMENT', False)
            and attachment_parts
        )

        def _call(system: str, user: str) -> str:
            if sees_doc:
                content = ([{'type': 'text', 'text': user}]
                           + list(attachment_parts or []))
                from ...llm_client import call_llm_with_pdf
                return call_llm_with_pdf(
                    system=system,
                    user_content=content,
                    model=self.model,
                    temperature=cfg.INDEPENDENT_VERIFIER_TEMPERATURE,
                    max_tokens=cfg.INDEPENDENT_VERIFIER_MAX_TOKENS,
                )
            return call_llm(
                system=system,
                user=user,
                model=self.model,
                temperature=cfg.INDEPENDENT_VERIFIER_TEMPERATURE,
                max_tokens=cfg.INDEPENDENT_VERIFIER_MAX_TOKENS,
            )

        try:
            return build_independent_target(
                stem, call_fn=_call, model=self.model,
            )
        except (BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError):
            # Lỗi hạ tầng phải nổi lên để orchestrator dừng đúng cách, không
            # được nuốt thành "không kiểm chứng được".
            raise

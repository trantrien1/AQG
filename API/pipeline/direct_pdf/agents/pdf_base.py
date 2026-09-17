"""PdfAwareAgent — base cho agent gọi model vision với các trang PDF đính kèm.

Khác BaseAgent thường: thay vì `call_llm(system, user_text)`, agent PDF gọi
`call_llm_with_pdf(system, [{'type':'text','text':prompt}] + attachment_parts)`
để model ĐỌC TRỰC TIẾP các trang tài liệu (ảnh/PDF) làm context.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...agents.base import BaseAgent
from ... import config as cfg
from ...llm_client import call_llm_with_pdf


class PdfAwareAgent(BaseAgent):
    """Base agent cho Direct_PDF_Mode multi-agent.

    `_call_pdf` để `PdfUnsupportedError` propagate (web/jobs.py bắt được), giữ
    cùng cơ chế retry/throttle của `call_llm_with_pdf`.
    """

    def __init__(self, name: str, skills: Optional[List[str]] = None,
                 use_skills: bool = True, model: Optional[str] = None):
        super().__init__(name, skills=skills, use_skills=use_skills)
        self.model = model or cfg.GENERATOR_MODEL

    def _call_pdf(self, prompt_text: str,
                  attachment_parts: List[Dict[str, Any]],
                  max_tokens: int,
                  model: Optional[str] = None) -> str:
        text_part = [{'type': 'text', 'text': prompt_text}]
        if getattr(cfg, 'ATTACHMENTS_FIRST', False):
            # Tài liệu đứng trước ⇒ tiền tố giống hệt nhau qua mọi lời gọi của
            # cùng tài liệu, server tự host dùng lại KV cache đã tính.
            content = list(attachment_parts) + text_part
        else:
            content = text_part + list(attachment_parts)
        return call_llm_with_pdf(
            system=cfg.SYSTEM_PROMPT,
            user_content=content,
            model=model or self.model,
            max_tokens=max_tokens,
        )

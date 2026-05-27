"""DistractorAgent — Stage 2 của pipeline 3-stage.

Nhận candidate từ Writer, sinh 3 distractor gắn misconception. Gọi LLM riêng
biệt để tách concern: Writer lo nội dung câu hỏi, Distractor lo độ đánh lừa.
"""
from __future__ import annotations

from .base import BaseAgent
from .messages import DistractorRequest, DistractorResponse
from ..distractor import DistractorWriter
from ..llm_client import BudgetExceeded


class DistractorAgent(BaseAgent):
    def __init__(self):
        super().__init__('distractor', skills=['distractor-generation'])
        self._writer = DistractorWriter(skill_instructions=self.skill_instructions())

    def run(self, request: DistractorRequest) -> DistractorResponse:
        try:
            ds = self._writer.write(
                request.candidate,
                request.slot,
                context=request.context,
                feedback=request.feedback,
            )
            return DistractorResponse(distractors=ds)
        except BudgetExceeded:
            raise
        except Exception as e:
            return DistractorResponse(distractors=[], error=str(e))

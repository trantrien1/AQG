"""QuestionWriterAgent — Stage 1 của pipeline 3-stage.

Sinh stem + answer + reasoning + verifier hint (KHÔNG distractor).
DistractorAgent chạy sau, gắn distractor với misconception cụ thể.
"""
from __future__ import annotations

from .base import BaseAgent
from .messages import WriteRequest, WriteResponse
from ..writer import QuestionWriter
from ..llm_client import BudgetExceeded


class QuestionWriterAgent(BaseAgent):
    def __init__(self):
        super().__init__('writer', skills=[
            'question-writing',
            'bloom-taxonomy-alignment',
            'verifier-hint-authoring',
        ])
        self._writer = QuestionWriter(skill_instructions=self.skill_instructions())

    def run(self, request: WriteRequest) -> WriteResponse:
        errors: list[str] = []
        candidates = []
        try:
            candidates = self._writer.write(
                request.slot, request.context,
                num_samples=request.num_samples,
                feedback=request.feedback,
            )
        except BudgetExceeded:
            raise
        except Exception as e:
            errors.append(f'writer error: {e}')
        return WriteResponse(
            slot_id=request.slot['slot_id'],
            candidates=candidates,
            errors=errors,
        )

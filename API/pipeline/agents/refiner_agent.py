"""RefinerAgent — Iterative critique→correction loop (MCQG-SRefine).

Khi CriticAgent chấm candidate dưới ngưỡng nhưng không reject hẳn (ví dụ
quality 0.55, ngay sát threshold 0.6), RefinerAgent gọi LLM với rationale
từ multi-trait critic để CHỈNH LẠI candidate.

Loop được điều khiển bởi OrchestratorAgent: Refiner chạy 1-2 lần là dừng.
"""
from __future__ import annotations

from .base import BaseAgent
from .messages import RefineRequest, RefineResponse
from ..refiner import Refiner
from ..llm_client import BudgetExceeded


class RefinerAgent(BaseAgent):
    def __init__(self):
        super().__init__('refiner', skills=['question-refinement'])
        self._refiner = Refiner(skill_instructions=self.skill_instructions())

    def run(self, request: RefineRequest) -> RefineResponse:
        try:
            refined = self._refiner.refine(request.candidate, request.critique_traits)
            return RefineResponse(candidate=refined)
        except BudgetExceeded:
            raise
        except Exception as e:
            return RefineResponse(candidate=request.candidate, error=str(e))

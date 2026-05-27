"""QuestionGeneratorAgent - Fast Mode full MCQ generation.

One LLM call emits the stem, four options, answer key, explanation,
detailed-solution fields, source quote, and verifier payload. Deterministic
validators/verifiers decide acceptance after this agent.
"""
from __future__ import annotations

from .base import BaseAgent
from .messages import GenerateRequest, GenerateResponse
from ..generator import QuestionGenerator
from ..llm_client import BudgetExceeded
from ..rule_validator import first_issue_code, validate_candidate


class QuestionGeneratorAgent(BaseAgent):
    def __init__(self):
        # Fast Mode keeps generator instructions inline to avoid per-call skill
        # prompt bloat.
        super().__init__('question_generator', skills=[])
        self._generator = QuestionGenerator()

    def run(self, request: GenerateRequest) -> GenerateResponse:
        errors: list[str] = []
        candidates = []
        try:
            candidates = self._generator.generate_for_slot(
                request.slot,
                request.context,
                num_samples=request.num_samples,
            )
        except BudgetExceeded:
            raise
        except Exception as exc:
            errors.append(f'generator error: {exc}')

        valid = []
        for cand in candidates:
            issues = validate_candidate(cand, request.slot)
            if issues:
                errors.append(f'validator:{first_issue_code(issues)}: {issues}')
                continue
            valid.append(cand)

        return GenerateResponse(
            slot_id=request.slot['slot_id'],
            candidates=valid,
            errors=errors,
        )

"""CriticAgent — multi-trait rubric scoring (RMTS — NAACL 2025).

Thay scoring đơn lẻ bằng:
  1. Grounding (giữ): mọi sự kiện trong stem/answer/explanation phải có trong context
  2. Multi-trait quality: clarity / cognitive_depth / distractor_plausibility / answer_uniqueness
     Mỗi trait có rationale (1 câu) TRƯỚC, score sau (RMTS pattern).
  3. Aggregate quality = mean(traits)

Rationale từ multi-trait được orchestrator chuyển cho RefinerAgent khi candidate
ở ngưỡng có thể cải thiện (không reject hẳn).
"""
from __future__ import annotations

import copy
from typing import Any, Dict

from .base import BaseAgent
from .messages import CriticRequest, CriticResponse
from .. import grounding as gj
from .. import config as cfg


class CriticAgent(BaseAgent):
    """Hai chiều độc lập:

    1. Grounding (LLM + heuristic): mọi sự kiện có trong context.
    2. Multi-trait quality (LLM): rationale-before-score per trait.
    """

    def __init__(self):
        super().__init__('critic', skills=[
            'source-grounding',
            'rubric-critique',
            'curriculum-alignment',
        ])
        self._skill_instructions = self.skill_instructions()

    def run(self, request: CriticRequest) -> CriticResponse:
        c: Dict[str, Any] = copy.copy(request.candidate)
        annotations: Dict[str, Any] = {}

        # Heuristic guards — chỉ giữ lại check thực sự catch lỗi rõ ràng.
        # `unsupported_stem_numbers` từng reject câu math hợp lệ có ví dụ cụ
        # thể (a=6, b=8). Demote thành annotation; LLM grounding judge mới là
        # gate thực sự (theo nguyên tắc "agent judgment > heuristic rules").
        unsupported = gj.unsupported_stem_numbers(request.context, c)
        if unsupported:
            annotations['_unsupported_stem_numbers'] = unsupported
            # KHÔNG reject ở đây; grounding judge sẽ thấy và hạ điểm nếu cần.

        contradiction = gj.directional_contradiction(request.context, c)
        if contradiction:
            annotations['_grounding'] = 0.0
            annotations['_local_contradiction'] = contradiction
            return CriticResponse(
                annotations=annotations, rejected=True,
                reject_reason=f'local contradiction: {contradiction}',
            )

        trace = gj.distractor_context_trace(request.context, c)
        annotations['_distractor_context_trace'] = trace

        # --- Grounding ---
        try:
            g = gj.judge_grounding(
                request.context, c,
                skill_instructions=self._skill_instructions,
            )
            annotations['_grounding'] = g
            annotations['_quote_in_context'] = c.get('_quote_in_context')
            annotations['_unsupported_stem_numbers'] = c.get('_unsupported_stem_numbers')
            if g < cfg.GROUNDING_THRESHOLD:
                in_ctx = c.get('_quote_in_context')
                return CriticResponse(
                    annotations=annotations, rejected=True,
                    reject_reason=(
                        f'grounding={g:.2f} < {cfg.GROUNDING_THRESHOLD}'
                        + ('' if in_ctx else ' (quote không trong context)')
                    ),
                )
        except Exception as e:
            print(f'    [critic] grounding error: {e}')
            annotations['_grounding'] = None

        # --- Multi-trait quality (RMTS) ---
        try:
            mt = gj.judge_multi_trait(
                topic=request.topic,
                cognitive_level=request.cognitive_level,
                difficulty_target=request.candidate.get('_slot_difficulty_target', 0.5),
                response=c,
                skill_instructions=self._skill_instructions,
            )
            traits = mt['traits']
            q = mt['quality']
            annotations['_quality'] = q
            annotations['_quality_traits'] = traits  # cho Refiner sử dụng
            bloom_score = traits.get('bloom_alignment', {}).get('score', 1.0)
            annotations['_bloom_alignment'] = bloom_score
            if q < cfg.QUALITY_THRESHOLD:
                # Không reject hẳn nếu chỉ thấp do plausibility/clarity (Refiner có thể cứu);
                # nhưng nếu answer_uniqueness thấp → reject (multi-answer khả nghi).
                uniq = traits.get('answer_uniqueness', {}).get('score', 1.0)
                if uniq < 0.5:
                    return CriticResponse(
                        annotations=annotations, rejected=True,
                        reject_reason=(
                            f'quality={q:.2f}<{cfg.QUALITY_THRESHOLD}; '
                            f'uniqueness={uniq:.2f} (likely multi-answer)'
                        ),
                    )
                # Else: trả về với cờ refinable=True để Orchestrator gọi Refiner.
                annotations['_refinable'] = True
            elif q <= cfg.QUALITY_THRESHOLD + 0.05:
                annotations['_refinable'] = True
                annotations['_refine_reason'] = 'quality_close_to_threshold'
            elif bloom_score < 0.7:
                # Bloom lệch nghiêm trọng dù quality tổng OK → vẫn cần refine
                annotations['_refinable'] = True
                annotations['_refine_reason'] = 'bloom_alignment thấp'
        except Exception as e:
            print(f'    [critic] quality error: {e}')
            annotations['_quality'] = 0.5
            annotations['_quality_traits'] = {}

        return CriticResponse(annotations=annotations, rejected=False)

"""PlannerAgent - blueprint planning plus user-reviewable rich plans."""
from __future__ import annotations

import re
import secrets
import time
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from .messages import PlanRequest, PlanResponse
from ..blueprint import build_blueprint, summary as bp_summary
from ..context_utils import strip_markdown


class PlannerAgent(BaseAgent):
    """Decide question count, difficulty, source chunk, skill, and pattern."""

    def __init__(self):
        super().__init__('planner', skills=[
            'topic-keyword-extraction',
            'blueprint-planning',
            'bloom-taxonomy-alignment',
        ])

    def run(self, request: PlanRequest) -> PlanResponse:
        slots = build_blueprint(
            request.dataset,
            num_questions=request.num_questions,
            seed=request.seed,
            difficulty_distribution=request.difficulty_distribution,
            skill_instructions=self.skill_instructions(),
        )
        return PlanResponse(slots=slots, summary=bp_summary(slots))

    def build_rich_plan(
        self,
        dataset: Dict[str, Any],
        num_questions: int,
        seed: int = 42,
        difficulty_distribution: Optional[List[Dict[str, Any]]] = None,
        source: str = '',
    ) -> Dict[str, Any]:
        """Return a draft plan suitable for user review before generation.

        Each slot keeps the legacy generation keys at top level, while also
        exposing nested `source_chunk`, `question_spec`, and `distractor_spec`
        blocks for UI editing.
        """
        plan_resp = self.run(PlanRequest(
            dataset=dataset,
            num_questions=num_questions,
            seed=seed,
            difficulty_distribution=difficulty_distribution,
        ))
        slots = [
            self._rich_slot(slot, dataset.get(slot.get('doc_id', ''), {}))
            for slot in plan_resp.slots
        ]
        warning_details = self._plan_warnings(slots, dataset)
        now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        return {
            'plan_id': f'plan_{time.strftime("%Y%m%d_%H%M%S", time.gmtime())}_{secrets.token_hex(3)}',
            'source': source or (dataset.get('metadata', {}) or {}).get('source', ''),
            'total_questions': len(slots),
            'distribution': self._distribution(slots),
            'difficulty_distribution': self._difficulty_distribution(slots),
            'top_misconceptions': self._top_misconceptions(slots),
            'slots': slots,
            'warnings': [w.get('message', '') for w in warning_details if w.get('message')],
            'warning_details': warning_details,
            'plan_status': 'draft',
            'review_mode': 'summary',
            'created_at': now,
            'updated_at': now,
            'blueprint_summary': bp_summary(slots),
        }

    def _rich_slot(self, slot: Dict[str, Any],
                   doc: Dict[str, Any]) -> Dict[str, Any]:
        clean = doc.get('clean_context') if isinstance(doc.get('clean_context'), dict) else {}
        context = clean.get('clean_text') or doc.get('context', '') or ''
        topic = slot.get('topic') or clean.get('topic') or doc.get('topic') or ''
        misconceptions = [
            self._rich_misconception(m, i)
            for i, m in enumerate(slot.get('inferred_misconceptions') or [])
            if isinstance(m, dict)
        ]
        return {
            **slot,
            'source_chunk': {
                'doc_id': slot.get('doc_id'),
                'topic': topic,
                'pages': doc.get('pages', [])[:5],
                'excerpt': self._excerpt(context),
                'selected_context_ids': slot.get('selected_context_ids') or [],
                'context_quality': slot.get('context_quality') or clean.get('quality') or {},
            },
            'question_spec': {
                'cognitive_level': slot.get('cognitive_level'),
                'difficulty_target': slot.get('difficulty_target'),
                'question_type': slot.get('meta_pattern') or slot.get('question_pattern'),
                'skill_tested': slot.get('skill') or topic,
                'knowledge_focus': self._knowledge_focus(topic, slot, context),
                'rationale': self._slot_rationale(slot, context),
            },
            'distractor_spec': {
                'planned_misconceptions': misconceptions,
                'distractor_strategy': self._distractor_strategy(slot, misconceptions),
            },
            'status': 'pending_review',
        }

    @staticmethod
    def _excerpt(context: str, max_len: int = 420) -> str:
        text = strip_markdown(context)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) <= max_len:
            return text
        cut = text.rfind('.', 0, max_len)
        if cut < max_len * 0.55:
            cut = text.rfind(' ', 0, max_len)
        if cut < max_len * 0.55:
            cut = max_len
        return text[:cut].strip(' ,;:.') + '...'

    @staticmethod
    def _knowledge_focus(topic: str, slot: Dict[str, Any],
                         context: str) -> str:
        topic = (topic or '').strip()
        skill = (slot.get('skill') or '').strip()
        if topic and skill and topic.lower() not in skill.lower():
            return f'{topic}: {skill}'
        if skill:
            return skill
        if topic:
            return topic
        text = strip_markdown(context)
        m = re.search(
            r'\b(nguyên lý|quy tắc|qui tắc|tổ hợp|chỉnh hợp|định lý|hệ thức)\b.{0,80}',
            text,
            re.IGNORECASE,
        )
        if m:
            return re.sub(r'\s+', ' ', m.group(0)).strip()
        return str(slot.get('question_pattern') or '').replace('_', ' ')

    @staticmethod
    def _slot_rationale(slot: Dict[str, Any], context: str) -> str:
        text = strip_markdown(context).lower()
        signals = []
        if re.search(r'\b(ví dụ|lời giải|bài toán)\b', text):
            signals.append('có ví dụ/lời giải cụ thể')
        if re.search(r'\d|=|C\s*\(|\^|\bmod\b', text):
            signals.append('có dữ kiện hoặc công thức kiểm tra được')
        if slot.get('inferred_misconceptions'):
            signals.append('có misconception suy luận từ chunk')
        if not signals:
            signals.append('có nội dung nguồn trực tiếp để grounding')
        return (
            f"Chunk {slot.get('doc_id')} về \"{slot.get('topic', '')}\" "
            f"phù hợp mức {slot.get('cognitive_level')} vì " + ', '.join(signals) + '.'
        )

    @staticmethod
    def _rich_misconception(m: Dict[str, Any], idx: int) -> Dict[str, str]:
        mid = str(m.get('id') or f'm_{idx + 1}').strip()
        desc = str(m.get('wrong_form') or m.get('rationale') or mid).strip()
        rationale = str(m.get('rationale') or '').strip()
        text = f'{mid} {desc} {rationale}'.lower()
        if any(x in text for x in ('cộng', 'nhân', 'tính', 'sai số', 'formula')):
            dtype = 'computation_error'
        elif any(x in text for x in ('bỏ qua', 'điều kiện', 'ràng buộc', 'constraint')):
            dtype = 'missing_condition'
        elif any(x in text for x in ('nhầm', 'đọc', 'misread')):
            dtype = 'misread_problem'
        elif any(x in text for x in ('khái niệm', 'định nghĩa', 'concept')):
            dtype = 'conceptual_confusion'
        else:
            dtype = 'plausible_misconception'
        return {'id': mid, 'description': desc, 'distractor_type': dtype}

    @staticmethod
    def _distractor_strategy(slot: Dict[str, Any],
                             misconceptions: List[Dict[str, str]]) -> str:
        if misconceptions:
            return 'Mỗi distractor bám một misconception đã lên kế hoạch và cùng dạng với đáp án đúng.'
        pattern = str(slot.get('question_pattern') or '').lower()
        if 'count' in pattern or 'computation' in pattern:
            return 'Mỗi distractor là một kết quả tính toán sai ở đúng một bước.'
        return 'Mỗi distractor là một lựa chọn sai nhưng gần với khái niệm trong nguồn.'

    @staticmethod
    def _difficulty_distribution(slots: List[Dict[str, Any]]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for slot in slots:
            level = (
                slot.get('question_spec', {}).get('cognitive_level')
                or slot.get('cognitive_level')
                or 'unknown'
            )
            out[level] = out.get(level, 0) + 1
        return out

    @classmethod
    def _distribution(cls, slots: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
        by_topic: Dict[str, int] = {}
        by_type: Dict[str, int] = {}
        for slot in slots:
            topic = (
                slot.get('source_chunk', {}).get('topic')
                or slot.get('topic')
                or 'Chưa rõ chủ đề'
            )
            qtype = (
                slot.get('question_spec', {}).get('question_type')
                or slot.get('meta_pattern')
                or slot.get('question_pattern')
                or 'conceptual'
            )
            by_topic[topic] = by_topic.get(topic, 0) + 1
            by_type[qtype] = by_type.get(qtype, 0) + 1
        return {
            'by_topic': by_topic,
            'by_difficulty': cls._difficulty_distribution(slots),
            'by_type': by_type,
        }

    @staticmethod
    def _top_misconceptions(slots: List[Dict[str, Any]], limit: int = 8) -> List[str]:
        counts: Dict[str, int] = {}
        labels: Dict[str, str] = {}
        for slot in slots:
            for m in slot.get('distractor_spec', {}).get('planned_misconceptions', []):
                if not isinstance(m, dict):
                    continue
                key = (m.get('description') or m.get('id') or '').strip()
                if not key:
                    continue
                norm = key.lower()
                counts[norm] = counts.get(norm, 0) + 1
                labels.setdefault(norm, key)
        ranked = sorted(counts, key=lambda key: (-counts[key], labels[key]))
        return [labels[key] for key in ranked[:limit]]

    @staticmethod
    def _plan_warnings(slots: List[Dict[str, Any]],
                       dataset: Dict[str, Any]) -> List[Dict[str, str]]:
        warnings: List[Dict[str, str]] = []
        for slot in slots:
            doc = dataset.get(slot.get('doc_id'), {})
            context = strip_markdown(doc.get('context', '') or '')
            level = slot.get('cognitive_level') or ''
            has_example = re.search(r'\b(ví dụ|lời giải|bài toán)\b', context, re.I) is not None
            has_formula = re.search(r'\d|=|C\s*\(|\^|\bmod\b', context) is not None
            risk = slot.get('risk_warning') or ''
            if risk:
                warnings.append({
                    'slot_id': slot.get('slot_id', ''),
                    'type': 'weak_clean_context',
                    'message': f"Chunk {slot.get('doc_id')} có cảnh báo context: {risk}.",
                })
            if level == 'Vận dụng cao' and (len(context) < 700 or not (has_example and has_formula)):
                warnings.append({
                    'slot_id': slot.get('slot_id', ''),
                    'type': 'insufficient_content',
                    'message': (
                        f"Chunk {slot.get('doc_id')} có thể chưa đủ ví dụ/công thức "
                        'để sinh câu Vận dụng cao ổn định.'
                    ),
                })
        return warnings

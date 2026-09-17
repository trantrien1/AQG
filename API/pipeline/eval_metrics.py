"""Metric cho khung đánh giá — tính TỪ artifact của một run, không sinh số.

Nguyên tắc chi phối cả module:

* Metric nào cần biết đáp án ĐÚNG THẬT (correctness, false positive/negative của
  verifier) chỉ tính được khi có nhãn ngoài — kiểm bằng CAS độc lập hoặc chuyên
  gia người. Không có nhãn thì metric đó trả ``None`` kèm lý do, TUYỆT ĐỐI không
  thay bằng một proxy rồi gọi tên như thể là correctness.
* Metric đến từ LLM-judge được gắn hậu tố ``_judge`` để không bị đọc nhầm thành
  đo lường khách quan.
* Mọi tỉ lệ đều kèm tử số/mẫu số để người đọc tự kiểm và tự ghép lại.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .verification_status import VerificationStatus

#: Nhãn ngoài: question_id -> {'key_correct': bool, 'source': str, 'note': str}
GroundTruth = Dict[str, Dict[str, Any]]


@dataclass
class Ratio:
    """Một tỉ lệ luôn đi kèm tử/mẫu; ``value`` là None khi mẫu bằng 0."""

    numerator: int = 0
    denominator: int = 0
    unavailable_reason: str = ''

    @property
    def value(self) -> Optional[float]:
        if self.unavailable_reason or not self.denominator:
            return None
        return self.numerator / self.denominator

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            'value': round(self.value, 4) if self.value is not None else None,
            'n': self.numerator,
            'of': self.denominator,
        }
        if self.unavailable_reason:
            out['unavailable_reason'] = self.unavailable_reason
        return out


@dataclass
class RunMetrics:
    counts: Dict[str, Any] = field(default_factory=dict)
    verification: Dict[str, Any] = field(default_factory=dict)
    correctness: Dict[str, Any] = field(default_factory=dict)
    quality_judge: Dict[str, Any] = field(default_factory=dict)
    alignment: Dict[str, Any] = field(default_factory=dict)
    cost: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'counts': self.counts,
            'verification': self.verification,
            'correctness': self.correctness,
            'quality_judge': self.quality_judge,
            'alignment': self.alignment,
            'cost': self.cost,
        }


def _verification(record: Dict[str, Any]) -> Dict[str, Any]:
    return record.get('verification') or {}


def _status(record: Dict[str, Any]) -> str:
    status = _verification(record).get('status')
    if status in VerificationStatus.ALL:
        return status
    legacy = _verification(record).get('verified')
    engine = _verification(record).get('engine')
    if not engine or engine == 'none':
        return VerificationStatus.NON_VERIFIABLE
    if legacy is True:
        return VerificationStatus.CONSISTENCY_CONFIRMED
    if legacy is False:
        return VerificationStatus.MISMATCH
    return VerificationStatus.NON_VERIFIABLE


def _mean(values: Iterable[Any]) -> Optional[float]:
    nums = [float(v) for v in values if isinstance(v, (int, float))]
    return round(sum(nums) / len(nums), 4) if nums else None


def _trait(record: Dict[str, Any], name: str) -> Optional[float]:
    traits = (record.get('judging') or {}).get('quality_traits') or {}
    entry = traits.get(name)
    if isinstance(entry, dict):
        value = entry.get('score')
        return float(value) if isinstance(value, (int, float)) else None
    return float(entry) if isinstance(entry, (int, float)) else None


def compute_metrics(
    questions: List[Dict[str, Any]],
    rejected: Optional[List[Dict[str, Any]]] = None,
    *,
    ground_truth: Optional[GroundTruth] = None,
    cost: Optional[Dict[str, Any]] = None,
    duration_seconds: Optional[float] = None,
    requested: Optional[int] = None,
) -> RunMetrics:
    """Gom mọi metric của một run.

    ``ground_truth`` là nhãn NGOÀI (audit CAS độc lập hoặc chuyên gia). Thiếu nó
    thì nhóm ``correctness`` báo không tính được — đó là câu trả lời đúng, không
    phải lý do để thay bằng số khác.
    """
    rejected = rejected or []
    delivered = len(questions)
    candidates = delivered + len(rejected)
    metrics = RunMetrics()

    # ---- Đếm cơ bản ----
    metrics.counts = {
        'requested': requested,
        # "delivered" = qua hết cổng tự động. KHÔNG phải "được người duyệt".
        'pipeline_delivered': delivered,
        'rejected_candidates': len(rejected),
        'total_candidates': candidates,
        'admission_rate': Ratio(delivered, candidates).to_dict(),
        'delivery_rate_vs_requested': (
            Ratio(delivered, requested).to_dict() if requested else None
        ),
        'reject_reasons': dict(Counter(
            str(r.get('reject_reason_code') or r.get('reject_reason') or 'unknown')[:60]
            for r in rejected
        )),
        'review_status': dict(Counter(
            str(q.get('review_status') or 'unknown') for q in questions
        )),
    }

    # ---- Trạng thái kiểm chứng ----
    statuses = [_status(q) for q in questions]
    dist = Counter(statuses)
    machine_verifiable = sum(
        1 for q in questions
        if _verification(q).get('machine_verifiable')
        or _verification(q).get('engine') not in (None, '', 'none')
    )
    independent_attempted = sum(
        1 for q in questions
        if (_verification(q).get('independent') or {}).get('attempted')
    )
    independent_definite = sum(
        1 for q in questions
        if (_verification(q).get('independent') or {}).get('definite')
    )
    metrics.verification = {
        'status_distribution': {s: dist.get(s, 0) for s in VerificationStatus.ALL},
        # Bao nhiêu câu THUỘC DẠNG máy kiểm được — trần trên của mọi kiểm chứng.
        'machine_verifiable_coverage': Ratio(machine_verifiable, delivered).to_dict(),
        'conceptual_share': Ratio(delivered - machine_verifiable, delivered).to_dict(),
        'independent_target_attempted': Ratio(independent_attempted, delivered).to_dict(),
        'independent_target_definite': Ratio(independent_definite, delivered).to_dict(),
        # Tỉ lệ câu có bằng chứng ĐỘC LẬP. Đây KHÔNG phải tỉ lệ đáp án đúng:
        # nó chỉ nói hai nguồn tính toán tách biệt cùng ra một giá trị.
        'independently_verified_rate': Ratio(
            dist.get(VerificationStatus.INDEPENDENTLY_VERIFIED, 0), delivered,
        ).to_dict(),
        'consistency_only_rate': Ratio(
            dist.get(VerificationStatus.CONSISTENCY_CONFIRMED, 0), delivered,
        ).to_dict(),
        'routed_to_human_rate': Ratio(
            dist.get(VerificationStatus.MISMATCH, 0)
            + dist.get(VerificationStatus.REFUTED, 0),
            delivered,
        ).to_dict(),
        'answer_key_repaired': sum(
            1 for q in questions if _verification(q).get('answer_key_repaired')
        ),
        'verifier_hint_errored': sum(
            1 for q in questions if _verification(q).get('verifier_errored')
        ),
    }

    # ---- Correctness (cần nhãn ngoài) ----
    metrics.correctness = _correctness_metrics(questions, ground_truth)

    # ---- Điểm do LLM-judge chấm ----
    metrics.quality_judge = {
        'grounding_judge': _mean((q.get('judging') or {}).get('grounding') for q in questions),
        'overall_quality_judge': _mean((q.get('judging') or {}).get('quality') for q in questions),
        'answer_uniqueness_judge': _mean(_trait(q, 'answer_uniqueness') for q in questions),
        'distractor_plausibility_judge': _mean(
            _trait(q, 'distractor_plausibility') for q in questions),
        'error_value_consistency_judge': _mean(
            _trait(q, 'error_distractor_consistency') for q in questions),
        'clarity_judge': _mean(_trait(q, 'clarity') for q in questions),
        'cognitive_depth_judge': _mean(_trait(q, 'cognitive_depth') for q in questions),
        '_note': (
            'Mọi số trong nhóm này do một model chấm, không phải đo lường khách '
            'quan; đọc như ý kiến một giám khảo tự động, một lượt chấm.'
        ),
    }

    # ---- Bám mức Bloom / độ khó ----
    metrics.alignment = {
        'bloom_alignment_judge': _mean(
            (q.get('judging') or {}).get('bloom_alignment') for q in questions),
        'bloom_distribution': dict(Counter(
            str(q.get('cognitive_level') or '') for q in questions)),
        'difficulty_alignment_heuristic': _mean(
            q.get('difficulty_alignment') for q in questions),
        'difficulty_target_mean': _mean(q.get('difficulty_target') for q in questions),
        'difficulty_estimated_mean': _mean(q.get('difficulty_estimated') for q in questions),
        '_note': (
            'difficulty_estimated là ước lượng heuristic trước triển khai, chưa '
            'hiệu chỉnh trên dữ liệu học sinh thật.'
        ),
    }

    # ---- Chi phí ----
    cost = cost or {}
    tokens = cost.get('tokens')
    calls = cost.get('calls')
    metrics.cost = {
        'tokens': tokens,
        'model_calls': calls,
        'tokens_per_delivered': (
            round(tokens / delivered, 1) if tokens and delivered else None),
        'calls_per_delivered': (
            round(calls / delivered, 2) if calls and delivered else None),
        'duration_seconds': (
            round(duration_seconds, 1) if duration_seconds is not None else None),
        'seconds_per_delivered': (
            round(duration_seconds / delivered, 1)
            if duration_seconds is not None and delivered else None),
    }
    return metrics


def _correctness_metrics(
    questions: List[Dict[str, Any]],
    ground_truth: Optional[GroundTruth],
) -> Dict[str, Any]:
    """Correctness + sai số của verifier, CHỈ khi có nhãn ngoài."""
    reason = (
        'chưa có nhãn ground-truth ngoài (audit CAS độc lập hoặc chuyên gia '
        'người). Không có nhãn thì không tồn tại correctness rate — trạng thái '
        'kiểm chứng của pipeline không thay thế được.'
    )
    if not ground_truth:
        blank = Ratio(unavailable_reason=reason).to_dict()
        return {
            'labelled': 0,
            'independently_correct_answer_rate': blank,
            'verifier_false_positive_rate': blank,
            'verifier_false_negative_rate': blank,
            'ground_truth_source': None,
        }

    labelled = [q for q in questions if q.get('question_id') in ground_truth]
    correct = wrong = 0
    fp = fn = 0            # FP: cấp nhãn "đã kiểm" cho key SAI; FN: gắn cờ key ĐÚNG
    for q in labelled:
        label = ground_truth[q['question_id']]
        is_correct = bool(label.get('key_correct'))
        machine_checked = _status(q) in VerificationStatus.MACHINE_CHECKED
        flagged = _status(q) in VerificationStatus.NEEDS_HUMAN
        if is_correct:
            correct += 1
            if flagged:
                fn += 1
        else:
            wrong += 1
            if machine_checked:
                fp += 1
    sources = sorted({
        str(ground_truth[q['question_id']].get('source') or 'unknown')
        for q in labelled
    })
    return {
        'labelled': len(labelled),
        'unlabelled': len(questions) - len(labelled),
        'ground_truth_source': sources,
        'independently_correct_answer_rate':
            Ratio(correct, len(labelled)).to_dict(),
        # P(verifier nói "đã kiểm" | đáp án key SAI) — chính là tỉ lệ lọt lưới.
        'verifier_false_positive_rate': Ratio(fp, wrong).to_dict(),
        # P(verifier gắn cờ | đáp án key ĐÚNG) — tỉ lệ báo động giả.
        'verifier_false_negative_rate': Ratio(fn, correct).to_dict(),
        'wrong_keys': wrong,
        'correct_keys': correct,
    }


def load_ground_truth(path: str | Path) -> GroundTruth:
    """Đọc file nhãn ngoài.

    Định dạng::

        {"source": "cas_audit",
         "labels": {"q_2026_ab12cd34": {"key_correct": false,
                                        "note": "CAS cho 43/3, key ghi 47/3"}}}

    File này do CON NGƯỜI (hoặc script audit CAS độc lập) tạo ra. Pipeline không
    bao giờ tự ghi vào đây — nếu nó tự chấm mình thì nhãn hết là ground truth.
    """
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    source = data.get('source') or 'unknown'
    labels: GroundTruth = {}
    for qid, entry in (data.get('labels') or {}).items():
        if not isinstance(entry, dict) or 'key_correct' not in entry:
            raise ValueError(f'nhãn thiếu key_correct cho {qid}')
        labels[str(qid)] = {
            'key_correct': bool(entry['key_correct']),
            'source': entry.get('source') or source,
            'note': str(entry.get('note') or ''),
        }
    return labels


def metrics_from_run_file(
    path: str | Path,
    *,
    ground_truth: Optional[GroundTruth] = None,
) -> RunMetrics:
    """Tính metric từ một file artifact do `scripts/bench_b1.py` ghi ra."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    md = data.get('metadata') or {}
    return compute_metrics(
        data.get('questions') or [],
        data.get('rejected') or [],
        ground_truth=ground_truth,
        cost=md.get('cost') or {},
        duration_seconds=md.get('duration_seconds'),
        requested=md.get('requested_questions'),
    )

"""Đánh giá bởi giáo viên Toán — xuất phiếu ẩn nguồn, nhập lại, đo đồng thuận.

Module này KHÔNG sinh điểm. Nó chỉ:

1. xuất phiếu chấm đã **ẩn nguồn** (blind) và **xáo thứ tự** (randomised), kèm
   một file ánh xạ riêng mà người chấm không được xem;
2. đọc phiếu đã chấm về;
3. tính thống kê mô tả và **độ đồng thuận giữa các người chấm**.

Nếu chưa có phiếu nào được chấm, :func:`aggregate_ratings` báo lỗi rõ ràng thay
vì trả về số 0 hay số mặc định. Một bảng kết quả human evaluation chỉ được phép
tồn tại khi có người thật đã chấm.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: Sáu tiêu chí. Thứ tự này cũng là thứ tự hiển thị trên phiếu.
CRITERIA: Dict[str, str] = {
    'mathematical_correctness':
        'Đáp án và lời giải có đúng về mặt toán học không?',
    'clarity':
        'Đề bài có rõ ràng, không mơ hồ, không thiếu dữ kiện không?',
    'difficulty_appropriateness':
        'Độ khó có phù hợp với học sinh lớp 12 ở mức nhận thức đề ra không?',
    'distractor_plausibility':
        'Ba phương án nhiễu có hợp lý, gắn với lỗi học sinh hay mắc không?',
    'bloom_alignment':
        'Câu hỏi có đúng mức tư duy (Bloom) được ghi không?',
    'pedagogical_usefulness':
        'Bạn có sẵn sàng dùng câu này trong một bài kiểm tra thật không?',
}

#: Thang Likert mặc định. Đổi được, nhưng phải ghi vào phiếu để phân tích sau
#: biết đang đọc thang nào.
DEFAULT_SCALE = {
    'min': 1,
    'max': 5,
    'labels': {
        1: 'Rất kém / hoàn toàn không dùng được',
        2: 'Kém — cần sửa nhiều',
        3: 'Tạm được — cần sửa nhỏ',
        4: 'Tốt — dùng được gần như nguyên trạng',
        5: 'Rất tốt — dùng được ngay',
    },
}

#: Trường bị XOÁ khỏi phiếu chấm. Mỗi trường ở đây đều tiết lộ hoặc hệ thống
#: nào sinh ra câu hỏi, hoặc máy đã chấm nó thế nào — cả hai đều làm hỏng tính
#: mù của phiên đánh giá.
_BLINDED_FIELDS = (
    'verification', 'judging', 'quality_trace', 'agent_trace', 'review',
    'review_status', 'difficulty_estimated', 'difficulty_alignment',
    'difficulty_features', 'blueprint_slot_id', 'question_id', 'version',
    'discrimination', 'estimated_time_seconds', 'kc_ids',
    'explanation_per_distractor', 'why_others_wrong',
)


@dataclass
class BlindExport:
    """Kết quả xuất phiếu: phần công khai cho người chấm + phần bí mật giữ lại."""

    items: List[Dict[str, Any]] = field(default_factory=list)
    #: item_id -> {'question_id', 'system', 'run', 'source_index'}
    assignment: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    seed: int = 0
    scale: Dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_SCALE))


def build_blind_export(
    sources: Dict[str, Sequence[Dict[str, Any]]],
    *,
    seed: int = 20260725,
    include_explanation: bool = False,
    scale: Optional[Dict[str, Any]] = None,
) -> BlindExport:
    """Gộp câu hỏi từ nhiều hệ thống thành MỘT tập ẩn nguồn, xáo thứ tự.

    ``sources`` là ``{'tên hệ thống': [record, ...]}``. Tên hệ thống chỉ tồn tại
    trong phần ánh xạ bí mật; phiếu gửi cho giáo viên không mang dấu vết nào của
    nó, kể cả thứ tự (các nguồn được trộn lẫn).

    ``include_explanation`` mặc định False: cho người chấm xem lời giải của hệ
    thống sẽ neo họ theo lập luận đó khi chấm tính đúng đắn. Bật lên chỉ khi
    thiết kế nghiên cứu CỐ Ý muốn chấm cả phần giải thích.
    """
    rng = random.Random(seed)
    export = BlindExport(seed=seed, scale=dict(scale or DEFAULT_SCALE))

    pooled: List[Tuple[str, int, Dict[str, Any]]] = []
    for system, records in sources.items():
        for index, record in enumerate(records):
            pooled.append((system, index, record))
    rng.shuffle(pooled)

    for position, (system, index, record) in enumerate(pooled, start=1):
        item_id = f'item_{position:04d}'
        export.items.append(_blind_item(item_id, record, include_explanation))
        export.assignment[item_id] = {
            'question_id': record.get('question_id'),
            'system': system,
            'source_index': index,
        }
    return export


def _blind_item(item_id: str, record: Dict[str, Any],
                include_explanation: bool) -> Dict[str, Any]:
    options = [
        {'key': o.get('key'), 'text': o.get('text')}
        for o in (record.get('options') or [])
    ]
    item = {
        'item_id': item_id,
        'stem': record.get('stem', ''),
        'options': options,
        'answer_key': record.get('answer_key'),
        'cognitive_level': record.get('cognitive_level'),
        'topic': record.get('topic'),
        'source_quote': (record.get('source') or {}).get('quote', ''),
    }
    if include_explanation:
        item['explanation'] = record.get('explanation_correct', '')
    leaked = [f for f in _BLINDED_FIELDS if f in item]
    assert not leaked, f'phiếu chấm bị rò trường nội bộ: {leaked}'
    return item


def write_review_packet(
    export: BlindExport,
    out_dir: str | Path,
    reviewers: Sequence[str],
) -> Dict[str, Path]:
    """Ghi ra: 1 phiếu trống cho MỖI người chấm + 1 file ánh xạ bí mật.

    File ánh xạ (`_assignment_SECRET.json`) KHÔNG được gửi cho người chấm; tên
    file cố ý gây chú ý.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}

    for reviewer in reviewers:
        form = {
            'reviewer_id': reviewer,
            'instructions': _INSTRUCTIONS,
            'scale': export.scale,
            'criteria': CRITERIA,
            'ratings': [
                {
                    'item_id': item['item_id'],
                    'question': item,
                    'scores': {name: None for name in CRITERIA},
                    'comment': '',
                }
                for item in export.items
            ],
        }
        path = out / f'ratings_{reviewer}.json'
        path.write_text(json.dumps(form, ensure_ascii=False, indent=2),
                        encoding='utf-8')
        written[reviewer] = path

    secret = out / '_assignment_SECRET.json'
    secret.write_text(json.dumps({
        'seed': export.seed,
        'note': 'KHÔNG gửi file này cho người chấm — nó lộ hệ thống nguồn.',
        'assignment': export.assignment,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    written['_assignment'] = secret
    return written


_INSTRUCTIONS = (
    'Bạn sẽ chấm một tập câu hỏi trắc nghiệm Toán lớp 12. Các câu đến từ nhiều '
    'nguồn khác nhau và đã được xáo thứ tự; bạn KHÔNG được cho biết nguồn của '
    'từng câu và cũng không nên đoán. Với mỗi câu, cho điểm từng tiêu chí theo '
    'thang đã ghi và viết ghi chú nếu cần. Nếu một tiêu chí không áp dụng được '
    'cho câu đó, để trống (null) thay vì cho điểm trung bình.'
)


# ============ Nhập phiếu + thống kê ============

class NoRatingsError(RuntimeError):
    """Chưa có phiếu nào được chấm — không có gì để tổng hợp."""


def load_ratings(paths: Iterable[str | Path]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Đọc phiếu đã chấm → {reviewer_id: {item_id: {criterion: score}}}."""
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for path in paths:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        reviewer = str(data.get('reviewer_id') or Path(path).stem)
        per_item: Dict[str, Dict[str, Any]] = {}
        for row in data.get('ratings') or []:
            scores = {
                name: value
                for name, value in (row.get('scores') or {}).items()
                if isinstance(value, (int, float))
            }
            if scores:
                per_item[str(row.get('item_id'))] = scores
        out[reviewer] = per_item
    return out


def aggregate_ratings(
    ratings: Dict[str, Dict[str, Dict[str, Any]]],
    *,
    assignment: Optional[Dict[str, Dict[str, Any]]] = None,
    scale: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Thống kê mô tả + đồng thuận giữa người chấm.

    Raise :class:`NoRatingsError` nếu không có điểm nào — đây là hành vi cố ý:
    một bảng human-evaluation rỗng phải làm pipeline báo cáo dừng lại, chứ không
    được lặng lẽ in ra số 0 rồi bị đọc thành kết quả.
    """
    scale = scale or DEFAULT_SCALE
    reviewers = [r for r, items in ratings.items() if items]
    if not reviewers:
        raise NoRatingsError(
            'Không có phiếu nào được chấm. Human evaluation chưa chạy — không '
            'có số nào để báo cáo.'
        )

    summary: Dict[str, Any] = {
        'reviewers': sorted(reviewers),
        'n_reviewers': len(reviewers),
        'scale': scale,
        'per_criterion': {},
        'per_reviewer': {},
        'coverage': {},
    }

    all_items = sorted({item for items in ratings.values() for item in items})
    summary['coverage'] = {
        'items_rated': len(all_items),
        'items_rated_by_all': sum(
            1 for item in all_items
            if all(item in ratings[r] for r in reviewers)
        ),
    }

    for criterion in CRITERIA:
        per_item_scores: Dict[str, List[float]] = {}
        for reviewer in reviewers:
            for item, scores in ratings[reviewer].items():
                if criterion in scores:
                    per_item_scores.setdefault(item, []).append(float(scores[criterion]))
        flat = [s for scores in per_item_scores.values() for s in scores]
        entry: Dict[str, Any] = {
            'n_ratings': len(flat),
            'n_items': len(per_item_scores),
            'mean': round(sum(flat) / len(flat), 3) if flat else None,
            'sd': round(_stdev(flat), 3) if len(flat) > 1 else None,
            'ci95': _mean_ci95(flat),
            'distribution': _distribution(flat, scale),
        }
        entry['agreement'] = inter_rater_agreement(
            {r: {i: s[criterion] for i, s in ratings[r].items() if criterion in s}
             for r in reviewers}
        )
        summary['per_criterion'][criterion] = entry

    for reviewer in reviewers:
        flat = [float(v) for scores in ratings[reviewer].values()
                for v in scores.values()]
        summary['per_reviewer'][reviewer] = {
            'items': len(ratings[reviewer]),
            'mean': round(sum(flat) / len(flat), 3) if flat else None,
        }

    if assignment:
        summary['per_system'] = _per_system(ratings, assignment)
    return summary


def _per_system(
    ratings: Dict[str, Dict[str, Dict[str, Any]]],
    assignment: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Bóc mù SAU KHI đã chấm: gộp điểm theo hệ thống nguồn."""
    buckets: Dict[str, Dict[str, List[float]]] = {}
    for items in ratings.values():
        for item, scores in items.items():
            system = str((assignment.get(item) or {}).get('system') or 'unknown')
            bucket = buckets.setdefault(system, {})
            for criterion, value in scores.items():
                bucket.setdefault(criterion, []).append(float(value))
    return {
        system: {
            criterion: {
                'mean': round(sum(vals) / len(vals), 3),
                'n': len(vals),
                'ci95': _mean_ci95(vals),
            }
            for criterion, vals in sorted(criteria.items())
        }
        for system, criteria in sorted(buckets.items())
    }


# ============ Đồng thuận giữa người chấm ============

def inter_rater_agreement(
    by_reviewer: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    """Đồng thuận cho MỘT tiêu chí.

    Trả về Krippendorff's alpha (thang thứ bậc — hợp với Likert), tỉ lệ trùng
    khít, và Cohen's kappa có trọng số bậc hai khi đúng hai người chấm.
    """
    units: Dict[str, List[float]] = {}
    for scores in by_reviewer.values():
        for item, value in scores.items():
            units.setdefault(item, []).append(float(value))
    overlapping = {u: vs for u, vs in units.items() if len(vs) >= 2}
    result: Dict[str, Any] = {
        'n_units_with_multiple_ratings': len(overlapping),
        'krippendorff_alpha_ordinal': None,
        'exact_agreement': None,
        'cohen_kappa_quadratic': None,
    }
    if not overlapping:
        result['note'] = (
            'không có câu nào được từ hai người trở lên chấm — chưa tính được '
            'độ đồng thuận'
        )
        return result

    result['krippendorff_alpha_ordinal'] = _krippendorff_alpha_ordinal(overlapping)
    exact = sum(1 for vs in overlapping.values() if len(set(vs)) == 1)
    result['exact_agreement'] = round(exact / len(overlapping), 4)

    reviewers = [r for r in by_reviewer if by_reviewer[r]]
    if len(reviewers) == 2:
        a, b = reviewers
        pairs = [
            (by_reviewer[a][item], by_reviewer[b][item])
            for item in sorted(set(by_reviewer[a]) & set(by_reviewer[b]))
        ]
        result['cohen_kappa_quadratic'] = _cohen_kappa_quadratic(pairs)
    return result


def _krippendorff_alpha_ordinal(units: Dict[str, List[float]]) -> Optional[float]:
    """Krippendorff's alpha với hàm khoảng cách thứ bậc.

    Dùng ma trận trùng hợp (coincidence matrix) nên chịu được số người chấm
    khác nhau giữa các câu và dữ liệu khuyết.
    """
    values = sorted({v for vs in units.values() for v in vs})
    if len(values) < 2:
        # Mọi người cho cùng một điểm ở mọi câu: không có phương sai để chia.
        return None
    index = {v: i for i, v in enumerate(values)}
    size = len(values)

    coincidence = [[0.0]*size for _ in range(size)]
    for vs in units.values():
        m = len(vs)
        if m < 2:
            continue
        for i, vi in enumerate(vs):
            for j, vj in enumerate(vs):
                if i == j:
                    continue
                coincidence[index[vi]][index[vj]] += 1.0 / (m - 1)

    n_c = [sum(row) for row in coincidence]
    n = sum(n_c)
    if n <= 1:
        return None

    def delta2(c: int, k: int) -> float:
        lo, hi = (c, k) if c <= k else (k, c)
        inner = sum(n_c[lo:hi + 1]) - (n_c[c] + n_c[k]) / 2.0
        return inner * inner

    observed = sum(
        coincidence[c][k] * delta2(c, k)
        for c in range(size) for k in range(size)
    )
    expected = sum(
        n_c[c] * (n_c[k] - (1 if c == k else 0)) / (n - 1) * delta2(c, k)
        for c in range(size) for k in range(size)
    )
    if expected == 0:
        return None
    return round(1.0 - observed / expected, 4)


def _cohen_kappa_quadratic(pairs: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Cohen's kappa trọng số bậc hai — hợp với thang thứ bậc."""
    if len(pairs) < 2:
        return None
    values = sorted({v for pair in pairs for v in pair})
    if len(values) < 2:
        return None
    index = {v: i for i, v in enumerate(values)}
    size = len(values)
    total = len(pairs)

    observed = [[0.0]*size for _ in range(size)]
    row_marg = [0.0]*size
    col_marg = [0.0]*size
    for a, b in pairs:
        observed[index[a]][index[b]] += 1
        row_marg[index[a]] += 1
        col_marg[index[b]] += 1

    def weight(i: int, j: int) -> float:
        return ((i - j) ** 2) / ((size - 1) ** 2)

    num = sum(weight(i, j) * observed[i][j]
              for i in range(size) for j in range(size))
    den = sum(weight(i, j) * row_marg[i] * col_marg[j] / total
              for i in range(size) for j in range(size))
    if den == 0:
        return None
    return round(1.0 - num / den, 4)


# ============ Tiện ích thống kê ============

def _stdev(values: Sequence[float]) -> float:
    n = len(values)
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


def _mean_ci95(values: Sequence[float]) -> Optional[List[float]]:
    """Khoảng tin cậy 95% của trung bình (xấp xỉ chuẩn).

    Trả None khi n < 2 — với cỡ mẫu đó thì khoảng tin cậy vô nghĩa và in ra chỉ
    tạo cảm giác chắc chắn giả.
    """
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    half = 1.96 * _stdev(values) / math.sqrt(n)
    return [round(mean - half, 3), round(mean + half, 3)]


def _distribution(values: Sequence[float], scale: Dict[str, Any]) -> Dict[str, int]:
    lo, hi = int(scale.get('min', 1)), int(scale.get('max', 5))
    counts = {str(v): 0 for v in range(lo, hi + 1)}
    for value in values:
        key = str(int(round(value)))
        counts[key] = counts.get(key, 0) + 1
    return counts

"""Hiệu chỉnh ngưỡng trên tập validation do NGƯỜI gán nhãn.

Mọi ngưỡng quyết định của pipeline hiện là số chọn tay. Module này dò lại chúng
trên một tập câu hỏi đã có nhãn người (dùng được / không dùng được) và báo cáo
giá trị đề xuất kèm ma trận nhầm lẫn ở từng mức.

Nó KHÔNG tự ghi đè config: kết quả là một bản đề xuất để người đọc rồi quyết
định, vì đổi ngưỡng làm mọi số liệu cũ không còn so sánh được.

Giới hạn thành thật: với vài chục nhãn, ngưỡng dò được sẽ khớp quá mức vào chính
tập đó. :func:`calibrate` luôn kèm cảnh báo cỡ mẫu và, khi đủ dữ liệu, một ước
lượng kiểm chéo (cross-validated) bên cạnh giá trị khớp toàn tập.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import config as cfg

#: Ngưỡng → cách lấy điểm tương ứng từ một record. Thêm ngưỡng mới thì thêm
#: một dòng ở đây, không phải sửa thuật toán dò.
SCORE_ACCESSORS: Dict[str, Callable[[Dict[str, Any]], Optional[float]]] = {
    'QUALITY_THRESHOLD':
        lambda r: _num((r.get('judging') or {}).get('quality')),
    'GROUNDING_THRESHOLD':
        lambda r: _num((r.get('judging') or {}).get('grounding')),
    'ANSWER_UNIQUENESS_THRESHOLD':
        lambda r: _trait(r, 'answer_uniqueness'),
    'ERROR_VALUE_CONSISTENCY_THRESHOLD':
        lambda r: _trait(r, 'error_distractor_consistency'),
}

#: Ngưỡng có trong config nhưng CHƯA dò được từ artifact hiện tại, kèm lý do.
#: Ghi ra để bản báo cáo không im lặng bỏ qua chúng.
NOT_YET_CALIBRATABLE: Dict[str, str] = {
    'DISTRACTOR_SIMILARITY_THRESHOLD':
        'record không lưu ma trận cosine giữa các phương án nhiễu',
    'QUESTION_DEDUP_THRESHOLD':
        'record không lưu điểm tương đồng ngữ nghĩa với câu đã có',
    'LEXICAL_DEDUP_THRESHOLD':
        'record không lưu điểm trùng lặp từ ngữ với câu đã có',
    'VERIFICATION_REL_TOLERANCE':
        'không phải ngưỡng chấp nhận/loại — cần thí nghiệm riêng về sai số số học',
}

#: Dưới mức này, ngưỡng dò được coi như không có ý nghĩa thống kê.
MIN_LABELS_FOR_CALIBRATION = 30


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def _trait(record: Dict[str, Any], name: str) -> Optional[float]:
    traits = (record.get('judging') or {}).get('quality_traits') or {}
    entry = traits.get(name)
    if isinstance(entry, dict):
        return _num(entry.get('score'))
    return _num(entry)


@dataclass
class ThresholdFit:
    name: str
    current: Optional[float]
    suggested: Optional[float] = None
    objective: str = 'f1'
    best_score: Optional[float] = None
    n_labelled: int = 0
    n_usable: int = 0
    curve: List[Dict[str, Any]] = field(default_factory=list)
    cross_validated: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'current': self.current,
            'suggested': self.suggested,
            'objective': self.objective,
            'best_score': self.best_score,
            'n_labelled': self.n_labelled,
            'n_usable': self.n_usable,
            'curve': self.curve,
            'cross_validated': self.cross_validated,
            'warnings': self.warnings,
        }


def load_validation_set(path: str | Path) -> List[Dict[str, Any]]:
    """Đọc tập validation.

    Định dạng::

        {"source": "expert_review",
         "items": [{"record": {...}, "usable": true, "note": "..."}, ...]}

    ``usable`` là phán quyết của NGƯỜI: câu này có dùng được không. ``record`` là
    bản ghi câu hỏi như pipeline xuất ra (để lấy các điểm số đã chấm).
    """
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    items = []
    for entry in data.get('items') or []:
        if 'usable' not in entry or 'record' not in entry:
            raise ValueError('mỗi item cần có "record" và "usable"')
        items.append({
            'record': entry['record'],
            'usable': bool(entry['usable']),
            'note': str(entry.get('note') or ''),
        })
    return items


def calibrate(
    validation_items: Sequence[Dict[str, Any]],
    *,
    thresholds: Optional[Sequence[str]] = None,
    objective: str = 'f1',
    folds: int = 5,
) -> Dict[str, Any]:
    """Dò lại từng ngưỡng trên tập validation.

    Quy ước: điểm CAO = tốt, nên luật giữ câu là ``score >= threshold``. Ngưỡng
    tốt nhất là ngưỡng tối ưu ``objective`` khi coi "người nói dùng được" là lớp
    dương.
    """
    names = list(thresholds or SCORE_ACCESSORS)
    report: Dict[str, Any] = {
        'n_items': len(validation_items),
        'objective': objective,
        'thresholds': {},
        'not_yet_calibratable': dict(NOT_YET_CALIBRATABLE),
        'warnings': [],
    }
    if len(validation_items) < MIN_LABELS_FOR_CALIBRATION:
        report['warnings'].append(
            f'chỉ có {len(validation_items)} nhãn (< {MIN_LABELS_FOR_CALIBRATION}): '
            f'ngưỡng dò ra sẽ khớp quá mức vào chính tập này, chỉ nên đọc như '
            f'gợi ý định hướng'
        )

    for name in names:
        accessor = SCORE_ACCESSORS.get(name)
        if accessor is None:
            report['thresholds'][name] = ThresholdFit(
                name=name, current=getattr(cfg, name, None),
                warnings=[NOT_YET_CALIBRATABLE.get(name, 'chưa hỗ trợ dò')],
            ).to_dict()
            continue
        report['thresholds'][name] = _fit_threshold(
            name, accessor, validation_items, objective, folds,
        ).to_dict()
    return report


def _fit_threshold(
    name: str,
    accessor: Callable[[Dict[str, Any]], Optional[float]],
    items: Sequence[Dict[str, Any]],
    objective: str,
    folds: int,
) -> ThresholdFit:
    fit = ThresholdFit(name=name, current=getattr(cfg, name, None),
                       objective=objective, n_labelled=len(items))
    samples: List[Tuple[float, bool]] = []
    for entry in items:
        score = accessor(entry['record'])
        if score is not None:
            samples.append((score, bool(entry['usable'])))
    fit.n_usable = len(samples)
    if len(samples) < 2:
        fit.warnings.append('không đủ record có điểm số cho ngưỡng này')
        return fit
    if len({label for _s, label in samples}) < 2:
        fit.warnings.append('tập nhãn chỉ có một lớp — không dò được ngưỡng')
        return fit

    best_value, best_score, curve = _sweep(samples, objective)
    fit.suggested = best_value
    fit.best_score = best_score
    fit.curve = curve

    if len(samples) >= max(MIN_LABELS_FOR_CALIBRATION, folds * 2):
        fit.cross_validated = _cross_validate(samples, objective, folds)
    else:
        fit.warnings.append('quá ít mẫu để kiểm chéo')
    return fit


def _candidate_thresholds(samples: Sequence[Tuple[float, bool]]) -> List[float]:
    values = sorted({round(s, 4) for s, _ in samples})
    # Đặt ngưỡng giữa hai giá trị quan sát liền kề để không phụ thuộc vào việc
    # một điểm cụ thể nằm bên nào của dấu >=.
    mids = [round((a + b) / 2, 4) for a, b in zip(values, values[1:])]
    return sorted({values[0], *mids, values[-1]})


def _confusion(samples: Sequence[Tuple[float, bool]],
               threshold: float) -> Tuple[int, int, int, int]:
    tp = fp = tn = fn = 0
    for score, usable in samples:
        kept = score >= threshold
        if kept and usable:
            tp += 1
        elif kept and not usable:
            fp += 1
        elif not kept and usable:
            fn += 1
        else:
            tn += 1
    return tp, fp, tn, fn


def _objective_value(objective: str, tp: int, fp: int, tn: int, fn: int) -> float:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if objective == 'precision':
        return precision
    if objective == 'recall':
        return recall
    if objective == 'youden':
        specificity = tn / (tn + fp) if (tn + fp) else 0.0
        return recall + specificity - 1.0
    if objective == 'accuracy':
        total = tp + fp + tn + fn
        return (tp + tn) / total if total else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _sweep(samples: Sequence[Tuple[float, bool]],
           objective: str) -> Tuple[float, float, List[Dict[str, Any]]]:
    curve: List[Dict[str, Any]] = []
    best_value, best_score = None, -1.0
    for threshold in _candidate_thresholds(samples):
        tp, fp, tn, fn = _confusion(samples, threshold)
        score = _objective_value(objective, tp, fp, tn, fn)
        curve.append({
            'threshold': threshold, 'objective': round(score, 4),
            'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
        })
        # Hoà điểm thì chọn ngưỡng THẤP hơn: giữ lại nhiều câu hơn, để phần
        # quyết định cuối cho người duyệt thay vì im lặng loại bớt.
        if score > best_score:
            best_value, best_score = threshold, score
    return float(best_value), round(best_score, 4), curve


def _cross_validate(samples: Sequence[Tuple[float, bool]],
                    objective: str, folds: int) -> Dict[str, Any]:
    """Dò ngưỡng trên k-1 phần, chấm trên phần còn lại."""
    ordered = sorted(samples, key=lambda s: s[0])
    buckets: List[List[Tuple[float, bool]]] = [[] for _ in range(folds)]
    for i, sample in enumerate(ordered):
        buckets[i % folds].append(sample)

    held_out_scores: List[float] = []
    chosen: List[float] = []
    for k in range(folds):
        test = buckets[k]
        train = [s for j, bucket in enumerate(buckets) if j != k for s in bucket]
        if not test or not train or len({lab for _s, lab in train}) < 2:
            continue
        threshold, _score, _curve = _sweep(train, objective)
        tp, fp, tn, fn = _confusion(test, threshold)
        held_out_scores.append(_objective_value(objective, tp, fp, tn, fn))
        chosen.append(threshold)
    if not held_out_scores:
        return {'folds': 0, 'note': 'không chia được fold hợp lệ'}
    mean = sum(held_out_scores) / len(held_out_scores)
    return {
        'folds': len(held_out_scores),
        'mean_held_out_objective': round(mean, 4),
        'thresholds_per_fold': [round(t, 4) for t in chosen],
        'threshold_spread': round(max(chosen) - min(chosen), 4),
    }


def render_report(report: Dict[str, Any]) -> str:
    """Bản Markdown gọn để dán vào ghi chép — không tự áp dụng gì cả."""
    lines = [
        '# Hiệu chỉnh ngưỡng',
        '',
        f"Tập validation: {report['n_items']} câu có nhãn người. "
        f"Hàm mục tiêu: `{report['objective']}`.",
        '',
    ]
    for warning in report.get('warnings') or []:
        lines.append(f'> ⚠ {warning}')
    lines += ['', '| Ngưỡng | Đang dùng | Đề xuất | Mục tiêu | n | Ghi chú |',
              '|---|---|---|---|---|---|']
    for name, fit in report['thresholds'].items():
        note = '; '.join(fit.get('warnings') or []) or ''
        cv = fit.get('cross_validated') or {}
        if cv.get('mean_held_out_objective') is not None:
            note = (f"kiểm chéo {cv['folds']} fold: "
                    f"{cv['mean_held_out_objective']}; " + note).strip('; ')
        lines.append(
            f"| `{name}` | {fit.get('current')} | {fit.get('suggested')} | "
            f"{fit.get('best_score')} | {fit.get('n_usable')} | {note} |"
        )
    lines += ['', '## Chưa dò được', '']
    for name, reason in (report.get('not_yet_calibratable') or {}).items():
        lines.append(f'- `{name}` — {reason}')
    lines += [
        '',
        'Không ngưỡng nào được áp dụng tự động. Đổi ngưỡng làm mọi số liệu đã '
        'công bố không còn so sánh được, nên phải là một quyết định có ý thức.',
        '',
    ]
    return '\n'.join(lines)

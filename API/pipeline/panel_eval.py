"""Đánh giá hội đồng solver độc lập trên các câu ĐÃ CÓ NHÃN audit CAS.

Trả lời câu hỏi mà một lần sinh câu hỏi không trả lời được: khi đáp án key SAI,
solver độc lập có tái tạo đúng giá trị sai đó không (lỗi tương quan), và việc
đòi đồng thuận giữa các họ model khác nhau đổi tỉ lệ "key sai vẫn được cấp
nhãn" ra sao — với bao nhiêu câu đúng bị mất nhãn làm cái giá.

Module này thuần tính toán: nạp câu + nhãn từ artifact, nhận các
:class:`IndependentTarget` đã có (do script replay gọi model, hoặc đọc lại từ
artifact), rồi chạy ĐÚNG hàm gộp và hàm phân xử của pipeline. Không gọi model.
"""
from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .independent_target import (
    IndependentTarget, aggregate_panel, consensus_size, is_derivation,
    parse_answer_value, values_agree,
)
from .model_family import model_family
from .verification_status import VerificationStatus, adjudicate


# ============ Thống kê ============

def wilson_interval(k: int, n: int, z: float = 1.96) -> Optional[Tuple[float, float]]:
    """Khoảng Wilson 95% cho tỉ lệ k/n; None khi n = 0."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k: int, n: int) -> Dict[str, Any]:
    ci = wilson_interval(k, n)
    return {
        'n': k, 'of': n,
        'value': round(k / n, 4) if n else None,
        'ci95': [round(ci[0], 4), round(ci[1], 4)] if ci else None,
    }


def cohen_kappa_binary(pairs: Sequence[Tuple[bool, bool]]) -> Optional[float]:
    """Cohen's κ cho hai nhãn nhị phân; None khi không đủ dữ liệu/biến thiên."""
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    pa = sum(1 for a, _ in pairs if a) / n
    pb = sum(1 for _, b in pairs if b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


# ============ Nạp câu đã có nhãn ============

@dataclass
class LabelledItem:
    item_id: str
    run: str
    stem: str
    key_correct: bool
    key_value: Optional[float]
    distractor_values: List[Optional[float]]
    writer_verified: Optional[bool]
    writer_engine: str
    original_status: str = ''
    question_id: str = ''
    recorded: Optional[Dict[str, Any]] = None
    generator: str = ''
    note: str = ''


@dataclass
class RunSource:
    """Một run đã audit: nơi đọc câu hỏi + nơi đọc nhãn."""

    name: str
    root: str
    #: glob tương đối với root, đọc theo thứ tự đường dẫn POSIX đã sort
    pattern: str
    labels: str
    #: 'question_id' — nhãn khoá theo question_id (định dạng ground_truth_cas);
    #: 'index' — khoá theo số thứ tự 1-based qua mọi file (định dạng cas_verdicts)
    keyed_by: str
    generator: str = 'gpt-4o'
    expected_items: Optional[int] = None


#: Ba run đã audit trong bài báo (Run A/B/C).
DEFAULT_SOURCES: Tuple[RunSource, ...] = (
    RunSource('run_a', 'report/bench/20260724-b1-postparse', 'b1_file_*.json',
              'ground_truth_cas.json', 'question_id', expected_items=40),
    RunSource('run_b', 'report/bench/suite-20260725', 'full_system/seed*/*.json',
              'ground_truth_cas.json', 'question_id', expected_items=89),
    RunSource('run_c', 'report/bench/suite-20260730', 'full_system/seed*/*.json',
              'cas_verdicts.json', 'index', expected_items=187),
)


def _run_questions(root: Path, pattern: str) -> List[Dict[str, Any]]:
    files = sorted(
        (p for p in root.glob(pattern)
         if not p.name.endswith('.manifest.json') and not p.name.endswith('_summary.json')),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    questions: List[Dict[str, Any]] = []
    for path in files:
        data = json.loads(path.read_text(encoding='utf-8'))
        questions.extend(data.get('questions') or [])
    return questions


def _labels(path: Path, keyed_by: str) -> Dict[str, Dict[str, Any]]:
    data = json.loads(path.read_text(encoding='utf-8'))
    if keyed_by == 'index':
        return {str(k): v for k, v in (data.get('verdicts') or {}).items()}
    return {str(k): v for k, v in (data.get('labels') or {}).items()}


def option_values(record: Dict[str, Any]) -> Tuple[Optional[float], List[Optional[float]]]:
    key = record.get('answer_key')
    keyed: Optional[float] = None
    others: List[Optional[float]] = []
    for option in record.get('options') or []:
        value = parse_answer_value(str(option.get('text') or ''))
        if option.get('key') == key:
            keyed = value
        else:
            others.append(value)
    return keyed, others


def load_labelled_items(
    api_root: str | Path,
    sources: Iterable[RunSource] = DEFAULT_SOURCES,
) -> List[LabelledItem]:
    """Mọi câu có nhãn key_correct trong các run đã audit."""
    api_root = Path(api_root)
    items: List[LabelledItem] = []
    for src in sources:
        root = api_root / src.root
        questions = _run_questions(root, src.pattern)
        if src.expected_items is not None and len(questions) != src.expected_items:
            raise ValueError(
                f'{src.name}: đọc được {len(questions)} câu, mong đợi '
                f'{src.expected_items} — thứ tự đánh số nhãn không còn tin được')
        labels = _labels(root / src.labels, src.keyed_by)
        for index, record in enumerate(questions, start=1):
            key = (str(index) if src.keyed_by == 'index'
                   else str(record.get('question_id')))
            label = labels.get(key)
            if not isinstance(label, dict) or 'key_correct' not in label:
                continue
            verification = record.get('verification') or {}
            keyed, others = option_values(record)
            recorded = verification.get('independent')
            items.append(LabelledItem(
                item_id=f'{src.name}:{index:03d}',
                run=src.name,
                stem=str(record.get('stem') or ''),
                key_correct=bool(label['key_correct']),
                key_value=keyed,
                distractor_values=others,
                writer_verified=verification.get('verified'),
                writer_engine=str(verification.get('engine') or 'none'),
                original_status=str(verification.get('status') or ''),
                question_id=str(record.get('question_id') or ''),
                recorded=(recorded if isinstance(recorded, dict)
                          and recorded.get('attempted') else None),
                generator=src.generator,
                note=str(label.get('note') or '')[:200],
            ))
    return items


def target_from_dict(raw: Optional[Dict[str, Any]]) -> Optional[IndependentTarget]:
    if not isinstance(raw, dict):
        return None
    known = set(IndependentTarget.__dataclass_fields__)
    target = IndependentTarget(**{k: v for k, v in raw.items() if k in known})
    if 'derivation' not in raw and target.definite:
        # Artifact ghi trước khi có luật "phải có phép tính": suy lại cờ từ
        # biểu thức bằng đúng hàm pipeline hiện dùng.
        target.derivation = is_derivation(target.expression)
    return target


# ============ Phân tích ============

Targets = Dict[str, Dict[str, IndependentTarget]]   # solver -> item_id -> target


def outcome(target: Optional[IndependentTarget], key_value: Optional[float]) -> str:
    """missing | error | abstain | no_key_value | agree | disagree."""
    if target is None:
        return 'missing'
    if target.source == 'error':
        return 'error'
    if not target.definite or target.value is None:
        return 'abstain'
    if key_value is None:
        return 'no_key_value'
    return 'agree' if values_agree(target.value, key_value) else 'disagree'


def solver_summary(items: List[LabelledItem], targets: Targets,
                   solver: str) -> Dict[str, Any]:
    by_solver = targets.get(solver) or {}
    wrong = [i for i in items if not i.key_correct and i.item_id in by_solver]
    right = [i for i in items if i.key_correct and i.item_id in by_solver]

    def _count(group: List[LabelledItem], name: str) -> int:
        return sum(1 for i in group if outcome(by_solver[i.item_id], i.key_value) == name)

    models = sorted({t.model for t in by_solver.values() if t.model})
    return {
        'solver': solver,
        'models': models,
        'families': sorted({model_family(m) for m in models}),
        'items': len(by_solver),
        'wrong_keys': {
            'n': len(wrong),
            # giải ra đúng giá trị SAI của key: lỗi tương quan với generator
            'reproduced_wrong_key': rate(_count(wrong, 'agree'), len(wrong)),
            'caught': rate(_count(wrong, 'disagree'), len(wrong)),
            'abstained': _count(wrong, 'abstain'),
            'errors': _count(wrong, 'error'),
        },
        'correct_keys': {
            'n': len(right),
            'confirmed': rate(_count(right, 'agree'), len(right)),
            'false_alarm': rate(_count(right, 'disagree'), len(right)),
            'abstained': _count(right, 'abstain'),
            'errors': _count(right, 'error'),
        },
    }


def pairwise_summary(items: List[LabelledItem], targets: Targets,
                     a: str, b: str) -> Dict[str, Any]:
    ta, tb = targets.get(a) or {}, targets.get(b) or {}
    kappa_pairs: List[Tuple[bool, bool]] = []
    both_definite = value_agree = 0
    joint_wrong = wrong_both = 0
    for item in items:
        x, y = ta.get(item.item_id), tb.get(item.item_id)
        ox, oy = outcome(x, item.key_value), outcome(y, item.key_value)
        if x is not None and y is not None and x.definite and y.definite \
                and x.value is not None and y.value is not None:
            both_definite += 1
            value_agree += values_agree(x.value, y.value)
        if ox in ('agree', 'disagree') and oy in ('agree', 'disagree'):
            kappa_pairs.append((ox == 'agree', oy == 'agree'))
            if not item.key_correct:
                wrong_both += 1
                joint_wrong += (ox == 'agree' and oy == 'agree')
    kappa = cohen_kappa_binary(kappa_pairs)
    return {
        'pair': [a, b],
        'both_definite': both_definite,
        'value_agreement': rate(value_agree, both_definite),
        'kappa_agrees_with_key': round(kappa, 4) if kappa is not None else None,
        'kappa_n': len(kappa_pairs),
        # trên các key sai mà cả hai cùng có kết quả: bao nhiêu lần CẢ HAI tái
        # tạo đúng giá trị sai — đồng thuận kiểu này mới là thứ lọt lưới
        'both_reproduce_wrong_key': rate(joint_wrong, wrong_both),
    }


def configuration_summary(
    items: List[LabelledItem],
    targets: Targets,
    members: Sequence[str],
    consensus: Any = 'all',
) -> Dict[str, Any]:
    """Chạy gộp + phân xử của pipeline cho một cấu hình hội đồng."""
    covered = [i for i in items
               if all(i.item_id in (targets.get(m) or {}) for m in members)]
    statuses: Dict[str, Dict[str, int]] = {'wrong': {}, 'correct': {}}
    certified = {'wrong': 0, 'correct': 0}
    flagged = {'wrong': 0, 'correct': 0}
    certified_wrong_ids: List[str] = []
    for item in covered:
        panel = aggregate_panel(
            [_copy(targets[m][item.item_id]) for m in members], consensus=consensus)
        adj = adjudicate(
            writer_verified=item.writer_verified,
            writer_engine=item.writer_engine,
            independent=panel,
            keyed_value=item.key_value,
            distractor_values=item.distractor_values,
        )
        group = 'correct' if item.key_correct else 'wrong'
        statuses[group][adj.status] = statuses[group].get(adj.status, 0) + 1
        if adj.status == VerificationStatus.INDEPENDENTLY_VERIFIED:
            certified[group] += 1
            if group == 'wrong':
                certified_wrong_ids.append(item.item_id)
        if adj.status in VerificationStatus.NEEDS_HUMAN:
            flagged[group] += 1
    n_wrong = sum(1 for i in covered if not i.key_correct)
    n_right = len(covered) - n_wrong
    return {
        'members': list(members),
        'consensus': str(consensus),
        'consensus_size': consensus_size(consensus, len(members)),
        'items': len(covered),
        # P(nhãn "đã kiểm chứng độc lập" | key sai) — lỗ hổng cần đóng
        'wrong_key_certified': rate(certified['wrong'], n_wrong),
        'wrong_key_flagged': rate(flagged['wrong'], n_wrong),
        # P(nhãn | key đúng) — độ phủ còn giữ được
        'correct_key_certified': rate(certified['correct'], n_right),
        # gánh nặng duyệt tay trên câu vốn đúng
        'correct_key_flagged': rate(flagged['correct'], n_right),
        'status_by_key': statuses,
        'certified_wrong_items': certified_wrong_ids,
    }


def all_configurations(
    items: List[LabelledItem],
    targets: Targets,
    solvers: Sequence[str],
    max_size: int = 4,
) -> List[Dict[str, Any]]:
    """Mọi hội đồng con (1..max_size thành viên) × mọi luật k-trên-n."""
    rows: List[Dict[str, Any]] = []
    for size in range(1, min(max_size, len(solvers)) + 1):
        for members in itertools.combinations(solvers, size):
            rules: List[Any] = ['all'] + [str(k) for k in range(1, size)]
            for rule in rules:
                rows.append(configuration_summary(items, targets, members, rule))
    return rows


def _copy(target: IndependentTarget) -> IndependentTarget:
    # aggregate_panel ghi vào thành viên đơn lẻ; không được làm bẩn cache dùng chung.
    return target_from_dict(target.to_dict()) or target

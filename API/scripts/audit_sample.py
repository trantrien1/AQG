# -*- coding: utf-8 -*-
"""Audit hai pha cho một run: lấy mẫu phân tầng MÙ + ước lượng tỉ lệ key sai.

Pha 1 — ``sample``: chia câu của run theo trạng thái kiểm chứng. Tầng
``independently_verified`` (lời hứa mạnh nhất của hệ thống) được audit TOÀN BỘ;
các tầng khác lấy mẫu ngẫu nhiên có seed. Phiếu audit (CSV mở bằng Excel) chỉ
có đề + phương án + key, xáo thứ tự, KHÔNG có trạng thái, lời giải hay giá trị
solver — người audit không bị neo theo kết luận của máy. Ánh xạ phiếu → trạng
thái nằm ở ``audit_plan_SECRET.json``.

Pha 2 — ``estimate``: đọc phiếu đã điền cột ``key_correct`` (1/0, bỏ trống nếu
đề lỗi không có đáp án duy nhất), tính tỉ lệ key sai từng tầng kèm khoảng
Wilson, ước lượng phân tầng cho cả run, và ghi file nhãn ground-truth theo
question_id để ``bench_suite.py --aggregate-only --ground-truth`` dùng được.
Truyền hai phiếu (hai người audit độc lập) để có Cohen's κ và danh sách bất
đồng; khi đó ``--adjudicated`` là phiếu đã thống nhất dùng để ước lượng.

    python scripts/audit_sample.py sample --run report/bench/colab-20260917 \\
        --out report/bench/colab-20260917/audit --per-stratum 10
    python scripts/audit_sample.py estimate \\
        --plan report/bench/colab-20260917/audit/audit_plan_SECRET.json \\
        --sheet report/bench/colab-20260917/audit/audit_sheet.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SHEET_COLUMNS = ['audit_id', 'stem', 'A', 'B', 'C', 'D', 'answer_key',
                 'key_correct', 'correct_value', 'note']
_TRUE = {'1', 'y', 'yes', 'true', 'đúng', 'dung', 'd', 'x'}
_FALSE = {'0', 'n', 'no', 'false', 'sai', 's'}


def load_run(run_dir: Path) -> List[Dict[str, Any]]:
    """Câu của run theo thứ tự đường dẫn POSIX đã sort (giống bench_suite)."""
    files = sorted(
        (p for p in run_dir.rglob('*.json')
         if not p.name.endswith('.manifest.json')
         and not p.name.startswith(('suite_', 'audit', 'replay_', 'human_eval'))
         and 'audit' not in p.parts and 'human_eval' not in p.parts),
        key=lambda p: p.relative_to(run_dir).as_posix(),
    )
    rows: List[Dict[str, Any]] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(data, dict) or not isinstance(data.get('questions'), list):
            continue
        for q in data['questions']:
            rows.append({'index': len(rows) + 1,
                         'file': path.relative_to(run_dir).as_posix(),
                         'record': q})
    return rows


def _status(record: Dict[str, Any]) -> str:
    return str((record.get('verification') or {}).get('status') or 'unknown')


def cmd_sample(args) -> int:
    run_dir = Path(args.run)
    rows = load_run(run_dir)
    if not rows:
        print(f'không có câu nào trong {run_dir}')
        return 1
    strata: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        strata.setdefault(_status(row['record']), []).append(row)

    rng = random.Random(args.seed)
    chosen: List[Dict[str, Any]] = []
    plan_strata: Dict[str, Any] = {}
    for name in sorted(strata):
        members = strata[name]
        if name in args.census or len(members) <= args.per_stratum:
            picked = list(members)
        else:
            picked = rng.sample(members, args.per_stratum)
        plan_strata[name] = {'population': len(members), 'sampled': len(picked),
                             'census': len(picked) == len(members)}
        chosen.extend(picked)
    rng.shuffle(chosen)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    assignment: Dict[str, Any] = {}
    with open(out / 'audit_sheet.csv', 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for n, row in enumerate(chosen, start=1):
            rec = row['record']
            audit_id = f'audit_{n:03d}'
            options = {o.get('key'): o.get('text', '') for o in rec.get('options') or []}
            writer.writerow({
                'audit_id': audit_id, 'stem': rec.get('stem', ''),
                'A': options.get('A', ''), 'B': options.get('B', ''),
                'C': options.get('C', ''), 'D': options.get('D', ''),
                'answer_key': rec.get('answer_key', ''),
                'key_correct': '', 'correct_value': '', 'note': '',
            })
            assignment[audit_id] = {
                'index': row['index'], 'file': row['file'],
                'question_id': rec.get('question_id'),
                'status': _status(rec),
            }
    plan = {
        'run': str(run_dir), 'seed': args.seed,
        'population': len(rows), 'strata': plan_strata,
        'note': 'KHÔNG đưa file này cho người audit — nó lộ trạng thái của máy.',
        'assignment': assignment,
    }
    (out / 'audit_plan_SECRET.json').write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[audit] {len(chosen)}/{len(rows)} câu vào phiếu -> {out / "audit_sheet.csv"}')
    for name, s in plan_strata.items():
        print(f"[audit]   {name}: {s['sampled']}/{s['population']}"
              + (' (toàn bộ)' if s['census'] else ''))
    return 0


def read_sheet(path: Path) -> Dict[str, Optional[bool]]:
    labels: Dict[str, Optional[bool]] = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            value = str(row.get('key_correct') or '').strip().lower()
            if value in _TRUE:
                labels[row['audit_id']] = True
            elif value in _FALSE:
                labels[row['audit_id']] = False
            else:
                labels[row['audit_id']] = None
    return labels


def cmd_estimate(args) -> int:
    from pipeline.panel_eval import cohen_kappa_binary, rate

    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    sheets = [read_sheet(Path(p)) for p in args.sheet]
    report: Dict[str, Any] = {'plan': args.plan, 'sheets': args.sheet}

    if len(sheets) >= 2:
        a, b = sheets[0], sheets[1]
        both = [k for k in a if a.get(k) is not None and b.get(k) is not None]
        kappa = cohen_kappa_binary([(a[k], b[k]) for k in both])
        report['inter_rater'] = {
            'items_both_labelled': len(both),
            'agreement': rate(sum(a[k] == b[k] for k in both), len(both)),
            'cohen_kappa': round(kappa, 4) if kappa is not None else None,
            'disagreements': [k for k in both if a[k] != b[k]],
        }
    labels = read_sheet(Path(args.adjudicated)) if args.adjudicated else sheets[0]

    per_stratum: Dict[str, Dict[str, int]] = {}
    for audit_id, info in plan['assignment'].items():
        value = labels.get(audit_id)
        entry = per_stratum.setdefault(info['status'], {'wrong': 0, 'labelled': 0,
                                                        'blank': 0})
        if value is None:
            entry['blank'] += 1
            continue
        entry['labelled'] += 1
        entry['wrong'] += (value is False)

    total = plan['population']
    estimate = 0.0
    variance = 0.0
    strata_out = {}
    for name, s in plan['strata'].items():
        e = per_stratum.get(name, {'wrong': 0, 'labelled': 0, 'blank': 0})
        n, N = e['labelled'], s['population']
        strata_out[name] = {
            'population': N, 'sampled': s['sampled'], 'labelled': n,
            'blank_or_defective': e['blank'],
            'wrong_key_rate': rate(e['wrong'], n),
        }
        if n == 0:
            continue
        p = e['wrong'] / n
        w = N / total
        estimate += w * p
        fpc = (N - n) / (N - 1) if N > 1 else 0.0
        variance += w * w * p * (1 - p) / n * fpc
    se = math.sqrt(variance)
    report['strata'] = strata_out
    report['stratified_wrong_key_rate'] = {
        'estimate': round(estimate, 4),
        'se': round(se, 4),
        'ci95_normal': [round(max(0.0, estimate - 1.96 * se), 4),
                        round(min(1.0, estimate + 1.96 * se), 4)],
        'note': ('ước lượng phân tầng theo trạng thái kiểm chứng; tầng nào '
                 'không có nhãn thì không đóng góp — xem strata'),
    }

    ground_truth = {
        'source': 'cas_audit',
        'note': f'audit mù theo {args.plan}',
        'labels': {
            str(info['question_id']): {
                'key_correct': labels[aid],
                'note': f"{aid}; tầng {info['status']}",
            }
            for aid, info in plan['assignment'].items()
            if labels.get(aid) is not None and info.get('question_id')
        },
    }
    out_dir = Path(args.plan).parent
    (out_dir / 'ground_truth_cas.json').write_text(
        json.dumps(ground_truth, ensure_ascii=False, indent=2), encoding='utf-8')
    (out_dir / 'audit_estimate.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({'strata': strata_out,
                      'stratified_wrong_key_rate': report['stratified_wrong_key_rate'],
                      'inter_rater': report.get('inter_rater')},
                     ensure_ascii=False, indent=2))
    print(f'[audit] nhãn -> {out_dir / "ground_truth_cas.json"}')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('sample')
    s.add_argument('--run', required=True, help='thư mục run (vd output của bench_suite)')
    s.add_argument('--out', required=True)
    s.add_argument('--seed', type=int, default=20260917)
    s.add_argument('--per-stratum', type=int, default=10)
    s.add_argument('--census', nargs='*', default=['independently_verified'],
                   help='tầng audit toàn bộ')
    e = sub.add_parser('estimate')
    e.add_argument('--plan', required=True)
    e.add_argument('--sheet', nargs='+', required=True,
                   help='một hoặc hai phiếu đã điền (hai người audit độc lập)')
    e.add_argument('--adjudicated', default='',
                   help='phiếu đã thống nhất sau khi hai người đối chiếu')
    args = ap.parse_args()
    return cmd_sample(args) if args.cmd == 'sample' else cmd_estimate(args)


if __name__ == '__main__':
    sys.exit(main())

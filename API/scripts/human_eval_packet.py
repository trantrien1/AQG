# -*- coding: utf-8 -*-
"""Phiếu chấm giáo viên cho một run: xuất (mù) → nhập → tổng hợp.

    # 1) xuất 60 câu, mọi giáo viên chấm CÙNG 60 câu (để tính đồng thuận)
    python scripts/human_eval_packet.py export --run report/bench/colab-20260917 \\
        --out report/bench/colab-20260917/human_eval --n 60 --reviewers gv1 gv2 gv3

    # 2) giáo viên điền file ratings_<gv>.csv (Excel) rồi chuyển về JSON
    python scripts/human_eval_packet.py import-csv \\
        --csv report/bench/colab-20260917/human_eval/ratings_gv1.csv

    # 3) tổng hợp (Krippendorff α, κ, trung bình + CI từng tiêu chí)
    python scripts/human_eval_packet.py aggregate \\
        --dir report/bench/colab-20260917/human_eval

Câu được chọn rải đều theo tài liệu nguồn (seed cố định). Phiếu không mang
trạng thái kiểm chứng, lời giải hay tên hệ thống; ánh xạ nằm ở
``_assignment_SECRET.json``.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _pick(rows: List[Dict[str, Any]], n: int, seed: int) -> List[Dict[str, Any]]:
    """Rải đều theo file nguồn (round-robin trên từng nhóm đã xáo)."""
    rng = random.Random(seed)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row['file'].rsplit('/', 1)[-1], []).append(row)
    for members in groups.values():
        rng.shuffle(members)
    order = sorted(groups)
    picked: List[Dict[str, Any]] = []
    while len(picked) < n and any(groups[g] for g in order):
        for g in order:
            if groups[g] and len(picked) < n:
                picked.append(groups[g].pop())
    return picked


def cmd_export(args) -> int:
    from pipeline.human_eval import CRITERIA, build_blind_export, write_review_packet
    from audit_sample import load_run

    rows = load_run(Path(args.run))
    picked = _pick(rows, args.n, args.seed)
    export = build_blind_export(
        {args.system: [r['record'] for r in picked]}, seed=args.seed)
    written = write_review_packet(export, args.out, args.reviewers)
    columns = ['item_id', 'stem', 'A', 'B', 'C', 'D', 'answer_key'] + list(CRITERIA) + ['comment']
    for reviewer in args.reviewers:
        path = Path(args.out) / f'ratings_{reviewer}.csv'
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for item in export.items:
                options = {o['key']: o['text'] for o in item['options']}
                writer.writerow({
                    'item_id': item['item_id'], 'stem': item['stem'],
                    **{k: options.get(k, '') for k in 'ABCD'},
                    'answer_key': item['answer_key'],
                })
    guide = Path(args.out) / 'HUONG_DAN_CHAM.txt'
    guide.write_text(
        'Mỗi dòng là một câu hỏi. Chấm mỗi cột tiêu chí từ 1 (rất kém) đến 5 '
        '(rất tốt); để trống nếu không áp dụng được.\n\n'
        + '\n'.join(f'- {k}: {v}' for k, v in CRITERIA.items())
        + '\n\nKhông trao đổi với người chấm khác trước khi nộp phiếu.\n',
        encoding='utf-8')
    print(f'[human-eval] {len(export.items)} câu, {len(args.reviewers)} người chấm '
          f'-> {args.out}')
    print(f"[human-eval] KHÔNG gửi {written['_assignment'].name} cho giáo viên.")
    return 0


def cmd_import_csv(args) -> int:
    from pipeline.human_eval import CRITERIA, DEFAULT_SCALE

    path = Path(args.csv)
    reviewer = path.stem.replace('ratings_', '', 1)
    ratings = []
    with open(path, encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            scores: Dict[str, Any] = {}
            for name in CRITERIA:
                raw = str(row.get(name) or '').strip().replace(',', '.')
                if not raw:
                    scores[name] = None
                    continue
                value = float(raw)
                if not DEFAULT_SCALE['min'] <= value <= DEFAULT_SCALE['max']:
                    raise SystemExit(f'{row["item_id"]}: {name}={raw} nằm ngoài thang 1-5')
                scores[name] = value
            ratings.append({'item_id': row['item_id'], 'scores': scores,
                            'comment': row.get('comment', '')})
    out = path.with_name(f'ratings_{reviewer}.json')
    form = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {}
    form.update({'reviewer_id': reviewer, 'ratings': ratings})
    out.write_text(json.dumps(form, ensure_ascii=False, indent=2), encoding='utf-8')
    rated = sum(1 for r in ratings if any(v is not None for v in r['scores'].values()))
    print(f'[human-eval] {reviewer}: {rated}/{len(ratings)} câu có điểm -> {out}')
    return 0


def cmd_aggregate(args) -> int:
    from pipeline.human_eval import NoRatingsError, aggregate_ratings, load_ratings

    folder = Path(args.dir)
    ratings = load_ratings(sorted(folder.glob('ratings_*.json')))
    secret = folder / '_assignment_SECRET.json'
    assignment = (json.loads(secret.read_text(encoding='utf-8')).get('assignment')
                  if secret.exists() else None)
    try:
        summary = aggregate_ratings(ratings, assignment=assignment)
    except NoRatingsError as exc:
        print(f'[human-eval] {exc}')
        return 1
    (folder / 'human_eval_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    for name, entry in summary['per_criterion'].items():
        agreement = entry['agreement']
        print(f"{name:28s} mean={entry['mean']} ci={entry['ci95']} "
              f"alpha={agreement.get('krippendorff_alpha_ordinal')} "
              f"n={entry['n_ratings']}")
    print(f"[human-eval] -> {folder / 'human_eval_summary.json'}")
    return 0


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('export')
    e.add_argument('--run', required=True)
    e.add_argument('--out', required=True)
    e.add_argument('--n', type=int, default=60)
    e.add_argument('--reviewers', nargs='+', default=['gv1', 'gv2', 'gv3'])
    e.add_argument('--seed', type=int, default=20260917)
    e.add_argument('--system', default='pipeline')
    i = sub.add_parser('import-csv')
    i.add_argument('--csv', required=True)
    a = sub.add_parser('aggregate')
    a.add_argument('--dir', required=True)
    args = ap.parse_args()
    handler = {'export': cmd_export, 'import-csv': cmd_import_csv,
               'aggregate': cmd_aggregate}[args.cmd]
    return handler(args)


if __name__ == '__main__':
    sys.exit(main())

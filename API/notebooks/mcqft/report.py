"""So sánh các thí nghiệm.

    python -m mcqft.report --data /content/data --exp A=/content/exp_a \
        --exp B=/content/exp_b --judge /content/judge --out /content/report \
        --katex-modules /content/katex/node_modules

Mỗi thư mục thí nghiệm gồm ``train_summary.json`` và ``preds/``. Chỉ số chính của
tác vụ sinh là **tỉ lệ câu dùng được (ước lượng)**: đọc được đúng khuôn, mọi công
thức dựng được bằng KaTeX, giám khảo khác họ giải ra đúng đáp án mô hình ghi, và
không phải bản chép gần nguyên văn một câu train.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from typing import Dict, List, Optional

from .data import LEVELS, load_split, read_jsonl, write_jsonl
from .metrics import (NoveltyIndex, extract_answer, mcnemar_exact, paired_bootstrap,
                      parse_generated, self_similarity, wilson)

NEAR_COPY = 0.8


def katex_bad(records: List[Dict], modules: Optional[str]) -> Optional[Dict[str, int]]:
    if not modules or not shutil.which('node') or not records:
        return None
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'katex_check.js')
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'in.jsonl')
        write_jsonl(path, records)
        env = dict(os.environ, NODE_PATH=modules)
        out = subprocess.run(['node', script, path], capture_output=True, text=True,
                             encoding='utf-8', env=env, check=True).stdout
    return {r['key']: r['bad'] for r in map(json.loads, out.splitlines())}


def load_judge(folder: Optional[str]) -> Dict[str, Dict]:
    if not folder:
        return {}
    return {r['key']: r for r in read_jsonl(os.path.join(folder, 'judge.jsonl'))}


def score_gen(exp: str, system: str, rows: List[Dict], test: Dict[str, Dict],
              novelty: NoveltyIndex, judge: Dict[str, Dict],
              katex_modules: Optional[str]) -> Dict:
    parsed = []
    for row in rows:
        rec, errors = parse_generated(row['text'])
        key = f"{exp}/{system}/{row['id']}/{row['sample']}"
        parsed.append({'key': key, 'row': row, 'rec': rec, 'errors': errors})
    valid = [p for p in parsed if not p['errors']]
    bad = katex_bad([dict(p['rec'], key=p['key']) for p in valid], katex_modules)
    per_prompt: Dict[str, List[float]] = defaultdict(list)
    per_level: Dict[str, List[float]] = defaultdict(list)
    err_counts: Counter = Counter()
    sims, copies, agree, undecided = [], 0, 0, 0
    for p in parsed:
        err_counts.update(p['errors'])
        if p['errors']:
            ok = False
        else:
            katex_ok = bad is None or bad.get(p['key'], 1) == 0
            j = judge.get(p['key'])
            judge_ok = True
            if judge:
                judge_ok = bool(j) and j['pred'] == p['rec']['answer']
                agree += judge_ok
                undecided += bool(j) and j['pred'] is None
            sim, _ = novelty.nearest(p['rec'])
            sims.append(sim)
            copies += sim >= NEAR_COPY
            ok = katex_ok and judge_ok and sim < NEAR_COPY
        per_prompt[p['row']['id']].append(float(ok))
        per_level[test[p['row']['id']]['difficulty']].append(float(ok))
    n = len(parsed)
    usable = sum(sum(v) for v in per_prompt.values())
    return {
        'outputs': n,
        'format_valid': len(valid) / n if n else 0,
        'katex_ok_of_valid': (sum(1 for p in valid if bad.get(p['key'], 1) == 0) / len(valid)
                              if bad is not None and valid else None),
        'judge_agree_of_valid': agree / len(valid) if judge and valid else None,
        'judge_undecided': undecided,
        'novelty_mean_max_jaccard': sum(sims) / len(sims) if sims else None,
        'near_copy_rate': copies / len(valid) if valid else None,
        'self_similarity': self_similarity([p['rec'] for p in valid]),
        'truncated': sum(1 for p in parsed if p['row'].get('finish_reason') == 'length') / n
        if n else 0,
        'mean_output_tokens': sum(p['row']['output_tokens'] for p in parsed) / n if n else 0,
        'usable_rate': usable / n if n else 0,
        'usable_ci': wilson(int(usable), n),
        'usable_by_level': {lv: sum(v) / len(v) for lv, v in per_level.items() if v},
        'errors': dict(err_counts),
        '_per_prompt': {k: sum(v) / len(v) for k, v in per_prompt.items()},
    }


def score_solve(rows: List[Dict], test: Dict[str, Dict]) -> Dict:
    correct: Dict[str, bool] = {}
    by_level: Dict[str, List[bool]] = defaultdict(list)
    missing = 0
    for row in rows:
        pred = extract_answer(row['text'])
        missing += pred is None
        ok = pred == test[row['id']]['answer']
        correct[row['id']] = ok
        by_level[test[row['id']]['difficulty']].append(ok)
    k, n = sum(correct.values()), len(correct)
    return {'accuracy': k / n if n else 0, 'ci': wilson(k, n), 'n': n,
            'no_answer': missing,
            'by_level': {lv: sum(v) / len(v) for lv, v in by_level.items()},
            '_correct': correct}


def fmt(x, pct=True) -> str:
    if x is None:
        return '–'
    return f'{100 * x:.1f}' if pct else f'{x:.3f}'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data', required=True)
    ap.add_argument('--exp', action='append', required=True, help='TÊN=thư mục thí nghiệm')
    ap.add_argument('--judge', default=None)
    ap.add_argument('--out', required=True)
    ap.add_argument('--katex-modules', default=None, help='thư mục node_modules có katex')
    args = ap.parse_args()

    splits = load_split(args.data)
    test = {it['id']: it for it in splits['test']}
    novelty = NoveltyIndex(splits['train'])
    judge = load_judge(args.judge)
    exps = [tuple(e.split('=', 1)) for e in args.exp]

    gen: Dict[str, Dict] = {}
    solve: Dict[str, Dict] = {}
    info: Dict[str, Dict] = {}
    for exp, folder in exps:
        preds = os.path.join(folder, 'preds')
        summary_path = os.path.join(preds, 'infer_summary.json')
        infer_summary = json.load(open(summary_path, encoding='utf-8')) \
            if os.path.exists(summary_path) else {'runs': {}}
        train_path = os.path.join(folder, 'train_summary.json')
        train = json.load(open(train_path, encoding='utf-8')) if os.path.exists(train_path) else {}
        info[exp] = {'model': infer_summary.get('model') or train.get('model'),
                     'train': {k: train.get(k) for k in (
                         'train_seconds', 'train_tokens_per_second', 'peak_gpu_mem_gb',
                         'best_eval_loss', 'train_examples')},
                     'infer': infer_summary['runs']}
        for path in sorted(glob.glob(os.path.join(preds, '*.jsonl'))):
            base = os.path.basename(path)[:-len('.jsonl')]   # vd. lora.gen_ctx
            if '.' not in base:
                continue
            task = base.rsplit('.', 1)[1]
            rows = read_jsonl(path)
            name = f'{exp}.{base}'
            if task in ('gen', 'gen_ctx'):
                gen[name] = score_gen(exp, base, rows, test, novelty, judge,
                                      args.katex_modules)
            elif task == 'solve':
                solve[name] = score_solve(rows, test)

    lines = ['# So sánh thí nghiệm', '']
    if not judge:
        lines += ['> Chưa có kết quả giám khảo: cột "Dùng được" chưa trừ các câu sai đáp án.', '']
    if not args.katex_modules:
        lines += ['> Chưa kiểm tra KaTeX: cột "Dùng được" chưa trừ các câu hỏng công thức.', '']
    for exp, meta in info.items():
        t = meta['train']
        lines.append(f"- **{exp}**: `{meta['model']}`; train {t['train_examples']} mẫu, "
                     f"{t['train_seconds']} s, {t['train_tokens_per_second']} token/s, "
                     f"VRAM đỉnh {t['peak_gpu_mem_gb']} GB, val loss tốt nhất {t['best_eval_loss']}")
    if judge:
        real = [r for k, r in judge.items() if k.startswith('real/')]
        acc = sum(r['pred'] == r['key_answer'] for r in real) / max(1, len(real))
        lines.append(f'- Giám khảo giải đúng {fmt(acc)}% câu test thật '
                     f'(trần của cột "giám khảo khớp").')
    lines += ['', '## Tác vụ sinh câu hỏi', '',
              '| Hệ | Đầu ra | Đúng khuôn % | KaTeX ổn % | Giám khảo khớp % | Chép gần nguyên văn % '
              '| Jaccard gần nhất | Tự tương đồng | Bị cắt % | Token/câu | Token/s | **Dùng được %** (95% CI) |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for name, g in gen.items():
        exp, base = name.split('.', 1)
        tps = info[exp]['infer'].get(base, {}).get('output_tokens_per_second')
        lo, hi = g['usable_ci']
        lines.append(
            f"| {name} | {g['outputs']} | {fmt(g['format_valid'])} | {fmt(g['katex_ok_of_valid'])} "
            f"| {fmt(g['judge_agree_of_valid'])} | {fmt(g['near_copy_rate'])} "
            f"| {fmt(g['novelty_mean_max_jaccard'], False)} | {fmt(g['self_similarity'], False)} "
            f"| {fmt(g['truncated'])} | {g['mean_output_tokens']:.0f} | {tps or '–'} "
            f"| **{fmt(g['usable_rate'])}** ({fmt(lo)}–{fmt(hi)}) |")
    lines += ['', 'Tỉ lệ dùng được theo mức độ yêu cầu:', '',
              '| Hệ | ' + ' | '.join(LEVELS) + ' |', '|---|' + '---|' * len(LEVELS)]
    for name, g in gen.items():
        lines.append(f'| {name} | ' + ' | '.join(fmt(g['usable_by_level'].get(lv))
                                                for lv in LEVELS) + ' |')
    lines += ['', '## Tác vụ giải câu hỏi (test thật)', '',
              '| Hệ | Đúng % (95% CI) | Không ra đáp án | ' + ' | '.join(LEVELS) + ' |',
              '|---|---|---|' + '---|' * len(LEVELS)]
    for name, s in solve.items():
        lo, hi = s['ci']
        lines.append(f"| {name} | {fmt(s['accuracy'])} ({fmt(lo)}–{fmt(hi)}) | {s['no_answer']} | "
                     + ' | '.join(fmt(s['by_level'].get(lv)) for lv in LEVELS) + ' |')

    # So sánh từng cặp trên cùng các câu test
    pairs = []
    names = [e for e, _ in exps]
    tasks = ('gen', 'gen_ctx', 'solve')
    for exp in names:
        pairs += [(f'{exp}.base.{t}', f'{exp}.lora.{t}') for t in tasks]
        pairs.append((f'{exp}.base_fs3.gen', f'{exp}.lora.gen'))
    for a, b in zip(names, names[1:]):
        pairs += [(f'{a}.lora.{t}', f'{b}.lora.{t}') for t in tasks]
        pairs += [(f'{a}.base.{t}', f'{b}.base.{t}') for t in tasks]
    lines += ['', '## So sánh cặp (bootstrap ghép cặp theo câu test, 10 000 lần)', '',
              '| Cặp (X → Y) | Tác vụ | Y − X (điểm %) | 95% CI | McNemar p |',
              '|---|---|---|---|---|']
    comparisons = []
    for x, y in pairs:
        if x in gen and y in gen:
            ids = sorted(set(gen[x]['_per_prompt']) & set(gen[y]['_per_prompt']))
            bs = paired_bootstrap([gen[x]['_per_prompt'][i] for i in ids],
                                  [gen[y]['_per_prompt'][i] for i in ids])
            comparisons.append({'x': x, 'y': y, 'task': 'gen', **bs})
            lines.append(f"| {x} → {y} | sinh | {100 * bs['diff']:+.1f} "
                         f"| {100 * bs['lo']:+.1f} … {100 * bs['hi']:+.1f} | – |")
        if x in solve and y in solve:
            ids = sorted(set(solve[x]['_correct']) & set(solve[y]['_correct']))
            ca = [solve[x]['_correct'][i] for i in ids]
            cb = [solve[y]['_correct'][i] for i in ids]
            bs = paired_bootstrap([float(v) for v in ca], [float(v) for v in cb])
            mc = mcnemar_exact(ca, cb)
            comparisons.append({'x': x, 'y': y, 'task': 'solve', **bs, 'mcnemar': mc})
            lines.append(f"| {x} → {y} | giải | {100 * bs['diff']:+.1f} "
                         f"| {100 * bs['lo']:+.1f} … {100 * bs['hi']:+.1f} | {mc['p']:.3f} |")

    os.makedirs(args.out, exist_ok=True)
    md = '\n'.join(lines) + '\n'
    with open(os.path.join(args.out, 'report.md'), 'w', encoding='utf-8') as fh:
        fh.write(md)
    strip = lambda d: {k: v for k, v in d.items() if not k.startswith('_')}  # noqa: E731
    with open(os.path.join(args.out, 'report.json'), 'w', encoding='utf-8') as fh:
        json.dump({'info': info, 'gen': {k: strip(v) for k, v in gen.items()},
                   'solve': {k: strip(v) for k, v in solve.items()},
                   'comparisons': comparisons}, fh, ensure_ascii=False, indent=1)
    print(md)


if __name__ == '__main__':
    main()

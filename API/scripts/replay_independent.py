# -*- coding: utf-8 -*-
"""Replay hội đồng solver độc lập trên các câu ĐÃ AUDIT (Run A/B/C).

Không sinh câu mới và không cần audit thêm: lấy đề bài của 197 câu đã có nhãn
CAS, cho từng solver giải lại CHỈ từ đề bài (đúng prompt bịt mắt của pipeline),
rồi chạy đúng hàm gộp + phân xử của pipeline trên mọi hội đồng con.

Kết quả trả lời trực tiếp câu hỏi của reviewer: solver cùng họ với generator có
tái tạo key sai không, và đòi đồng thuận khác họ thì tỉ lệ key sai được cấp nhãn
và độ phủ trên key đúng đổi ra sao.

    python scripts/replay_independent.py \\
        --solver microsoft/phi-4@http://127.0.0.1:8001/v1 \\
        --solver Qwen/Qwen3-VL-32B-Instruct-FP8@http://127.0.0.1:8000/v1 \\
        --api-key "$VLLM_KEY" --out report/replay/20260917

    # chỉ phân tích lại từ cache, không gọi model:
    python scripts/replay_independent.py --out report/replay/20260917 --analyze-only

Kết quả gpt-4o-mini đã lưu trong artifact (Run B/C) được đưa vào như solver
``recorded`` trừ khi có ``--no-recorded``. Mỗi lời giải được cache theo
(solver, câu, phiên bản prompt) trong ``<out>/cache`` nên chạy lại chỉ gọi phần
còn thiếu; lời gọi lỗi không được cache.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

RECORDED = 'recorded'


def _slug(text: str) -> str:
    return re.sub(r'[^0-9A-Za-z_.-]+', '_', text)[:80]


def _cache_path(out: Path, solver: str) -> Path:
    return out / 'cache' / f'{_slug(solver)}.jsonl'


def _load_cache(path: Path, prompt_version: str) -> Dict[str, Dict[str, Any]]:
    cached: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return cached
    for line in path.read_text(encoding='utf-8').splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get('prompt_version') == prompt_version:
            cached[row['item_id']] = row['target']
    return cached


def solve_all(items, spec, *, out: Path, api_key: str, workers: int,
              max_tokens: int) -> Dict[str, Dict[str, Any]]:
    """Giải mọi câu cho một solver, dùng cache. Trả item_id -> target dict."""
    from pipeline.independent_target import (
        INDEPENDENT_PROMPT_VERSION, build_independent_target,
    )
    from pipeline.llm_client import (
        BudgetExceeded, NonRetryableLLMError, call_llm, get_tracker,
    )

    path = _cache_path(out, spec.model)
    path.parent.mkdir(parents=True, exist_ok=True)
    done = _load_cache(path, INDEPENDENT_PROMPT_VERSION)
    todo = [i for i in items if i.item_id not in done]
    print(f'[replay] {spec.model}: {len(done)} câu có sẵn trong cache, '
          f'{len(todo)} câu cần giải', flush=True)
    if not todo:
        return done

    def _call(system: str, user: str) -> str:
        return call_llm(system=system, user=user, model=spec.model,
                        temperature=0.0, max_tokens=max_tokens, retries=3,
                        base_url=spec.base_url or None, api_key=api_key or None)

    def _one(item):
        target = build_independent_target(
            item.stem, call_fn=_call, model=spec.model,
            reraise=(BudgetExceeded, NonRetryableLLMError))
        return item, target

    tokens_before = get_tracker().tokens
    started = time.time()
    errors = 0
    with open(path, 'a', encoding='utf-8') as sink, \
            ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(_one, item) for item in todo]
        for n, fut in enumerate(as_completed(futures), start=1):
            item, target = fut.result()   # lỗi hạ tầng nổi lên và dừng hẳn
            data = target.to_dict()
            if target.source == 'error':
                errors += 1          # không cache: lần chạy sau thử lại
            else:
                sink.write(json.dumps({
                    'item_id': item.item_id,
                    'prompt_version': INDEPENDENT_PROMPT_VERSION,
                    'target': data,
                }, ensure_ascii=False) + '\n')
                sink.flush()
                done[item.item_id] = data
            if n % 20 == 0 or n == len(todo):
                print(f'[replay]   {spec.model}: {n}/{len(todo)} '
                      f'({time.time() - started:.0f}s, lỗi tạm thời {errors})',
                      flush=True)
    print(f'[replay] {spec.model}: xong, {get_tracker().tokens - tokens_before} '
          f'token, {errors} câu lỗi chưa cache', flush=True)
    return done


def write_markdown(summary: Dict[str, Any], out: Path) -> None:
    def pct(r):
        if not r or r.get('value') is None:
            return '—'
        lo, hi = r['ci95']
        return f"{r['n']}/{r['of']} ({100 * r['value']:.1f}%, CI {100 * lo:.0f}–{100 * hi:.0f})"

    lines = [
        '# Replay hội đồng solver độc lập trên câu đã audit',
        '',
        f"Sinh lúc {summary['generated_at']}. {summary['items']['total']} câu có "
        f"nhãn CAS ({summary['items']['wrong_keys']} key sai, "
        f"{summary['items']['correct_keys']} key đúng); generator của các câu "
        f"này: {summary['generator']} (họ {summary['generator_family']}).",
        '',
        'Mọi trạng thái dưới đây được tính bằng đúng hàm gộp và hàm phân xử của '
        'pipeline. Chỉ tính trên câu mà MỌI thành viên của cấu hình đều có kết '
        'quả (solver `recorded` không có dữ liệu cho Run A).',
        '',
        '## Từng solver',
        '',
        '| Solver | Họ | Câu | Key sai: tái tạo giá trị sai | Key sai: bắt được | '
        'Key đúng: xác nhận | Key đúng: báo động giả |',
        '|---|---|---|---|---|---|---|',
    ]
    for row in summary['solvers']:
        lines.append(
            f"| `{row['solver']}` | {', '.join(row['families'])} | {row['items']} | "
            f"{pct(row['wrong_keys']['reproduced_wrong_key'])} | "
            f"{pct(row['wrong_keys']['caught'])} | "
            f"{pct(row['correct_keys']['confirmed'])} | "
            f"{pct(row['correct_keys']['false_alarm'])} |")
    lines += [
        '',
        '## Từng cặp solver',
        '',
        '| Cặp | Cùng có kết quả | Trùng giá trị | κ (đồng ý với key) | '
        'Cả hai tái tạo key sai |',
        '|---|---|---|---|---|',
    ]
    for row in summary['pairs']:
        lines.append(
            f"| `{row['pair'][0]}` × `{row['pair'][1]}` | {row['both_definite']} | "
            f"{pct(row['value_agreement'])} | {row['kappa_agrees_with_key']} "
            f"(n={row['kappa_n']}) | {pct(row['both_reproduce_wrong_key'])} |")
    lines += [
        '',
        '## Cấu hình hội đồng',
        '',
        'Nhãn = `independently_verified`. Cờ = `mismatch` hoặc `refuted` '
        '(chuyển người duyệt).',
        '',
        '| Hội đồng | Luật | Câu | Key sai được cấp nhãn ↓ | Key sai bị gắn cờ ↑ | '
        'Key đúng được cấp nhãn ↑ | Key đúng bị gắn cờ ↓ |',
        '|---|---|---|---|---|---|---|',
    ]
    for row in summary['configurations']:
        rule = ('tất cả' if row['consensus'] == 'all'
                else f"≥{row['consensus_size']}/{len(row['members'])}")
        lines.append(
            f"| {' + '.join(f'`{m}`' for m in row['members'])} | {rule} | "
            f"{row['items']} | {pct(row['wrong_key_certified'])} | "
            f"{pct(row['wrong_key_flagged'])} | {pct(row['correct_key_certified'])} | "
            f"{pct(row['correct_key_flagged'])} |")
    lines += ['', '## Key sai vẫn được cấp nhãn', '']
    any_leak = False
    for row in summary['configurations']:
        if row['certified_wrong_items']:
            any_leak = True
            lines.append(f"- {' + '.join(row['members'])} ({row['consensus']}): "
                         f"{', '.join(row['certified_wrong_items'])}")
    if not any_leak:
        lines.append('Không cấu hình nào cấp nhãn cho key sai.')
    lines.append('')
    (out / 'replay_summary.md').write_text('\n'.join(lines), encoding='utf-8')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--solver', action='append', default=[],
                    help="'model' hoặc 'model@http://host:port/v1' (lặp lại được)")
    ap.add_argument('--api-key', default=os.getenv('AQG_INDEPENDENT_API_KEY')
                    or os.getenv('OPENAI_API_KEY', ''))
    ap.add_argument('--out', required=True)
    ap.add_argument('--no-recorded', action='store_true',
                    help='không dùng kết quả gpt-4o-mini đã lưu trong artifact')
    ap.add_argument('--runs', nargs='+', default=['run_a', 'run_b', 'run_c'])
    ap.add_argument('--limit', type=int, default=0, help='chỉ lấy N câu đầu (chạy thử)')
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--max-tokens', type=int, default=1200)
    ap.add_argument('--max-panel', type=int, default=4)
    ap.add_argument('--analyze-only', action='store_true')
    args = ap.parse_args()

    os.chdir(API_ROOT)
    from pipeline import panel_eval as pe
    from pipeline.direct_pdf.agents.pdf_independent_agent import parse_solver_specs
    from pipeline.model_family import model_family

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sources = [s for s in pe.DEFAULT_SOURCES if s.name in args.runs]
    items = pe.load_labelled_items(API_ROOT, sources)
    if args.limit:
        items = items[:args.limit]
    print(f'[replay] {len(items)} câu có nhãn '
          f'({sum(1 for i in items if not i.key_correct)} key sai)', flush=True)

    specs = parse_solver_specs(args.solver, '')
    targets: pe.Targets = {}
    for spec in specs:
        if args.analyze_only:
            from pipeline.independent_target import INDEPENDENT_PROMPT_VERSION
            raw = _load_cache(_cache_path(out, spec.model), INDEPENDENT_PROMPT_VERSION)
        else:
            raw = solve_all(items, spec, out=out, api_key=args.api_key,
                            workers=args.workers, max_tokens=args.max_tokens)
        targets[spec.model] = {k: pe.target_from_dict(v) for k, v in raw.items()}
    if args.analyze_only and not specs:
        for path in sorted((out / 'cache').glob('*.jsonl')):
            print(f'[replay] gợi ý: thêm --solver cho cache {path.name}')

    if not args.no_recorded:
        targets[RECORDED] = {
            i.item_id: pe.target_from_dict(i.recorded) for i in items if i.recorded}

    solvers = list(targets)
    if not solvers:
        ap.error('không có solver nào (thêm --solver hoặc bỏ --no-recorded)')

    generators = sorted({i.generator for i in items})
    summary = {
        'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'generator': ', '.join(generators),
        'generator_family': ', '.join(sorted({model_family(g) for g in generators})),
        'items': {
            'total': len(items),
            'wrong_keys': sum(1 for i in items if not i.key_correct),
            'correct_keys': sum(1 for i in items if i.key_correct),
            'by_run': {s.name: sum(1 for i in items if i.run == s.name)
                       for s in sources},
            'without_numeric_key': sum(1 for i in items if i.key_value is None),
        },
        'solvers': [pe.solver_summary(items, targets, s) for s in solvers],
        'pairs': [pe.pairwise_summary(items, targets, a, b)
                  for n, a in enumerate(solvers) for b in solvers[n + 1:]],
        'configurations': pe.all_configurations(items, targets, solvers,
                                                max_size=args.max_panel),
    }
    (out / 'replay_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'replay_items.json').write_text(json.dumps([
        {
            'item_id': i.item_id, 'question_id': i.question_id,
            'key_correct': i.key_correct, 'key_value': i.key_value,
            'original_status': i.original_status,
            'solvers': {s: (targets[s][i.item_id].to_dict()
                            if i.item_id in targets[s] else None) for s in solvers},
        } for i in items
    ], ensure_ascii=False, indent=2), encoding='utf-8')
    write_markdown(summary, out)
    print(f'[replay] -> {out / "replay_summary.md"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

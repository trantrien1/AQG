# -*- coding: utf-8 -*-
"""Benchmark quét: nhiều tài liệu × nhiều seed × nhiều arm ablation.

Mở rộng `bench_b1.py` (một tài liệu, một cấu hình) thành một lưới thí nghiệm.
Mỗi ô của lưới là một *cell* chạy trong subprocess riêng và ghi ra:

    <out>/<arm>/seed<k>/<doc>.json          artifact thô (câu + câu bị loại)
    <out>/<arm>/seed<k>/<doc>.manifest.json điều kiện chạy (seed/model/hash/...)
    <out>/<arm>/seed<k>/<doc>.log           log

Sau khi chạy xong, `--aggregate-only` gộp mọi cell thành `suite_metrics.json`
và `suite_summary.md`.

Script này KHÔNG bịa số: mỗi ô trong bảng tổng hợp chỉ xuất hiện khi cell tương
ứng đã chạy thật và để lại artifact. Ô chưa chạy hiện là `—`.

Ví dụ::

    python scripts/bench_suite.py \\
        --pdfs pdftest/file_1_trang_1-31.pdf pdftest/file_2_trang_31-61.pdf \\
        --arms full_system plus_verifier --seeds 42 43 --n 10 \\
        --out report/bench/suite-20260725

    python scripts/bench_suite.py --out report/bench/suite-20260725 \\
        --aggregate-only --ground-truth report/bench/.../ground_truth_cas.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


#: run_cell trả mã này khi nhà cung cấp chặn hạn mức — driver dừng cả lưới.
EXIT_QUOTA_EXHAUSTED = 3


def _slug(text: str) -> str:
    return re.sub(r'[^0-9A-Za-z_-]+', '_', str(text))[:48]


# ------------------------------------------------------------------ one cell
def run_cell(pdf_path: str, out_json: str, n: int, arm: str, seed: int) -> int:
    """Chạy MỘT ô của lưới trong process này."""
    os.chdir(API_ROOT)
    import random

    from pipeline import ablation
    from pipeline import config as cfg
    from pipeline.direct_pdf.generator import DirectPdfQuestionGenerator
    from pipeline.llm_client import get_tracker, reset_tracker
    from pipeline.run_manifest import (
        build_manifest, reproducibility_gaps, validity_warnings,
    )

    if not cfg.has_llm_api_key():
        print(f'Missing LLM key: {cfg.missing_llm_api_key_message()}')
        return 2

    ablation.set_arm(arm)
    random.seed(seed)

    manifest = build_manifest(
        run_id=f'{arm}-seed{seed}-{Path(pdf_path).stem}',
        documents=[pdf_path], seed=seed,
        label=f'bench_suite arm={arm} seed={seed}',
        notes={'requested_questions': n},
    )

    from pipeline.llm_client import ProviderQuotaExhausted

    reset_tracker()
    t0 = time.time()

    def _progress(event: Dict[str, Any]) -> None:
        # Một dòng mỗi câu được nhận: đủ để theo dõi từ xa (vd notebook Colab)
        # mà không làm log phình.
        if event.get('stage') in ('question_accepted', 'generation_finished'):
            print(f"[cell] {event.get('stage')} {event.get('accepted')}/"
                  f"{event.get('target')} sau {event.get('attempted')} lượt "
                  f"({time.time() - t0:.0f}s)", flush=True)

    try:
        result = DirectPdfQuestionGenerator(model=cfg.GENERATOR_MODEL).generate(
            pdf_path=pdf_path,
            requested_count=n,
            bloom_distribution=[dict(x) for x in cfg.DEFAULT_DIFFICULTY_DISTRIBUTION],
            progress_callback=_progress,
        )
    except ProviderQuotaExhausted as exc:
        # Hết hạn mức tài khoản: các ô còn lại cũng sẽ hết. Báo mã riêng để
        # driver dừng cả lưới thay vì đẻ thêm artifact rỗng.
        print(f'[cell] QUOTA EXHAUSTED, bỏ ô này và dừng lưới: {exc}')
        return EXIT_QUOTA_EXHAUSTED
    duration = time.time() - t0
    cost = get_tracker().report()
    manifest.finish()

    out = Path(out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        'metadata': {
            'bench': 'suite',
            'arm': arm,
            'seed': seed,
            'source_pdf': str(pdf_path),
            'source_pdf_name': os.path.basename(pdf_path),
            'requested_questions': result.requested_count,
            'accepted_questions': result.accepted_count,
            'is_partial': result.is_partial,
            'parse_errors': result.parse_errors,
            'verify_failures': result.verify_failures,
            'error_code': result.error_code,
            'error_message': result.error_message,
            'cost': cost,
            'duration_seconds': duration,
            'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        },
        'questions': result.questions,
        'rejected': result.rejected,
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    manifest.notes['reproducibility_gaps'] = reproducibility_gaps(manifest)
    manifest.notes['validity_warnings'] = validity_warnings(manifest)
    manifest.write(out.with_suffix('.manifest.json'))

    print(f'[cell] arm={arm} seed={seed} {os.path.basename(pdf_path)}: '
          f'delivered={result.accepted_count}/{n} '
          f'rejected={len(result.rejected)} tokens={cost.get("tokens")} '
          f'{duration:.0f}s')
    return 0


def _has_usable_artifact(path: Path) -> bool:
    """Ô đã chạy được rồi thì lần chạy sau bỏ qua (resume sau khi hết quota).

    Artifact rỗng (0 token) KHÔNG tính là đã chạy — nó chính là thứ cần chạy lại.
    """
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return False
    md = data.get('metadata') or {}
    return bool((md.get('cost') or {}).get('tokens'))


# ------------------------------------------------------------------ gộp lưới
def aggregate(out_dir: Path, ground_truth_path: Optional[str]) -> Dict[str, Any]:
    from pipeline.eval_metrics import compute_metrics, load_ground_truth

    ground_truth = load_ground_truth(ground_truth_path) if ground_truth_path else None
    cells: List[Dict[str, Any]] = []
    for path in sorted(out_dir.rglob('*.json')):
        if path.name.endswith('.manifest.json') or path.name.startswith('suite_'):
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        md = data.get('metadata') or {}
        if md.get('bench') != 'suite':
            continue
        metrics = compute_metrics(
            data.get('questions') or [],
            data.get('rejected') or [],
            ground_truth=ground_truth,
            cost=md.get('cost') or {},
            duration_seconds=md.get('duration_seconds'),
            requested=md.get('requested_questions'),
        )
        manifest_path = path.with_suffix('.manifest.json')
        manifest = None
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except Exception:
                manifest = None
        cells.append({
            'arm': md.get('arm'),
            'seed': md.get('seed'),
            'document': md.get('source_pdf_name'),
            'artifact': str(path.relative_to(out_dir)),
            'metrics': metrics.to_dict(),
            'manifest': {
                'run_id': (manifest or {}).get('run_id'),
                'mechanisms': (manifest or {}).get('mechanisms'),
                'models': (manifest or {}).get('models'),
                'prompt_version': (manifest or {}).get('prompt_version'),
                'verifier_version': (manifest or {}).get('verifier_version'),
                'code': (manifest or {}).get('code'),
                'reproducibility_gaps':
                    ((manifest or {}).get('notes') or {}).get('reproducibility_gaps'),
                'validity_warnings':
                    ((manifest or {}).get('notes') or {}).get('validity_warnings'),
            } if manifest else None,
        })

    ran = [c for c in cells if _cell_ran(c)]
    starved = [
        {'arm': c['arm'], 'seed': c['seed'], 'document': c['document'],
         'reason': 'không tiêu token nào — nhiều khả năng nhà cung cấp chặn hạn mức'}
        for c in cells if not _cell_ran(c)
    ]
    return {
        'generated_at': dt.datetime.now(dt.timezone.utc).isoformat(),
        'ground_truth': ground_truth_path,
        'n_cells': len(ran),
        'n_cells_with_artifact': len(cells),
        'cells_without_data': starved,
        'arms': sorted({str(c['arm']) for c in ran if c['arm']}),
        'seeds': sorted({c['seed'] for c in ran if c['seed'] is not None}),
        'documents': sorted({str(c['document']) for c in ran if c['document']}),
        'cells': cells,
        'by_arm': _by_arm(cells),
    }


def _cell_ran(cell: Dict[str, Any]) -> bool:
    """Ô có thực sự chạy được không.

    Khi tài khoản hết hạn mức, mọi lượt gọi trả 429 và ô vẫn ghi ra artifact
    với 0 câu, 0 token, kèm một nắm bản ghi "writer không sinh được". Gộp những
    ô đó vào mẫu số sẽ kéo tỉ lệ nhận xuống một con số vô nghĩa và trông y hệt
    như chất lượng kém. Ô không tiêu một token nào = không có dữ liệu, không
    phải kết quả xấu.
    """
    cost = cell['metrics']['cost']
    return bool(cost.get('tokens')) or bool(
        cell['metrics']['counts']['pipeline_delivered'])


def _by_arm(cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Gộp theo arm — chỉ gộp những ô THẬT SỰ chạy được."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for cell in cells:
        if not _cell_ran(cell):
            continue
        grouped.setdefault(str(cell['arm']), []).append(cell)

    out: Dict[str, Any] = {}
    for arm, arm_cells in grouped.items():
        delivered = sum(c['metrics']['counts']['pipeline_delivered'] for c in arm_cells)
        candidates = sum(c['metrics']['counts']['total_candidates'] for c in arm_cells)
        tokens = [c['metrics']['cost']['tokens'] for c in arm_cells
                  if c['metrics']['cost']['tokens']]
        seconds = [c['metrics']['cost']['duration_seconds'] for c in arm_cells
                   if c['metrics']['cost']['duration_seconds']]
        status_totals: Dict[str, int] = {}
        for cell in arm_cells:
            for status, count in cell['metrics']['verification']['status_distribution'].items():
                status_totals[status] = status_totals.get(status, 0) + count
        incomplete = sum(c['metrics']['verification'].get('verification_incomplete', 0)
                         for c in arm_cells)
        dissent = sum(c['metrics']['verification'].get('panel_dissent', 0)
                      for c in arm_cells)
        independence = sorted({
            str(((c.get('manifest') or {}).get('models') or {}).get('independence'))
            for c in arm_cells})
        correct = [c['metrics']['correctness'] for c in arm_cells]
        labelled = sum(c.get('labelled', 0) for c in correct)
        out[arm] = {
            'n_cells': len(arm_cells),
            'n_seeds': len({c['seed'] for c in arm_cells}),
            'n_documents': len({c['document'] for c in arm_cells}),
            'pipeline_delivered': delivered,
            'total_candidates': candidates,
            'admission_rate': round(delivered / candidates, 4) if candidates else None,
            'status_totals': status_totals,
            # Câu có solver độc lập không chạy được — không phải 'không kiểm được'.
            'verification_incomplete': incomplete,
            'panel_dissent': dissent,
            'independence': independence,
            'tokens_per_delivered': (
                round(sum(tokens) / delivered, 1) if tokens and delivered else None),
            'seconds_per_delivered': (
                round(sum(seconds) / delivered, 1) if seconds and delivered else None),
            'correctness': (
                _pool_correctness(correct) if labelled else
                {'labelled': 0,
                 'note': 'chưa có nhãn ground-truth cho arm này — không có '
                         'correctness rate để báo cáo'}
            ),
            # CỘNG DỒN theo seed. Phiên bản trước dùng dict-comprehension nên
            # nhiều ô cùng seed ghi đè nhau và bảng biến thiên toàn số của ô
            # cuối cùng.
            'per_seed': _per_seed(arm_cells),
        }
    return out


def _per_seed(arm_cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    seeds: Dict[str, Dict[str, int]] = {}
    for cell in arm_cells:
        entry = seeds.setdefault(str(cell['seed']), {'cells': 0, 'delivered': 0,
                                                    'candidates': 0})
        entry['cells'] += 1
        entry['delivered'] += cell['metrics']['counts']['pipeline_delivered']
        entry['candidates'] += cell['metrics']['counts']['total_candidates']
    return dict(sorted(seeds.items()))


def _pool_correctness(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    labelled = sum(e.get('labelled', 0) for e in entries)
    correct = sum(e.get('correct_keys', 0) for e in entries)
    wrong = sum(e.get('wrong_keys', 0) for e in entries)
    fp = sum((e.get('verifier_false_positive_rate') or {}).get('n', 0) for e in entries)
    fn = sum((e.get('verifier_false_negative_rate') or {}).get('n', 0) for e in entries)
    return {
        'labelled': labelled,
        'correct_keys': correct,
        'wrong_keys': wrong,
        'independently_correct_answer_rate':
            round(correct / labelled, 4) if labelled else None,
        'verifier_false_positive_rate': round(fp / wrong, 4) if wrong else None,
        'verifier_false_negative_rate': round(fn / correct, 4) if correct else None,
    }


def write_markdown(summary: Dict[str, Any], out_dir: Path) -> None:
    lines = [
        '# Benchmark suite',
        '',
        f"Sinh lúc {summary['generated_at']}. "
        f"{summary['n_cells']} ô có dữ liệu "
        f"({len(summary['arms'])} arm × {len(summary['seeds'])} seed × "
        f"{len(summary['documents'])} tài liệu).",
        '',
        'Ô nào chưa chạy thì KHÔNG có dòng nào trong bảng — bảng này chỉ chứa '
        'kết quả thật.',
        '',
    ]
    starved = summary.get('cells_without_data') or []
    if starved:
        lines += [
            f'> ⚠ {len(starved)} ô có artifact nhưng KHÔNG tiêu token nào (nhà '
            f'cung cấp chặn hạn mức). Chúng đã bị loại khỏi mọi mẫu số dưới '
            f'đây — gộp vào sẽ trông y hệt chất lượng kém.',
            '',
        ]
        for c in starved:
            lines.append(f"> - `{c['arm']}` seed {c['seed']} — {c['document']}")
        lines.append('')
    lines += [
        '## Theo arm',
        '',
        '| Arm | Ô | Câu giao ra | Tỉ lệ nhận | Độc lập xác nhận | Chỉ nhất quán | '
        'Chuyển người | Token/câu | Giây/câu |',
        '|---|---|---|---|---|---|---|---|---|',
    ]
    from pipeline.ablation import ARM_ORDER
    order = [a for a in ARM_ORDER if a in summary['by_arm']]
    order += [a for a in sorted(summary['by_arm']) if a not in order]
    for arm in order:
        row = summary['by_arm'][arm]
        st = row['status_totals']
        lines.append(
            f"| `{arm}` | {row['n_cells']} | {row['pipeline_delivered']} | "
            f"{row['admission_rate']} | "
            f"{st.get('independently_verified', 0)} | "
            f"{st.get('consistency_confirmed', 0)} | "
            f"{st.get('mismatch', 0) + st.get('refuted', 0)} | "
            f"{row['tokens_per_delivered']} | {row['seconds_per_delivered']} |"
        )

    lines += ['', '## Độc lập của kiểm chứng', '']
    for arm in order:
        row = summary['by_arm'][arm]
        lines.append(
            f"- `{arm}`: mức độc lập {', '.join(row.get('independence') or ['?'])}; "
            f"{row.get('verification_incomplete', 0)} câu có solver không chạy được; "
            f"{row.get('panel_dissent', 0)} câu hội đồng bất đồng")
    lines += ['', '## Correctness (chỉ khi có nhãn ngoài)', '']
    any_labels = False
    for arm in order:
        c = summary['by_arm'][arm]['correctness']
        if not c.get('labelled'):
            continue
        any_labels = True
        lines.append(
            f"- `{arm}`: {c['correct_keys']}/{c['labelled']} key đúng "
            f"({c['independently_correct_answer_rate']}), "
            f"verifier FP {c['verifier_false_positive_rate']}, "
            f"FN {c['verifier_false_negative_rate']}"
        )
    if not any_labels:
        lines.append(
            'Chưa có nhãn ground-truth nào. Không có correctness rate để báo cáo '
            '— trạng thái kiểm chứng của pipeline KHÔNG thay thế được nhãn ngoài.'
        )

    lines += ['', '## Biến thiên giữa các seed', '']
    measurable = False
    for arm in order:
        per_seed = summary['by_arm'][arm]['per_seed']
        if len(per_seed) > 1:
            measurable = True
            lines.append(f'- `{arm}`:')
            for seed, row in per_seed.items():
                lines.append(
                    f"  - seed {seed}: {row['delivered']} câu / "
                    f"{row['candidates']} ứng viên, {row['cells']} ô")
    if not measurable:
        lines.append(
            'Chỉ MỘT seed có dữ liệu — biến thiên giữa các lần chạy CHƯA đo được. '
            'Đây là số liệu còn thiếu, không phải số liệu bằng 0.'
        )
    lines.append('')
    (out_dir / 'suite_summary.md').write_text('\n'.join(lines), encoding='utf-8')


# --------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description='Multi-document / seed / arm benchmark')
    ap.add_argument('--cell', nargs=5,
                    metavar=('PDF', 'OUT_JSON', 'N', 'ARM', 'SEED'),
                    help='internal: chạy một ô trong process này')
    ap.add_argument('--pdfs', nargs='+', help='các PDF nguồn')
    ap.add_argument('--arms', nargs='+', default=['full_system'],
                    help='arm ablation (xem pipeline.ablation.ARMS)')
    ap.add_argument('--seeds', nargs='+', type=int, default=[42])
    ap.add_argument('--n', type=int, default=10, help='số câu mỗi ô')
    # KHÔNG required: chế độ --cell (do chính script tự gọi lại qua subprocess)
    # đã mang sẵn đường dẫn output trong tham số của nó. Đặt required=True ở đây
    # làm mọi ô chết ngay ở argparse trước khi chạy được dòng nào.
    ap.add_argument('--out', default='', help='thư mục output của suite')
    ap.add_argument('--ground-truth', default='', help='file nhãn ngoài (tuỳ chọn)')
    ap.add_argument('--aggregate-only', action='store_true')
    return ap


def main() -> int:
    ap = build_parser()
    args = ap.parse_args()

    if args.cell:
        pdf, out_json, n, arm, seed = args.cell
        return run_cell(pdf, out_json, int(n), arm, int(seed))

    if not args.out:
        ap.error('--out bắt buộc khi chạy cả suite')
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.aggregate_only:
        if not args.pdfs:
            ap.error('--pdfs bắt buộc (trừ khi --aggregate-only)')
        from pipeline.ablation import ARMS
        unknown = [a for a in args.arms if a not in ARMS]
        if unknown:
            ap.error(f'arm không hợp lệ: {unknown}; hợp lệ: {sorted(ARMS)}')

        py = str(API_ROOT / 'venv' / 'Scripts' / 'python.exe')
        if not Path(py).exists():
            py = sys.executable
        total = len(args.arms) * len(args.seeds) * len(args.pdfs)
        done = 0
        quota_exhausted = False
        for arm in args.arms:
            for seed in args.seeds:
                for pdf in args.pdfs:
                    done += 1
                    cell_dir = out_dir / _slug(arm) / f'seed{seed}'
                    cell_dir.mkdir(parents=True, exist_ok=True)
                    out_json = cell_dir / f'{_slug(Path(pdf).stem)}.json'
                    log_path = out_json.with_suffix('.log')
                    if _has_usable_artifact(out_json):
                        print(f'[suite {done}/{total}] BỎ QUA (đã có dữ liệu) '
                              f'{out_json}', flush=True)
                        continue
                    print(f'[suite {done}/{total}] arm={arm} seed={seed} {pdf}',
                          flush=True)
                    with open(log_path, 'w', encoding='utf-8') as log:
                        proc = subprocess.run(
                            [py, str(Path(__file__)), '--cell', pdf,
                             str(out_json), str(args.n), arm, str(seed)],
                            stdout=log, stderr=subprocess.STDOUT, cwd=str(API_ROOT),
                        )
                    print(f'[suite]   exit={proc.returncode} (log: {log_path})',
                          flush=True)
                    if proc.returncode == EXIT_QUOTA_EXHAUSTED:
                        print(f'[suite] DỪNG: hết hạn mức nhà cung cấp sau '
                              f'{done - 1}/{total} ô. Chạy lại cùng --out để '
                              f'làm nốt phần còn lại khi quota mở.', flush=True)
                        quota_exhausted = True
                        break
                if quota_exhausted:
                    break
            if quota_exhausted:
                break

    summary = aggregate(out_dir, args.ground_truth or None)
    (out_dir / 'suite_metrics.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    write_markdown(summary, out_dir)
    print(f'[suite] {summary["n_cells"]} ô -> {out_dir / "suite_summary.md"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

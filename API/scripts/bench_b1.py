# -*- coding: utf-8 -*-
"""B1 — System benchmark: chạy pipeline thật trên một loạt PDF, gom metric.

Mỗi PDF chạy trong MỘT subprocess riêng (cách ly tracker/token đếm phí và
tránh một PDF hỏng kéo sập cả batch). Mỗi run lưu trọn:
  metadata (cost/duration/config) + questions (accepted) + rejected (reason-coded)

Sau batch, gộp thành b1_summary.json + b1_summary.md — số liệu cho section
Evaluation của paper: acceptance rate, phân bố reject theo stage/reason,
sự kiện verifier (mismatch giữ lại, sửa answer key, multi-answer, hint lỗi),
chi phí token/call và thời gian.

Cách chạy (từ thư mục API, venv đã có sẵn):
  venv\\Scripts\\python.exe scripts\\bench_b1.py ^
      --pdfs pdftest\\file_1_trang_1-31.pdf pdftest\\file_2_trang_31-61.pdf ^
      --n 10 --out report\\bench\\<stamp>

Chạy lại 1 PDF đơn lẻ (nội bộ, batch tự gọi):
  ... scripts\\bench_b1.py --single <pdf> <out_json> <n>
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
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

# Windows consoles default to cp1252, which cannot encode the Vietnamese
# summary strings printed below — a UnicodeEncodeError there would crash the
# batch with exit 1 even though every PDF and all artifacts completed fine.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


# ---------------------------------------------------------------- single run
def run_single(pdf_path: str, out_json: str, n: int) -> int:
    """Chạy pipeline 1 PDF trong process này; lưu đầy đủ artifacts."""
    os.chdir(API_ROOT)
    from pipeline import config as cfg
    from pipeline.direct_pdf.generator import DirectPdfQuestionGenerator
    from pipeline.llm_client import get_tracker, reset_tracker
    from pipeline.run_manifest import build_manifest, reproducibility_gaps

    if not cfg.has_llm_api_key():
        print(f'Missing LLM key: {cfg.missing_llm_api_key_message()}')
        return 2

    # Chụp điều kiện chạy TRƯỚC khi sinh: seed, model, phiên bản prompt/verifier,
    # hash tài liệu, commit code, bảng ngưỡng và bảng bật/tắt cơ chế. Không có
    # cái này thì một con số trong bài báo không truy được về bản đã sinh ra nó.
    manifest = build_manifest(
        run_id=f'b1-{os.path.splitext(os.path.basename(pdf_path))[0]}',
        documents=[pdf_path], label='bench_b1',
        notes={'requested_questions': n},
    )

    reset_tracker()
    t0 = time.time()
    gen = DirectPdfQuestionGenerator(model=cfg.GENERATOR_MODEL)
    result = gen.generate(
        pdf_path=pdf_path,
        requested_count=n,
        bloom_distribution=[dict(x) for x in cfg.DEFAULT_DIFFICULTY_DISTRIBUTION],
    )
    duration = time.time() - t0
    cost = get_tracker().report()

    payload = {
        'metadata': {
            'bench': 'B1',
            'mode': 'Direct_PDF_Mode',
            'source_pdf': str(pdf_path),
            'source_pdf_name': os.path.basename(pdf_path),
            'requested_questions': result.requested_count,
            'accepted_questions': result.accepted_count,
            'is_partial': result.is_partial,
            'parse_errors': result.parse_errors,
            'verify_failures': result.verify_failures,
            'error_code': result.error_code,
            'error_message': result.error_message,
            'generator_model': cfg.GENERATOR_MODEL,
            'judge_model': cfg.JUDGE_MODEL,
            'parallel_slots': cfg.DIRECT_PDF_PARALLEL_SLOTS,
            'pdf_attach_mode': getattr(cfg, 'PDF_ATTACH_MODE', ''),
            'cost': cost,
            'duration_seconds': duration,
            'generated_at': dt.datetime.utcnow().isoformat() + 'Z',
        },
        'questions': result.questions,
        'rejected': result.rejected,
    }
    os.makedirs(os.path.dirname(out_json) or '.', exist_ok=True)
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    manifest.finish()
    manifest.notes['reproducibility_gaps'] = reproducibility_gaps(manifest)
    manifest.write(os.path.splitext(out_json)[0] + '.manifest.json')
    print(f'[B1-single] {os.path.basename(pdf_path)}: '
          f'accepted={result.accepted_count}/{n} '
          f'rejected={len(result.rejected)} '
          f'tokens={cost.get("tokens")} calls={cost.get("calls")} '
          f'duration={duration:.0f}s')
    return 0


# ------------------------------------------------------------- reject triage
_VERIFIER_REASON_BUCKETS = [
    ('answer_text_mismatch', re.compile(r'answer_text_mismatch')),
    ('multi_answer', re.compile(r'^multi_answer')),
    ('distractor_validator', re.compile(r'^distractor_validator')),
    ('rule_validator', re.compile(r'rule validator failed')),
]


def _classify_reject(stage: str, reason: str) -> str:
    reason = str(reason or '')
    if stage == 'verifier':
        for name, rx in _VERIFIER_REASON_BUCKETS:
            if rx.search(reason):
                return f'verifier:{name}'
        return 'verifier:other'
    if stage == 'critic':
        m = re.match(r'\s*([a-z_]+)=', reason)
        return f'critic:{m.group(1)}' if m else 'critic:other'
    return stage or 'unknown'


def _reject_stage(rec: Dict[str, Any]) -> str:
    # _rejected_record ghi stage vào reject_log[0].stage hoặc reject_stage.
    stage = rec.get('reject_stage') or rec.get('stage')
    if not stage:
        log = rec.get('reject_log') or []
        for entry in log:
            if isinstance(entry, dict) and entry.get('stage'):
                stage = entry['stage']
                break
    return str(stage or 'unknown')


def _reject_reason(rec: Dict[str, Any]) -> str:
    reason = rec.get('reject_reason')
    if not reason:
        log = rec.get('reject_log') or []
        for entry in log:
            if isinstance(entry, dict) and entry.get('reason'):
                reason = entry['reason']
                break
    return str(reason or '')


# ---------------------------------------------------------------- aggregate
def aggregate(out_dir: Path) -> Dict[str, Any]:
    per_pdf: List[Dict[str, Any]] = []
    for p in sorted(out_dir.glob('b1_*.json')):
        if p.name in ('b1_summary.json',):
            continue
        data = json.loads(p.read_text(encoding='utf-8'))
        md = data.get('metadata') or {}
        qs = data.get('questions') or []
        rej = data.get('rejected') or []

        reject_dist: Counter = Counter()
        for r in rej:
            reject_dist[_classify_reject(_reject_stage(r), _reject_reason(r))] += 1

        ver_true = sum(1 for q in qs if (q.get('verification') or {}).get('verified') is True)
        ver_false = sum(1 for q in qs if (q.get('verification') or {}).get('verified') is False)
        ver_none = len(qs) - ver_true - ver_false
        key_repaired = sum(1 for q in qs if (q.get('verification') or {}).get('answer_key_repaired'))
        hint_errored = sum(1 for q in qs if (q.get('verification') or {}).get('verifier_errored'))
        quote_repaired = sum(1 for q in qs if (q.get('verification') or {}).get('source_quote_repaired'))
        needs_rev = sum(1 for q in qs if q.get('review_status') == 'needs_revision')

        def _avg(vals):
            vals = [v for v in vals if isinstance(v, (int, float))]
            return round(sum(vals) / len(vals), 4) if vals else None

        cost = md.get('cost') or {}
        accepted = len(qs)
        attempted = accepted + len(rej)
        per_pdf.append({
            'pdf': md.get('source_pdf_name'),
            'requested': md.get('requested_questions'),
            'accepted': accepted,
            'rejected': len(rej),
            'attempted_candidates': attempted,
            'acceptance_rate': round(accepted / attempted, 4) if attempted else None,
            'reject_distribution': dict(reject_dist),
            'verification': {
                'verified_true': ver_true,
                'verified_false_kept': ver_false,   # mismatch giữ lại -> needs_revision
                'verified_none': ver_none,          # type=none / không machine-checkable
                'answer_key_repaired': key_repaired,
                'verifier_hint_errored': hint_errored,
                'source_quote_repaired': quote_repaired,
            },
            'needs_revision': needs_rev,
            'quality_avg': _avg((q.get('judging') or {}).get('quality') for q in qs),
            'grounding_avg': _avg((q.get('judging') or {}).get('grounding') for q in qs),
            'bloom_distribution': dict(Counter(q.get('cognitive_level') for q in qs)),
            'cost_tokens': cost.get('tokens'),
            'cost_calls': cost.get('calls'),
            'duration_seconds': round(md.get('duration_seconds') or 0, 1),
            'seconds_per_accepted': (
                round((md.get('duration_seconds') or 0) / accepted, 1) if accepted else None
            ),
            'calls_per_accepted': (
                round((cost.get('calls') or 0) / accepted, 2) if accepted else None
            ),
        })

    # ---- totals ----
    def _sum(key):
        return sum((row.get(key) or 0) for row in per_pdf)

    total_accepted = _sum('accepted')
    total_attempted = _sum('attempted_candidates')
    total_reject: Counter = Counter()
    for row in per_pdf:
        total_reject.update(row['reject_distribution'])
    totals = {
        'pdfs': len(per_pdf),
        'requested': _sum('requested'),
        'accepted': total_accepted,
        'rejected': _sum('rejected'),
        'acceptance_rate': round(total_accepted / total_attempted, 4) if total_attempted else None,
        'reject_distribution': dict(total_reject),
        'verification': {
            k: sum((row['verification'][k] or 0) for row in per_pdf)
            for k in ('verified_true', 'verified_false_kept', 'verified_none',
                      'answer_key_repaired', 'verifier_hint_errored',
                      'source_quote_repaired')
        },
        'needs_revision': _sum('needs_revision'),
        'cost_tokens': _sum('cost_tokens'),
        'cost_calls': _sum('cost_calls'),
        'duration_seconds': round(_sum('duration_seconds'), 1),
        'seconds_per_accepted': (
            round(_sum('duration_seconds') / total_accepted, 1) if total_accepted else None
        ),
    }
    return {'per_pdf': per_pdf, 'totals': totals}


def write_mismatch_review(out_dir: Path) -> int:
    """Gom mọi ca liên quan verifier để NGƯỜI duyệt: mismatch giữ lại,
    answer_text_mismatch bị loại, answer-key repair. Đây là hồ sơ để tác giả
    tự phân loại 'hint viết lệch' vs 'LLM sai thật' — KHÔNG tự kết luận."""
    rows: List[str] = []
    for p in sorted(out_dir.glob('b1_*.json')):
        if p.name == 'b1_summary.json':
            continue
        data = json.loads(p.read_text(encoding='utf-8'))
        pdf = (data.get('metadata') or {}).get('source_pdf_name')
        for q in data.get('questions') or []:
            v = q.get('verification') or {}
            if v.get('verified') is False or v.get('answer_key_repaired'):
                kind = ('KEY-REPAIRED' if v.get('answer_key_repaired')
                        else 'MISMATCH-KEPT')
                rows.append(
                    f"### [{kind}] {pdf} — {q.get('question_id')}\n\n"
                    f"- **Stem**: {q.get('stem')}\n"
                    f"- **Answer key**: {q.get('answer_key')} | options: "
                    + ' | '.join(f"{o.get('key')}: {o.get('text')}"
                                 for o in q.get('options') or []) + '\n'
                    f"- **Verifier detail**: `{v.get('detail')}`\n"
                    f"- **Phân loại của người duyệt (điền tay)**: "
                    f"[ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác\n"
                )
        for r in data.get('rejected') or []:
            reason = _reject_reason(r)
            if 'answer_text_mismatch' in reason or reason.startswith('multi_answer'):
                rows.append(
                    f"### [REJECTED] {pdf} — stage={_reject_stage(r)}\n\n"
                    f"- **Reason**: {reason[:300]}\n"
                    f"- **Stem**: {(r.get('stem') or '(không có)')}\n"
                    f"- **Phân loại của người duyệt (điền tay)**: "
                    f"[ ] loại đúng  [ ] loại oan\n"
                )
    text = (
        '# Hồ sơ duyệt tay các ca verifier (B1)\n\n'
        'Mỗi ca dưới đây cần tác giả tự kiểm tra lại bằng tay và tick phân loại.\n'
        'Con số đưa vào paper là kết quả TICK TAY, không phải con số tự động.\n\n'
        + '\n'.join(rows) if rows else
        '# Hồ sơ duyệt tay các ca verifier (B1)\n\nKhông có ca nào trong batch này.\n'
    )
    (out_dir / 'mismatch_review.md').write_text(text, encoding='utf-8')
    return len(rows)


def write_markdown(summary: Dict[str, Any], out_dir: Path) -> None:
    t = summary['totals']
    lines = [
        '# B1 — System benchmark (pipeline thật, không mô phỏng)',
        '',
        f"*Sinh lúc: {dt.datetime.now().isoformat(timespec='seconds')}*",
        '',
        '## Tổng hợp',
        '',
        '| Metric | Giá trị |',
        '|---|---|',
        f"| Số PDF | {t['pdfs']} |",
        f"| Yêu cầu / chấp nhận | {t['requested']} / {t['accepted']} |",
        f"| Ứng viên bị loại | {t['rejected']} |",
        f"| Acceptance rate (trên mọi ứng viên) | {t['acceptance_rate']} |",
        f"| Verified=True / False(kept) / None | "
        f"{t['verification']['verified_true']} / "
        f"{t['verification']['verified_false_kept']} / "
        f"{t['verification']['verified_none']} |",
        f"| Answer-key repaired | {t['verification']['answer_key_repaired']} |",
        f"| Hint lỗi (fallback) | {t['verification']['verifier_hint_errored']} |",
        f"| Needs revision (routed to human) | {t['needs_revision']} |",
        f"| Tokens / calls | {t['cost_tokens']} / {t['cost_calls']} |",
        f"| Tổng thời gian | {t['duration_seconds']}s "
        f"({t['seconds_per_accepted']}s / câu chấp nhận) |",
        '',
        '## Phân bố reject theo gate',
        '',
        '| Gate:reason | Số ca |',
        '|---|---|',
    ]
    for k, v in sorted(t['reject_distribution'].items(), key=lambda x: -x[1]):
        lines.append(f'| {k} | {v} |')
    lines += ['', '## Từng PDF', '']
    for row in summary['per_pdf']:
        lines += [
            f"### {row['pdf']}",
            '',
            f"- accepted {row['accepted']}/{row['requested']} "
            f"(candidates {row['attempted_candidates']}, "
            f"rate {row['acceptance_rate']})",
            f"- verification: {row['verification']}",
            f"- quality_avg {row['quality_avg']} | grounding_avg {row['grounding_avg']}",
            f"- bloom: {row['bloom_distribution']}",
            f"- cost: {row['cost_tokens']} tokens / {row['cost_calls']} calls | "
            f"{row['duration_seconds']}s ({row['seconds_per_accepted']}s/câu)",
            f"- reject: {row['reject_distribution']}",
            '',
        ]
    (out_dir / 'b1_summary.md').write_text('\n'.join(lines), encoding='utf-8')


# -------------------------------------------------------------------- batch
def main() -> int:
    ap = argparse.ArgumentParser(description='B1 system benchmark')
    ap.add_argument('--single', nargs=3, metavar=('PDF', 'OUT_JSON', 'N'),
                    help='internal: chạy 1 PDF trong process này')
    ap.add_argument('--pdfs', nargs='+', help='các PDF nguồn')
    ap.add_argument('--n', type=int, default=10, help='số câu mỗi PDF')
    ap.add_argument('--out', default='', help='thư mục output')
    ap.add_argument('--aggregate-only', action='store_true',
                    help='chỉ gộp lại metric từ output có sẵn trong --out')
    args = ap.parse_args()

    if args.single:
        pdf, out_json, n = args.single
        return run_single(pdf, out_json, int(n))

    out_dir = Path(args.out or
                   f'report/bench/{dt.datetime.now():%Y%m%d-%H%M%S}')
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.aggregate_only:
        if not args.pdfs:
            ap.error('--pdfs bắt buộc (trừ khi --aggregate-only)')
        py = str(API_ROOT / 'venv' / 'Scripts' / 'python.exe')
        for pdf in args.pdfs:
            stem = re.sub(r'[^0-9A-Za-z_-]+', '_', Path(pdf).stem)[:40]
            out_json = out_dir / f'b1_{stem}.json'
            log_path = out_dir / f'b1_{stem}.log'
            print(f'[B1] {pdf} -> {out_json}')
            with open(log_path, 'w', encoding='utf-8') as log:
                proc = subprocess.run(
                    [py, str(Path(__file__)), '--single', pdf,
                     str(out_json), str(args.n)],
                    stdout=log, stderr=subprocess.STDOUT,
                    cwd=str(API_ROOT),
                )
            print(f'[B1]   exit={proc.returncode} (log: {log_path})')

    summary = aggregate(out_dir)
    (out_dir / 'b1_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    n_review = write_mismatch_review(out_dir)
    write_markdown(summary, out_dir)
    print(f'[B1] summary -> {out_dir / "b1_summary.md"}; '
          f'{n_review} ca cần duyệt tay -> mismatch_review.md')
    return 0


if __name__ == '__main__':
    sys.exit(main())

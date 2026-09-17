"""Sinh thử N câu bằng MỘT mô hình rồi soi lỗi bằng các phép kiểm tất định.

Dùng cho hai việc: (a) kiểm tra nhanh sau khi sửa code, (b) làm một ô của phép
quét nhiều mô hình về sau — nên tham số hoá theo mô hình và nhà cung cấp.

Chỉ báo cáo những gì kiểm được bằng máy. KHÔNG chấm chất lượng, không kết luận
câu hỏi hay hay dở — việc đó là của scripts/eqg_eval.py và của người.

    python scripts/gen_probe.py --model openai/gpt-4o-mini \
        --pdf pdftest/file_3_trang_61-90.pdf --n 10 --out report/probe/mini
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def configure(model: str, provider: str, attach: str,
              independent_model: str = '') -> None:
    """Đặt env TRƯỚC khi import pipeline.config (config đọc env lúc import)."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    raw = (ROOT / '.env').read_text(encoding='utf-8-sig')
    if provider == '9router':
        # Khối 9router trong .env đang bị comment; lấy giá trị từ đó.
        def commented(name: str, default: str = '') -> str:
            m = re.search(rf'^#\s*{name}=(\S+)', raw, re.M)
            return m.group(1) if m else default
        os.environ['AQG_LLM_PROVIDER'] = '9router'
        os.environ['NINEROUTER_BASE_URL'] = commented(
            'NINEROUTER_BASE_URL', 'http://127.0.0.1:20128/v1')
        key = commented('OPENAI_API_KEY')
        if key:
            os.environ['OPENAI_API_KEY'] = key
        os.environ['NINEROUTER_GENERATOR_MODEL'] = model
        os.environ['NINEROUTER_JUDGE_MODEL'] = model
    else:
        # .env khai nhiều khối provider chồng nhau; cờ --provider phải thắng,
        # nếu không thì tưởng đang quét OpenRouter mà thực ra vẫn gọi chat2api.
        os.environ['AQG_LLM_PROVIDER'] = provider
    os.environ['AQG_GENERATOR_MODEL'] = model
    os.environ['AQG_JUDGE_MODEL'] = model
    os.environ['AQG_PDF_ATTACH_MODE'] = attach
    # Bộ giải độc lập PHẢI cố định khi quét nhiều mô hình sinh. Mặc định nó bám
    # theo JUDGE_MODEL, tức là quét bộ sinh sẽ kéo tầng kiểm chứng đổi theo —
    # đổi hai thứ cùng lúc thì không quy được hiệu ứng nào cho thứ nào.
    if independent_model:
        os.environ['AQG_INDEPENDENT_VERIFIER_MODEL'] = independent_model


# ------------------------------------------------------- phép kiểm tất định
def inspect(questions):
    from pipeline.rule_validator import _stem_asks_question

    issues = collections.Counter()
    per_q = []
    for q in questions:
        bad = []
        stem = (q.get('stem') or '').strip()
        opts = q.get('options') or []
        key = q.get('answer_key')
        texts = [str(o.get('text', '')).strip() for o in opts]

        if not stem:
            bad.append('stem_empty')
        elif not _stem_asks_question(stem):
            bad.append('stem_asks_nothing')
        if stem.rstrip().endswith(','):
            bad.append('stem_ends_on_comma')

        if len(opts) != 4:
            bad.append(f'options_count={len(opts)}')
        if key not in {o.get('key') for o in opts}:
            bad.append('answer_key_not_in_options')
        if len(set(texts)) != len(texts):
            bad.append('duplicate_options')
        if any(not t for t in texts):
            bad.append('empty_option')

        for t in texts + [stem]:
            if t.count('\\(') != t.count('\\)') or t.count('$') % 2:
                bad.append('unbalanced_latex')
                break

        expl = q.get('explanation_per_distractor') or {}
        n_expl = len(expl) if isinstance(expl, dict) else len(expl or [])
        if n_expl < 3:
            bad.append(f'distractor_traces={n_expl}')

        sol = (q.get('detailed_solution') or q.get('explanation_correct') or '')
        if len(str(sol).strip()) < 30:
            bad.append('solution_too_short')

        src = (q.get('source') or {})
        quote = str(src.get('quote') or src.get('source_quote') or '').strip()
        if not (15 <= len(quote) <= 250):
            bad.append(f'source_quote_len={len(quote)}')

        v = q.get('verification') or {}
        per_q.append({
            'id': q.get('question_id'),
            'bloom': q.get('cognitive_level'),
            'status': v.get('status'),
            'machine_checked': v.get('machine_checked'),
            'independent': bool((v.get('independent') or {}).get('definite')),
            'derivation': bool((v.get('independent') or {}).get('derivation')),
            'review': q.get('review_status'),
            'issues': bad,
            'stem_len': len(stem),
            'stem_tail': stem[-90:],
        })
        for b in bad:
            issues[re.sub(r'=.*', '', b)] += 1
    return per_q, issues


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--model', required=True)
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--n', type=int, default=10)
    ap.add_argument('--out', required=True)
    ap.add_argument('--provider', default='9router')
    ap.add_argument('--attach', default='image',
                    help='file (OpenRouter native), file_url (chat2api), image')
    ap.add_argument('--independent-model', default='',
                    help='cố định bộ giải độc lập cho mọi ô của phép quét')
    ap.add_argument('--max-empty-streak', type=int, default=0,
                    help='số slot hỏng liên tiếp trước khi bỏ cuộc; đặt cố '
                         'định khi quét nhiều mô hình để mọi ô có cùng ngân '
                         'sách lượt thử (mặc định tự tính theo số câu)')
    ap.add_argument('--max-tokens', type=int, default=0,
                    help='ngân sách output mỗi lời gọi; model có reasoning cần '
                         'nhiều hơn hẳn vì phần suy luận cũng tính vào đây')
    args = ap.parse_args()

    if args.max_empty_streak:
        os.environ['AQG_MAX_EMPTY_STREAK'] = str(args.max_empty_streak)
    if args.max_tokens:
        # Đặt TRƯỚC khi import pipeline.config. Ngân sách chung phải đủ cho model
        # có reasoning: token suy luận cũng trừ vào max_tokens, hết ngân sách thì
        # JSON đứt giữa chừng ("Unterminated string") và slot mất trắng.
        os.environ['AQG_GEN_MAX_TOKENS'] = str(args.max_tokens)
        os.environ['AQG_DIRECT_PDF_TOKENS_PER_QUESTION'] = str(args.max_tokens)
        # Hai tác nhân con cũng phải được nới, nếu không model có reasoning vẫn
        # đứt JSON ở khâu Distractor/Critic dù khâu Writer đã đủ chỗ.
        os.environ['AQG_DISTRACTOR_MAX_TOKENS'] = str(args.max_tokens)
        os.environ['AQG_CRITIC_MAX_TOKENS'] = str(args.max_tokens)
        os.environ['AQG_WRITER_NO_EXPLANATION_MAX_TOKENS'] = str(args.max_tokens)
    configure(args.model, args.provider, args.attach, args.independent_model)

    from pipeline import config as cfg
    from pipeline.direct_pdf.generator import DirectPdfQuestionGenerator
    from pipeline.llm_client import (assert_pdf_native_support, get_tracker,
                                     PdfNotNativeError, reset_tracker)
    from pipeline.run_manifest import build_manifest

    print(f'provider={cfg.LLM_PROVIDER} generator={cfg.GENERATOR_MODEL} '
          f'judge={cfg.JUDGE_MODEL} attach={cfg.PDF_ATTACH_MODE}')
    print(f'pdf={args.pdf}  n={args.n}')

    # Chặn đầu vào: model không tự đọc được PDF thì OpenRouter sẽ trích text mà
    # không báo gì. Hỏng ở đây rẻ hơn hỏng sau khi đã tiêu hết token.
    try:
        handling = assert_pdf_native_support(cfg.GENERATOR_MODEL)
    except PdfNotNativeError as exc:
        print(f'DỪNG: {exc}', file=sys.stderr)
        return 4
    print('tài liệu tới mô hình dạng:', handling.get('document_handling'))

    manifest = build_manifest(
        run_id=f"gen_probe-{args.model.replace('/', '_')}-{Path(args.pdf).stem}",
        documents=[args.pdf], seed=42,
        label=f'gen_probe {args.model}',
        notes={'requested_questions': args.n})
    reset_tracker()
    t0 = time.time()
    result = DirectPdfQuestionGenerator(model=cfg.GENERATOR_MODEL).generate(
        pdf_path=args.pdf,
        requested_count=args.n,
        bloom_distribution=[dict(x) for x in cfg.DEFAULT_DIFFICULTY_DISTRIBUTION],
    )
    dur = time.time() - t0
    cost = get_tracker().report()
    manifest.finish()

    import dataclasses
    payload = (dataclasses.asdict(result)
               if dataclasses.is_dataclass(result) else dict(result))
    qs = payload.get('questions') or []
    per_q, issues = inspect(qs)

    if payload.get('error_code'):
        print(f"LỖI generator: {payload['error_code']} "
              f"{str(payload.get('error_message'))[:300]}", file=sys.stderr)

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    (out / 'result.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'manifest.json').write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=1),
        encoding='utf-8')
    rejected = len(payload.get('rejected') or [])
    report = {
        'model': args.model, 'pdf': args.pdf, 'requested': args.n,
        'delivered': len(qs), 'rejected': rejected,
        # Mẫu số ĐÚNG để so giữa các mô hình. Cơ chế bỏ cuộc sớm khiến mỗi mô
        # hình dùng một số lượt khác nhau, nên "giao ra / số câu yêu cầu" so
        # chéo được là do may, còn "giao ra / số lượt đã thử" thì luôn so được.
        'attempted': len(qs) + rejected,
        'error_code': payload.get('error_code'),
        'duration_seconds': round(dur, 1), 'cost': cost,
        'issue_counts': dict(issues),
        'status_counts': dict(collections.Counter(
            p['status'] for p in per_q)),
        'bloom_counts': dict(collections.Counter(p['bloom'] for p in per_q)),
        'per_question': per_q,
    }
    (out / 'probe_report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')

    print(f'\ngiao ra {len(qs)}/{args.n}, loại {report["rejected"]}, '
          f'{dur:.0f}s, {cost.get("tokens", 0):,} token')
    print('trạng thái kiểm chứng:', report['status_counts'])
    print('Bloom:', report['bloom_counts'])
    print('LỖI máy bắt được:', dict(issues) or 'không có')
    for p in per_q:
        if p['issues']:
            print(f"  - {p['id']}: {p['issues']}  ...{p['stem_tail']!r}")
    print(f'\nchi tiết: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

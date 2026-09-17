"""Quét nhiều mô hình SINH trên cùng một tài liệu, cùng một cấu hình.

Mỗi ô là một lần gọi `gen_probe.py` trong tiến trình riêng — cấu hình đọc env
lúc import nên tiến trình riêng là cách duy nhất để hai ô không dính cấu hình
của nhau.

Điều kiện để bảng kết quả có nghĩa (mọi ô phải giống nhau trừ MỘT thứ):

* cùng tài liệu, cùng số câu yêu cầu, cùng phân bố Bloom;
* cùng cách tài liệu tới mô hình — mọi ô chạy chế độ ảnh trang, vì đó là cách
  duy nhất mọi nhà cung cấp đều làm được như nhau (nhiều mô hình không nhận
  đầu vào file, và để chúng tụt xuống trích text là đổi luôn bài toán);
* cùng trần token — trần cũ hiệu chỉnh theo độ dài lời văn của OpenAI, mô hình
  viết dài hơn bị cắt giữa chừng rồi bị tính nhầm thành "sinh kém";
* cùng bộ giải độc lập, cố định, KHÔNG chạy theo mô hình sinh.

Thứ duy nhất thay đổi giữa các ô là mô hình sinh.

    python scripts/bench_models.py --pdf pdftest/file_3_trang_61-90.pdf --n 20
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Mô hình rẻ, nhiều nhà khác nhau, cỡ nhỏ — câu hỏi cần trả lời là kiến trúc có
# đứng vững ngoài họ mô hình nó được dựng lên cùng hay không.
# Hệ thống được thiết kế quanh việc đẩy NGUYÊN PDF cho mô hình, nên phép quét
# chỉ nhận mô hình có modality `file` trên OpenRouter. Ràng buộc này thu hẹp
# danh sách rất mạnh: chỉ 6 nhà có mô hình như vậy (OpenAI 46, Anthropic 16,
# Google 13, Mistral 11, x-ai 5, Amazon 1) — không có Qwen, Llama, GLM.
DEFAULT_MODELS = [
    # Cùng ô, cùng mọi tham số với lượt chạy ảnh trang ⇒ chênh lệch còn lại chỉ
    # do CÁCH TÀI LIỆU TỚI MÔ HÌNH. Đây là ô quan trọng nhất của cả bảng.
    'openai/gpt-4.1-nano',
    'amazon/nova-2-lite-v1',        # Amazon
    'mistralai/mistral-medium-3.1',  # Mistral
    'anthropic/claude-haiku-4.5',   # Anthropic
]

# Đã thử và LOẠI, kèm lý do — để lần sau không mất tiền thử lại:
#   mistralai/mistral-small-3.2-24b-instruct  (chế độ ảnh)
#       nhà cung cấp chặn cứng 5–8 ảnh mỗi prompt ("At most 5 image(s) may be
#       provided in one prompt"), nên tài liệu 30 trang không tới được mô hình.
#       Đây là giới hạn hạ tầng, KHÔNG phải kết quả về chất lượng sinh.
#   z-ai/glm-4.6v
#       mô hình có suy luận: phần suy luận tiêu vào CHÍNH trần token của câu
#       trả lời, nên ở trần chung nó trả về nội dung rỗng. Một trần duy nhất
#       không thể vừa công bằng cho mô hình trả lời thẳng vừa cho mô hình suy
#       luận — nên phép quét này chỉ nhận mô hình trả lời thẳng (instruct).
#   qwen/qwen3-vl-*, meta-llama/llama-4-scout
#       không có modality `file`; gửi PDF cho chúng thì OpenRouter âm thầm
#       TRÍCH TEXT. Chỉ chạy được ở chế độ ảnh, và kết quả chế độ ảnh không so
#       trực tiếp với kết quả PDF nguyên bản được.

# Bộ giải độc lập chỉ thấy đề bài, không thấy tài liệu, nên chọn theo năng lực
# suy luận chứ không theo thị giác. Cố định cho MỌI ô.
INDEPENDENT_MODEL = 'openai/gpt-4.1-mini'


def run_cell(model: str, pdf: str, n: int, out_root: Path, max_tokens: int,
             independent: str, empty_streak: int, attach: str) -> dict:
    slug = model.replace('/', '_')
    out = out_root / slug
    cmd = [
        sys.executable, str(ROOT / 'scripts' / 'gen_probe.py'),
        '--provider', 'openrouter',
        '--attach', attach,
        '--model', model,
        '--independent-model', independent,
        '--max-tokens', str(max_tokens),
        '--max-empty-streak', str(empty_streak),
        '--pdf', pdf,
        '--n', str(n),
        '--out', str(out.relative_to(ROOT)),
    ]
    print(f'\n=== {model}', flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, text=True, encoding='utf-8',
                          errors='replace', capture_output=True)
    sys.stdout.write(proc.stdout or '')
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr or '')
    report_path = out / 'probe_report.json'
    if not report_path.exists():
        return {'model': model, 'failed': True, 'returncode': proc.returncode,
                'stderr': (proc.stderr or '')[-2000:],
                'wall_seconds': round(time.time() - t0, 1)}
    rep = json.loads(report_path.read_text(encoding='utf-8'))
    rep['wall_seconds'] = round(time.time() - t0, 1)
    rep['failed'] = False
    return rep


def _pct(part: int, whole: int) -> str:
    return f'{100.0 * part / whole:.0f}%' if whole else '-'


def summarize(cells: list, requested: int) -> str:
    """Bảng so sánh. Cột nào không đo được thì để trống, không suy đoán.

    Cột **nhận/lượt thử** mới là con số so chéo được: cơ chế bỏ cuộc sớm cấp
    cho mỗi ô một số lượt khác nhau, nên "giao ra / số câu yêu cầu" trộn lẫn
    chất lượng mô hình với việc nó bị dừng sớm hay muộn.
    """
    lines = [
        '| mô hình | giao ra | lượt thử | nhận/lượt thử | kiểm chứng độc lập |'
        ' khớp nhất quán | lệch | không kiểm được | lời gọi | token | phút |',
        '|---|---|---|---|---|---|---|---|---|---|---|',
    ]
    for c in cells:
        if c.get('failed'):
            lines.append(f"| `{c['model']}` | **hỏng cả ô** | | | | | | | | | "
                         f"{c['wall_seconds'] / 60:.0f} |")
            continue
        st = c.get('status_counts') or {}
        cost = c.get('cost') or {}
        d = c.get('delivered', 0)
        att = c.get('attempted') or (d + c.get('rejected', 0))
        lines.append(
            f"| `{c['model']}` | {d}/{requested} "
            f"| {att} "
            f"| **{_pct(d, att)}** "
            f"| {st.get('independently_verified', 0)} "
            f"| {st.get('consistency_confirmed', 0)} "
            f"| {st.get('mismatch', 0)} "
            f"| {st.get('non_verifiable', 0)} "
            f"| {cost.get('calls', 0)} "
            f"| {cost.get('tokens', 0):,} "
            f"| {c.get('wall_seconds', 0) / 60:.0f} |")
    return '\n'.join(lines)


def issue_table(cells: list) -> str:
    keys = sorted({k for c in cells for k in (c.get('issue_counts') or {})})
    if not keys:
        return '_Không phép kiểm tất định nào bắt lỗi ở các câu đã giao ra._'
    head = '| mô hình | ' + ' | '.join(f'`{k}`' for k in keys) + ' |'
    sep = '|---' * (len(keys) + 1) + '|'
    rows = [head, sep]
    for c in cells:
        counts = c.get('issue_counts') or {}
        rows.append(f"| `{c['model']}` | "
                    + ' | '.join(str(counts.get(k, 0)) for k in keys) + ' |')
    return '\n'.join(rows)


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--models', nargs='*', default=DEFAULT_MODELS)
    ap.add_argument('--independent-model', default=INDEPENDENT_MODEL)
    ap.add_argument('--max-tokens', type=int, default=8000,
                    help='trần chung cho mọi ô; phải rộng hơn nhu cầu của mô '
                         'hình viết dài nhất, nếu không là đo độ dài lời văn '
                         'chứ không đo chất lượng')
    ap.add_argument('--max-empty-streak', type=int, default=60,
                    help='ngân sách lượt thử chung cho mọi ô. Mặc định của hệ '
                         'thống là bỏ cuộc sau vài slot hỏng liên tiếp — hợp '
                         'lý khi chạy thật, nhưng ở phép quét thì nó cấp cho '
                         'mô hình yếu ÍT lượt hơn mô hình khoẻ')
    ap.add_argument('--attach', default='file',
                    help="'file' = PDF nguyên bản (mặc định, đúng cách hệ "
                         "thống được thiết kế); 'image' = ảnh từng trang, chỉ "
                         "dùng khi mô hình không nhận đầu vào file")
    ap.add_argument('--out', default='report/bench')
    args = ap.parse_args()

    out_root = ROOT / args.out
    out_root.mkdir(parents=True, exist_ok=True)

    cells = []
    for model in args.models:
        cells.append(run_cell(model, args.pdf, args.n, out_root,
                              args.max_tokens, args.independent_model,
                              args.max_empty_streak, args.attach))
        (out_root / 'cells.json').write_text(
            json.dumps(cells, ensure_ascii=False, indent=1), encoding='utf-8')

    md = [
        f'# Quét mô hình sinh — {args.pdf}',
        '',
        f'- {args.n} câu yêu cầu mỗi ô, tài liệu tới mô hình dạng '
        + ('**ảnh từng trang**' if args.attach == 'image'
           else '**PDF nguyên bản**'),
        f'- trần token mỗi lời gọi: **{args.max_tokens}** (chung cho mọi ô)',
        f'- bộ giải độc lập cố định: `{args.independent_model}`',
        f'- ngân sách lượt thử chung: bỏ cuộc sau **{args.max_empty_streak}** '
        f'slot hỏng liên tiếp',
        '',
        summarize(cells, args.n),
        '',
        '## Lỗi các phép kiểm tất định bắt được',
        '',
        issue_table([c for c in cells if not c.get('failed')]),
        '',
    ]
    (out_root / 'summary.md').write_text('\n'.join(md), encoding='utf-8')
    print('\n' + '\n'.join(md))
    print(f'\nchi tiết: {out_root}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

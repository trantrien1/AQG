"""Chạy nhỏ giọt bench_suite: cứ hết hạn mức thì chờ rồi chạy tiếp.

Hạn mức gpt-4o của tài khoản ChatGPT mở lại theo cửa sổ, nên một lượt chạy chỉ
lấy được hơn chục câu. Vòng này chạy lại đúng cùng --out; bench_suite bỏ qua ô đã
có dữ liệu nên không sinh lại và không tốn thêm hạn mức cho phần đã xong.

    python scripts/drip_run.py --out report/bench/suite-20260730 --sleep 1800

Dừng bằng cách xoá file <out>/drip_STOP hoặc kill tiến trình.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent
PY = API_ROOT / 'venv' / 'Scripts' / 'python.exe'


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S')


def _delivered(out_dir: Path) -> tuple[int, int]:
    """(số ô có dữ liệu, tổng số câu giao được)."""
    cells = 0
    total = 0
    for f in out_dir.rglob('*.json'):
        if f.name.endswith('.manifest.json') or f.name == 'suite_metrics.json':
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except Exception:  # noqa: BLE001
            continue
        qs = data.get('questions')
        if isinstance(qs, list):
            cells += 1
            total += len(qs)
    return cells, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--pdf-glob', default='pdftest/corpus2/*.pdf')
    ap.add_argument('--seeds', nargs='+', default=['42', '43', '44'])
    ap.add_argument('--n', default='12')
    ap.add_argument('--sleep', type=int, default=1800, help='giây chờ giữa hai lượt')
    ap.add_argument('--max-rounds', type=int, default=96)
    args = ap.parse_args()

    out_dir = API_ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    stop_flag = out_dir / 'drip_STOP'
    log = out_dir / 'drip_run.log'
    pdfs = sorted(str(p.relative_to(API_ROOT)).replace('\\', '/')
                  for p in API_ROOT.glob(args.pdf_glob))
    target_cells = len(pdfs) * len(args.seeds)

    def say(msg: str) -> None:
        line = '[%s] %s' % (_now(), msg)
        print(line, flush=True)
        with log.open('a', encoding='utf-8') as fh:
            fh.write(line + '\n')

    say('bat dau: %d tai lieu x %d seed = %d o, moi o %s cau'
        % (len(pdfs), len(args.seeds), target_cells, args.n))

    for rnd in range(1, args.max_rounds + 1):
        if stop_flag.exists():
            say('thay drip_STOP -> dung')
            return 0

        cells, total = _delivered(out_dir)
        if cells >= target_cells:
            say('XONG: %d/%d o, %d cau' % (cells, target_cells, total))
            return 0

        say('luot %d: dang co %d/%d o, %d cau -> chay tiep'
            % (rnd, cells, target_cells, total))
        cmd = [str(PY) if PY.exists() else sys.executable,
               str(API_ROOT / 'scripts' / 'bench_suite.py'),
               '--pdfs', *pdfs, '--seeds', *args.seeds,
               '--n', args.n, '--out', args.out]
        proc = subprocess.run(cmd, cwd=str(API_ROOT), capture_output=True,
                              text=True, encoding='utf-8', errors='replace')

        new_cells, new_total = _delivered(out_dir)
        gained = new_total - total
        say('luot %d ket thuc (exit=%d): +%d cau, tong %d cau / %d o'
            % (rnd, proc.returncode, gained, new_total, new_cells))

        if new_cells >= target_cells:
            say('XONG: du %d o, %d cau' % (new_cells, new_total))
            return 0

        if gained == 0 and rnd >= 3:
            say('CANH BAO: 0 cau moi o luot nay')

        say('cho %d phut roi chay tiep...' % (args.sleep // 60))
        time.sleep(args.sleep)

    say('het so luot cho phep (%d)' % args.max_rounds)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

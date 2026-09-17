"""CLI của bench_suite: chế độ `--cell` phải parse được đúng như subprocess gọi.

Lý do có file này: bản đầu đặt `--out` là required, nên mọi ô con do chính
script tự gọi lại qua subprocess đều chết ở argparse (exit 2) trước khi chạy
được dòng nào — cả lưới 12 ô fail sạch mà driver vẫn exit 0. Đây là kiểu lỗi
chỉ lộ ra khi chạy thật, nên khoá lại bằng test.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parent.parent / 'scripts' / 'bench_suite.py'


def _load():
    spec = importlib.util.spec_from_file_location('bench_suite_cli', _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['bench_suite_cli'] = module
    spec.loader.exec_module(module)
    return module


bench_suite = _load()


def test_cell_mode_parses_without_out():
    """Đúng hình dạng lệnh mà driver dựng cho subprocess."""
    args = bench_suite.build_parser().parse_args(
        ['--cell', 'doc.pdf', 'out/x.json', '8', 'full_system', '42'])
    assert args.cell == ['doc.pdf', 'out/x.json', '8', 'full_system', '42']
    assert args.out == ''


def test_suite_mode_still_requires_out():
    with pytest.raises(SystemExit):
        parser = bench_suite.build_parser()
        args = parser.parse_args(['--pdfs', 'a.pdf'])
        if not args.out:
            parser.error('--out bắt buộc')


def test_suite_mode_parses_a_full_grid():
    args = bench_suite.build_parser().parse_args([
        '--out', 'report/x', '--pdfs', 'a.pdf', 'b.pdf',
        '--arms', 'full_system', 'plus_verifier', '--seeds', '42', '43', '--n', '8',
    ])
    assert args.pdfs == ['a.pdf', 'b.pdf']
    assert args.arms == ['full_system', 'plus_verifier']
    assert args.seeds == [42, 43]
    assert args.n == 8


def test_declared_arms_exist():
    from pipeline.ablation import ARMS
    defaults = bench_suite.build_parser().parse_args(['--out', 'x'])
    assert all(arm in ARMS for arm in defaults.arms)


def test_aggregate_of_empty_dir_reports_nothing_rather_than_zeros(tmp_path):
    summary = bench_suite.aggregate(tmp_path, None)
    assert summary['n_cells'] == 0
    assert summary['cells'] == []
    assert summary['by_arm'] == {}

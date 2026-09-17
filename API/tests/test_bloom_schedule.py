"""Lịch rải Bloom phải giao đúng tỉ lệ người dùng khai báo.

Bản cũ dựng danh sách phẳng với trọng số ``max(1, int(round(frac*10)))``. Hai
chỗ hỏng: (a) làm tròn ngân hàng của Python biến ``round(2.5)`` thành 2, nên một
mức khai 25% chỉ nhận 2/9 = 22,2%; (b) việc lượng tử hoá về bội của 1/10 làm mọi
tỉ lệ không tròn số bị bóp méo. Phân bố mặc định 10/25/40/25 chạy thành
11,1/22,2/44,4/22,2 — sai lệch xảy ra trước cả lời gọi mô hình đầu tiên và không
cổng nào phía sau nhìn thấy.

Đo trên run 2026-07-25 (89 câu): mức cao nhất được giao 15,7% so với 25% được
yêu cầu. Lượng tử hoá giải thích một phần; phần còn lại là do slot hỏng không
được bù đúng mức Bloom của nó (xem docstring của `_pick_cognitive`).
"""
from __future__ import annotations

import collections

import pytest

from pipeline import config as cfg
from pipeline.direct_pdf.agents.pdf_orchestrator import _pick_cognitive

DEFAULT = [dict(x) for x in cfg.DEFAULT_DIFFICULTY_DISTRIBUTION]


def _share(dist, n):
    c = collections.Counter(_pick_cognitive(dist, i) for i in range(n))
    return {lv: c[lv] / n for lv in {d['cognitive_level'] for d in dist}}


@pytest.mark.parametrize('n', [20, 100, 900])
def test_default_distribution_is_delivered_exactly(n):
    """Ở độ dài chia hết, lịch phải khớp tỉ lệ khai báo tuyệt đối."""
    got = _share(DEFAULT, n)
    for d in DEFAULT:
        assert got[d['cognitive_level']] == pytest.approx(d['fraction']), (
            f"{d['cognitive_level']}: {got[d['cognitive_level']]:.3f} "
            f"!= {d['fraction']}"
        )


def test_bankers_rounding_regression():
    """Hai mức cùng 25% phải nhận đúng 25%, không phải 22,2%."""
    dist = [
        {'cognitive_level': 'A', 'fraction': 0.25},
        {'cognitive_level': 'B', 'fraction': 0.25},
        {'cognitive_level': 'C', 'fraction': 0.50},
    ]
    got = _share(dist, 100)
    assert got['A'] == pytest.approx(0.25)
    assert got['B'] == pytest.approx(0.25)
    assert got['C'] == pytest.approx(0.50)


def test_fractions_that_are_not_multiples_of_a_tenth():
    """Tỉ lệ lẻ không bị lượng tử hoá về bội của 1/10."""
    dist = [
        {'cognitive_level': 'A', 'fraction': 0.05},
        {'cognitive_level': 'B', 'fraction': 0.35},
        {'cognitive_level': 'C', 'fraction': 0.60},
    ]
    got = _share(dist, 100)
    assert got['A'] == pytest.approx(0.05)
    assert got['B'] == pytest.approx(0.35)
    assert got['C'] == pytest.approx(0.60)


def test_unnormalised_weights_are_normalised():
    dist = [
        {'cognitive_level': 'A', 'fraction': 1},
        {'cognitive_level': 'B', 'fraction': 3},
    ]
    got = _share(dist, 100)
    assert got['A'] == pytest.approx(0.25)
    assert got['B'] == pytest.approx(0.75)


def test_levels_are_interleaved_not_clumped():
    """Rải đều: không mức nào chạy liên tiếp quá phần nó đáng được hưởng."""
    seq = [_pick_cognitive(DEFAULT, i) for i in range(40)]
    longest = max(len(list(g)) for _, g in __import__('itertools').groupby(seq))
    assert longest <= 2, f'lịch bị dồn cục: {seq}'


def test_deterministic_in_index():
    a = [_pick_cognitive(DEFAULT, i) for i in range(30)]
    b = [_pick_cognitive(DEFAULT, i) for i in range(30)]
    assert a == b


@pytest.mark.parametrize('dist', [None, [], [{'cognitive_level': ''}]])
def test_empty_distribution_falls_back(dist):
    assert _pick_cognitive(dist, 7) == 'Thông hiểu'

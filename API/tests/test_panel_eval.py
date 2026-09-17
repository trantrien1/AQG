"""panel_eval: nạp đúng 197 câu đã audit và tái phân xử khớp artifact.

Các con số ở đây là số đã báo cáo trong bài báo; test này giữ cho script replay
không lặng lẽ đánh số lệch nhãn (Run C khoá nhãn theo SỐ THỨ TỰ câu).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from pipeline.independent_target import aggregate_panel
from pipeline.panel_eval import (
    cohen_kappa_binary, configuration_summary, load_labelled_items,
    target_from_dict, wilson_interval,
)
from pipeline.verification_status import VerificationStatus, adjudicate

API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope='module')
def items():
    if not (API_ROOT / 'report/bench/suite-20260730/cas_verdicts.json').exists():
        pytest.skip('thiếu artifact audit')
    return load_labelled_items(API_ROOT)


def test_label_counts_match_the_paper(items):
    counts = Counter((i.run, i.key_correct) for i in items)
    assert counts == {
        ('run_a', True): 31, ('run_a', False): 4,
        ('run_b', True): 71, ('run_b', False): 4,
        ('run_c', True): 79, ('run_c', False): 8,
    }


def test_run_c_index_labels_point_at_the_right_items(items):
    by_id = {i.item_id: i for i in items}
    assert 'Viete' in by_id['run_c:001'].note
    assert 'x_' in by_id['run_c:001'].stem
    assert 'khối nón' in by_id['run_c:013'].stem


def test_replayed_adjudication_reproduces_run_c(items):
    for item in items:
        if item.run != 'run_c' or not item.recorded:
            continue
        adj = adjudicate(
            writer_verified=item.writer_verified, writer_engine=item.writer_engine,
            independent=aggregate_panel([target_from_dict(item.recorded)]),
            keyed_value=item.key_value, distractor_values=item.distractor_values,
        )
        assert adj.status == item.original_status, item.item_id


def test_recorded_solver_certifies_exactly_the_known_false_positive(items):
    targets = {'recorded': {i.item_id: target_from_dict(i.recorded)
                            for i in items if i.recorded}}
    row = configuration_summary(items, targets, ['recorded'])
    assert row['certified_wrong_items'] == ['run_c:121']
    assert row['wrong_key_certified']['of'] == 12


def test_legacy_records_get_derivation_from_expression():
    bare = target_from_dict({'attempted': True, 'definite': True, 'value': 4.0,
                             'expression': '4'})
    computed = target_from_dict({'attempted': True, 'definite': True, 'value': 4.0,
                                 'expression': 'binomial(4,3)'})
    assert bare.derivation is False
    assert computed.derivation is True


def test_statistics_helpers():
    lo, hi = wilson_interval(1, 8)
    assert 0.0 < lo < 0.125 < hi < 0.6
    assert wilson_interval(0, 0) is None
    assert cohen_kappa_binary([(True, True), (False, False)]) == pytest.approx(1.0)
    assert cohen_kappa_binary([(True, True), (True, True)]) is None
    assert VerificationStatus.INDEPENDENTLY_VERIFIED == 'independently_verified'

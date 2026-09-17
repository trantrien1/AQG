"""Đánh giá bởi người: phiếu phải THẬT SỰ mù, và không có điểm thì không có bảng.

Hai tính chất được khoá ở đây:

1. Phiếu gửi cho giáo viên không được chứa bất kỳ dấu vết nào về hệ thống nguồn
   hay điểm máy đã chấm — kể cả gián tiếp qua thứ tự.
2. Khi chưa ai chấm, hàm tổng hợp phải NÉM LỖI. Trả về bảng rỗng sẽ bị đọc nhầm
   thành "đã đánh giá và kết quả bằng 0".
"""
from __future__ import annotations

import json

import pytest

from pipeline.human_eval import (
    CRITERIA, NoRatingsError, aggregate_ratings, build_blind_export,
    inter_rater_agreement, load_ratings, write_review_packet,
)


def _record(qid, stem, *, system_marker='X'):
    return {
        'question_id': qid,
        'stem': stem,
        'options': [{'key': k, 'text': f'{k}-text', 'error_type': 'misc'}
                    for k in 'ABCD'],
        'answer_key': 'B',
        'cognitive_level': 'Vận dụng',
        'topic': 'tích phân',
        'explanation_correct': f'giải thích của {system_marker}',
        'source': {'quote': 'trích dẫn'},
        'verification': {'status': 'independently_verified', 'verified': True},
        'judging': {'quality': 0.93, 'grounding': 0.91},
        'review_status': 'pending_review',
        'agent_trace': ['writer', 'critic'],
        'difficulty_estimated': 0.7,
    }


def _sources():
    # Stem cố ý KHÔNG chứa tên hệ thống, để test tính mù không tự tạo ra bằng
    # chứng giả từ nội dung fixture.
    return {
        'pipeline': [_record(f'p{i}', f'Tính tích phân số {i}.', system_marker='P')
                     for i in range(5)],
        'baseline': [_record(f'b{i}', f'Tính đạo hàm số {i}.', system_marker='B')
                     for i in range(5)],
    }


# ---- Tính mù ----

def test_export_strips_every_internal_field():
    export = build_blind_export(_sources(), seed=1)
    assert len(export.items) == 10
    for item in export.items:
        for leaked in ('verification', 'judging', 'review_status', 'agent_trace',
                       'question_id', 'difficulty_estimated'):
            assert leaked not in item, leaked
        for option in item['options']:
            assert set(option) == {'key', 'text'}      # error_type cũng lộ máy


def test_export_hides_the_model_explanation_by_default():
    export = build_blind_export(_sources(), seed=1)
    assert all('explanation' not in item for item in export.items)
    with_expl = build_blind_export(_sources(), seed=1, include_explanation=True)
    assert all('explanation' in item for item in with_expl.items)


def test_export_interleaves_the_two_systems():
    """Thứ tự cũng là thông tin: hai nguồn phải trộn vào nhau, không xếp khối."""
    export = build_blind_export(_sources(), seed=7)
    systems = [export.assignment[i['item_id']]['system'] for i in export.items]
    assert set(systems) == {'pipeline', 'baseline'}
    switches = sum(1 for a, b in zip(systems, systems[1:]) if a != b)
    assert switches >= 2, f'thứ tự gần như xếp khối theo nguồn: {systems}'


def test_export_is_deterministic_for_a_given_seed():
    a = build_blind_export(_sources(), seed=99)
    b = build_blind_export(_sources(), seed=99)
    assert [i['stem'] for i in a.items] == [i['stem'] for i in b.items]
    assert a.assignment == b.assignment


def test_packet_keeps_the_mapping_in_a_separate_file(tmp_path):
    export = build_blind_export(_sources(), seed=3)
    written = write_review_packet(export, tmp_path, ['gv1', 'gv2'])
    assert set(written) == {'gv1', 'gv2', '_assignment'}

    form = json.loads(written['gv1'].read_text(encoding='utf-8'))
    assert set(form['ratings'][0]['scores']) == set(CRITERIA)
    assert all(v is None for v in form['ratings'][0]['scores'].values())
    # Không được có chữ nào lộ nguồn trong phiếu.
    assert 'pipeline' not in written['gv1'].read_text(encoding='utf-8')
    assert 'SECRET' in written['_assignment'].name


# ---- Không có điểm thì không có bảng ----

def test_aggregate_refuses_when_nothing_has_been_rated():
    with pytest.raises(NoRatingsError):
        aggregate_ratings({'gv1': {}, 'gv2': {}})
    with pytest.raises(NoRatingsError):
        aggregate_ratings({})


def test_load_ratings_ignores_unfilled_rows(tmp_path):
    path = tmp_path / 'ratings_gv1.json'
    path.write_text(json.dumps({
        'reviewer_id': 'gv1',
        'ratings': [
            {'item_id': 'item_0001', 'scores': {'clarity': None}},
            {'item_id': 'item_0002', 'scores': {'clarity': 4}},
        ],
    }), encoding='utf-8')
    loaded = load_ratings([path])
    assert loaded['gv1'] == {'item_0002': {'clarity': 4}}


# ---- Thống kê + đồng thuận ----

def _ratings(scores_by_reviewer):
    return {
        reviewer: {item: {'clarity': value} for item, value in items.items()}
        for reviewer, items in scores_by_reviewer.items()
    }


def test_perfect_agreement_gives_alpha_one():
    agreement = inter_rater_agreement({
        'a': {'i1': 5, 'i2': 3, 'i3': 1},
        'b': {'i1': 5, 'i2': 3, 'i3': 1},
    })
    assert agreement['krippendorff_alpha_ordinal'] == 1.0
    assert agreement['exact_agreement'] == 1.0
    assert agreement['cohen_kappa_quadratic'] == 1.0


def test_systematic_disagreement_gives_low_alpha():
    agreement = inter_rater_agreement({
        'a': {'i1': 5, 'i2': 5, 'i3': 5, 'i4': 5},
        'b': {'i1': 1, 'i2': 1, 'i3': 1, 'i4': 1},
    })
    assert agreement['krippendorff_alpha_ordinal'] < 0
    assert agreement['exact_agreement'] == 0.0


def test_agreement_reports_when_there_is_no_overlap():
    agreement = inter_rater_agreement({'a': {'i1': 5}, 'b': {'i2': 4}})
    assert agreement['krippendorff_alpha_ordinal'] is None
    assert 'chưa tính được' in agreement['note']


def test_aggregate_reports_ci_and_agreement_per_criterion():
    summary = aggregate_ratings(_ratings({
        'gv1': {'item_0001': 4, 'item_0002': 5, 'item_0003': 3},
        'gv2': {'item_0001': 4, 'item_0002': 4, 'item_0003': 3},
    }))
    clarity = summary['per_criterion']['clarity']
    assert clarity['n_ratings'] == 6
    assert clarity['mean'] == pytest.approx(3.833, abs=1e-3)
    assert clarity['ci95'] is not None
    assert clarity['agreement']['n_units_with_multiple_ratings'] == 3
    assert summary['coverage']['items_rated_by_all'] == 3
    assert summary['n_reviewers'] == 2


def test_single_rating_gets_no_confidence_interval():
    summary = aggregate_ratings(_ratings({'gv1': {'item_0001': 4}}))
    assert summary['per_criterion']['clarity']['ci95'] is None
    assert summary['per_criterion']['clarity']['sd'] is None


def test_unblinding_happens_only_after_rating():
    export = build_blind_export(_sources(), seed=5)
    first_two = [item['item_id'] for item in export.items[:2]]
    summary = aggregate_ratings(
        _ratings({'gv1': {first_two[0]: 5, first_two[1]: 2}}),
        assignment=export.assignment,
    )
    per_system = summary['per_system']
    assert set(per_system) <= {'pipeline', 'baseline'}
    total = sum(v['clarity']['n'] for v in per_system.values())
    assert total == 2

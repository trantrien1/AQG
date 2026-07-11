"""Test phân loại câu hỏi theo Chuẩn đầu ra (không gọi LLM)."""
from __future__ import annotations

from pipeline.outcome_classifier import (
    attach_outcomes,
    normalize_outcomes,
    parse_assignments,
)


# ---- normalize_outcomes ----

def test_normalize_list_of_strings_auto_codes():
    out = normalize_outcomes([
        'Tính được nguyên hàm của các hàm số cơ bản',
        'Vận dụng tích phân tính diện tích, thể tích',
    ])
    assert [o['code'] for o in out] == ['CĐR1', 'CĐR2']
    assert out[1]['description'].startswith('Vận dụng')


def test_normalize_string_with_inline_code_prefix():
    out = normalize_outcomes(['CLO1: Hiểu định nghĩa tích phân xác định'])
    assert out[0]['code'] == 'CLO1'
    assert out[0]['description'] == 'Hiểu định nghĩa tích phân xác định'


def test_normalize_multiline_text_and_dicts():
    out = normalize_outcomes('Chuẩn A\n\nChuẩn B')
    assert len(out) == 2 and out[0]['code'] == 'CĐR1'
    out2 = normalize_outcomes([{'code': 'G1', 'description': 'x'},
                               {'description': 'y'}])
    assert [o['code'] for o in out2] == ['G1', 'CĐR2']


def test_normalize_duplicate_codes_get_suffix():
    out = normalize_outcomes([{'code': 'G1', 'description': 'a'},
                              {'code': 'G1', 'description': 'b'}])
    assert [o['code'] for o in out] == ['G1', 'G1.2']


def test_normalize_empty_inputs():
    assert normalize_outcomes(None) == []
    assert normalize_outcomes('') == []
    assert normalize_outcomes(['   ', {'description': ''}]) == []


# ---- parse_assignments ----

_RAW = '''```json
{"assignments": [
  {"question_id": "q1", "outcomes": ["CĐR1", "CĐR2", "CĐR1"]},
  {"question_id": "q2", "outcomes": ["CĐR9"]},
  {"question_id": "unknown", "outcomes": ["CĐR1"]},
  {"question_id": "q3", "outcomes": []}
]}
```'''


def test_parse_assignments_filters_invalid_codes_and_ids():
    got = parse_assignments(_RAW, ['CĐR1', 'CĐR2'], ['q1', 'q2', 'q3'])
    assert got['q1'] == ['CĐR1', 'CĐR2']  # khử trùng lặp, giữ thứ tự
    assert got['q2'] == []                # mã bịa -> lọc bỏ
    assert got['q3'] == []
    assert 'unknown' not in got


def test_parse_assignments_garbage_returns_empty():
    assert parse_assignments('not json at all', ['CĐR1'], ['q1']) == {}
    assert parse_assignments('{"assignments": "oops"}', ['CĐR1'], ['q1']) == {}


# ---- attach_outcomes ----

def test_attach_outcomes_sets_empty_list_for_unmatched():
    questions = [{'question_id': 'q1'}, {'question_id': 'q2'}]
    attach_outcomes(questions, {'q1': ['CĐR1']})
    assert questions[0]['learning_outcomes'] == ['CĐR1']
    assert questions[1]['learning_outcomes'] == []

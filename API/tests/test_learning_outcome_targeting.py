"""Test CĐR đi vào KHÂU SINH (slot targeting + prompt), không gọi LLM."""
from __future__ import annotations

from pipeline.direct_pdf.agents.pdf_orchestrator import _pick_outcome
from pipeline.direct_pdf.agents.pdf_writer_agent import _outcome_rule
from pipeline.direct_pdf.generator import _build_prompt, _outcomes_block
from pipeline.outcome_classifier import attach_outcomes

_OUTCOMES = [
    {'code': 'CĐR1', 'description': 'Tính được nguyên hàm của hàm số cơ bản'},
    {'code': 'CĐR2', 'description': 'Vận dụng tích phân tính diện tích, thể tích'},
]


# ---- _pick_outcome (orchestrator rải CĐR round-robin theo slot) ----

def test_pick_outcome_round_robin():
    got = [_pick_outcome(_OUTCOMES, i)['code'] for i in range(5)]
    assert got == ['CĐR1', 'CĐR2', 'CĐR1', 'CĐR2', 'CĐR1']


def test_pick_outcome_empty_and_invalid():
    assert _pick_outcome(None, 0) is None
    assert _pick_outcome([], 3) is None
    # phần tử thiếu description bị bỏ qua
    assert _pick_outcome([{'code': 'X', 'description': '  '}], 0) is None
    only = _pick_outcome([{'code': 'X', 'description': ''},
                          {'code': 'G1', 'description': 'ok'}], 1)
    assert only['code'] == 'G1'


# ---- _outcome_rule (ràng buộc trong prompt của PdfWriter) ----

def test_outcome_rule_mentions_code_and_description():
    rule = _outcome_rule(_OUTCOMES[0])
    assert 'CĐR1' in rule
    assert 'nguyên hàm' in rule
    assert 'CHUẨN ĐẦU RA' in rule


def test_outcome_rule_empty_when_no_outcome():
    assert _outcome_rule(None) == ''
    assert _outcome_rule({}) == ''
    assert _outcome_rule({'code': 'CĐR1', 'description': '   '}) == ''
    assert _outcome_rule('CĐR1') == ''


# ---- _outcomes_block (prompt monolith liệt kê & yêu cầu phủ đều CĐR) ----

def test_outcomes_block_lists_all_and_requires_coverage():
    block = _outcomes_block(_OUTCOMES)
    assert 'CĐR1' in block and 'CĐR2' in block
    assert 'PHỦ ĐỀU' in block
    assert _outcomes_block(None) == ''
    assert _outcomes_block([]) == ''


def test_build_prompt_includes_outcomes_block():
    prompt = _build_prompt(4, None, learning_outcomes=_OUTCOMES)
    assert 'CĐR2: Vận dụng tích phân' in prompt
    # không khai báo CĐR -> prompt không chứa khối chuẩn đầu ra
    assert 'CHUẨN ĐẦU RA' not in _build_prompt(4, None)


# ---- attach_outcomes giữ nhãn sơ bộ khi classifier không có kết quả ----

def test_attach_outcomes_keeps_preseeded_label_when_missing():
    questions = [
        {'question_id': 'q1', 'learning_outcomes': ['CĐR1']},  # judge im lặng
        {'question_id': 'q2', 'learning_outcomes': ['CĐR1']},  # judge sửa nhãn
        {'question_id': 'q3'},                                  # không nhãn nào
    ]
    attach_outcomes(questions, {'q2': ['CĐR2']})
    assert questions[0]['learning_outcomes'] == ['CĐR1']
    assert questions[1]['learning_outcomes'] == ['CĐR2']
    assert questions[2]['learning_outcomes'] == []

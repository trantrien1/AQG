"""Công tắc ablation: từng cơ chế phải tắt/bật được ĐỘC LẬP và có tác dụng thật.

Test ở đây kiểm hai điều: (a) API công tắc đúng thứ tự ưu tiên, và (b) tắt một
cơ chế thì prompt/hành vi tương ứng THẬT SỰ đổi — không phải chỉ đổi một cờ mà
code vẫn chạy y như cũ.
"""
from __future__ import annotations

import os

import pytest

from pipeline import ablation


def test_defaults_are_full_system():
    assert ablation.snapshot() == {name: True for name in ablation.MECHANISMS}


def test_every_arm_is_a_subset_of_the_next():
    """Các arm phải tăng dần: arm sau bật đủ mọi cơ chế của arm trước."""
    for earlier, later in zip(ablation.ARM_ORDER, ablation.ARM_ORDER[1:]):
        assert set(ablation.ARMS[earlier]) <= set(ablation.ARMS[later]), (
            f'{later} thiếu cơ chế mà {earlier} đã bật'
        )


def test_single_prompt_arm_disables_everything():
    assert ablation.ARMS['single_prompt'] == []
    assert set(ablation.ARMS['full_system']) == set(ablation.MECHANISMS)


def test_override_context_manager_restores_state():
    with ablation.override(independent_verification=False):
        assert ablation.is_enabled(ablation.INDEPENDENT_VERIFICATION) is False
        assert ablation.is_enabled(ablation.SYMBOLIC_VERIFIER) is True
    assert ablation.is_enabled(ablation.INDEPENDENT_VERIFICATION) is True


def test_arm_override_sets_the_whole_table():
    with ablation.override(arm='plus_verifier'):
        assert ablation.current_arm() == 'plus_verifier'
        assert ablation.is_enabled(ablation.SYMBOLIC_VERIFIER) is True
        assert ablation.is_enabled(ablation.INDEPENDENT_VERIFICATION) is False
        assert ablation.is_enabled(ablation.DISTRACTOR_AGENT) is False
    assert ablation.current_arm() is None


def test_mechanism_override_beats_arm():
    with ablation.override(arm='single_prompt', symbolic_verifier=True):
        assert ablation.is_enabled(ablation.SYMBOLIC_VERIFIER) is True
        assert ablation.is_enabled(ablation.DISTRACTOR_AGENT) is False


def test_env_flag_beats_arm(monkeypatch):
    monkeypatch.setenv('AQG_ABLATION_DISTRACTOR_AGENT', '1')
    with ablation.override(arm='single_prompt'):
        assert ablation.is_enabled(ablation.DISTRACTOR_AGENT) is True


def test_unknown_names_raise():
    with pytest.raises(KeyError):
        ablation.is_enabled('not_a_mechanism')
    with pytest.raises(KeyError):
        ablation.set_arm('not_an_arm')
    with pytest.raises(KeyError):
        with ablation.override(not_a_mechanism=True):
            pass


def test_describe_arm_does_not_change_process_state():
    table = ablation.describe_arm('plus_independent')
    assert table[ablation.INDEPENDENT_VERIFICATION] is True
    assert table[ablation.DISTRACTOR_AGENT] is False
    assert ablation.current_arm() is None


# ---- Cơ chế tắt phải đổi hành vi thật ----

_SLOT = {'cognitive_level': 'Vận dụng cao', 'difficulty_target': 0.85,
         'topic': 'tích phân', 'skill': 'ứng dụng tích phân'}


def _writer_prompt(slot=None):
    from pipeline.direct_pdf.agents.messages import PdfWriteRequest
    from pipeline.direct_pdf.agents.pdf_writer_agent import PdfWriterAgent
    agent = PdfWriterAgent(use_skills=False)
    return agent._user_prompt(PdfWriteRequest(
        attachment_parts=[], slot=dict(slot or _SLOT),
        avoid_stems=['Một câu đã có từ trước về thể tích khối tròn xoay'],
    ))


def test_difficulty_control_off_removes_computation_constraints():
    with_control = _writer_prompt()
    assert 'ĐỘ NẶNG PHÉP TÍNH' in with_control
    with ablation.override(difficulty_control=False):
        without = _writer_prompt()
    assert 'ĐỘ NẶNG PHÉP TÍNH' not in without
    assert len(without) < len(with_control)


def test_outcome_scheduler_off_removes_learning_outcome_block():
    slot = dict(_SLOT, _learning_outcome={'code': 'CĐR1', 'description': 'Tính tích phân'})
    assert 'CHUẨN ĐẦU RA' in _writer_prompt(slot)
    with ablation.override(outcome_scheduler=False):
        assert 'CHUẨN ĐẦU RA' not in _writer_prompt(slot)


def test_feedback_steering_off_removes_feedback_block():
    slot = dict(_SLOT, _feedback_guidance='Ưu tiên bài toán thực tế')
    assert 'PHẢN HỒI NGƯỜI DÙNG' in _writer_prompt(slot)
    with ablation.override(feedback_steering=False):
        assert 'PHẢN HỒI NGƯỜI DÙNG' not in _writer_prompt(slot)


def test_semantic_dedup_off_removes_avoid_list():
    assert 'KHÔNG lặp lại' in _writer_prompt()
    with ablation.override(semantic_dedup=False):
        assert 'KHÔNG lặp lại' not in _writer_prompt()


def test_distractor_agent_off_makes_writer_emit_its_own_options():
    prompt = _writer_prompt()
    assert 'Trả `distractors` là danh sách rỗng' in prompt
    with ablation.override(distractor_agent=False):
        solo = _writer_prompt()
    assert 'Sinh ĐÚNG 3 phương án nhiễu' in solo
    assert 'danh sách rỗng' not in solo


def test_misconception_catalogue_off_empties_the_block():
    from pipeline.direct_pdf.agents.pdf_distractor_agent import _misconception_block
    candidate = {'question_text': 'Tính thể tích khối tròn xoay',
                 'answer_explanation_text': 'Dùng công thức tích phân'}
    assert _misconception_block(candidate, _SLOT).strip()
    with ablation.override(misconception_catalogue=False):
        assert _misconception_block(candidate, _SLOT) == ''


_EXPR = '12 + integrate(t**2-6*t+5, (t, 0, 1))'
_VERIFY_SLOT = dict(_SLOT, source_chunk_type='exercise',
                    question_pattern='computation')


def _verify_candidate(with_independent: bool):
    """Câu ĐÚNG (43/3) đủ nặng để qua rule validator, tuỳ chọn gắn nguồn độc lập."""
    candidate = {
        'question_text': (
            'Một bể nuôi cá được bơm nước trong \\(t\\) phút, thể tích \\(V(t)\\) '
            'thoả \\(V\'(t)=t^2-6t+5\\) và ban đầu bể có \\(12\\) đơn vị nước. '
            'Tính thể tích tại thời điểm tốc độ bơm giảm về \\(0\\) lần đầu.'
        ),
        'answer_text': r'\(\frac{43}{3}\)',
        'answer_explanation_text': (
            'Tốc độ bằng 0 lần đầu tại \\(t=1\\); lấy tích phân \\(V\'\\) trên '
            '\\([0;1]\\) rồi cộng thể tích ban đầu.'
        ),
        'source_quote_text': ('Nếu \\(F\'(x)=f(x)\\) trên \\([a;b]\\) thì '
                              '\\(\\int_a^b f(x)\\,dx=F(b)-F(a)\\).'),
        'distractors': [
            {'distractor_text': r'\(\frac{61}{3}\)',
             'distractor_explanation_text': 'Lấy nhầm mốc \\(t=5\\).'},
            {'distractor_text': r'\(\frac{11}{3}\)',
             'distractor_explanation_text': 'Quên cộng thể tích ban đầu.'},
            {'distractor_text': r'\(\frac{7}{3}\)',
             'distractor_explanation_text': 'Chỉ lấy phần tích phân.'},
        ],
        'verifier_hint': {'type': 'numeric_eval',
                          'payload': {'expr': _EXPR, 'expected_numeric': 43 / 3}},
    }
    if with_independent:
        candidate['_independent_target'] = {
            'attempted': True, 'definite': True, 'derivation': True,
            'value': 43 / 3, 'expression': _EXPR, 'stated_answer': '43/3',
            'stated_value': 43 / 3, 'source': 'llm_resolver',
        }
    return candidate


def _run_verifier(candidate):
    from pipeline.agents.messages import VerifyRequest
    from pipeline.agents.verifier_agent import VerifierAgent
    resp = VerifierAgent(use_skills=False).run(VerifyRequest(
        candidate=candidate, slot=dict(_VERIFY_SLOT), context=''))
    assert '_verification' in resp.annotations, resp.reject_reason
    return resp.annotations['_verification']


def test_symbolic_verifier_off_skips_the_engine():
    from pipeline.verification_status import VerificationStatus

    on = _run_verifier(_verify_candidate(with_independent=False))
    assert on['status'] == VerificationStatus.CONSISTENCY_CONFIRMED

    with ablation.override(symbolic_verifier=False):
        off = _run_verifier(_verify_candidate(with_independent=False))
    assert off['status'] == VerificationStatus.NON_VERIFIABLE
    assert off['verified'] is None


def test_independent_verification_off_ignores_an_attached_target():
    from pipeline.verification_status import VerificationStatus

    on = _run_verifier(_verify_candidate(with_independent=True))
    assert on['status'] == VerificationStatus.INDEPENDENTLY_VERIFIED

    with ablation.override(independent_verification=False):
        off = _run_verifier(_verify_candidate(with_independent=True))
    assert off['status'] == VerificationStatus.CONSISTENCY_CONFIRMED

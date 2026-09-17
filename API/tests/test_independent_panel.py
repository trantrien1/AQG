"""Hội đồng solver độc lập khác họ + phân loại lỗi hạ tầng.

Kịch bản trung tâm lấy từ phản ví dụ trong bài báo (tiếp tuyến–mặt cầu): key
ghi 5√3−4 ≈ 4.660 trong khi đáp án đúng là 3√3−4 ≈ 1.196, và solver CÙNG HỌ
với generator tái tạo đúng giá trị sai đó. Một solver khác họ giải ra giá trị
đúng phải kéo câu về MISMATCH thay vì để nó mang nhãn "đã kiểm chứng độc lập".
"""
from __future__ import annotations

import json
import math

import pytest

from pipeline import config as cfg
from pipeline.agents.verifier_agent import _independent_from_candidate
from pipeline.direct_pdf.agents import pdf_independent_agent as agent_mod
from pipeline.direct_pdf.agents.pdf_independent_agent import (
    PdfIndependentVerifierAgent, SolverSpec, parse_solver_specs,
)
from pipeline.independent_target import (
    IndependentTarget, aggregate_panel, build_independent_target, consensus_size,
)
from pipeline.llm_client import NonRetryableLLMError
from pipeline.model_family import independence_level, model_family
from pipeline.verification_status import VerificationStatus, adjudicate

WRONG_KEY = 5 * math.sqrt(3) - 4      # ≈ 4.660, key sai
TRUE_VALUE = 3 * math.sqrt(3) - 4     # ≈ 1.196, đáp án đúng


def _member(value, *, model='m', derivation=True, definite=True, source='llm_resolver'):
    return IndependentTarget(
        attempted=True, definite=definite, derivation=derivation,
        value=value if definite else None, expression='5*sqrt(3)-4',
        stated_answer='x', stated_value=value, source=source, model=model,
        family=model_family(model),
    )


# ---- Họ model ----

@pytest.mark.parametrize('model,family', [
    ('gpt-4o', 'openai'),
    ('gpt-4o-mini', 'openai'),
    ('openai/gpt-4.1-nano', 'openai'),
    ('Qwen/Qwen3-VL-32B-Instruct-FP8', 'qwen'),
    ('qwen/qwen-2.5-72b-instruct', 'qwen'),
    ('microsoft/phi-4', 'microsoft-phi'),
    ('deepseek-ai/DeepSeek-R1-Distill-Qwen-7B', 'qwen'),
    ('deepseek/deepseek-chat', 'deepseek'),
    ('meta-llama/Llama-3.3-70B-Instruct', 'meta-llama'),
    ('google/gemma-3-27b-it', 'google'),
    ('mistralai/Mistral-Small-3.2-24B-Instruct-2506', 'mistral'),
    ('z-ai/glm-4.5', 'zhipu-glm'),
    ('gen', 'unknown'),
    ('', 'unknown'),
])
def test_model_family(model, family):
    assert model_family(model) == family


def test_independence_level():
    assert independence_level('gpt-4o', ['gpt-4o-mini']) == 'same_family'
    assert independence_level('gpt-4o', ['microsoft/phi-4']) == 'cross_family'
    assert independence_level(
        'gpt-4o', ['gpt-4o-mini', 'microsoft/phi-4']) == 'partly_same_family'
    assert independence_level('gen', ['microsoft/phi-4']) == 'unknown'
    assert independence_level('gpt-4o', []) == 'unknown'


def test_parse_solver_specs():
    specs = parse_solver_specs(
        ['microsoft/phi-4@http://127.0.0.1:8001/v1', ' gpt-4o-mini ', ''], 'fallback')
    assert specs == [
        SolverSpec('microsoft/phi-4', 'http://127.0.0.1:8001/v1'),
        SolverSpec('gpt-4o-mini', ''),
    ]
    assert parse_solver_specs([], 'fallback') == [SolverSpec('fallback', '')]


# ---- Lỗi hạ tầng không bị ghi thành "không kiểm được" ----

def test_infrastructure_errors_propagate_when_requested():
    def _unauthorized(system, user):
        raise NonRetryableLLMError(RuntimeError('401 Unauthorized'))

    with pytest.raises(NonRetryableLLMError):
        build_independent_target('Tính 2+3.', call_fn=_unauthorized,
                                 reraise=(NonRetryableLLMError,))


def test_transient_error_marks_verification_incomplete():
    target = build_independent_target(
        'Tính 2+3.', call_fn=lambda s, u: (_ for _ in ()).throw(TimeoutError('slow')))
    adj = adjudicate(writer_verified=None, writer_engine='none',
                     independent=target, keyed_value=5.0)
    assert adj.status == VerificationStatus.NON_VERIFIABLE
    assert adj.verification_incomplete is True
    assert adj.to_dict()['verification_incomplete'] is True


def test_not_applicable_is_not_incomplete():
    target = build_independent_target(
        'Phát biểu nào đúng?',
        call_fn=lambda s, u: json.dumps({'computable': False}))
    adj = adjudicate(writer_verified=None, writer_engine='none', independent=target)
    assert adj.status == VerificationStatus.NON_VERIFIABLE
    assert adj.verification_incomplete is False


# ---- Gộp hội đồng ----

def test_consensus_size():
    assert consensus_size('all', 3) == 3
    assert consensus_size('2', 3) == 2
    assert consensus_size(5, 3) == 3
    assert consensus_size('0', 3) == 1
    assert consensus_size('rác', 2) == 2


def test_single_member_is_returned_unchanged():
    member = _member(TRUE_VALUE)
    agg = aggregate_panel([member])
    assert agg is member
    assert agg.definite_values == [TRUE_VALUE]
    assert 'panel' not in agg.to_dict()


def test_unanimous_panel_is_definite():
    agg = aggregate_panel([_member(TRUE_VALUE, model='gpt-4o-mini'),
                           _member(TRUE_VALUE, model='microsoft/phi-4')])
    assert agg.definite and agg.derivation
    assert agg.value == pytest.approx(TRUE_VALUE)
    assert agg.agreeing == 2
    assert agg.source == 'panel'
    assert agg.family == 'openai+microsoft-phi'


def test_split_panel_is_not_definite_but_keeps_values():
    agg = aggregate_panel([_member(WRONG_KEY, model='gpt-4o-mini'),
                           _member(TRUE_VALUE, model='microsoft/phi-4')])
    assert agg.definite is False
    assert sorted(agg.definite_values) == pytest.approx(sorted([WRONG_KEY, TRUE_VALUE]))
    assert 'chưa đồng thuận' in agg.detail


def test_k_of_n_consensus_and_tie():
    members = [_member(1.0), _member(1.0), _member(2.0)]
    assert aggregate_panel(members, consensus='2').definite is True
    assert aggregate_panel(members, consensus='all').definite is False
    tie = aggregate_panel([_member(1.0), _member(2.0)], consensus='1')
    assert tie.definite is False


def test_derivation_needs_one_computing_member():
    agg = aggregate_panel([_member(6.0, derivation=False),
                           _member(6.0, derivation=True)])
    assert agg.definite and agg.derivation
    bare = aggregate_panel([_member(6.0, derivation=False),
                            _member(6.0, derivation=False)])
    assert bare.definite and not bare.derivation


def test_errored_member_blocks_unanimity_and_flags_incomplete():
    errored = IndependentTarget(attempted=True, source='error', incomplete=True,
                                errors=['timeout'])
    agg = aggregate_panel([_member(TRUE_VALUE), errored])
    assert agg.definite is False
    assert agg.incomplete is True


# ---- Phân xử với hội đồng ----

def _adjudicate(independent, keyed=WRONG_KEY, distractors=(TRUE_VALUE + 1, 0.5, 7.0),
                writer_verified=True):
    return adjudicate(
        writer_verified=writer_verified, writer_engine='numeric_eval',
        independent=independent, keyed_value=keyed,
        distractor_values=list(distractors),
    )


def test_same_family_solver_alone_certifies_the_wrong_key():
    """Tái hiện lỗ hổng của bài báo: một solver cùng họ tái tạo key sai."""
    adj = _adjudicate(aggregate_panel([_member(WRONG_KEY, model='gpt-4o-mini')]))
    assert adj.status == VerificationStatus.INDEPENDENTLY_VERIFIED


def test_cross_family_dissent_routes_wrong_key_to_human():
    panel = aggregate_panel([_member(WRONG_KEY, model='gpt-4o-mini'),
                             _member(TRUE_VALUE, model='microsoft/phi-4')])
    adj = _adjudicate(panel)
    assert adj.status == VerificationStatus.MISMATCH
    assert adj.needs_human_review is True


def test_majority_agreeing_with_key_is_not_enough_when_one_dissents():
    panel = aggregate_panel([_member(WRONG_KEY), _member(WRONG_KEY),
                             _member(TRUE_VALUE)], consensus='2')
    assert panel.definite is True
    adj = _adjudicate(panel)
    assert adj.status == VerificationStatus.MISMATCH


def test_unanimous_panel_against_key_matching_distractor_refutes():
    panel = aggregate_panel([_member(TRUE_VALUE), _member(TRUE_VALUE)])
    adj = _adjudicate(panel, distractors=(TRUE_VALUE, 0.5, 7.0))
    assert adj.status == VerificationStatus.REFUTED


def test_unanimous_panel_agreeing_with_correct_key_verifies():
    panel = aggregate_panel([_member(TRUE_VALUE), _member(TRUE_VALUE)])
    adj = _adjudicate(panel, keyed=TRUE_VALUE, distractors=(WRONG_KEY, 0.5, 7.0))
    assert adj.status == VerificationStatus.INDEPENDENTLY_VERIFIED


def test_errored_member_falls_back_and_is_flagged():
    errored = IndependentTarget(attempted=True, source='error', incomplete=True)
    panel = aggregate_panel([_member(TRUE_VALUE), errored])
    adj = _adjudicate(panel, keyed=TRUE_VALUE)
    assert adj.status == VerificationStatus.CONSISTENCY_CONFIRMED
    assert adj.verification_incomplete is True


def test_panel_survives_the_candidate_dict_round_trip():
    """Orchestrator lưu mục tiêu dạng dict; verifier dựng lại rồi mới phân xử."""
    panel = aggregate_panel([_member(WRONG_KEY, model='gpt-4o-mini'),
                             _member(TRUE_VALUE, model='microsoft/phi-4')])
    rebuilt = _independent_from_candidate({'_independent_target': panel.to_dict()})
    assert rebuilt.definite_values == panel.definite_values
    assert _adjudicate(rebuilt).status == VerificationStatus.MISMATCH


# ---- Agent: định tuyến endpoint + lỗi hạ tầng ----

def _answer(expression):
    return json.dumps({'computable': True, 'quantity': 'q',
                       'expression': expression, 'answer': expression})


def test_agent_routes_each_solver_to_its_endpoint(monkeypatch):
    calls = []

    def _fake_call_llm(system, user, model=None, base_url=None, api_key=None, **kw):
        calls.append((model, base_url))
        return _answer('3*sqrt(3)-4' if model == 'microsoft/phi-4' else '5*sqrt(3)-4')

    monkeypatch.setattr(agent_mod, 'call_llm', _fake_call_llm)
    agent = PdfIndependentVerifierAgent(solvers=[
        SolverSpec('gpt-4o-mini'),
        SolverSpec('microsoft/phi-4', 'http://127.0.0.1:8001/v1'),
    ])
    target = agent.run({'question_text': 'Tìm k.', 'answer_text': 'LEAK'})
    assert sorted(calls) == sorted([('gpt-4o-mini', None),
                                    ('microsoft/phi-4', 'http://127.0.0.1:8001/v1')])
    assert target.definite is False
    assert len(target.panel) == 2
    assert all('LEAK' not in json.dumps(m) for m in target.panel)


def test_agent_propagates_infrastructure_error_from_any_member(monkeypatch):
    def _fake_call_llm(system, user, model=None, base_url=None, **kw):
        if base_url:
            raise NonRetryableLLMError(RuntimeError('401 Unauthorized'))
        return _answer('2+3')

    monkeypatch.setattr(agent_mod, 'call_llm', _fake_call_llm)
    agent = PdfIndependentVerifierAgent(solvers=[
        SolverSpec('gpt-4o-mini'), SolverSpec('microsoft/phi-4', 'http://x/v1')])
    with pytest.raises(NonRetryableLLMError):
        agent.run({'question_text': 'Tính 2+3.'})


def test_same_family_panel_warns_or_refuses(monkeypatch, capsys):
    agent = PdfIndependentVerifierAgent(solvers=[SolverSpec('gpt-4o-mini')])
    monkeypatch.setattr(cfg, 'INDEPENDENT_REQUIRE_CROSS_FAMILY', False)
    assert agent.check_independence('gpt-4o') == 'same_family'
    assert 'CẢNH BÁO' in capsys.readouterr().out

    monkeypatch.setattr(cfg, 'INDEPENDENT_REQUIRE_CROSS_FAMILY', True)
    with pytest.raises(NonRetryableLLMError):
        agent.check_independence('gpt-4o')

    cross = PdfIndependentVerifierAgent(solvers=[SolverSpec('microsoft/phi-4')])
    assert cross.check_independence('gpt-4o') == 'cross_family'

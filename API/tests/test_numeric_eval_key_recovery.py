"""Regression: numeric_eval false-flag recovery (Fix B).

Benchmark 2026-07-23 (report/bench/20260723-b1) surfaced correct
solid-of-revolution answers of the form \\frac{k\\pi}{5} being marked
verified=False and routed to review. The numeric_eval engine compares the
writer's `expr` against a *separately* supplied `expected_numeric`; when the
writer restates that redundant scalar inconsistently, the item is flagged even
though `expr` integrates to exactly the keyed answer.

VerifierAgent upgrades such an item to verified=True when the computed value
matches the keyed option, and only then: if the computation disagrees with the
key the verdict stays False.

SCOPE OF THAT GUARANTEE (corrected 2026-07-25). The upgrade proves only that the
writer's ``expr`` and the writer's keyed option agree — both authored by the same
agent. Run `20260724-b1-postparse` item #34 is a counter-example: a consistently
wrong ``expr`` matched a wrong key and this helper upgraded it. The recovery is
therefore a *consistency* signal, never a correctness one; the item's published
status caps at CONSISTENCY_CONFIRMED and only
`pipeline.independent_target` can raise it to INDEPENDENTLY_VERIFIED. See
`tests/test_verifier_blindspot_regression.py`.
"""
from __future__ import annotations

import copy

from pipeline.agents.messages import VerifyRequest
from pipeline.agents.verifier_agent import VerifierAgent

_STEM = (
    "Một khối tròn xoay được tạo thành khi quay miền phẳng giới hạn bởi parabol "
    "có đỉnh \\(I(0;5)\\), đi qua điểm \\(A(3;2)\\), trục hoành và hai đường "
    "thẳng \\(x=-3, x=3\\) quanh trục \\(Ox\\). Tính thể tích của khối tròn xoay đó."
)
_QUOTE = (
    "Thể tích khối tròn xoay khi quay quanh trục \\(Ox\\) được tính bởi công "
    "thức \\(\\pi\\int_a^b f(x)^2\\,dx\\)."
)
_SLOT = {
    'cognitive_level': 'Thông hiểu',
    'question_pattern': 'computation',
    'topic': 'thể tích khối tròn xoay',
    'skill': 'thể tích tròn xoay',
}


def _candidate(expr, expected_numeric, answer):
    return {
        'question_text': _STEM,
        'answer_text': answer,
        'answer_explanation_text': (
            "Parabol \\(y=5-\\frac{x^2}{3}\\); thể tích "
            "\\(\\pi\\int_{-3}^{3}(5-\\frac{x^2}{3})^2dx=\\frac{504\\pi}{5}\\)."
        ),
        'source_quote_text': _QUOTE,
        'distractors': [
            {'distractor_text': '\\(\\frac{336\\pi}{5}\\)',
             'distractor_explanation_text': 'Quên đổi cận khi đặt \\(x=3u\\), tính \\(\\int\\) sai.'},
            {'distractor_text': '\\(\\frac{80\\sqrt{15}\\pi}{3}\\)',
             'distractor_explanation_text': 'Lấy miền \\(x=\\pm\\sqrt{15}\\) nơi parabol cắt trục hoành.'},
            {'distractor_text': '\\(\\frac{504}{5}\\)',
             'distractor_explanation_text': 'Quên nhân hằng số \\(\\pi\\) trong công thức thể tích.'},
        ],
        'verifier_hint': {
            'type': 'numeric_eval',
            'payload': {'expr': expr, 'expected_numeric': expected_numeric},
        },
    }


def _verify(expr, expected_numeric, answer):
    agent = VerifierAgent(use_skills=False)
    req = VerifyRequest(
        candidate=_candidate(expr, expected_numeric, answer),
        slot=copy.deepcopy(_SLOT),
        context=_QUOTE,
    )
    return agent.run(req)


def test_numeric_eval_recovers_correct_pi_volume():
    # expr integrates to 504*pi/5 = 316.67 (correct); writer's expected_numeric
    # is an inconsistent 300 -> engine returns False -> must be recovered.
    resp = _verify('pi*integrate((5-x**2/3)**2,(x,-3,3))', 300.0,
                   r'\(\frac{504\pi}{5}\)')
    assert resp.annotations['_verification']['verified'] is True
    assert resp.annotations.get('_numeric_eval_key_recovered') is True
    assert resp.rejected is False


def test_numeric_eval_does_not_certify_disagreeing_key():
    # expr computes 200 and disagrees with expected_numeric (999) -> engine
    # returns False; 200 != keyed 316.67 -> Fix B must NOT upgrade.
    resp = _verify('200', 999.0, r'\(\frac{504\pi}{5}\)')
    assert resp.annotations['_verification']['verified'] is False
    assert resp.annotations.get('_numeric_eval_key_recovered') is None


def test_recover_helper_contract():
    """Unit-level contract of the shared helper, independent of the agent."""
    from pipeline.verifier import VerificationResult
    from pipeline.agents.verifier_agent import recover_numeric_eval_against_key

    # computed value matches the keyed answer -> upgrade in place
    r = VerificationResult(verified=False, engine='numeric_eval',
                           actual=316.6725, detail='expr = 316.6725')
    assert recover_numeric_eval_against_key(r, r'\(\frac{504\pi}{5}\)') is True
    assert r.verified is True

    # computed value disagrees with the key -> never upgrade
    r2 = VerificationResult(verified=False, engine='numeric_eval',
                            actual=200.0, detail='expr = 200')
    assert recover_numeric_eval_against_key(r2, r'\(\frac{504\pi}{5}\)') is False
    assert r2.verified is False

    # only numeric_eval is eligible; other engines are left untouched
    r3 = VerificationResult(verified=False, engine='sympy.integrate',
                            actual=316.6725, detail='')
    assert recover_numeric_eval_against_key(r3, r'\(\frac{504\pi}{5}\)') is False
    assert r3.verified is False

    # a True/None verdict is never downgraded or touched
    r4 = VerificationResult(verified=True, engine='numeric_eval', actual=1.0)
    assert recover_numeric_eval_against_key(r4, '1') is False
    assert r4.verified is True

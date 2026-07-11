"""Quote-relevance strictness: lenient (default) vs strict (legacy env gate).

Regression coverage for the audit finding where the formula-family hard gate
rejected 100% of computational questions written from a theory-only source
chunk (definitions / general rules).
"""
from __future__ import annotations

import importlib

import pytest


# A legitimate computational question written from a definition-only quote.
# The quote states the general rule; the question applies it to concrete values.
QUOTE_DEFINITION = (
    "Hàm số F(x) được gọi là nguyên hàm của hàm số f(x) trên K "
    "nếu F'(x) = f(x) với mọi x thuộc K."
)
CANDIDATE_COMPUTATIONAL = {
    'question_text': 'Cho F(x)=x^3-2x+5 và f(x)=3x^2-2. Lý do nào cho thấy F(x) là một nguyên hàm của f(x)?',
    'answer_text': 'Vì F′(x)=3x^2-2=f(x) trên R',
    'answer_explanation_text': 'Đạo hàm của F(x) bằng f(x) nên F là một nguyên hàm của f theo định nghĩa nguyên hàm.',
    'source_quote_text': QUOTE_DEFINITION,
    'distractors': [
        {'distractor_text': 'Vì F(x) là đa thức bậc ba'},
        {'distractor_text': 'Vì f(x) là đạo hàm cấp hai của F(x)'},
        {'distractor_text': 'Vì F(0)=5'},
    ],
}


def _reload_with(monkeypatch, strict_value: str):
    """Reload config + rule_validator under a given env so the module-level
    flag is re-evaluated."""
    monkeypatch.setenv('AQG_QUOTE_RELEVANCE_STRICT', strict_value)
    from pipeline import config as cfg
    importlib.reload(cfg)
    from pipeline import rule_validator as rv
    importlib.reload(rv)
    return rv


def test_lenient_accepts_computational_question_on_definition_quote(monkeypatch):
    rv = _reload_with(monkeypatch, '0')
    try:
        issues = rv.validate_candidate(CANDIDATE_COMPUTATIONAL)
        assert not any(i.startswith('quote_mismatch:source_quote_not_relevant') for i in issues), (
            f'lenient mode should not hard-reject on formula-family mismatch; issues={issues}'
        )
    finally:
        # Restore default module state for other tests.
        monkeypatch.delenv('AQG_QUOTE_RELEVANCE_STRICT', raising=False)
        _reload_with(monkeypatch, '0')


def test_strict_still_rejects_computational_question_on_definition_quote(monkeypatch):
    rv = _reload_with(monkeypatch, '1')
    try:
        issues = rv.validate_candidate(CANDIDATE_COMPUTATIONAL)
        assert any(i.startswith('quote_mismatch:source_quote_not_relevant') for i in issues), (
            f'strict mode should preserve the legacy formula-family gate; issues={issues}'
        )
    finally:
        monkeypatch.delenv('AQG_QUOTE_RELEVANCE_STRICT', raising=False)
        _reload_with(monkeypatch, '0')


def test_lenient_still_rejects_off_topic_quote(monkeypatch):
    """Topical relevance is still enforced via token overlap."""
    rv = _reload_with(monkeypatch, '0')
    try:
        off_topic = dict(CANDIDATE_COMPUTATIONAL)
        off_topic['source_quote_text'] = (
            'Đồ thị hàm số bậc hai là một parabol có trục đối xứng song song với trục tung.'
        )
        issues = rv.validate_candidate(off_topic)
        assert any('quote_mismatch' in i for i in issues), (
            f'an unrelated quote should still be flagged; issues={issues}'
        )
    finally:
        monkeypatch.delenv('AQG_QUOTE_RELEVANCE_STRICT', raising=False)
        _reload_with(monkeypatch, '0')

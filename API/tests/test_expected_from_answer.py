"""Regression: _expected_from_answer must not mis-parse LaTeX unit wrappers
or Vietnamese thousands-grouped numbers.

Found via a real 20-question run on toan-thuc-te-nguyen-ham-va-tich-phan-toan-12.pdf:
  - "\\(\\frac{352}{3}\\,\\text{m}\\)" (true value 352/3 ≈ 117.33) was parsed as 352,
    causing a correct answer to be rejected as answer_text_mismatch.
  - "\\(600.000\\) đồng" (true value 600000, VN thousands separator) was parsed
    as 600.0, causing a correct answer to be rejected as answer_text_mismatch.
"""
from __future__ import annotations

import math

import pytest

from pipeline.agents.verifier_agent import _expected_from_answer


@pytest.mark.parametrize('answer_text,expected', [
    (r'\(\frac{352}{3}\,\text{m}\)', 352 / 3),
    (r'\frac{1}{2}\text{cm}', 0.5),
    (r'\(600.000\) đồng', 600000),
    (r'1.234.567 đồng', 1234567),
    (r'\(600.000\,\text{đồng}\)', 600000),
    ('42', 42),
    (r'\(3,5\)', 3.5),  # decimal comma, not thousands grouping
    # Run 2026-07-10: \dfrac{432\pi}{5} was read as 432 (frac regex only
    # accepted plain numbers), rejecting correct answers vs actual 271.43.
    (r'\(\dfrac{432\pi}{5}\,\text{cm}^3\)', 432 * math.pi / 5),
    (r'\(\frac{512\pi}{5}\,\text{cm}^3\)', 512 * math.pi / 5),
    (r'\(8\pi\)', 8 * math.pi),
    (r'\(\pi\)', math.pi),
])
def test_expected_from_answer_parses_correctly(answer_text, expected):
    got = _expected_from_answer(answer_text)
    assert got is not None, f'failed to parse: {answer_text!r}'
    assert abs(float(got) - float(expected)) < 1e-6, (
        f'{answer_text!r} -> {got}, expected {expected}'
    )

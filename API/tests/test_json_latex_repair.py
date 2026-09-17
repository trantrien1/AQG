"""Regression: loads_json_maybe_repair must parse LLM question JSON that
carries unescaped LaTeX backslashes, without failing and without silently
turning \\theta / \\beta / \\nabla into control characters.

Benchmark 2026-07-24 lost 17 writer candidates to ``Invalid \\escape`` because
the old two-regex repair only doubled a whitelist of commands: an escaped
delimiter and a non-whitelisted command appearing together (e.g. ``\\(`` next to
``\\pi``) raised, and ``\\t``/``\\n``/``\\b``/``\\f``/``\\r`` prefixes
(``\\theta``, ``\\nabla``, ``\\beta``, ``\\forall``, ``\\rho``) were parsed as
tab/newline/backspace/form-feed/carriage-return. The single-pass scanner fixes
both classes.
"""
from __future__ import annotations

import json

import pytest

from pipeline.parsing import loads_json_maybe_repair


def _obj(body: str) -> str:
    """A one-field JSON object whose string value is `body`, with SINGLE
    backslashes (i.e. invalid JSON, exactly what the model emits)."""
    return '{"a": "' + body + '"}'


@pytest.mark.parametrize('body,expected', [
    # commands that previously RAISED Invalid \escape
    (r'Tinh \(\frac{1}{2}\pi\) va \(\sqrt{2}\)',
     r'Tinh \(\frac{1}{2}\pi\) va \(\sqrt{2}\)'),
    (r'Nhiet do \(26^{\circ}C\)', r'Nhiet do \(26^{\circ}C\)'),
    (r'\(\Delta x\) va \(\nabla f\)', r'\(\Delta x\) va \(\nabla f\)'),
    (r'\(\alpha+\beta+\rho\)', r'\(\alpha+\beta+\rho\)'),
    (r'\(0\le x\le 4\), \(x\ne 2\)', r'\(0\le x\le 4\), \(x\ne 2\)'),
    (r'\(\underbrace{x}_{n}\)', r'\(\underbrace{x}_{n}\)'),
    (r'\(x>0 \Rightarrow y>0\)', r'\(x>0 \Rightarrow y>0\)'),
    # commands that previously PARSED but corrupted to control chars
    (r'Goc \(\theta\) voi \(\tau\)', r'Goc \(\theta\) voi \(\tau\)'),
    (r'Cho \(v(t)=\nu t\)', r'Cho \(v(t)=\nu t\)'),
    (r'\(\boldsymbol{v}\)', r'\(\boldsymbol{v}\)'),
    (r'\(\forall x\)', r'\(\forall x\)'),
])
def test_repairs_unescaped_latex(body, expected):
    obj = loads_json_maybe_repair(_obj(body))
    assert obj['a'] == expected
    # no control characters leaked in
    assert not any(ord(c) < 32 for c in obj['a'])


def test_valid_json_is_untouched_fast_path():
    # a real \n escape must remain a newline, not be doubled
    assert loads_json_maybe_repair(json.dumps({'a': 'l1\nl2'}))['a'] == 'l1\nl2'
    # already-escaped LaTeX (valid JSON) parses to single backslashes
    assert loads_json_maybe_repair(r'{"a": "\\(\\frac{1}{2}\\)"}')['a'] == r'\(\frac{1}{2}\)'


def test_mixed_escaped_and_unescaped():
    # one delimiter already escaped, the command not — the exact shape that
    # broke the old repair
    raw = r'{"a": "\\(\frac{1}{2}\pi\\)"}'
    assert loads_json_maybe_repair(raw)['a'] == r'\(\frac{1}{2}\pi\)'


def test_list_of_question_objects():
    raw = (r'[{"q": "Tinh \(\int_0^2 x\,dx\)"},'
           r' {"q": "\(\theta=\pi/2\)"}]')
    out = loads_json_maybe_repair(raw)
    assert [d['q'] for d in out] == [r'Tinh \(\int_0^2 x\,dx\)', r'\(\theta=\pi/2\)']


# --- Ký tự điều khiển thô trong chuỗi (gemini-2.5-flash, 2026-07-28) ---------
# Model xuống dòng thật giữa lời giải thay vì viết \n. json.loads ném
# "Invalid control character" và cả candidate bị bỏ. Nếu không sửa thì khi quét
# nhiều mô hình, điểm yếu của BỘ PARSE bị tính thành điểm yếu của MODEL.

def test_raw_newline_inside_string_is_repaired():
    raw = '{"a": "dòng một\ndòng hai"}'
    assert loads_json_maybe_repair(raw) == {'a': 'dòng một\ndòng hai'}


def test_raw_tab_and_carriage_return_are_repaired():
    raw = '{"a": "x\ty\rz"}'
    assert loads_json_maybe_repair(raw) == {'a': 'x\ty\rz'}


def test_other_control_chars_become_unicode_escapes():
    raw = '{"a": "x\x0bz"}'
    assert loads_json_maybe_repair(raw) == {'a': 'x\x0bz'}


def test_control_char_together_with_latex_backslash():
    raw = r'{"a": "\(x^2\)' '\n' r'vậy \frac{1}{2}"}'
    out = loads_json_maybe_repair(raw)
    assert out['a'] == r'\(x^2\)' '\n' r'vậy \frac{1}{2}'


def test_newline_between_json_values_is_untouched():
    """Xuống dòng NGOÀI chuỗi là hợp lệ, không được đụng vào."""
    raw = '{\n  "a": 1,\n  "b": 2\n}'
    assert loads_json_maybe_repair(raw) == {'a': 1, 'b': 2}

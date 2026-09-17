"""Independent Verification Target Builder — đánh giá biểu thức + ràng buộc bịt mắt."""
from __future__ import annotations

import json

import pytest

from pipeline.independent_target import (
    build_independent_prompt, build_independent_target,
    evaluate_independent_expression, parse_answer_value, values_agree,
)


# ---- Lớp SymPy (thuần, không LLM) ----

@pytest.mark.parametrize('expr,expected', [
    ('2+3', 5.0),
    ('binomial(10,4)', 210.0),
    ('factorial(5)', 120.0),
    ('sqrt(2)*sqrt(3)', 2.449489742783178),
    ('integrate(x**2, (x, 0, 3))', 9.0),
    ('12 + integrate(t**2-6*t+5, (t, 0, 1))', 43 / 3),
    ('pi*integrate((5-x**2/3)**2, (x, -3, 3))', 316.6725162),
    ('limit(sin(x)/x, x, 0)', 1.0),
    ('diff(x**3, x).subs(x, 2)', 12.0),
    ('Rational(47,3)', 47 / 3),
    ('2**10', 1024.0),
])
def test_evaluates_closed_form_expressions(expr, expected):
    value, detail = evaluate_independent_expression(expr)
    assert value is not None, detail
    assert values_agree(value, expected, rel_tol=1e-6)


def test_caret_and_latex_wrappers_are_normalised():
    value, _ = evaluate_independent_expression(r'\(2^5\)')
    assert value == 32.0


@pytest.mark.parametrize('expr', [
    '',
    'x + 1',                    # còn biến tự do
    'integrate(1/x, (x, -1, 1))',  # phân kỳ
    'sqrt(-4)',                 # giá trị phức
    'not a formula ((',
    '1/0',
])
def test_non_definite_expressions_are_rejected(expr):
    value, detail = evaluate_independent_expression(expr)
    assert value is None
    assert detail


def test_expression_namespace_is_restricted():
    """Tên ngoài whitelist không phân giải được — không eval tuỳ ý."""
    value, detail = evaluate_independent_expression('__import__("os").getpid()')
    assert value is None


def test_parse_answer_value_reads_latex():
    assert values_agree(parse_answer_value(r'\(\frac{47}{3}\)'), 47 / 3)
    assert values_agree(parse_answer_value(r'\(\frac{468\sqrt{2}\pi}{5}\)'),
                        415.8538430116231)


# ---- Ràng buộc bịt mắt ----

def test_prompt_never_leaks_writer_material():
    stem = 'Tính \\(\\int_0^1 x^2 dx\\).'
    prompt = build_independent_prompt(stem)
    assert stem in prompt
    # Không có chỗ nào trong prompt để nhét đáp án/lời giải/phương án.
    for leaked in ('1/3', 'đáp án đề xuất', 'Phương án A', 'expected_numeric'):
        assert leaked not in prompt


def test_builder_only_receives_the_stem():
    """Builder chỉ nhận `stem`; nếu ai đó truyền cả candidate thì phải lộ ra ở
    chữ ký hàm chứ không âm thầm rò rỉ."""
    import inspect
    params = set(inspect.signature(build_independent_target).parameters)
    assert params == {'stem', 'call_fn', 'model', 'givens'}


# ---- Builder với call_fn giả ----

def _fake_call(payload):
    def _call(system, user):
        return json.dumps(payload, ensure_ascii=False)
    return _call


def test_builder_returns_definite_target_when_self_consistent():
    target = build_independent_target(
        'Tính tích phân.',
        call_fn=_fake_call({
            'computable': True,
            'quantity': 'giá trị tích phân',
            'expression': 'integrate(x**2, (x, 0, 3))',
            'answer': '9',
        }),
        model='test-model',
    )
    assert target.attempted is True
    assert target.definite is True
    assert values_agree(target.value, 9.0)
    assert target.model == 'test-model'


def test_builder_rejects_self_inconsistent_solver():
    """Tác nhân độc lập tự mâu thuẫn thì KHÔNG được dùng làm bằng chứng.

    Đây đúng là hình dạng của lỗi ta đang muốn diệt — chỉ khác là ở phía kiểm
    chứng. Tin một nguồn tự mâu thuẫn sẽ tái tạo lại lỗ hổng cũ.
    """
    target = build_independent_target(
        'Tính tích phân.',
        call_fn=_fake_call({
            'computable': True,
            'expression': 'integrate(x**2, (x, 0, 3))',   # = 9
            'answer': '27',                               # tự khai khác
        }),
    )
    assert target.attempted is True
    assert target.definite is False
    assert 'mâu thuẫn' in target.detail


def test_builder_honours_not_computable():
    target = build_independent_target(
        'Phát biểu nào sau đây đúng về hàm liên tục?',
        call_fn=_fake_call({'computable': False, 'expression': '', 'answer': ''}),
    )
    assert target.definite is False
    assert target.source == 'not_applicable'


def test_builder_survives_model_failure():
    def _boom(system, user):
        raise RuntimeError('gateway down')

    target = build_independent_target('Tính gì đó.', call_fn=_boom)
    assert target.attempted is True
    assert target.definite is False
    assert target.source == 'unavailable'
    assert target.errors


def test_builder_survives_non_json_reply():
    def _prose(system, user):
        return 'Tôi nghĩ đáp án là 9.'

    target = build_independent_target('Tính gì đó.', call_fn=_prose)
    assert target.definite is False
    assert target.source == 'unavailable'


def test_builder_reads_json_inside_code_fence():
    def _fenced(system, user):
        return ('```json\n{"computable": true, "expression": "2+3", '
                '"answer": "5"}\n```')

    target = build_independent_target('Tính 2+3.', call_fn=_fenced)
    assert target.definite is True
    assert target.value == 5.0


def test_target_round_trips_through_dict():
    from pipeline.independent_target import IndependentTarget
    target = build_independent_target(
        'Tính tích phân.',
        call_fn=_fake_call({'computable': True,
                            'expression': 'integrate(x**2, (x, 0, 3))',
                            'answer': '9'}),
    )
    restored = IndependentTarget(**target.to_dict())
    assert restored.definite is True
    assert restored.value == target.value

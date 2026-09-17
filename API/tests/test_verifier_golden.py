"""Golden test set cho verifier: bài toán đã biết đáp án chính xác.

Dữ liệu ở `tests/golden/verifier_golden.json`. Mỗi ca ghi rõ kết luận verifier
PHẢI đưa ra; ca `expect:false` (claim sai) và `expect:null` (không phán định
được) quan trọng ngang ca đúng — một verifier luôn nói "true" thì vô dụng, và
một verifier im lặng coi như "đúng" thì còn tệ hơn.

Bộ này cũng là lưới an toàn khi thêm engine mới: mọi type trong
`verifier.supported_types()` phải có ít nhất một ca đúng và một ca sai.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from pipeline.verifier import supported_types, verify, verify_distractor

_GOLDEN = json.loads(
    (pathlib.Path(__file__).parent / 'golden' / 'verifier_golden.json')
    .read_text(encoding='utf-8')
)
_CASES = _GOLDEN['cases']


@pytest.mark.parametrize('case', _CASES, ids=[c['id'] for c in _CASES])
def test_golden_case(case):
    result = verify({'type': case['type'], 'payload': case['payload']})
    assert result.verified is case['expect'], (
        f"{case['id']}: mong {case['expect']}, nhận {result.verified} "
        f"(engine={result.engine}, detail={result.detail[:160]})"
    )


def test_every_supported_type_has_a_true_and_a_false_case():
    """Engine mới thêm vào mà không có golden case sẽ làm test này đỏ."""
    by_type: dict[str, set] = {}
    for case in _CASES:
        by_type.setdefault(case['type'], set()).add(case['expect'])
    missing = []
    for verifier_type in supported_types():
        seen = by_type.get(verifier_type, set())
        if True not in seen or False not in seen:
            missing.append(verifier_type)
    assert not missing, f'thiếu golden case (cần cả đúng lẫn sai) cho: {missing}'


def test_golden_ids_are_unique():
    ids = [c['id'] for c in _CASES]
    assert len(ids) == len(set(ids))


# ---- Nhiều đáp án đúng ----

def test_distractor_with_same_value_is_detected_as_also_correct():
    """Phương án nhiễu trùng GIÁ TRỊ đáp án (khác cách viết) phải bị bắt."""
    hint = {'type': 'numeric_eval',
            'payload': {'expr': '1/2', 'expected_numeric': 0.5}}
    assert verify_distractor(hint, '0.5') is True
    assert verify_distractor(hint, r'\(\frac{1}{2}\)') is True
    assert verify_distractor(hint, '0.25') is False


def test_distractor_check_is_none_for_unverifiable_questions():
    assert verify_distractor({'type': 'none', 'payload': {}}, 'bất kỳ') is None
    assert verify_distractor({}, 'bất kỳ') is None


def test_solve_equation_distractor_root_set():
    hint = {'type': 'solve_equation',
            'payload': {'equation': 'x**2 - 5*x + 6', 'variable': 'x',
                        'claimed_roots': [2, 3]}}
    assert verify_distractor(hint, '2, 3') is True
    assert verify_distractor(hint, '1, 6') is False


# ---- Đầu vào méo mó: không bao giờ raise, không bao giờ mặc định "đúng" ----

@pytest.mark.parametrize('hint', [
    None, 'not a dict', 42, [],
    {'type': 'numeric_eval'},
    {'type': 'numeric_eval', 'payload': None},
    {'type': 'numeric_eval', 'payload': 'expr=1'},
    {'type': 'counting', 'payload': {'formula': 'binomial(10,4)'}},
    {'type': 'geometry_triangle', 'payload': {'property': 'area'}},
    {'type': 'graph_property', 'payload': {'property': 'unsupported_thing'}},
    {'type': 'recurrence', 'payload': {'recurrence': [1, 1], 'initial': [0], 'n': 5, 'expected': 3}},
])
def test_malformed_hints_never_return_true(hint):
    result = verify(hint) if isinstance(hint, dict) else verify(hint)  # type: ignore[arg-type]
    assert result.verified is not True


def test_payload_given_as_json_string_is_parsed():
    result = verify({'type': 'numeric_eval',
                     'payload': '{"expr": "2+3", "expected_numeric": 5}'})
    assert result.verified is True


# ---- Độ chính xác số ----

def test_numeric_crosscheck_catches_symbolically_hard_mismatch():
    """simplify không rút gọn về 0 nhưng hai biểu thức KHÁC nhau thật."""
    result = verify({'type': 'simplify_equiv',
                     'payload': {'expr_a': 'sqrt(x**2)', 'expr_b': '-x',
                                 'variables': ['x']}})
    assert result.verified is False


def test_numeric_crosscheck_accepts_equivalent_hard_forms():
    result = verify({'type': 'trig_identity',
                     'payload': {'expr_a': 'cos(2*x)',
                                 'expr_b': '1 - 2*sin(x)**2'}})
    assert result.verified is True

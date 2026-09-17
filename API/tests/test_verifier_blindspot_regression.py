"""Regression: các ca verifier từng XÁC NHẬN NHẦM một đáp án sai.

Bốn ca thật, lấy từ hai lần chạy benchmark và được kiểm lại bằng SymPy độc lập:

    run 20260723   Q2   đáp án đúng 12,          key khai 14
    run 20260723   Q31  đáp án đúng 1296π/5,     key khai 864π/5
    run 20260724-b1-postparse #6   đúng 43/3,    key khai 47/3
    run 20260724-b1-postparse #34  đúng 576√2π/5, key khai 468√2π/5

Cả bốn đều mang `verified=True`. Nguyên nhân chung: Writer viết CẢ lời giải LẪN
biểu thức kiểm chứng, nên khi nó mô hình hoá sai một cách nhất quán thì "hai
nguồn" thực chất là một, và phép so nào giữa chúng cũng khớp.

Bộ test này khoá lại hai điều:

1. Số học nền: giá trị đúng của từng bài, tính lại bằng SymPy từ dữ kiện đề —
   không dùng biểu thức nào của Writer.
2. Hành vi mới: khi có mục tiêu kiểm chứng độc lập, những câu này KHÔNG còn
   được cấp trạng thái "đã kiểm chứng" và bị đẩy sang duyệt tay.

Lưu ý về dữ liệu: bản ghi của run cũ chỉ lưu chuỗi `detail` ("expr = 15.666…")
chứ không lưu nguyên văn `verifier_hint`, nên ở đây ta tái dựng ĐÚNG ĐẶC TRƯNG
của lỗi (biểu thức của Writer ra đúng giá trị key) thay vì bịa lại nguyên văn
biểu thức. Từ bản này trở đi record có lưu `verifier_hint` để không phải đoán.

Chỉ #6 và #34 còn đủ dữ liệu (đề bài + phương án) để dựng lại; hai ca của run
20260723 chỉ còn con số trong ghi chép nên không được tái dựng đề ở đây — dựng
lại một đề "na ná" rồi gọi nó là ca thật là bịa dữ liệu.
"""
from __future__ import annotations

import copy

import pytest
import sympy as sp

from pipeline.agents.messages import VerifyRequest
from pipeline.agents.verifier_agent import VerifierAgent
from pipeline.independent_target import evaluate_independent_expression, values_agree
from pipeline.verification_status import VerificationStatus


# ============ 1. Số học nền (SymPy độc lập) ============

def test_case6_water_tank_true_value_is_43_over_3():
    """V'(t)=t²−6t+5, V(0)=12; lần đầu V'=0 tại t=1 ⇒ V(1)=43/3, không phải 47/3."""
    t = sp.Symbol('t', positive=True)
    roots = sorted(sp.solve(sp.Eq(t**2 - 6*t + 5, 0), t))
    assert roots[0] == 1
    volume = 12 + sp.integrate(t**2 - 6*t + 5, (t, 0, roots[0]))
    assert sp.nsimplify(volume) == sp.Rational(43, 3)
    assert sp.nsimplify(volume) != sp.Rational(47, 3)


def test_case34_paraboloid_true_value_is_576_sqrt2_pi_over_5():
    """y=ax²+b qua A(0;6), B(3;3) ⇒ y=6−x²/3; quay quanh Ox giữa hai nghiệm."""
    x, a, b = sp.symbols('x a b')
    sol = sp.solve([sp.Eq(b, 6), sp.Eq(9*a + b, 3)], [a, b], dict=True)[0]
    curve = sol[a]*x**2 + sol[b]
    assert sp.simplify(curve - (6 - x**2/3)) == 0
    limit = sp.sqrt(18)                      # nghiệm dương của 6 − x²/3 = 0
    volume = sp.pi*sp.integrate(curve**2, (x, -limit, limit))
    assert sp.simplify(volume - 576*sp.sqrt(2)*sp.pi/5) == 0
    assert sp.simplify(volume - 468*sp.sqrt(2)*sp.pi/5) != 0


@pytest.mark.parametrize('expression,expected', [
    ('12 + integrate(t**2-6*t+5, (t, 0, 1))', 43 / 3),
    ('pi*integrate((6-x**2/3)**2, (x, -sqrt(18), sqrt(18)))',
     float(576*sp.sqrt(2)*sp.pi/5)),
])
def test_independent_layer_reproduces_the_true_values(expression, expected):
    """Đúng những biểu thức mà tác nhân độc lập cần nộp — SymPy tính lại được."""
    value, detail = evaluate_independent_expression(expression)
    assert value is not None, detail
    assert values_agree(value, expected, rel_tol=1e-9)


# ============ 2. Hành vi mới, chạy qua VerifierAgent ============

_CASE6_STEM = (
    'Một bể nuôi cá được bơm nước trong thời gian \\(t\\) phút. Gọi \\(V(t)\\) '
    'là thể tích nước trong bể. Tốc độ thay đổi thể tích nước được xác định '
    'bởi \\(V\'(t)=t^2-6t+5\\). Biết ban đầu bể có \\(12\\) đơn vị nước. Hỏi '
    'thể tích nước tại thời điểm tốc độ bơm giảm về \\(0\\) lần đầu tiên bằng '
    'bao nhiêu?'
)
_CASE6_QUOTE = (
    'Nếu \\(F\'(x)=f(x)\\) trên đoạn \\([a;b]\\) thì '
    '\\(\\int_a^b f(x)\\,dx=F(b)-F(a)\\).'
)
_SLOT = {
    'cognitive_level': 'Vận dụng',
    'question_pattern': 'computation',
    'topic': 'nguyên hàm và tích phân',
    'skill': 'ứng dụng tích phân',
    # Giống slot mà orchestrator dựng cho Direct_PDF: câu là BÀI TẬP MỚI viết
    # theo phương pháp trong tài liệu, quote là công thức chung nên bỏ kiểm
    # trùng token giữa quote và đề.
    'source_chunk_type': 'exercise',
}


def _case6_candidate():
    """Câu #6 như hệ thống đã sinh ra: key 47/3 và biểu thức Writer cũng ra 47/3."""
    return {
        'question_text': _CASE6_STEM,
        'answer_text': r'\(\frac{47}{3}\)',
        'answer_explanation_text': (
            'Tốc độ bằng 0 lần đầu tại \\(t=1\\); lấy tích phân của '
            '\\(V\'(t)\\) rồi cộng thể tích ban đầu.'
        ),
        'source_quote_text': _CASE6_QUOTE,
        'distractors': [
            {'distractor_text': r'\(\frac{61}{3}\)',
             'distractor_explanation_text': 'Lấy nhầm mốc \\(t=5\\) thay vì \\(t=1\\).'},
            {'distractor_text': r'\(\frac{11}{3}\)',
             'distractor_explanation_text': 'Quên cộng thể tích ban đầu của bể.'},
            {'distractor_text': r'\(\frac{7}{3}\)',
             'distractor_explanation_text': 'Chỉ lấy phần tích phân, bỏ hằng số đầu.'},
        ],
        # Đặc trưng của lỗi: expr của Writer ra ĐÚNG giá trị key sai (47/3).
        'verifier_hint': {
            'type': 'numeric_eval',
            'payload': {'expr': '47/3', 'expected_numeric': 47 / 3},
        },
    }


def _verify(candidate, independent=None):
    if independent is not None:
        candidate = dict(candidate, _independent_target=independent)
    return VerifierAgent(use_skills=False).run(VerifyRequest(
        candidate=candidate, slot=copy.deepcopy(_SLOT), context=_CASE6_QUOTE,
    ))


def test_case6_without_independent_target_is_only_consistency_confirmed():
    """Hành vi cũ vẫn tái hiện được — nhưng nhãn không còn nói 'đã kiểm chứng'."""
    resp = _verify(_case6_candidate())
    ver = resp.annotations['_verification']
    assert ver['verified'] is True            # nhất quán nội bộ: vẫn True
    assert ver['status'] == VerificationStatus.CONSISTENCY_CONFIRMED
    assert ver['status'] != VerificationStatus.INDEPENDENTLY_VERIFIED
    assert ver['independent']['attempted'] is False


def test_case6_with_independent_target_is_routed_to_human():
    """Đây là điểm sửa: nguồn độc lập ra 43/3, câu không còn lặng lẽ đi qua."""
    independent = {
        'attempted': True, 'definite': True, 'value': 43 / 3,
        'expression': '12 + integrate(t**2-6*t+5, (t, 0, 1))',
        'stated_answer': '43/3', 'stated_value': 43 / 3, 'source': 'llm_resolver',
    }
    resp = _verify(_case6_candidate(), independent)
    ver = resp.annotations['_verification']
    assert ver['status'] == VerificationStatus.MISMATCH
    assert ver['needs_human_review'] is True
    assert ver['machine_checked'] is False
    assert resp.rejected is False             # không loại — chuyển người duyệt


def test_case6_record_is_flagged_needs_revision():
    from pipeline.schema import to_question_record
    independent = {'attempted': True, 'definite': True, 'value': 43 / 3,
                   'expression': '12 + integrate(t**2-6*t+5, (t, 0, 1))',
                   'stated_answer': '43/3', 'stated_value': 43 / 3,
                   'source': 'llm_resolver'}
    candidate = _case6_candidate()
    resp = _verify(candidate, independent)
    candidate.update(resp.annotations)
    slot = dict(_SLOT, slot_id='regression_case6', difficulty_target=0.7)
    record = to_question_record(slot, candidate)
    assert record['review_status'] == 'needs_revision'
    assert record['verification']['status'] == VerificationStatus.MISMATCH
    assert record['verification']['machine_checked'] is False
    assert VerificationStatus.MISMATCH in record['review']['issues']


def test_correct_answer_with_agreeing_independent_target_is_upgraded():
    """Ca đối chứng: key ĐÚNG thì mới được lên INDEPENDENTLY_VERIFIED."""
    candidate = _case6_candidate()
    candidate['answer_text'] = r'\(\frac{43}{3}\)'
    candidate['verifier_hint']['payload'] = {
        'expr': '12 + integrate(t**2-6*t+5, (t, 0, 1))',
        'expected_numeric': 43 / 3,
    }
    independent = {'attempted': True, 'definite': True, 'derivation': True,
                   'value': 43 / 3,
                   'expression': '12 + integrate(t**2-6*t+5, (t, 0, 1))',
                   'stated_answer': '43/3', 'stated_value': 43 / 3,
                   'source': 'llm_resolver'}
    resp = _verify(candidate, independent)
    ver = resp.annotations['_verification']
    assert ver['status'] == VerificationStatus.INDEPENDENTLY_VERIFIED
    assert ver['needs_human_review'] is False
    assert ver['machine_checked'] is True


def test_wrong_key_whose_true_value_is_an_option_is_refuted():
    """Khi giá trị đúng nằm ngay trong danh sách phương án ⇒ bác bỏ hẳn."""
    candidate = _case6_candidate()
    independent = {'attempted': True, 'definite': True, 'value': 11 / 3,
                   'expression': 'integrate(t**2-6*t+5, (t, 0, 5)) + 12',
                   'stated_answer': '11/3', 'stated_value': 11 / 3,
                   'source': 'llm_resolver'}
    resp = _verify(candidate, independent)
    ver = resp.annotations['_verification']
    assert ver['status'] == VerificationStatus.REFUTED
    assert ver['needs_human_review'] is True


def test_answer_key_repair_requires_independent_evidence():
    """Không có bằng chứng độc lập thì KHÔNG được tự viết đè đáp án key."""
    from pipeline.agents.verifier_agent import _repair_answer_from_verified_distractor
    from pipeline.verifier import VerificationResult

    candidate = _case6_candidate()
    candidate['detailed_solution'] = {'steps': [], 'final_answer': r'\(\frac{11}{3}\)'}
    result = VerificationResult(verified=True, engine='numeric_eval',
                                actual=11 / 3, detail='expr = 3.6667')

    # Chỉ có biểu thức của Writer -> từ chối sửa.
    assert _repair_answer_from_verified_distractor(
        candidate, 'numeric_eval', result, None) is False
    assert candidate['answer_text'] == r'\(\frac{47}{3}\)'

    # Có nguồn độc lập xác nhận cùng giá trị -> mới được sửa.
    from pipeline.independent_target import IndependentTarget
    independent = IndependentTarget(attempted=True, definite=True, value=11 / 3)
    assert _repair_answer_from_verified_distractor(
        candidate, 'numeric_eval', result, independent) is True
    assert candidate['answer_text'] == r'\(\frac{11}{3}\)'
    assert candidate['_answer_key_repair_evidence']['independent_value'] == 11 / 3

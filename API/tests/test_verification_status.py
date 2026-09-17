"""Luật phân xử 5 trạng thái — phủ từng nhánh của `adjudicate`.

Không nhánh nào gọi LLM: mọi bằng chứng được truyền vào dưới dạng tham số.
"""
from __future__ import annotations

from pipeline.independent_target import IndependentTarget, disabled_target
from pipeline.verification_status import (
    VerificationStatus, adjudicate, is_machine_checked, review_status_for,
)


def _independent(value, definite=True, derivation=True):
    """Mục tiêu độc lập ĐÃ suy dẫn (mặc định).

    `expression` cố ý là một phép tính chứ không phải hằng số trần: một hằng số
    trần nghĩa là tác nhân độc lập chỉ khẳng định con số, không bắt máy tính gì
    — trường hợp đó có test riêng ở cuối file.
    """
    return IndependentTarget(
        attempted=True, definite=definite, derivation=derivation, value=value,
        expression=f'0 + {value}', stated_answer=str(value), stated_value=value,
        source='llm_resolver',
    )


# ---- 4. Không có bằng chứng độc lập ----

def test_no_engine_is_non_verifiable():
    adj = adjudicate(writer_verified=None, writer_engine='none',
                     independent=disabled_target(), keyed_value=5.0)
    assert adj.status == VerificationStatus.NON_VERIFIABLE
    assert adj.needs_human_review is False
    assert adj.independent_support is False


def test_writer_expression_alone_is_only_consistency():
    """Đây là điểm mấu chốt: writer nói đúng KHÔNG cho ra 'đã kiểm chứng'."""
    adj = adjudicate(writer_verified=True, writer_engine='numeric_eval',
                     independent=disabled_target(), keyed_value=5.0)
    assert adj.status == VerificationStatus.CONSISTENCY_CONFIRMED
    assert adj.status != VerificationStatus.INDEPENDENTLY_VERIFIED
    assert adj.independent_support is False


def test_writer_expression_disagreeing_is_mismatch():
    adj = adjudicate(writer_verified=False, writer_engine='numeric_eval',
                     independent=disabled_target(), keyed_value=5.0)
    assert adj.status == VerificationStatus.MISMATCH
    assert adj.needs_human_review is True


# ---- 2. Mục tiêu độc lập xác nhận ----

def test_independent_agreement_is_independently_verified():
    adj = adjudicate(writer_verified=True, writer_engine='numeric_eval',
                     independent=_independent(5.0), keyed_value=5.0)
    assert adj.status == VerificationStatus.INDEPENDENTLY_VERIFIED
    assert adj.independent_support is True
    assert adj.needs_human_review is False


def test_independent_agreement_survives_writer_false():
    """Writer viết lệch scalar dư nhưng nguồn độc lập xác nhận key."""
    adj = adjudicate(writer_verified=False, writer_engine='numeric_eval',
                     independent=_independent(5.0), keyed_value=5.0)
    assert adj.status == VerificationStatus.INDEPENDENTLY_VERIFIED


def test_independent_agreement_uses_relative_tolerance():
    adj = adjudicate(writer_verified=True, writer_engine='numeric_eval',
                     independent=_independent(316.6725), keyed_value=316.67251)
    assert adj.status == VerificationStatus.INDEPENDENTLY_VERIFIED


# ---- 3. Mục tiêu độc lập bác bỏ ----

def test_independent_matching_a_distractor_refutes_the_key():
    adj = adjudicate(writer_verified=True, writer_engine='numeric_eval',
                     independent=_independent(7.0), keyed_value=5.0,
                     distractor_values=[7.0, 9.0, 11.0])
    assert adj.status == VerificationStatus.REFUTED
    assert adj.needs_human_review is True
    assert adj.independent_support is True


def test_both_sources_disagreeing_with_key_refutes():
    adj = adjudicate(writer_verified=False, writer_engine='numeric_eval',
                     independent=_independent(7.0), keyed_value=5.0,
                     distractor_values=[1.0, 2.0, 3.0])
    assert adj.status == VerificationStatus.REFUTED


def test_independent_alone_disagreeing_is_only_mismatch():
    """Nguồn độc lập cũng là một model — một mình nó không đủ để kết luận sai.

    Đây chính là hình dạng của hai ca lọt lưới #6 và #34: biểu thức của Writer
    tự khớp với key sai, nguồn độc lập ra số khác, giá trị đúng không nằm trong
    4 phương án. Kết quả phải là chuyển người duyệt, không phải im lặng cho qua.
    """
    adj = adjudicate(writer_verified=True, writer_engine='numeric_eval',
                     independent=_independent(14.3333), keyed_value=15.6667,
                     distractor_values=[20.3333, 3.6667, 2.3333])
    assert adj.status == VerificationStatus.MISMATCH
    assert adj.needs_human_review is True


def test_inconclusive_independent_falls_back_to_writer_evidence():
    adj = adjudicate(writer_verified=True, writer_engine='numeric_eval',
                     independent=_independent(99.0, definite=False),
                     keyed_value=5.0)
    assert adj.status == VerificationStatus.CONSISTENCY_CONFIRMED


def test_unreadable_key_cannot_be_independently_verified():
    adj = adjudicate(writer_verified=True, writer_engine='numeric_eval',
                     independent=_independent(5.0), keyed_value=None)
    assert adj.status == VerificationStatus.CONSISTENCY_CONFIRMED


# ---- 1. Nhiều đáp án đúng ----

def test_multi_answer_refutes():
    adj = adjudicate(writer_verified=True, writer_engine='solve_equation',
                     independent=disabled_target(), keyed_value=5.0,
                     multi_answer_options=[r'\(5\)'])
    assert adj.status == VerificationStatus.REFUTED
    assert adj.needs_human_review is True


def test_distractor_equal_to_verified_answer_refutes():
    """Đáp án đúng nhưng một phương án nhiễu có CÙNG giá trị ⇒ hai đáp án."""
    adj = adjudicate(writer_verified=True, writer_engine='numeric_eval',
                     independent=_independent(5.0), keyed_value=5.0,
                     distractor_values=[5.0, 9.0, 11.0])
    assert adj.status == VerificationStatus.REFUTED


# ---- Hệ quả xuống record ----

def test_only_machine_checked_states_may_claim_a_machine_check():
    assert is_machine_checked(VerificationStatus.INDEPENDENTLY_VERIFIED)
    assert is_machine_checked(VerificationStatus.CONSISTENCY_CONFIRMED)
    assert not is_machine_checked(VerificationStatus.NON_VERIFIABLE)
    assert not is_machine_checked(VerificationStatus.MISMATCH)
    assert not is_machine_checked(VerificationStatus.REFUTED)


def test_review_routing():
    assert review_status_for(VerificationStatus.MISMATCH) == 'needs_revision'
    assert review_status_for(VerificationStatus.REFUTED) == 'needs_revision'
    assert review_status_for(
        VerificationStatus.INDEPENDENTLY_VERIFIED) == 'pending_review'
    assert review_status_for(
        VerificationStatus.NON_VERIFIABLE) == 'pending_review'


def test_every_status_has_both_labels():
    from pipeline.verification_status import STATUS_LABELS_EN, STATUS_LABELS_VI
    for status in VerificationStatus.ALL:
        assert STATUS_LABELS_VI.get(status)
        assert STATUS_LABELS_EN.get(status)


# ---- Hằng số trần không phải là "kiểm chứng độc lập" ----

def test_bare_constant_agreement_is_not_independent_verification():
    """Nguồn độc lập chỉ khẳng định một con số ⇒ không có phép tính nào được
    máy kiểm. Hai model cùng nói "6" là hai ý kiến trùng nhau, không phải một
    phép tái tính. Gọi nó là INDEPENDENTLY_VERIFIED là nói quá đúng thứ mà cả
    thiết kế này tồn tại để chống."""
    bare = IndependentTarget(attempted=True, definite=True, derivation=False,
                             value=6.0, expression='6', stated_answer='6',
                             stated_value=6.0, source='llm_resolver')
    adj = adjudicate(writer_verified=True, writer_engine='counting',
                     independent=bare, keyed_value=6.0)
    assert adj.status == VerificationStatus.CONSISTENCY_CONFIRMED
    assert adj.independent_support is False
    assert 'hằng số' in adj.detail


def test_bare_constant_disagreement_still_routes_to_human():
    """Bất đối xứng có chủ ý: đồng ý mà không suy dẫn thì bằng chứng yếu, nhưng
    BẤT ĐỒNG vẫn là tín hiệu đáng để người nhìn lại."""
    bare = IndependentTarget(attempted=True, definite=True, derivation=False,
                             value=5.0, expression='5', stated_answer='5',
                             stated_value=5.0, source='llm_resolver')
    adj = adjudicate(writer_verified=True, writer_engine='counting',
                     independent=bare, keyed_value=6.0,
                     distractor_values=[5.0, 3.0, 9.0])
    assert adj.status == VerificationStatus.REFUTED
    assert adj.needs_human_review is True


def test_derivation_agreement_is_independent_verification():
    derived = IndependentTarget(attempted=True, definite=True, derivation=True,
                                value=6.0, expression='binomial(4,2)',
                                stated_answer='6', stated_value=6.0,
                                source='llm_resolver')
    adj = adjudicate(writer_verified=True, writer_engine='counting',
                     independent=derived, keyed_value=6.0)
    assert adj.status == VerificationStatus.INDEPENDENTLY_VERIFIED


def test_is_derivation_classifier():
    from pipeline.independent_target import is_derivation
    for bare in ('6', '-3', '47/3', '2.5', ' 12 ', '0'):
        assert is_derivation(bare) is False, bare
    for real in ('3*5', 'binomial(4,3)', 'integrate(x**2,(x,0,1))', '2**10',
                 'pi', 'sqrt(2)'):
        assert is_derivation(real) is True, real

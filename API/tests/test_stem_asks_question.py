# -*- coding: utf-8 -*-
"""Đề phải THỰC SỰ hỏi gì đó.

Bản dò chuỗi con cũ cho qua 5 câu ở run 2026-07-25 chỉ vì trong đề có "máy
tính" (khớp dấu hiệu 'tính '), "Chọn hệ trục toạ độ" (khớp 'chọn ') hoặc "bit
bằng 0" (khớp 'bằng'). Những câu đó mô tả xong dữ kiện rồi dừng, người học
không biết phải trả lời gì, mà vẫn đi hết pipeline tới tay người dùng.
"""
from __future__ import annotations

import pytest

from pipeline.rule_validator import _stem_asks_question

ASKS = [
    'Giá trị của \(F(3)\) bằng bao nhiêu?',
    'Tính thể tích khối tròn xoay tạo thành.',
    'Hãy xác định giá trị thập phân của xâu bit \(B\).',
    'Thể tích phần không gian bên trong đường hầm bằng',
    'Khẳng định nào sau đây là đúng?',
    'Cho hàm số \(f(x)=x^2\). Tìm nguyên hàm của \(f\).',
    'Biết \(V(0)=20\), hỏi sau 5 giờ thể tích là bao nhiêu?',
]

DOES_NOT_ASK = [
    # Ca thật từ run 2026-07-25 (rút gọn), từng lọt qua bản cũ.
    'Cho tập vũ trụ \(U\). Gọi \(S\subseteq U\) là tập gồm các số chia hết '
    'cho 3 hoặc là số nguyên tố.',
    'Tập \(A\) được biểu diễn bởi xâu bit 10110100 (các vị trí bit được đánh '
    'số từ trái sang phải tương ứng với thứ tự các phần tử trong \(U\)).',
    'Máy tính biểu diễn các tập con bằng xâu bit theo thứ tự của \(U\), trong '
    'đó phép XOR bit tương ứng với phép lấy hiệu đối xứng \(A_k\triangle B\).',
    'Cho tập \(A\) gồm các máy chủ chia hết cho 3, tập \(B\) gồm các máy chủ '
    'mà khi cộng thêm 3 được một số chia hết cho 5,',
    'Chọn hệ trục toạ độ sao cho mặt đất là trục hoành. Biết cung parabol đi qua '
    'hai điểm \(A(-3;0)\), \(B(3;0)\) và tại \(x=1\) có độ cao \(3\,m\).',
    '',
]


@pytest.mark.parametrize('stem', ASKS)
def test_real_questions_are_accepted(stem):
    assert _stem_asks_question(stem) is True


@pytest.mark.parametrize('stem', DOES_NOT_ASK)
def test_descriptions_without_a_question_are_rejected(stem):
    assert _stem_asks_question(stem) is False


@pytest.mark.parametrize('phrase', ['máy tính', 'Chọn hệ trục toạ độ',
                                    'bit bằng 0 khi không thuộc tập',
                                    'tìm được nghiệm'])
def test_incidental_words_do_not_count_as_a_question(phrase):
    """Những cụm này từng làm dấu hiệu hỏi khớp nhầm."""
    assert _stem_asks_question(f'Cho một hệ thống. {phrase} theo quy ước.') is False


def test_validator_flags_a_stem_without_a_question():
    from pipeline.rule_validator import validate_candidate
    issues = validate_candidate({
        'question_text': 'Cho tập vũ trụ \(U\). Gọi \(A\) là tập các số lẻ.',
        'answer_text': '5',
        'answer_explanation_text': 'Đếm các số lẻ.',
        'source_quote_text': 'Tập hợp con của một tập hữu hạn.',
        'distractors': [{'distractor_text': str(i),
                         'distractor_explanation_text': 'sai'} for i in (3, 4, 6)],
    })
    assert 'stem_missing_question' in issues

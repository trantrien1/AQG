"""Đề dài không được mất câu hỏi khi đóng gói.

Run 2026-07-25: 6/89 câu giao ra có stem KHÔNG hỏi gì, một câu kết thúc bằng dấu
phẩy. Nguyên nhân: rule validator kiểm `question_text` GỐC (có câu hỏi, hợp lệ),
còn `_clean_stem_text` cắt bản HIỂN THỊ ở dấu câu cuối trước mốc 400 ký tự — và
mệnh đề hỏi luôn nằm cuối đề nên nó bị cắt trước tiên. Hai bên kiểm hai chuỗi
khác nhau nên không cổng nào bắt được.
"""
from __future__ import annotations

import pytest

from pipeline.rule_validator import _stem_asks_question
from pipeline.schema import _clean_stem_text

_LONG_STEM = (
    r'Một hệ thống máy tính dùng xâu bit để lưu quyền truy cập của các máy chủ '
    r'trong tập vũ trụ \(U=\{2,5,7,9,12,15,18,21,24,27\}\), với thứ tự phần '
    r'tử đúng như đã liệt kê và mỗi bit tương ứng một máy chủ theo đúng thứ tự '
    r'đó, trong đó bit bằng 1 nghĩa là máy chủ được cấp quyền truy cập, cho tập '
    r'\(A\) gồm các máy chủ có số hiệu chia hết cho 3, tập \(B\) gồm các máy '
    r'chủ có số hiệu mà khi cộng thêm 3 được một số chia hết cho 5, hãy xác định '
    r'xâu bit biểu diễn tập giao của \(A\) và \(B\).'
)


def test_long_stem_keeps_its_question():
    assert len(_LONG_STEM) > 400
    assert _stem_asks_question(_LONG_STEM)
    cleaned = _clean_stem_text(_LONG_STEM)
    assert _stem_asks_question(cleaned), (
        'đề dài bị cắt mất mệnh đề hỏi: ' + repr(cleaned[-70:])
    )


def test_cleaned_stem_never_ends_on_a_comma():
    """Kết thúc bằng dấu phẩy là chữ ký của việc bị cắt giữa chừng."""
    cleaned = _clean_stem_text(_LONG_STEM)
    assert not cleaned.rstrip().endswith(','), repr(cleaned[-70:])


@pytest.mark.parametrize('stem', [
    r'Tính \(\int_0^1 x^2\,dx\).',
    r'Giá trị của \(F(3)\) bằng bao nhiêu?',
    'Một bể chứa nước có thể tích ban đầu 20 m³. Hỏi sau 5 giờ còn bao nhiêu?',
])
def test_short_stems_keep_their_question(stem):
    """Đề ngắn giữ nguyên phần hỏi (cleaner vẫn được phép chuẩn hoá ký hiệu)."""
    cleaned = _clean_stem_text(stem)
    assert _stem_asks_question(cleaned)
    assert len(cleaned) >= len(stem) * 0.8


def test_stem_within_validator_limit_is_not_truncated():
    """Trần hiển thị phải khớp trần của validator (700), không phải 400."""
    stem = 'Cho hàm số. ' * 45 + r'Tính giá trị của \(F(3)\)?'
    assert 400 < len(stem) <= 700
    cleaned = _clean_stem_text(stem)
    assert _stem_asks_question(cleaned)

"""Rubric 19 lỗi soạn đề — mỗi luật phải bắt đúng lỗi của nó VÀ tha câu sạch.

Luật đo chất lượng mà sai thì tệ hơn không đo: nó tạo ra một con số trông có
thẩm quyền. Nên mỗi lỗi ở đây có cả ca dương và ca âm, và ca âm dùng câu hỏi
Toán thật lấy từ ngữ liệu đã sinh (nhiều LaTeX, nhiều đơn vị) — chính dạng dữ
liệu mà các luật đo độ dài/đếm từ dễ sai nhất.
"""
from __future__ import annotations

import pytest

from pipeline import iwf_rubric as R


def mcq(stem, options, key='D'):
    return {'stem': stem,
            'options': [{'key': k, 'text': t} for k, t in options],
            'answer_key': key}


CLEAN = mcq(
    'Một chất điểm chuyển động với vận tốc không đổi \\(v(t)=3\\,\\text{m/s}\\) '
    'trong \\(5\\) giây đầu tiên. Quãng đường đi được bằng bao nhiêu?',
    [('A', '\\(3\\,\\text{m}\\)'), ('B', '\\(8\\,\\text{m}\\)'),
     ('C', '\\(15\\,\\text{m}\\)'), ('D', '\\(45\\,\\text{m}\\)')],
    key='C')


# ------------------------------------------------------------ khung rubric
def test_rubric_has_exactly_nineteen_flaws():
    assert len(R.ALL_FLAWS) == 19
    assert len(R.RULE_FLAWS) == 14
    assert len(R.LLM_FLAWS) == 5
    assert not set(R.RULE_FLAWS) & set(R.LLM_FLAWS)


def test_acceptability_threshold_matches_the_rubric():
    """0–1 lỗi dùng được, từ 2 lỗi là không dùng được."""
    assert R.is_acceptable([])
    assert R.is_acceptable(['absolute_terms'])
    assert not R.is_acceptable(['absolute_terms', 'vague_terms'])


def test_a_real_generated_question_is_clean():
    assert R.rule_flaws(CLEAN) == []


def test_a_broken_rule_does_not_break_the_measurement():
    """Một luật ném lỗi thì bỏ qua luật đó, không làm hỏng cả câu."""
    assert R.rule_flaws({}) is not None


# --------------------------------------------------------- từng lỗi một
def test_none_of_the_above():
    q = mcq('Giá trị nào đúng?', [('A', '1'), ('B', '2'), ('C', '3'),
                                  ('D', 'Không có đáp án nào đúng')])
    assert 'none_of_the_above' in R.rule_flaws(q)
    assert 'none_of_the_above' not in R.rule_flaws(CLEAN)


def test_all_of_the_above():
    q = mcq('Mệnh đề nào đúng?', [('A', 'x>0'), ('B', 'y>0'), ('C', 'z>0'),
                                  ('D', 'Tất cả các đáp án trên')])
    assert 'all_of_the_above' in R.rule_flaws(q)


def test_longest_option_correct():
    q = mcq('Kết luận nào đúng?',
            [('A', 'Hàm đồng biến'), ('B', 'Hàm nghịch biến'),
             ('C', 'Hàm không đổi'),
             ('D', 'Hàm đồng biến trên khoảng âm và nghịch biến trên khoảng '
                   'dương, đạt cực đại tại điểm gốc toạ độ')])
    assert 'longest_option_correct' in R.rule_flaws(q)


def test_longest_option_correct_ignores_latex_wrapper_bulk():
    """Vỏ LaTeX dài không được tính là 'đáp án dài hơn'.

    \\(\\frac{115}{3}\\,\\text{m}\\) dài gấp ba '15 m' về ký tự thô mà nội dung
    thì tương đương — không bỏ vỏ thì luật này báo lỗi giả trên gần như mọi câu
    Toán.
    """
    q = mcq('Quãng đường bằng bao nhiêu?',
            [('A', '\\(8\\,\\text{m}\\)'), ('B', '\\(45\\,\\text{m}\\)'),
             ('C', '\\(3\\,\\text{m}\\)'),
             ('D', '\\(\\frac{115}{3}\\,\\text{m}\\)')])
    assert 'longest_option_correct' not in R.rule_flaws(q)


def test_true_false_question():
    q = mcq('Mệnh đề trên đúng hay sai?',
            [('A', 'Đúng'), ('B', 'Sai'), ('C', 'Đúng'), ('D', 'Sai')])
    assert 'true_false_question' in R.rule_flaws(q)


def test_complex_k_type():
    q = mcq('Cho các mệnh đề: (1) f đồng biến; (2) f có cực trị; '
            '(3) f bị chặn. Những mệnh đề nào đúng?',
            [('A', '(1) và (2)'), ('B', '(2) và (3)'), ('C', 'Chỉ (1)'),
             ('D', '(1), (2) và (3)')])
    assert 'complex_k_type' in R.rule_flaws(q)


def test_single_digit_answers_are_not_k_type():
    """Đáp số một chữ số là GIÁ TRỊ, không phải nhãn mệnh đề.

    Ca thật từ ngữ liệu: bốn phương án \\(2\\) \\(1\\) \\(4\\) \\(8\\) từng bị
    gắn nhầm K-type, và lỗi đó một mình thổi con số lên 10/89 câu.
    """
    q = mcq('Giá trị của tham số \\(m\\) bằng bao nhiêu?',
            [('A', '\\(2\\)'), ('B', '\\(1\\)'), ('C', '\\(4\\)'),
             ('D', '\\(8\\)')])
    assert 'complex_k_type' not in R.rule_flaws(q)


def test_k_type_needs_the_stem_to_enumerate():
    """Phương án trông như nhãn nhưng đề không đánh số thì không phải K-type."""
    q = mcq('Chọn phương án đúng.',
            [('A', '(1)'), ('B', '(2)'), ('C', '(3)'), ('D', '(4)')])
    assert 'complex_k_type' not in R.rule_flaws(q)


def test_fill_in_blank():
    q = mcq('Nguyên hàm của \\(f(x)=2x\\) là ______ cộng hằng số C.',
            [('A', 'x'), ('B', '2x'), ('C', '\\(x^3\\)'), ('D', '\\(x^2\\)')])
    assert 'fill_in_blank' in R.rule_flaws(q)


def test_trailing_ellipsis_is_not_a_blank():
    """Dấu ... dẫn ở cuối đề là cách viết bình thường, không phải khoét trống."""
    q = mcq('Tính tích phân sau...',
            [('A', '1'), ('B', '2'), ('C', '3'), ('D', '4')])
    assert 'fill_in_blank' not in R.rule_flaws(q)


def test_absolute_terms():
    q = mcq('Nhận định nào đúng?',
            [('A', 'Hàm số luôn luôn dương'), ('B', 'Hàm số nhận giá trị âm'),
             ('C', 'Hàm số không bao giờ bằng 0'), ('D', 'Hàm số đổi dấu')])
    assert 'absolute_terms' in R.rule_flaws(q)


def test_absolute_terms_only_flags_distractors():
    """Từ tuyệt đối ở ĐÁP ÁN ĐÚNG không phải manh mối loại trừ."""
    q = mcq('Nhận định nào đúng?',
            [('A', 'Hàm đổi dấu'), ('B', 'Hàm giảm'), ('C', 'Hàm tăng'),
             ('D', 'Hàm số luôn luôn dương')], key='D')
    assert 'absolute_terms' not in R.rule_flaws(q)


def test_vague_terms():
    q = mcq('Kết luận nào đúng?',
            [('A', 'Hàm số đôi khi tăng'), ('B', 'Hàm số tăng'),
             ('C', 'Hàm số giảm'), ('D', 'Hàm số không đổi')])
    assert 'vague_terms' in R.rule_flaws(q)


def test_word_repeats():
    q = mcq('Tính nguyên hàm của hàm số lượng giác đã cho.',
            [('A', '\\(x^2\\)'), ('B', '\\(2x\\)'), ('C', '\\(x^3\\)'),
             ('D', 'Nguyên hàm lượng giác')])
    assert 'word_repeats' in R.rule_flaws(q)


def test_word_repeats_not_flagged_when_shared_with_distractors():
    """Từ khoá lặp ở CẢ phương án sai thì không còn là manh mối."""
    q = mcq('Tính nguyên hàm của hàm số đã cho.',
            [('A', 'Nguyên hàm bậc nhất'), ('B', 'Nguyên hàm bậc hai'),
             ('C', 'Nguyên hàm bậc ba'), ('D', 'Nguyên hàm hằng')])
    assert 'word_repeats' not in R.rule_flaws(q)


def test_lost_sequence():
    q = mcq('Giá trị bằng bao nhiêu?',
            [('A', '\\(45\\)'), ('B', '\\(3\\)'), ('C', '\\(15\\)'),
             ('D', '\\(8\\)')])
    assert 'lost_sequence' in R.rule_flaws(q)


def test_lost_sequence_accepts_ordered_options():
    q = mcq('Giá trị bằng bao nhiêu?',
            [('A', '\\(3\\)'), ('B', '\\(8\\)'), ('C', '\\(15\\)'),
             ('D', '\\(45\\)')])
    assert 'lost_sequence' not in R.rule_flaws(q)


def test_lost_sequence_skips_non_numeric_options():
    q = mcq('Hàm nào đồng biến?',
            [('A', '\\(x^2\\)'), ('B', '\\(\\sin x\\)'), ('C', '\\(e^x\\)'),
             ('D', '\\(\\ln x\\)')])
    assert 'lost_sequence' not in R.rule_flaws(q)


def test_negative_worded():
    q = mcq('Mệnh đề nào sau đây KHÔNG ĐÚNG?',
            [('A', 'a'), ('B', 'b'), ('C', 'c'), ('D', 'd')])
    assert 'negative_worded' in R.rule_flaws(q)


def test_negation_in_the_data_is_not_a_negative_stem():
    """"Vận tốc KHÔNG đổi" là dữ kiện, không phải câu hỏi phủ định."""
    assert 'negative_worded' not in R.rule_flaws(CLEAN)


def test_unfocused_stem():
    q = mcq('Cho hàm số \\(f(x)=x^2\\),',
            [('A', '1'), ('B', '2'), ('C', '3'), ('D', '4')])
    assert 'unfocused_stem' in R.rule_flaws(q)


def test_opposite_set_relations_are_not_duplicates():
    """Ca thật từ ngữ liệu: hai quan hệ bao hàm NGƯỢC chiều không phải trùng.

    Nếu chuẩn hoá bằng cách xoá lệnh LaTeX thì \\(B\\subseteq A\\) và
    \\(A\\subseteq B\\) đều còn 'A B' — xoá toán tử là xoá đúng phần mang nghĩa.
    """
    q = mcq('Quan hệ nào giữa hai tập là đúng?',
            [('A', '\\(B\\subseteq A\\)'), ('B', '\\(A\\in B\\)'),
             ('C', '\\(A=B\\)'), ('D', '\\(A\\subseteq B\\)')])
    assert 'more_than_one_correct' not in R.rule_flaws(q)


def test_more_than_one_correct_by_duplicate_options():
    q = mcq('Giá trị bằng bao nhiêu?',
            [('A', '\\(15\\)'), ('B', '\\(15\\)'), ('C', '\\(3\\)'),
             ('D', '\\(8\\)')])
    assert 'more_than_one_correct' in R.rule_flaws(q)


def test_convergence_cues():
    q = mcq('Những khẳng định nào đúng?',
            [('A', 'tăng và lồi'), ('B', 'tăng và lõm'),
             ('C', 'tăng và bị chặn'), ('D', 'tăng và tuần hoàn')])
    assert 'convergence_cues' in R.rule_flaws(q)


# ------------------------------------------------- phần dành cho tầng LLM
def test_llm_flaws_are_declared_not_silently_passed():
    """5 lỗi cần phán đoán phải được KHAI BÁO, không được im lặng cho qua.

    Nếu chúng bị bỏ quên thì tỉ lệ 'chấp nhận được' sẽ đẹp lên một cách giả
    tạo, vì mẫu số vẫn là 19 lỗi mà thực tế chỉ kiểm 14.
    """
    defs = R.llm_flaw_definitions()
    assert set(defs) == set(R.LLM_FLAWS)
    assert all(v.strip() for v in defs.values())
    assert not set(defs) & set(R.RULE_FLAWS)


def test_every_flaw_has_a_description_for_the_judge_prompt():
    """Cả 19 lỗi phải có mô tả, không riêng 5 lỗi cần phán đoán.

    Đã xảy ra thật: prompt chỉ mô tả 5 lỗi, 14 lỗi còn lại đưa tên snake_case
    tiếng Anh trần. Mô hình phải tự đoán nghĩa, nên `lost_sequence` được nó gắn
    0/25 câu trong khi luật gắn 9/25 (kappa = 0), và `unfocused_stem` thì hai
    bên gắn hai câu KHÁC nhau (kappa âm). Phép so luật ↔ mô hình khi đó không
    đo độ đồng thuận mà đo việc mô hình có đoán trúng nghĩa cái tên hay không.
    """
    defs = R.flaw_definitions()
    assert set(defs) == set(R.ALL_FLAWS)
    assert list(defs) == list(R.ALL_FLAWS)
    for name, desc in defs.items():
        assert len(desc.strip()) >= 25, name

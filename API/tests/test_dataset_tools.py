"""Công cụ dựng dataset từ .docx: MathType -> LaTeX, TCVN3, tách câu hỏi."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'dataset', 'tools'))

import build_dataset as bd  # noqa: E402
import mtef  # noqa: E402
from docx_text import Para, tcvn3_to_unicode  # noqa: E402

# ---------------------------------------------------------------------------
# Dựng thân MTEF v5 bằng tay
# ---------------------------------------------------------------------------

HEADER = bytes([5, 1, 0, 6, 9]) + b'DSMT6\x00' + bytes([1])
END = bytes([0])
FN_VAR, FN_SYM, FN_NUM, FN_EXPAND, FN_FUNC, FN_TEXT = 3, 6, 8, 22, 2, 1


def char(c: str, typeface: int = FN_VAR) -> bytes:
    return bytes([2, 0, typeface + 128]) + struct.pack('<H', ord(c))


def line(*items: bytes) -> bytes:
    return bytes([1, 0]) + b''.join(items) + END


def null_line() -> bytes:
    return bytes([1, 0x01])


def tmpl(selector: int, variation: int, *items: bytes) -> bytes:
    return bytes([3, 0, selector, variation, 0]) + b''.join(items) + END


def latex(*items: bytes) -> str:
    return mtef.body_to_latex(HEADER + line(*items)).latex


def test_fraction_and_root():
    frac = tmpl(11, 0, line(char('1', FN_NUM)), line(char('2', FN_NUM)))
    root = tmpl(10, 0, line(char('x')), null_line())
    assert latex(frac) == r'\frac{1}{2}'
    assert latex(root) == r'\sqrt{x}'


def test_definite_integral_with_limits():
    # tvINT_1 | tvBO_LOWER | tvBO_UPPER; ký tự toán tử đứng sau các ô
    integral = tmpl(15, 0x31,
                    line(char('x'), char('d', FN_TEXT), char('x')),
                    line(char('0', FN_NUM)),
                    line(char('1', FN_NUM)),
                    char('∫', FN_SYM))
    assert latex(integral) == r'\int_{0}^{1} x\mathrm{d}x'


def test_integral_drawn_with_custom_operator_template():
    # tmINTOP: không có ký tự trong mẫu, toán tử nằm ở ô thứ tư
    op = tmpl(21, 0x30, null_line(), line(char('0', FN_NUM)),
              line(char('1', FN_NUM)), line(char('∫', FN_SYM)))
    assert latex(op) == r'\int\limits_{0}^{1}'


def test_absolute_value_uses_private_bar_glyphs():
    bars = tmpl(4, 3, line(char('x')),
                char('\uec07', FN_EXPAND), char('\uec08', FN_EXPAND))
    assert latex(bars) == r'\left| x \right|'


def test_system_with_left_brace_only():
    pile = bytes([4, 0, 1, 0]) + line(char('a')) + line(char('b')) + END
    brace = tmpl(2, 1, bytes([1, 0]) + pile + END, char('{', FN_EXPAND))
    assert latex(brace) == r'\left\{\begin{array}{l} a \\ b \end{array} \right.'


def test_function_names_and_superscript():
    sup = tmpl(28, 0, null_line(), line(char('2', FN_NUM)))
    out = latex(char('s', FN_FUNC), char('i', FN_FUNC), char('n', FN_FUNC),
                sup, char('x'))
    assert out == r'\sin ^{2}x'


def test_split_function_name_is_merged():
    assert mtef._tidy(r'-c\mathrm{ot}x') == r'-\cot x'
    assert mtef._tidy(r'\operatorname{s}\mathrm{inx}') == r'\sin x'
    assert mtef._tidy(r'd\mathrm{x}') == r'd\mathrm{x}'


def test_mtef_v3_is_reported_not_guessed():
    conv = mtef.body_to_latex(bytes([3, 1, 0, 0]))
    assert conv.latex is None and conv.error == 'mtef_v3'


def test_equation_embedded_in_wmf_picture():
    body = HEADER + line(char('y'), char('=', FN_SYM), char('2', FN_NUM))
    blob = b'Design Science, Inc.\x00' + body
    payload = (b'AppsMFCC' + struct.pack('<HII', 1, len(body), len(body))
               + blob)
    wmf = b'\xd7\xcd\xc6\x9a' + b'\x00' * 40 + payload + b'\x00' * 16
    assert mtef.picture_to_latex(wmf).latex == 'y=2'
    assert mtef.picture_to_latex(b'no equation here').latex is None


def test_truncated_body_is_an_error():
    conv = mtef.body_to_latex(HEADER + bytes([1, 0, 2, 0]))
    assert conv.latex is None and conv.error.startswith('parse')


# ---------------------------------------------------------------------------
# TCVN3
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('legacy,expected', [
    ('C©u 3. Mét nguyªn hµm cña hµm sè', 'Câu 3. Một nguyên hàm của hàm số'),
    ('Khi ®ã f(x) b»ng', 'Khi đó f(x) bằng'),
])
def test_tcvn3_to_unicode(legacy, expected):
    assert tcvn3_to_unicode(legacy) == expected


def test_tcvn3_uppercase_font():
    assert tcvn3_to_unicode('®Ò kiÓm tra', uppercase=True) == 'ĐỀ KIỂM TRA'


# ---------------------------------------------------------------------------
# Tách câu hỏi
# ---------------------------------------------------------------------------

def test_split_options_inline_and_ignores_letters_in_math():
    head, opts = bd.split_options(
        'Tính $I$. A. $x+A. B$ B. $2$ C. $3$. D. Đáp án khác.')
    assert head == 'Tính $I$. '
    assert opts == ['$x+A. B$', '$2$', '$3$', 'Đáp án khác']


def test_split_options_accepts_typo_in_last_label():
    _, opts = bd.split_options('A. 1\tB. 2\tC. 3\tC. 4')
    assert opts == ['1', '2', '3', '4']


def test_split_options_requires_order():
    assert bd.split_options('B. 1 A. 2 C. 3 D. 4') is None


def _paras(*texts, red=None):
    red = red or {}
    return [Para(t, red_letters=red.get(i, [])) for i, t in enumerate(texts)]


def test_segment_question_with_solution():
    paras = _paras(
        'DẠNG 1: TÍCH PHÂN CƠ BẢN',
        'Câu 1.\tTính $\\int_0^1 x\\,dx$.',
        'A. $1$.\tB. $\\frac{1}{2}$.',
        'C. $2$.\tD. $0$.',
        'Hướng dẫn giải',
        'Chọn B.   Ta có $\\int_0^1 x\\,dx=\\frac{1}{2}$.',
    )
    [raw] = bd.segment(paras)
    item = bd.finalize(raw, 'Tích phân', 'Cơ bản', 'f.docx').data
    assert item['question'] == 'Tính $\\int_0^1 x\\,dx$.'
    assert item['choices'] == ['A. $1$', 'B. $\\frac{1}{2}$', 'C. $2$', 'D. $0$']
    assert item['answer'] == 'B'
    assert item['answer_source'] == 'chon'
    assert item['solution'] == 'Ta có $\\int_0^1 x\\,dx=\\frac{1}{2}$.'
    assert item['section'] == 'DẠNG 1: TÍCH PHÂN CƠ BẢN'
    assert item['flags'] == []


def test_segment_exam_question_uses_red_letter():
    paras = _paras('Câu 7. Tính $2+2$ A. 3 B. 4 C. 5 D. 6', red={0: ['B']})
    [raw] = bd.segment(paras)
    item = bd.finalize(raw, 't', 's', 'f').data
    assert item['question'] == 'Tính $2+2$'
    assert item['answer'] == 'B'
    assert item['answer_source'] == 'red_mark'
    assert 'no_solution' in item['flags']


def test_red_letter_conflict_is_flagged_not_overridden():
    paras = _paras('Câu 1. Đề', 'A. 1 B. 2 C. 3 D. 4', 'Chọn A. vì...',
                   red={1: ['C']})
    item = bd.finalize(bd.segment(paras)[0], 't', 's', 'f').data
    assert item['answer'] == 'A'
    assert 'answer_conflict_red_C' in item['flags']


def test_solution_without_header_after_all_options():
    paras = _paras('Câu 2. Đề', 'A. 1 B. 2', 'C. 3 D. 4', 'Ta có lời giải.')
    item = bd.finalize(bd.segment(paras)[0], 't', 's', 'f').data
    assert item['choices'][-1] == 'D. 4'
    assert item['solution'] == 'Ta có lời giải.'
    assert 'no_answer' in item['flags']


def test_image_only_paragraph_goes_to_stem():
    paras = _paras('Câu 3. Đề', 'A. 1 B. 2 C. 3 D. 4', '[[HÌNH:image9.png]]',
                   'Hướng dẫn giải', 'Chọn D.')
    item = bd.finalize(bd.segment(paras)[0], 't', 's', 'f').data
    assert '[[HÌNH:image9.png]]' in item['question']
    assert item['answer'] == 'D'


def test_adjacent_formulas_keep_a_separator():
    assert bd.clean('$a\\Rightarrow$$f$') == '$a\\Rightarrow f$'


def test_duplicates_marked_across_files():
    a = {'id': 'x1', 'question': 'Đề  $\\left(x\\right)$', 'choices': ['A. 1'], 'flags': []}
    b = {'id': 'x2', 'question': 'Đề $(x)$', 'choices': ['A. 1'], 'flags': []}
    bd.mark_duplicates([a, b])
    assert a['duplicate_of'] is None
    assert b['duplicate_of'] == 'x1' and 'duplicate' in b['flags']


def _item(question, solution='', choices=None):
    return {'question': question, 'choices': choices or ['A. 1', 'B. 2', 'C. 3', 'D. 4'],
            'solution': solution, 'flags': []}


def test_figure_in_question_blocks_item():
    img = _item('Tính diện tích.\n![hình](images/a.png)')
    ref = _item('Cho đồ thị như hình vẽ. Tính $S$.')  # hình vẽ bằng shape, không có ảnh
    for it in (img, ref):
        bd.apply_figure_policy(it)
        it.update(answer='A', duplicate_of=None)
        assert 'figure_in_question' in it['flags']
        assert not bd.is_usable(it)


def test_illustration_only_in_solution_is_stripped():
    it = _item(r'Tính $\int_0^1 x\,dx$.', '![hình](images/b.png)\nTa có kết quả.')
    bd.apply_figure_policy(it)
    it['answer'] = 'A'
    assert it['solution'] == 'Ta có kết quả.'
    assert it['flags'] == ['figure_removed_from_solution']
    assert bd.is_usable(it)


def test_solution_relying_on_figure_blocks_item():
    it = _item('Tính $S$.', 'Từ hình vẽ ta có $S=2$.')
    bd.apply_figure_policy(it)
    assert it['flags'] == ['figure_in_solution']


def test_decomposed_vietnamese_still_matches_figure_reference():
    import unicodedata
    it = _item(bd.clean(unicodedata.normalize('NFD', 'Cho đồ thị như hình vẽ bên.')))
    bd.apply_figure_policy(it)
    assert it['flags'] == ['figure_in_question']


def test_next_exam_header_is_dropped_from_solution():
    paras = _paras('Câu 9. Đề', 'A. 1 B. 2 C. 3 D. 4',
                   'ĐỀ KIỂM TRA 279 (đề gồm 02 trang)', red={1: ['A']})
    item = bd.finalize(bd.segment(paras)[0], 't', 's', 'f').data
    assert item['solution'] == ''
    assert 'no_solution' in item['flags']


def _labeled(tmp_path, qnum='5'):
    (tmp_path / 'difficulty.tsv').write_text(
        'id\tfile\tquestion_number\tlevel\nq1\t3\t%s\tVDC\n' % qnum, encoding='utf-8')
    (tmp_path / 'review.tsv').write_text(
        'id\tfile\tquestion_number\tflag\tnote\nq1\t3\t%s\tkey_wrong\tđáp án đúng là B\n'
        % qnum, encoding='utf-8')
    it = _item('Đề')
    it.update(id='q1', answer='A', difficulty=None,
              source={'file': '3  NH.docx', 'question_number': 5})
    return it


def test_labels_set_difficulty_and_block_reviewed_items(tmp_path):
    it = _labeled(tmp_path)
    assert bd.apply_labels([it], tmp_path) == []
    assert it['difficulty'] == 'Vận dụng cao'
    assert it['difficulty_source'].startswith('claude')
    assert it['review_note'] == 'đáp án đúng là B'
    assert not bd.is_usable(it)


def test_labels_skipped_when_id_points_to_another_question(tmp_path):
    it = _labeled(tmp_path, qnum='6')
    warnings = bd.apply_labels([it], tmp_path)
    assert len(warnings) == 2
    assert it['difficulty'] is None and it['flags'] == []

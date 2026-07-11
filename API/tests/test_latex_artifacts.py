"""Test khử artifact LaTeX hiển thị: escape thừa, math span bị cắt cụt."""
from __future__ import annotations

from pipeline.parsing import (
    drop_orphan_math_closers,
    normalize_display_math,
    normalize_latex_escapes,
    trim_unclosed_math,
)
from pipeline.schema import _clean_display_text
from pipeline.direct_pdf.agents.pdf_critic_agent import _clean_rationale
from pipeline.direct_pdf.agents.pdf_orchestrator import DirectPdfOrchestrator


# ---- escape thừa \\( -> \( (lỗi option \\(\frac{1}{3}\\) trên UI) ----

def test_normalize_latex_escapes_collapses_runs():
    assert normalize_latex_escapes(r'\\(\frac{1}{3}\\)') == r'\(\frac{1}{3}\)'
    assert normalize_latex_escapes(r'\\\\(x^2\\\\)') == r'\(x^2\)'
    assert normalize_latex_escapes(r'\\[0,1\\]') == r'\[0,1\]'
    # khong dung cham escape don hop le
    assert normalize_latex_escapes(r'\(x\)') == r'\(x\)'
    assert normalize_latex_escapes(r'\frac{1}{2}') == r'\frac{1}{2}'


def test_normalize_display_math_fixes_double_escaped_stem():
    got = normalize_display_math(r'Tính \\(I=\int_0^1 x^2\,dx\\).')
    assert r'\\(' not in got and r'\\)' not in got
    assert r'\(I=' in got and r'dx\)' in got
    # khong con backslash mo coi trong span
    assert r'\ \)' not in got and not got.rstrip('.').endswith('\\')


def test_normalize_display_math_fixes_double_escaped_option():
    got = normalize_display_math(r'\\(\frac{1}{3}\\)')
    assert got == r'\(\frac{1}{3}\)'


# ---- math span bị cắt cụt (cap độ dài cắt giữa \( ... ) ----

def test_trim_unclosed_math_drops_partial_span():
    assert trim_unclosed_math(r'dùng sai cận, lấy \(0\le x') == 'dùng sai cận, lấy'
    assert trim_unclosed_math(r'kết quả \(x=2\) đúng') == r'kết quả \(x=2\) đúng'
    assert trim_unclosed_math('text sạch không toán') == 'text sạch không toán'
    assert trim_unclosed_math(r'tàn dư \\') == 'tàn dư'


def test_clean_display_text_cap_does_not_leave_unbalanced_math():
    # đoạn dài: phần đầu là chữ, công thức nằm vắt qua ranh giới cắt
    text = ('Học sinh dùng sai cận tích phân khi tính tổng chi phí trên toàn '
            'miền sản xuất cho phép, cụ thể là ' + r'\(0\le x\le 100\)' + ' thay vì '
            + r'\(0\le x\le 50\)' + ', dẫn tới kết quả lớn gấp đôi giá trị đúng '
            'và không khớp với bất kỳ phương án nào trong bốn lựa chọn đã cho.')
    got = _clean_display_text(text, max_len=100)
    assert got.count(r'\(') == got.count(r'\)'), got
    assert len(got) <= 110


def test_explanation_short_does_not_cut_mid_math():
    from pipeline.explanation import _short
    text = ('Khối tròn xoay có thể tích được tính bằng công thức tích phân của '
            'bình phương bán kính mặt cắt. Với bán kính ' + r'\(r=x^2\)' + ' trên đoạn '
            + r'\([0;1]\)' + ', ta tính được ' + r'\(V=\pi\int_0^1x^4dx=\frac{\pi}{5}\)'
            + ', xấp xỉ ' + r'\(0.63\)' + ' đơn vị thể tích.')
    got = _short(text, max_len=200)
    assert got.count(r'\(') == got.count(r'\)'), got


# ---- '\)' đóng thừa ngoài span (job 09eb7fcd15: '...\frac{x^2}{4}\)\)') ----

def test_drop_orphan_math_closers_removes_double_close():
    assert drop_orphan_math_closers(r'\(x^2\)\) và \(Ox\)\)') == r'\(x^2\) và \(Ox\)'
    # giữ nguyên text cân bằng
    assert drop_orphan_math_closers(r'\(a\) rồi \(b\)') == r'\(a\) rồi \(b\)'
    assert drop_orphan_math_closers('không có toán') == 'không có toán'


def test_normalize_display_math_fixes_double_close_stem():
    stem = (r'miền giới hạn bởi \(y=4-\frac{x^2}{4}\)\) và trục hoành trên đoạn '
            r'\(-4\le x\le4\). Khi quay quanh trục \(Ox\)\), thể tích bằng bao nhiêu?')
    got = normalize_display_math(stem)
    assert got.count(r'\(') == got.count(r'\)'), got
    assert r'\)\)' not in got


# ---- rationale của Critic (hiển thị màn chi tiết) ----

def test_clean_rationale_normalizes_and_balances():
    got = _clean_rationale(r'Chỉ \\(\frac{768}{5}\\,m^3\\) phù hợp')
    assert r'\\(' not in got and got.count(r'\(') == got.count(r'\)')
    long = 'x' * 290 + r' \(a+b'
    got2 = _clean_rationale(long)
    assert got2.count(r'\(') == got2.count(r'\)')


# ---- verified=False -> giữ câu nhưng needs_revision (duyệt tay) ----

def _mini_candidate(verified):
    return {
        'question_text': 'Tính \\(I=\\int_0^1 x\\,dx\\).',
        'answer_text': '\\(\\frac{1}{2}\\)',
        'answer_explanation_text': 'Nguyên hàm x^2/2, thế cận được 1/2.',
        'source_quote_text': 'Tích phân hàm lũy thừa.',
        'distractors': [
            {'distractor_text': '1', 'distractor_category_text': 'e1',
             'distractor_explanation_text': 'Quên chia 2.'},
            {'distractor_text': '2', 'distractor_category_text': 'e2',
             'distractor_explanation_text': 'Nhân đôi.'},
            {'distractor_text': '0', 'distractor_category_text': 'e3',
             'distractor_explanation_text': 'Thế nhầm cận.'},
        ],
        '_verification': {'engine': 'numeric_eval', 'verified': verified,
                          'detail': 'expr = 0.5'},
    }


def _mini_slot():
    return {'slot_id': 's1', 'cognitive_level': 'Thông hiểu',
            'difficulty_target': 0.5, 'topic': '', 'question_pattern': 'conceptual',
            'skill': '', 'expected_question_type': 'single_choice', 'doc_id': None}


def test_verified_false_record_flagged_needs_revision():
    from pipeline.schema import to_question_record
    rec = to_question_record(_mini_slot(), _mini_candidate(False))
    assert rec['review_status'] == 'needs_revision'
    assert 'verifier_numeric_mismatch' in rec['review']['issues']


def test_verified_true_record_stays_pending_review():
    from pipeline.schema import to_question_record
    rec = to_question_record(_mini_slot(), _mini_candidate(True))
    assert rec['review_status'] == 'pending_review'


def test_formatter_keeps_needs_revision_for_verified_false():
    from pipeline.agents.formatter_agent import FormatterAgent
    from pipeline.agents.messages import FormatAcceptedRequest
    cand = _mini_candidate(False)
    cand['_quality'] = 0.9
    cand['_grounding'] = 0.9
    resp = FormatterAgent(use_skills=False).run(FormatAcceptedRequest(
        slot=_mini_slot(), candidate=cand, doc={}, attempts=1))
    assert resp.record['review_status'] == 'needs_revision'
    assert 'verifier_numeric_mismatch' in resp.record['review']['issues']
    # KHÔNG cap quality: câu có thể vẫn đúng (hint lệch), giữ điểm xếp hạng.
    assert resp.record['judging']['quality'] == 0.9


# ---- critic không bị ghi đè model bằng generator model ----

def test_orchestrator_generate_does_not_override_critic_model():
    from pipeline import config as cfg
    orch = DirectPdfOrchestrator(model='gpt-4o', use_skills=False)
    judge_before = orch.critic.model
    assert judge_before == cfg.JUDGE_MODEL
    # requested_count=0 + attachment giả -> generate() thoát ngay trước khi
    # gọi LLM; chỉ cần kiểm tra bước gán model đầu hàm không đụng critic.
    result = orch.generate(
        pdf_path='unused.pdf', requested_count=0, model='gpt-4o',
        attachment_parts=[{'type': 'image_url', 'image_url': {'url': 'data:'}}],
    )
    assert result.accepted_count == 0
    assert orch.critic.model == judge_before
    assert orch.writer.model == 'gpt-4o'

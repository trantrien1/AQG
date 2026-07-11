"""Test 3 fix sau lượt chạy thật 2 file PDF (2026-07-08):

1. numeric_eval nhận alias cho `expr` (expression/formula/...) — trước đây
   KeyError 'expr' làm verifier fallback và formatter cap quality=0.5 oan.
2. _parse_critic chịu lỗi JSON cụt (hết max_tokens giữa chừng) — vớt các
   trait đã chấm xong thay vì rơi toàn bộ về trung tính 0.6.
3. rule_validator bắt "đề cụt" — stem đủ dữ kiện nhưng thiếu câu hỏi.

Không gọi LLM.
"""
from __future__ import annotations

from pipeline.verifier import verify
from pipeline.agents.verifier_agent import (
    _expected_from_answer,
    _normalize_hint_schema,
)
from pipeline.direct_pdf.agents.pdf_critic_agent import (
    _parse_critic,
    _salvage_trait_blocks,
)
from pipeline.rule_validator import _stem_asks_question, validate_candidate


# ---- Fix 1: numeric_eval alias ----

def test_numeric_eval_accepts_expression_alias():
    res = verify({'type': 'numeric_eval',
                  'payload': {'expression': '2 + 3*4', 'expected_numeric': 14}})
    assert res.verified is True


def test_numeric_eval_missing_expr_returns_clean_none():
    res = verify({'type': 'numeric_eval', 'payload': {'expected_numeric': 7}})
    assert res.verified is None
    assert res.detail == 'missing expr'


def test_normalize_hint_schema_maps_expr_aliases():
    hint = _normalize_hint_schema({
        'type': 'numeric_eval',
        'payload': {'formula': 'integrate(6*t - 4, (t, 0, 2)) + 3',
                    'expected_numeric': 7},
    })
    assert hint['payload']['expr'] == 'integrate(6*t - 4, (t, 0, 2)) + 3'
    res = verify(hint)
    assert res.verified is True


# ---- Fix 1b: đơn vị LaTeX có số mũ trong answer_text ----
# Lượt chạy 2026-07-08: "\(128\,\text{m}^3\)" bị đọc thành 128**3 (strip
# \text{m} để sót ^3) -> answer_text_mismatch reject oan 3 câu đúng.

def test_expected_from_answer_latex_volume_units():
    assert _expected_from_answer(r'\(128\,\text{m}^3\)') == 128
    assert abs(_expected_from_answer(r'\(\frac{140}{3}\,m^3\)') - 140 / 3) < 1e-9
    assert abs(_expected_from_answer(r'\(\frac{320}{3}\,m^3\)') - 320 / 3) < 1e-9


def test_expected_from_answer_regressions_still_pass():
    assert _expected_from_answer('600.000 đồng') == 600000
    assert _expected_from_answer('46,67') == 46.67
    assert _expected_from_answer('2^10') == 1024  # lũy thừa thật không bị xoá
    assert _expected_from_answer(r'\(45\,\text{m}^2\)') == 45
    assert _expected_from_answer('5 m/s') == 5


# ---- Fix 1c: \pi đứng sau '}' / ')' (job 18ddf54621 câu 4, 2026-07-11) ----
# "\frac{81}{10}\pi" bị đọc thành 81 (thiếu nhân tường minh -> sympify fail,
# fallback vớ số đầu tiên) -> multi_answer check không thấy option trùng
# GIÁ TRỊ đáp án "\frac{81\pi}{10}" viết khác dạng.

def test_expected_from_answer_pi_ngoai_frac():
    import math
    assert abs(_expected_from_answer(r'\(\frac{81}{10}\pi\)') - 8.1 * math.pi) < 1e-9
    assert abs(_expected_from_answer(r'\(\frac{81\pi}{10}\)') - 8.1 * math.pi) < 1e-9


def test_verify_distractor_bat_option_trung_gia_tri_khac_dang():
    import copy
    from pipeline.verifier import verify_distractor
    hint = {'type': 'numeric_eval',
            'payload': {'expr': 'pi*integrate((-x**2+7*x-10)**2, (x, 2, 5))',
                        'expected_numeric': 25.446900494077323}}
    # cùng giá trị 81π/10, hai cách viết -> multi_answer True (bị loại)
    assert verify_distractor(copy.deepcopy(hint), r'\(\frac{81}{10}\pi\)') is True
    assert verify_distractor(copy.deepcopy(hint), r'\(\frac{81\pi}{10}\)') is True
    # distractor sai thật -> False (không reject oan)
    assert verify_distractor(copy.deepcopy(hint), r'\(\frac{81\pi}{4}\)') is False
    assert verify_distractor(copy.deepcopy(hint), r'\(\frac{6981}{10}\pi\)') is False


# ---- Fix 2: critic JSON cụt ----

_TRUNCATED = '''{
  "grounding": {"rationale": "cong thuc co trong PDF", "score": 0.9},
  "clarity": {"rationale": "de ro rang", "score": 0.95},
  "cognitive_depth": {"rationale": "nhieu buoc \\\\(\\\\frac{a}{b}\\\\)", "score": 0.8},
  "bloom_alignment": {"rationale": "dung muc Van dung", "score": 0.85},
  "distractor_plausibility": {"rationale": "loi gan misconception", "sco'''


def test_salvage_trait_blocks_recovers_complete_traits():
    obj = _salvage_trait_blocks(_TRUNCATED)
    assert obj['grounding']['score'] == 0.9
    assert obj['clarity']['score'] == 0.95
    assert obj['cognitive_depth']['score'] == 0.8
    assert obj['bloom_alignment']['score'] == 0.85
    # Khối bị cụt giữa "score" -> không vớt, không bịa.
    assert 'distractor_plausibility' not in obj


def test_parse_critic_survives_truncated_json():
    grounding, rationale, traits, quality = _parse_critic(_TRUNCATED)
    assert grounding == 0.9
    assert rationale == 'cong thuc co trong PDF'
    assert traits['clarity']['score'] == 0.95
    assert traits['bloom_alignment']['score'] == 0.85
    # Trait mất do cụt nhận 0.5 trung tính, không kéo cả bộ về 0.6.
    assert traits['distractor_plausibility']['score'] == 0.5
    assert traits['error_distractor_consistency']['score'] == 0.5
    expected = (0.95 + 0.8 + 0.85 + 0.5 + 0.5 + 0.5) / 6
    assert abs(quality - expected) < 1e-9


def test_parse_critic_still_handles_wellformed_json():
    raw = ('```json\n{"grounding": {"rationale": "ok", "score": 0.7},'
           ' "clarity": {"rationale": "ok", "score": 0.6}}\n```')
    grounding, _, traits, _ = _parse_critic(raw)
    assert grounding == 0.7
    assert traits['clarity']['score'] == 0.6


# ---- Fix 3: đề cụt ----

def test_stem_asks_question_accepts_real_stems():
    assert _stem_asks_question('Giá trị của tích phân bằng bao nhiêu?')
    assert _stem_asks_question('Tính quãng đường ô tô đi được trong 8 giây.')
    assert _stem_asks_question('Tìm họ nguyên hàm của hàm số f(x)=x^4.')
    assert _stem_asks_question('Trong kí hiệu tích phân, cận dưới là số nào?')


def test_stem_missing_question_flagged():
    # Stem thật từ lượt chạy 2026-07-08: đủ dữ kiện nhưng không hỏi gì.
    broken = ('Một mô hình đường hầm dài 12 cm. Thiết diện là một hình parabol '
              'có chiều cao h(x)=4-x/4 cm và độ dài đáy gấp đôi chiều cao. '
              'Mô hình được chế tạo theo tỉ lệ 1:200 so với đường hầm thật.')
    assert not _stem_asks_question(broken)
    candidate = {
        'question_text': broken,
        'answer_text': '1075,2',
        'answer_explanation_text': 'Thể tích mô hình là 112 cm3.',
        'source_quote_text': 'trích dẫn',
        'distractors': [
            {'distractor_text': '806,4'},
            {'distractor_text': '1075200000'},
            {'distractor_text': '0,02688'},
        ],
    }
    assert 'stem_missing_question' in validate_candidate(candidate)

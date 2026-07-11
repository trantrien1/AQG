"""Test error-first distractor (misconception bank trong prompt) và trait
`error_distractor_consistency` của PdfCriticAgent. Không gọi LLM."""
from __future__ import annotations

import json

from pipeline.direct_pdf.agents.messages import PdfDistractorRequest
from pipeline.direct_pdf.agents.pdf_distractor_agent import (
    PdfDistractorAgent,
    _misconception_block,
    _missing_error_fields,
)
from pipeline.direct_pdf.agents.pdf_critic_agent import _TRAIT_KEYS, _parse_critic


_DERIVATIVE_CANDIDATE = {
    'question_text': 'Tính đạo hàm của hàm hợp y = sin(3x^2 + 1).',
    'answer_text': '\\(6x\\cos(3x^2+1)\\)',
    'answer_explanation_text': 'Áp dụng quy tắc dây chuyền cho hàm hợp sin(u).',
    'why_correct': 'Đạo hàm hàm hợp: nhân với đạo hàm hàm trong.',
}
_SLOT = {'slot_id': 'direct_pdf_0', 'topic': '', 'cognitive_level': 'Vận dụng'}


def test_misconception_block_matches_topic_and_is_deterministic():
    block = _misconception_block(_DERIVATIVE_CANDIDATE, _SLOT)
    # Có ít nhất một misconception về đạo hàm được chọn theo keyword match.
    assert 'missing_chain_rule_factor' in block or 'đạo hàm' in block.lower()
    # Format từng dòng: - [id] wrong_form — rationale
    assert block.startswith('- [')
    # Cùng candidate -> cùng danh sách (seed CRC32 theo nội dung).
    assert block == _misconception_block(_DERIVATIVE_CANDIDATE, _SLOT)


def test_distractor_prompt_contains_bank_and_error_first_process():
    agent = PdfDistractorAgent(use_skills=False)
    prompt = agent._user_prompt(PdfDistractorRequest(
        attachment_parts=[], candidate=_DERIVATIVE_CANDIDATE, slot=_SLOT,
    ))
    assert 'misconception bank' in prompt
    assert 'ERROR-FIRST' in prompt
    assert 'distractor_category_text' in prompt
    # Phần lõi MCQ vẫn được nhúng nguyên vẹn.
    assert _DERIVATIVE_CANDIDATE['question_text'] in prompt
    # Danh sách misconception thật sự xuất hiện (dòng dạng "- [id] ...").
    assert '- [' in prompt


def test_missing_error_fields_flags_empty_explanations():
    distractors = [
        {'distractor_text': 'A', 'distractor_explanation_text': 'quên nhân 6x'},
        {'distractor_text': 'B', 'distractor_explanation_text': ''},
        {'distractor_text': 'C'},
    ]
    assert _missing_error_fields(distractors) == [1, 2]
    assert _missing_error_fields([
        {'distractor_text': 'A', 'distractor_explanation_text': 'lỗi dấu'},
    ]) == []


def test_critic_traits_include_error_distractor_consistency():
    assert 'error_distractor_consistency' in _TRAIT_KEYS


def test_parse_critic_reads_consistency_score():
    raw = json.dumps({
        'grounding': {'rationale': 'ok', 'score': 0.9},
        'clarity': {'rationale': 'ok', 'score': 0.8},
        'cognitive_depth': {'rationale': 'ok', 'score': 0.8},
        'bloom_alignment': {'rationale': 'ok', 'score': 0.8},
        'distractor_plausibility': {'rationale': 'ok', 'score': 0.8},
        'answer_uniqueness': {'rationale': 'ok', 'score': 1.0},
        'error_distractor_consistency': {
            'rationale': 'distractor B không suy ra từ lỗi mô tả', 'score': 0.2},
    })
    grounding, _, traits, quality = _parse_critic(raw)
    assert grounding == 0.9
    assert traits['error_distractor_consistency']['score'] == 0.2
    # quality là mean của 6 traits (không gồm grounding).
    expected = (0.8 + 0.8 + 0.8 + 0.8 + 1.0 + 0.2) / 6
    assert abs(quality - expected) < 1e-9


def test_parse_critic_defaults_missing_consistency_to_neutral():
    # Model cũ/parse thiếu key mới -> 0.5 trung tính, không crash.
    raw = json.dumps({
        'grounding': {'rationale': 'ok', 'score': 0.9},
        'clarity': {'rationale': 'ok', 'score': 0.8},
    })
    _, _, traits, _ = _parse_critic(raw)
    assert traits['error_distractor_consistency']['score'] == 0.5

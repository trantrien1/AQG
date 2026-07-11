"""Test tổng hợp phản hồi người dùng thành hồ sơ sở thích (không gọi LLM)."""
from __future__ import annotations

from pipeline.feedback import build_guidance, normalize_entry, normalize_feedback


def _fb(**kw):
    base = {'question_id': 'q1', 'rating': 'down', 'tags': [], 'comment': ''}
    base.update(kw)
    return base


# ---- normalize ----

def test_normalize_entry_requires_qid_and_rating():
    assert normalize_entry({'question_id': '', 'rating': 'up'}) is None
    assert normalize_entry({'question_id': 'q1', 'rating': 'meh'}) is None
    assert normalize_entry('not a dict') is None
    entry = normalize_entry(_fb(rating='UP', tags=['too_easy', 'too_easy', ' '],
                                comment='  ok  '))
    assert entry['rating'] == 'up'
    assert entry['tags'] == ['too_easy']          # dedup + bỏ rỗng
    assert entry['comment'] == 'ok'


def test_normalize_feedback_filters_invalid():
    items = [_fb(), {'rating': 'down'}, None, _fb(question_id='q2', rating='up')]
    out = normalize_feedback(items)
    assert [e['question_id'] for e in out] == ['q1', 'q2']


# ---- build_guidance (deterministic, use_llm=False) ----

def test_build_guidance_empty():
    assert build_guidance([]) == ''
    assert build_guidance(None) == ''
    assert build_guidance('garbage') == ''


def test_build_guidance_maps_tags_to_directives():
    items = [
        _fb(question_id='q1', tags=['too_easy']),
        _fb(question_id='q2', tags=['too_easy', 'bad_distractors']),
        _fb(question_id='q3', rating='up', tags=['good_context']),
    ]
    g = build_guidance(items, use_llm=False)
    assert 'QUÁ DỄ' in g and '(x2)' in g          # đếm tag lặp
    assert 'nhiễu' in g.lower()                    # bad_distractors
    assert 'ngữ cảnh thực tế' in g                 # like directive


def test_build_guidance_lists_liked_and_disliked_stems():
    items = [
        _fb(question_id='q1', rating='up', stem='Tính tích phân của x^2 trên [0;1]'),
        _fb(question_id='q2', rating='down', tags=['unclear'],
            stem='Một câu hỏi rất mơ hồ nào đó'),
    ]
    g = build_guidance(items, use_llm=False)
    assert 'THÍCH' in g and 'Tính tích phân của x^2' in g
    assert 'CHÊ' in g and 'mơ hồ' in g and 'đề khó hiểu' in g


def test_build_guidance_includes_raw_comments_without_llm():
    items = [_fb(comment='Muốn nhiều bài toán thực tế hơn')]
    g = build_guidance(items, use_llm=False)
    assert 'Muốn nhiều bài toán thực tế hơn' in g


def test_build_guidance_respects_max_chars():
    items = [_fb(question_id=f'q{i}', stem='dài ' * 60, tags=['duplicate'])
             for i in range(20)]
    g = build_guidance(items, use_llm=False, max_chars=500)
    assert len(g) <= 500


def test_build_guidance_unknown_tag_passthrough():
    g = build_guidance([_fb(tags=['weird_tag'])], use_llm=False)
    assert 'weird_tag' in g

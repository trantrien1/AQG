"""Regression: strip ChatGPT/chat2api citation markers from LLM responses.

Found 2026-07-10 khi chuyển provider sang chat2api (gửi PDF dạng image_url
data URI): response chứa block Private-Use-Area
fileciteturn0file0L1-L2 — nếu không lọc sẽ lọt vào
stem/option/JSON của câu hỏi sinh ra.
"""
from __future__ import annotations

from pipeline.llm_client import _strip_provider_artifacts


def test_strips_citation_block():
    raw = ('Tài liệu trình bày định lý: đạo hàm của \\(x^2\\) bằng \\(2x\\). '
           'fileciteturn0file0L1-L2')
    assert _strip_provider_artifacts(raw) == (
        'Tài liệu trình bày định lý: đạo hàm của \\(x^2\\) bằng \\(2x\\). '
    )


def test_strips_stray_pua_chars():
    assert _strip_provider_artifacts('abc') == 'abc'


def test_plain_text_unchanged():
    s = 'Không có marker nào ở đây — kể cả tiếng Việt có dấu.'
    assert _strip_provider_artifacts(s) == s
    assert _strip_provider_artifacts('') == ''

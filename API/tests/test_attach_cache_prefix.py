"""Tài liệu phải đứng TRƯỚC prompt thì tiền tố mới cache được.

Prompt đổi theo từng lời gọi (số câu, Bloom, phản hồi vòng trước). Đặt nó trước
tài liệu thì mỗi lời gọi có một tiền tố khác nhau và không cache được gì — mà
tài liệu chính là phần lặp lớn nhất: nó đi kèm cả bốn lời gọi của mỗi câu và mọi
câu trong một lượt chạy. Đo thực tế trên OpenRouter: 127.616 -> ~10.300 token
mỗi lời gọi ở chế độ đính file.

Chế độ ảnh còn nặng hơn (mỗi trang một ảnh), nên phải có cùng cách sắp xếp.
"""
from __future__ import annotations

import base64

import pytest

from pipeline.direct_pdf.attach import (
    PdfAttachError,
    build_pdf_image_content,
    build_pdf_user_content,
)

pytest.importorskip('fitz')


def _one_page_pdf(pages: int = 2) -> bytes:
    import fitz
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f'trang {i + 1}')
    data = doc.tobytes()
    doc.close()
    return data


# ------------------------------------------------------------ chế độ đính file
def test_file_mode_puts_the_document_first_when_caching():
    parts = build_pdf_user_content(b'%PDF-1.4 x', 'a.pdf', 'PROMPT',
                                   pdf_first=True, cache_control=True)
    assert [p['type'] for p in parts] == ['file', 'text']
    assert parts[0]['cache_control'] == {'type': 'ephemeral'}


def test_file_mode_keeps_the_old_order_by_default():
    """Đường chat2api đã sinh ra ngữ liệu hiện có — không đổi hành vi của nó."""
    parts = build_pdf_user_content(b'%PDF-1.4 x', 'a.pdf', 'PROMPT')
    assert [p['type'] for p in parts] == ['text', 'file']
    assert 'cache_control' not in parts[0]


# --------------------------------------------------------------- chế độ ảnh
def test_image_mode_puts_every_page_before_the_prompt_when_caching():
    parts = build_pdf_image_content(_one_page_pdf(3), 'a.pdf', 'PROMPT',
                                    dpi=36, images_first=True,
                                    cache_control=True)
    assert [p['type'] for p in parts] == ['image_url'] * 3 + ['text']
    assert parts[-1]['text'] == 'PROMPT'


def test_image_mode_marks_the_cache_breakpoint_on_the_last_page_only():
    """Điểm cắt đặt ở ảnh cuối: mọi thứ trước nó là tiền tố dùng lại được."""
    parts = build_pdf_image_content(_one_page_pdf(3), 'a.pdf', 'PROMPT',
                                    dpi=36, images_first=True,
                                    cache_control=True)
    images = [p for p in parts if p['type'] == 'image_url']
    assert 'cache_control' not in images[0]
    assert 'cache_control' not in images[1]
    assert images[-1]['cache_control'] == {'type': 'ephemeral'}


def test_image_mode_keeps_the_old_order_by_default():
    parts = build_pdf_image_content(_one_page_pdf(2), 'a.pdf', 'PROMPT', dpi=36)
    assert parts[0]['type'] == 'text'
    assert all(p['type'] == 'image_url' for p in parts[1:])
    assert all('cache_control' not in p for p in parts)


def test_image_mode_still_renders_every_page_in_cache_order():
    plain = build_pdf_image_content(_one_page_pdf(4), 'a.pdf', 'P', dpi=36)
    cached = build_pdf_image_content(_one_page_pdf(4), 'a.pdf', 'P', dpi=36,
                                     images_first=True, cache_control=True)
    assert len(plain) == len(cached) == 5


def test_image_mode_honours_the_page_limit():
    parts = build_pdf_image_content(_one_page_pdf(5), 'a.pdf', 'P', dpi=36,
                                    max_pages=2, images_first=True)
    assert sum(1 for p in parts if p['type'] == 'image_url') == 2


def test_image_mode_pages_are_real_png_data_uris():
    parts = build_pdf_image_content(_one_page_pdf(1), 'a.pdf', 'P', dpi=36,
                                    images_first=True)
    url = parts[0]['image_url']['url']
    assert url.startswith('data:image/png;base64,')
    assert base64.b64decode(url.split(',', 1)[1])[:8] == b'\x89PNG\r\n\x1a\n'


def test_empty_pdf_still_raises_in_cache_order():
    with pytest.raises(PdfAttachError):
        build_pdf_image_content(b'', 'a.pdf', 'P', images_first=True,
                                cache_control=True)

"""Đính kèm PDF nguyên bản vào message user (Req 2).

Hai chiến lược đính kèm, đều KHÔNG trích xuất text từ PDF (Req 2.2):

1. `build_pdf_user_content` — part text + part file (PDF base64, data URI
   application/pdf). Dùng cho provider hỗ trợ đầu vào file trực tiếp.
2. `build_pdf_image_content` — part text + mỗi trang PDF render thành ảnh PNG
   đính kèm dạng `image_url`. Dùng cho provider chỉ hỗ trợ vision/ảnh (ví dụ
   gateway 9router local: chặn file PDF nhưng forward image_url). Giữ nguyên
   layout/công thức/bảng của tài liệu, không OCR/không trích text.
"""
from __future__ import annotations

import base64
from typing import Dict, List


class PdfAttachError(Exception):
    """PDF bytes rỗng hoặc không encode/không render được (Req 2.3)."""


def build_pdf_user_content(
    pdf_bytes: bytes,
    filename: str,
    prompt_text: str,
    as_image_url: bool = False,
    pdf_first: bool = False,
    cache_control: bool = False,
) -> List[Dict]:
    """Trả về `content` cho message user.

    - part text: prompt_text (yêu cầu số câu, Bloom, schema JSON).
    - part file: PDF nguyên bản encode base64 dưới data URI application/pdf.
      `as_image_url=True` bọc data URI trong part `image_url` thay vì part
      `file` — format mà các gateway kiểu chat2api nhận file (mọi loại file
      đều đi qua image_url với mime tương ứng).

    Không trích xuất/không cắt text từ PDF (Req 2.2). Raise `PdfAttachError` nếu
    `pdf_bytes` rỗng hoặc không encode được (Req 2.3).
    """
    if not pdf_bytes:
        raise PdfAttachError('PDF bytes rỗng — không thể đính kèm.')
    try:
        b64 = base64.b64encode(pdf_bytes).decode('ascii')
    except Exception as e:  # pragma: no cover - base64 hiếm khi lỗi
        raise PdfAttachError(f'Không thể encode PDF sang base64: {e}') from e

    data_uri = f'data:application/pdf;base64,{b64}'
    if as_image_url:
        pdf_part: Dict = {'type': 'image_url', 'image_url': {'url': data_uri}}
    else:
        pdf_part = {
            'type': 'file',
            'file': {
                'filename': filename,
                'file_data': data_uri,
            },
        }
    if cache_control:
        # Đánh dấu tài liệu là phần được cache. Nhà nào không hiểu thì bỏ qua.
        pdf_part['cache_control'] = {'type': 'ephemeral'}
    text_part = {'type': 'text', 'text': prompt_text}
    # Tài liệu ĐỨNG TRƯỚC prompt khi bật cache: prompt đổi theo từng lời gọi,
    # nên để nó trước thì tiền tố không còn ổn định và không cache được gì.
    # Cùng một tài liệu đi kèm 4 lời gọi mỗi câu và mọi câu trong một lượt chạy,
    # nên đây là phần lặp lớn nhất của toàn bộ chi phí.
    return [pdf_part, text_part] if pdf_first else [text_part, pdf_part]


def build_pdf_image_content(
    pdf_bytes: bytes,
    filename: str,
    prompt_text: str,
    dpi: int = 120,
    max_pages: int = 0,
    images_first: bool = False,
    cache_control: bool = False,
) -> List[Dict]:
    """Render mỗi trang PDF thành ảnh PNG rồi đính kèm dạng `image_url`.

    - part text: prompt_text.
    - mỗi trang PDF -> một part `image_url` (PNG base64 data URI).

    Không OCR, không trích xuất text — giữ nguyên hình ảnh trang tài liệu (Req 2.2).
    Raise `PdfAttachError` nếu `pdf_bytes` rỗng, không mở được PDF, hoặc không có
    trang nào render được (Req 2.3).

    `max_pages > 0` giới hạn số trang render (0 = tất cả).

    `images_first`/`cache_control` phục vụ cache tiền tố giống
    :func:`build_pdf_user_content`: cả tập ảnh trang phải đứng TRƯỚC prompt thì
    tiền tố mới ổn định qua các lời gọi. Ở chế độ ảnh phần lặp này còn lớn hơn
    hẳn chế độ file, vì mỗi trang là một ảnh riêng.
    """
    if not pdf_bytes:
        raise PdfAttachError('PDF bytes rỗng — không thể đính kèm.')
    try:
        import fitz  # PyMuPDF
    except Exception as e:  # pragma: no cover
        raise PdfAttachError(f'Thiếu PyMuPDF để render PDF: {e}') from e

    text_part: Dict = {'type': 'text', 'text': prompt_text}
    images: List[Dict] = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    except Exception as e:
        raise PdfAttachError(f'Không mở được PDF để render: {e}') from e

    try:
        total = len(doc)
        limit = total if max_pages <= 0 else min(total, max_pages)
        rendered = 0
        for i in range(limit):
            try:
                pix = doc[i].get_pixmap(dpi=dpi)
                png = pix.tobytes('png')
                b64 = base64.b64encode(png).decode('ascii')
            except Exception:
                continue
            images.append({
                'type': 'image_url',
                'image_url': {'url': f'data:image/png;base64,{b64}'},
            })
            rendered += 1
    finally:
        doc.close()

    if rendered == 0:
        raise PdfAttachError('Không render được trang nào từ PDF.')
    if cache_control:
        # Điểm cắt cache đặt ở ảnh CUỐI: mọi thứ trước nó là tiền tố dùng lại
        # được. Nhà nào không hiểu trường này thì bỏ qua, không gãy request.
        images[-1]['cache_control'] = {'type': 'ephemeral'}
    return images + [text_part] if images_first else [text_part] + images

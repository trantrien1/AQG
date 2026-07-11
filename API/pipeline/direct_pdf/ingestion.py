"""Xác thực PDF đầu vào cho Direct_PDF_Mode (Req 4, 5).

Kiểm tra tồn tại file, tính hợp lệ PDF, và ngưỡng trang/dung lượng trước khi gọi
mô hình. Fail-fast, không crash âm thầm.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .. import config as cfg


@dataclass
class PdfValidationResult:
    ok: bool
    error_code: Optional[str]      # 'path_not_found' | 'not_a_pdf' | 'empty_pdf'
                                   # | 'page_limit_exceeded' | 'size_limit_exceeded'
                                   # | 'validation_internal_error' | None
    error_message: Optional[str]   # thông báo tiếng Việt nêu rõ nguyên nhân
    num_pages: int                 # 0 nếu không đọc được
    size_bytes: int                # 0 nếu không đọc được


class PdfIngestionComponent:
    def __init__(self, page_limit: int = cfg.PDF_PAGE_LIMIT,
                 size_limit: int = cfg.PDF_SIZE_LIMIT):
        self.page_limit = page_limit
        self.size_limit = size_limit

    def validate(self, pdf_path: str) -> PdfValidationResult:
        """Thứ tự kiểm tra (fail-fast, trả về ở lỗi đầu tiên):
        1. path_not_found      — đường dẫn không tồn tại (Req 4.1)
        2. not_a_pdf           — mở/parse PDF thất bại (Req 4.2)
        3. empty_pdf           — num_pages == 0 hoặc size_bytes == 0 (Req 5.3)
        4. page_limit_exceeded — num_pages > page_limit (Req 5.1)
        5. size_limit_exceeded — size_bytes > size_limit (Req 5.2)
        Toàn bộ thân hàm bọc trong try/except; exception bất ngờ ->
        error_code='validation_internal_error' (Req 4.3), không crash âm thầm.
        """
        try:
            # 1. path_not_found
            if not pdf_path or not os.path.isfile(pdf_path):
                return PdfValidationResult(
                    ok=False,
                    error_code='path_not_found',
                    error_message=f'Không tìm thấy file PDF tại đường dẫn: {pdf_path!r}.',
                    num_pages=0,
                    size_bytes=0,
                )

            # đọc dung lượng
            try:
                size_bytes = os.path.getsize(pdf_path)
            except OSError:
                size_bytes = 0

            # 2. not_a_pdf — mở bằng PyMuPDF; lỗi mở/parse -> not_a_pdf
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(pdf_path)
                try:
                    num_pages = doc.page_count
                finally:
                    doc.close()
            except Exception:
                return PdfValidationResult(
                    ok=False,
                    error_code='not_a_pdf',
                    error_message=(
                        'File không phải PDF hợp lệ hoặc không thể mở/đọc được: '
                        f'{pdf_path!r}.'
                    ),
                    num_pages=0,
                    size_bytes=size_bytes,
                )

            # 3. empty_pdf — ưu tiên trước ngưỡng (Req 5.3)
            if num_pages == 0 or size_bytes == 0:
                return PdfValidationResult(
                    ok=False,
                    error_code='empty_pdf',
                    error_message='PDF rỗng (0 trang hoặc 0 byte), không thể sinh câu hỏi.',
                    num_pages=num_pages,
                    size_bytes=size_bytes,
                )

            # 4. page_limit_exceeded (Req 5.1)
            if num_pages > self.page_limit:
                return PdfValidationResult(
                    ok=False,
                    error_code='page_limit_exceeded',
                    error_message=(
                        f'PDF có {num_pages} trang, vượt ngưỡng {self.page_limit} trang. '
                        'Vui lòng chia nhỏ tài liệu thủ công rồi thử lại.'
                    ),
                    num_pages=num_pages,
                    size_bytes=size_bytes,
                )

            # 5. size_limit_exceeded (Req 5.2)
            if size_bytes > self.size_limit:
                return PdfValidationResult(
                    ok=False,
                    error_code='size_limit_exceeded',
                    error_message=(
                        f'PDF nặng {size_bytes} byte, vượt ngưỡng {self.size_limit} byte. '
                        'Vui lòng chia nhỏ tài liệu thủ công rồi thử lại.'
                    ),
                    num_pages=num_pages,
                    size_bytes=size_bytes,
                )

            return PdfValidationResult(
                ok=True,
                error_code=None,
                error_message=None,
                num_pages=num_pages,
                size_bytes=size_bytes,
            )
        except Exception as e:  # Req 4.3 — không crash âm thầm
            return PdfValidationResult(
                ok=False,
                error_code='validation_internal_error',
                error_message=f'Lỗi hệ thống khi xác thực PDF: {e}',
                num_pages=0,
                size_bytes=0,
            )

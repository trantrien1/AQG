"""run_direct_pdf: điều phối validate -> generate -> save (Req 7)."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

from .. import config as cfg
from .generator import DirectPdfQuestionGenerator
from .ingestion import PdfIngestionComponent


def _write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_direct_pdf(pdf_path: str,
                   requested_count: int,
                   output_path: str,
                   bloom_distribution: Optional[List[Dict[str, Any]]] = None,
                   model: Optional[str] = None) -> Dict[str, Any]:
    """Điều phối validate -> generate -> save.

    - validate lỗi -> trả {'error_code','error_message'}, KHÔNG tạo file MCQ / gọi mô hình.
    - accepted_count == 0 -> KHÔNG ghi file danh sách MCQ (Req 7.2).
    - accepted_count > 0 -> ghi file MCQ theo Question_Schema (Req 7.1).
    - Luôn có thể ghi metadata Direct_PDF_Mode (Req 7.3).
    """
    source_pdf_name = os.path.basename(pdf_path)
    generator_model = model or cfg.GENERATOR_MODEL

    # 1. Xác thực (Req 4, 5) — fail-fast trước khi gọi mô hình.
    ingestion = PdfIngestionComponent()
    validation = ingestion.validate(pdf_path)
    if not validation.ok:
        return {
            'error_code': validation.error_code,
            'error_message': validation.error_message,
            'mode': 'Direct_PDF_Mode',
            'source_pdf_name': source_pdf_name,
            'requested_questions': requested_count,
            'accepted_questions': 0,
            'is_partial': True,
            'parse_errors': 0,
            'generator_model': generator_model,
            'output_path': None,
        }

    # 2. Sinh câu hỏi (Req 2, 3, 6).
    generator = DirectPdfQuestionGenerator(model=generator_model)
    result = generator.generate(
        pdf_path=pdf_path,
        requested_count=requested_count,
        bloom_distribution=bloom_distribution,
        model=generator_model,
    )

    generated_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    metadata = {
        'mode': 'Direct_PDF_Mode',
        'source_pdf_name': source_pdf_name,
        'requested_questions': result.requested_count,
        'accepted_questions': result.accepted_count,
        'is_partial': result.is_partial,
        'parse_errors': result.parse_errors,
        'verify_failures': result.verify_failures,
        'generator_model': generator_model,
        'generated_at': generated_at,
    }

    # 3. Lưu output (Req 7.1, 7.2) — chỉ ghi file MCQ khi có câu chấp nhận.
    output_written = None
    if result.accepted_count > 0:
        _write_json(output_path, {
            'metadata': metadata,
            'questions': result.questions,
        })
        output_written = output_path

    summary = dict(metadata)
    summary.update({
        'error_code': result.error_code,
        'error_message': result.error_message,
        'output_path': output_written,
    })
    return summary

"""IngestionAgent — wrap pdf_parser. Parse PDF → cleaned chunked dataset."""
from __future__ import annotations

from pathlib import Path

from .base import BaseAgent
from .messages import IngestionRequest, IngestionResponse
from ..chunk_context_builder import attach_clean_contexts, build_clean_contexts
from ..document_preprocessor import preprocess_dataset
from ..pdf_parser import parse_pdf_to_dataset


class IngestionAgent(BaseAgent):
    """Đọc PDF → trả về dataset format giống `data/math_input.json`.

    Trách nhiệm:
    - Extract text per page (PyMuPDF)
    - Loại header/footer/page number lặp
    - Fix tiếng Việt encoding (ƣ → ư)
    - Detect heading + chunk theo target_chars
    - Filter chunks chất lượng thấp (mục lục, code-only)
    """

    def __init__(self):
        super().__init__('ingestion', skills=[
            'pdf-parsing',
            'document-classification',
            'long-document-detection',
            'noise-removal',
            'chunking',
            'knowledge-extraction',
            'relevance-filtering',
        ])

    def run(self, request: IngestionRequest) -> IngestionResponse:
        try:
            dataset = parse_pdf_to_dataset(
                request.pdf_path,
                target_chars=request.target_chars,
                filter_low_quality=request.filter_low_quality,
                chunk_page_threshold=request.chunk_page_threshold,
                force_chunk=request.force_chunk,
            )
            report = None
            if request.preprocess_long_documents:
                dataset, report = preprocess_dataset(
                    dataset,
                    long_doc_chars=request.long_doc_chars,
                    too_long_chars=request.too_long_doc_chars,
                    max_units=request.max_context_units,
                    section_filter=request.section_filter,
                )
                if report.get('requires_user_selection') and not request.allow_very_long:
                    return IngestionResponse(
                        dataset=dataset,
                        num_chunks=sum(1 for k in dataset if k != 'metadata'),
                        source_name=Path(request.pdf_path).name,
                        error='LONG_DOCUMENT_REQUIRES_SELECTION',
                        preprocessing_report=report,
                    )
            source_name = Path(request.pdf_path).name
            clean_contexts = build_clean_contexts(dataset, source_name=source_name)
            dataset = attach_clean_contexts(dataset, clean_contexts)
            dataset.setdefault('metadata', {})['clean_contexts_payload'] = clean_contexts.get('metadata', {})
            n_chunks = sum(1 for k in dataset if k != 'metadata')
            return IngestionResponse(
                dataset=dataset,
                num_chunks=n_chunks,
                source_name=source_name,
                preprocessing_report=report,
            )
        except Exception as e:
            return IngestionResponse(
                dataset={}, num_chunks=0, source_name='', error=str(e),
            )

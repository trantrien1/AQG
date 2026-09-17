"""Multi-agent pipeline cho Direct_PDF_Mode (PDF-vision).

Bản rút gọn của kiến trúc multi-agent trong `pipeline/agents/`, nhưng "context"
là các trang PDF đã render thành ảnh (`attachment_parts`) thay vì text. Chuỗi:

    PdfWriterAgent      — Stage 1: stem + answer + solution + source_quote (distractors=[])
    PdfDistractorAgent  — Stage 2: 3 distractor gắn misconception
    PdfIndependentVerifierAgent — Stage 3: giải lại bài toán CHỈ từ đề bài
    VerifierAgent       — (tái dùng) symbolic verify + phân xử đa nguồn (context='')
    PdfCriticAgent      — grounding + multi-trait rubric trên ảnh trang (vision)
    FormatterAgent      — (tái dùng) record cuối + shuffle options

Cô lập hoàn toàn với pipeline chunk: pipeline chunk KHÔNG import package này.
Bật/tắt qua env `AQG_DIRECT_PDF_MULTI_AGENT` (config `DIRECT_PDF_MULTI_AGENT`).
"""
from .pdf_independent_agent import PdfIndependentVerifierAgent
from .pdf_orchestrator import DirectPdfOrchestrator

__all__ = ['DirectPdfOrchestrator', 'PdfIndependentVerifierAgent']

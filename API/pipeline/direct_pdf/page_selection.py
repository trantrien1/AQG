"""Cache trang đã render + chọn trang liên quan (giảm token cho grounding).

Hiện mỗi agent nhận TOÀN BỘ các trang tài liệu đã render. Đó là lý do chi phí
token cao: cùng một tập ảnh trang được gửi lại ở mỗi lượt gọi của mỗi agent.

Hai cơ chế ở đây:

1. :func:`cached_page_parts` — cache ảnh trang trên đĩa theo (hash tài liệu,
   dpi, số trang). Thuần tiết kiệm CPU/thời gian, KHÔNG đổi nội dung gửi đi nên
   không ảnh hưởng chất lượng.
2. :func:`select_pages` — chọn tập con trang liên quan tới chủ đề của một slot
   dựa trên text trích được từ chính trang đó. Cơ chế này CÓ đánh đổi: gửi ít
   trang hơn thì rẻ hơn nhưng có thể mất ngữ cảnh.

Vì (2) là đánh đổi thật, nó **mặc định TẮT** và mọi lượt gọi đều ghi lại số
trang đã gửi (:func:`selection_trace`) để đo được quan hệ chi phí/chất lượng
thay vì đoán. Bật lên bằng ``AQG_PAGE_LOCALIZATION=1``; nếu không đo trước rồi
so sánh thì đừng bật trong bản chạy lấy số liệu.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

_CACHE_ROOT = Path(
    os.getenv('AQG_PAGE_CACHE_DIR', '')
    or Path(__file__).resolve().parent.parent.parent / '.cache' / 'pdf_pages'
)

#: Bật chọn trang theo chủ đề. Mặc định tắt — xem docstring module.
PAGE_LOCALIZATION = os.getenv('AQG_PAGE_LOCALIZATION', '0') in ('1', 'true', 'yes')
#: Số trang tối thiểu luôn gửi kèm dù điểm liên quan thấp.
MIN_PAGES = int(os.getenv('AQG_PAGE_LOCALIZATION_MIN_PAGES', '6'))
#: Trần số trang khi bật chọn lọc.
MAX_PAGES = int(os.getenv('AQG_PAGE_LOCALIZATION_MAX_PAGES', '12'))


def document_key(pdf_bytes: bytes, dpi: int, max_pages: int) -> str:
    digest = hashlib.sha256(pdf_bytes).hexdigest()[:32]
    return f'{digest}-dpi{dpi}-p{max_pages}'


def cached_page_parts(
    pdf_bytes: bytes,
    filename: str,
    *,
    dpi: int,
    max_pages: int,
    builder,
) -> List[Dict[str, Any]]:
    """Trả các part ảnh trang, dùng lại bản đã render nếu có trên đĩa.

    ``builder(pdf_bytes, filename, '', dpi=..., max_pages=...)`` là hàm render
    thật (thường là ``attach.build_pdf_image_content``). Cache chỉ lưu kết quả
    render nên không đổi một byte nào trong nội dung gửi lên model.
    """
    key = document_key(pdf_bytes, dpi, max_pages)
    path = _CACHE_ROOT / f'{key}.json'
    try:
        if path.exists():
            parts = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(parts, list) and parts:
                return parts
    except Exception:
        pass

    content = builder(pdf_bytes, filename, '', dpi=dpi, max_pages=max_pages)
    parts = [p for p in content if p.get('type') != 'text']
    try:
        _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(parts), encoding='utf-8')
    except Exception:
        # Cache là tối ưu hoá, hỏng cache không được làm hỏng lượt sinh.
        pass
    return parts


def extract_page_texts(pdf_bytes: bytes, max_pages: int = 0) -> List[str]:
    """Text thô của từng trang (chỉ dùng để CHỌN trang, không gửi cho model)."""
    try:
        import fitz  # PyMuPDF
    except Exception:
        return []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    except Exception:
        return []
    try:
        limit = len(doc) if max_pages <= 0 else min(len(doc), max_pages)
        return [_safe_page_text(doc[i]) for i in range(limit)]
    finally:
        doc.close()


def _safe_page_text(page) -> str:
    try:
        return str(page.get_text() or '')
    except Exception:
        return ''


def _fold(text: str) -> str:
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    norm = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()


_STOP = {
    'cua', 'cho', 'mot', 'cac', 'trong', 'khi', 'voi', 'thi', 'la', 'va',
    'hoac', 'nhu', 'theo', 'tren', 'duoi', 'bang', 'that', 'nay', 'do',
}


def _tokens(text: str) -> set:
    return {
        t for t in re.findall(r'[a-z0-9]{3,}', _fold(text))
        if t not in _STOP
    }


def score_pages(page_texts: Sequence[str], query: str) -> List[float]:
    """Điểm liên quan của mỗi trang với truy vấn (chủ đề/kỹ năng của slot)."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return [0.0]*len(page_texts)
    scores = []
    for text in page_texts:
        page_tokens = _tokens(text)
        if not page_tokens:
            scores.append(0.0)
            continue
        scores.append(len(page_tokens & query_tokens) / len(query_tokens))
    return scores


def select_pages(
    page_parts: Sequence[Dict[str, Any]],
    page_texts: Sequence[str],
    query: str,
    *,
    enabled: Optional[bool] = None,
    min_pages: int = MIN_PAGES,
    max_pages: int = MAX_PAGES,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Chọn tập con trang liên quan; trả (parts, vết đo).

    Vết đo luôn ghi ``pages_available`` và ``pages_sent`` kể cả khi cơ chế tắt,
    để mọi run đều có dữ liệu so sánh chi phí — không có vết đo thì không thể
    nói cơ chế này rẻ hơn bao nhiêu và mất gì.
    """
    parts = list(page_parts)
    trace: Dict[str, Any] = {
        'localization_enabled': bool(
            PAGE_LOCALIZATION if enabled is None else enabled),
        'pages_available': len(parts),
        'pages_sent': len(parts),
        'query': query[:120],
        'selected_indices': None,
    }
    if not trace['localization_enabled'] or not query.strip():
        return parts, trace
    if not page_texts or len(page_texts) < len(parts):
        trace['note'] = 'không trích được text của mọi trang — gửi đủ trang'
        return parts, trace

    scores = score_pages(page_texts[:len(parts)], query)
    ranked = sorted(range(len(parts)), key=lambda i: (-scores[i], i))
    keep = max(1, min(max_pages, max(min_pages, sum(1 for s in scores if s > 0))))
    chosen = sorted(ranked[:keep])
    trace['pages_sent'] = len(chosen)
    trace['selected_indices'] = chosen
    trace['top_scores'] = [round(scores[i], 3) for i in chosen[:10]]
    return [parts[i] for i in chosen], trace


def selection_trace(traces: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Gộp vết đo của nhiều lượt gọi thành một dòng chi phí/độ phủ."""
    if not traces:
        return {'calls': 0}
    available = sum(t.get('pages_available', 0) for t in traces)
    sent = sum(t.get('pages_sent', 0) for t in traces)
    return {
        'calls': len(traces),
        'pages_available_total': available,
        'pages_sent_total': sent,
        'page_reduction': (
            round(1 - sent / available, 4) if available else None),
        'localization_enabled': any(t.get('localization_enabled') for t in traces),
    }

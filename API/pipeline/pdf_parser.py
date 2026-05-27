"""PDF parser & chunker (mục 3) — phiên bản MVP.

Dùng PyMuPDF để extract text per page, clean header/footer/page number, rồi chunk
theo kích thước cố định (~target_chars), break tại ranh giới đoạn (\n\n).

Hạn chế MVP:
- Text-only: công thức ra Unicode/text thường, không phải LaTeX
- Không trích figures/tables/diagrams (chỉ chèn placeholder [FIGURE])
- Topic của mỗi chunk = câu đầu tiên / heading gần nhất (heuristic)

Để nâng cấp:
- Mathpix / Nougat cho LaTeX OCR
- Vision model cho figures
- Detect chapter/section bằng style font (PyMuPDF đã expose font size)
"""
from __future__ import annotations

import collections
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .context_utils import strip_markdown
except Exception:  # pragma: no cover - fallback for direct script-style imports
    def strip_markdown(text: str) -> str:
        return text or ''


# ==== Extraction ====

def extract_markdown(pdf_path: str) -> str:
    """Extract PDF to Markdown using pymupdf4llm. Falls back to plain text on error."""
    try:
        import pymupdf4llm
        md = pymupdf4llm.to_markdown(pdf_path)
        return _fix_vn_chars(md)
    except Exception:
        return ''


def extract_text_per_page(pdf_path: str) -> List[Dict[str, Any]]:
    """Trả list per-page: [{page, text, blocks}]."""
    import fitz  # PyMuPDF
    doc = fitz.open(pdf_path)
    pages = []
    try:
        for i, page in enumerate(doc):
            text = page.get_text('text')
            pages.append({'page': i + 1, 'text': text})
    finally:
        doc.close()
    return pages


# ==== Cleaning ====

_PAGE_NUMBER_PAT = re.compile(r'^\s*\d+\s*$')
_FORM_FEED = re.compile(r'\x0c+')
_MULTI_NEWLINE = re.compile(r'\n{3,}')
_MULTI_SPACE = re.compile(r'[ \t]+')


# Một số font tiếng Việt cũ encode chữ có dấu sai. Mapping về Unicode chuẩn.
# (chỉ liệt kê những ký tự sai phổ biến trong giáo trình PTIT/đại học)
_VN_CHAR_FIX = {
    'ƣ': 'ư',   # U+01A3 → U+01B0  (đƣợc → được, thƣờng → thường)
    'Ƣ': 'Ư',
    # 'ơ', 'ô', 'ê', 'â' thường đúng — không cần map
}


def _fix_vn_chars(text: str) -> str:
    for wrong, right in _VN_CHAR_FIX.items():
        text = text.replace(wrong, right)
    return text


_MATH_CONTENT_RE = re.compile(
    r'\b(?:định\s+nghĩa|định\s+lý|hệ\s+quả|bổ\s+đề|công\s+thức|ví\s+dụ|'
    r'bài\s+toán|lời\s+giải|nguyên\s+lý|quy\s+tắc|qui\s+tắc|tổ\s+hợp|'
    r'hoán\s+vị|chỉnh\s+hợp|xác\s+suất|ma\s+trận|đồ\s+thị|mệnh\s+đề|'
    r'definition|theorem|formula|example|exercise)\b|'
    r'(?:[=≤≥∈∉⊂⊆∪∩∀∃∑∫√]|\\frac|\\sqrt|\bC\s*\(|\bP\s*\(|\bn!\b|\bmod\b)',
    re.IGNORECASE,
)


def _has_math_content(text: str) -> bool:
    if not text:
        return False
    return _MATH_CONTENT_RE.search(text) is not None


def _is_low_quality_chunk(text: str) -> bool:
    """Reject only hard-noise chunks; preserve math-heavy text for clean-context builder."""
    if not text or len(text) < 80:
        return True
    dots = text.count('.')
    if dots / max(1, len(text)) > 0.20 and not _has_math_content(text):
        return True
    alpha_words = re.findall(r'[A-Za-zÀ-ỹ]{2,}', text)
    has_math = _has_math_content(text)
    if len(alpha_words) < 18 and not has_math:
        return True
    code_markers = re.findall(
        r'\b(?:printf|scanf|fscanf|void|return)\b|\b(?:for|if|while)\s*\(|\bint\s+[A-Za-z_]',
        text,
    )
    if len(code_markers) >= 8 and not has_math:
        return True
    symbol_chars = sum(
        1 for ch in text
        if unicodedata.category(ch).startswith('S')
    )
    if symbol_chars / max(1, len(text)) > 0.18 and not has_math:
        return True
    private_use_chars = sum(
        1 for ch in text
        if unicodedata.category(ch) == 'Co'
    )
    if private_use_chars / max(1, len(text)) > 0.08 and not has_math:
        return True
    code_chars = sum(text.count(c) for c in '{};=<>+/*[]')
    alpha_chars = sum(1 for c in text if c.isalpha())
    if alpha_chars > 0 and code_chars / alpha_chars > 0.8 and not has_math:
        return True
    return False


def _detect_repeated_lines(pages: List[Dict[str, Any]],
                           min_pages_ratio: float = 0.4) -> set:
    """Tìm các dòng xuất hiện ở >= min_pages_ratio số trang → đó là header/footer."""
    if len(pages) < 3:
        return set()
    counter: collections.Counter = collections.Counter()
    for p in pages:
        for line in p['text'].splitlines():
            line = line.strip()
            if 3 < len(line) < 120:
                counter[line] += 1
    threshold = max(2, int(len(pages) * min_pages_ratio))
    return {line for line, c in counter.items() if c >= threshold}


def clean_pages(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Loại form-feed, dòng số trang đơn lẻ, header/footer lặp, fix VN chars."""
    repeated = _detect_repeated_lines(pages)
    cleaned = []
    for p in pages:
        text = _FORM_FEED.sub('\n', p['text'])
        text = _fix_vn_chars(text)
        new_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                new_lines.append('')
                continue
            if _PAGE_NUMBER_PAT.match(stripped):
                continue
            if stripped in repeated:
                continue
            new_lines.append(line)
        text = '\n'.join(new_lines)
        text = _MULTI_NEWLINE.sub('\n\n', text)
        text = _MULTI_SPACE.sub(' ', text)
        text = text.strip()
        cleaned.append({'page': p['page'], 'text': text})
    return cleaned


# ==== Heading detection ====

# Patterns thường gặp trong giáo trình tiếng Việt và tiếng Anh
_HEADING_PATTERNS = [
    re.compile(r'^(Chương|CHƯƠNG)\s+\d+\s*[:.]?\s*(.{0,120})$', re.IGNORECASE),
    re.compile(r'^(Bài|BÀI)\s+\d+\s*[:.]?\s*(.{0,120})$', re.IGNORECASE),
    re.compile(r'^(Mục|MỤC)\s+\d+\s*[:.]?\s*(.{0,120})$', re.IGNORECASE),
    re.compile(r'^(Section|Chapter)\s+\d+\s*[:.]?\s*(.{0,120})$', re.IGNORECASE),
    re.compile(r'^(\d+\.\d+(?:\.\d+)?)\s+([^\n]{2,120})$'),         # 1.2 / 1.2.3
    re.compile(r'^(\d+)\.\s+([A-ZĐ][^\n]{2,120})$'),                # "1. Title"
]

_HEADING_PATTERNS.insert(
    -1,
    re.compile(r'^(\d+(?:\.\d+){1,5})\.\s+([^\n]{2,120})$'),
)

def _strip_topic_markup(line: str) -> str:
    s = (line or '').strip()
    s = re.sub(r'^\s{0,3}#{1,6}\s*', '', s)
    s = re.sub(r'^\*{1,2}(.+?)\*{1,2}$', r'\1', s)
    s = re.sub(r'^_{1,2}(.+?)_{1,2}$', r'\1', s)
    return s.strip()


def detect_heading(line: str) -> Optional[str]:
    s = _strip_topic_markup(line)
    if not s or len(s) > 140:
        return None
    for pat in _HEADING_PATTERNS:
        if pat.match(s):
            return s
    return None


# ==== Chunking ====

def chunk_pages(pages: List[Dict[str, Any]],
                target_chars: int = 1000,
                min_chars: int = 200,
                max_chars: int = 1800,
                respect_headings: bool = True) -> List[Dict[str, Any]]:
    """Cắt thành các chunk ~target_chars, break tại ranh giới đoạn.
    Topic của mỗi chunk = heading gần nhất (không phải chương) trong chunk đó;
    nếu không có thì dùng last_section_heading được kế thừa từ chunk trước;
    chỉ fallback về câu đầu tiên khi không có heading nào cả."""
    chunks: List[Dict[str, Any]] = []
    buf_paras: List[str] = []
    buf_pages: List[int] = []
    chunk_idx = 0
    last_section_heading: Optional[str] = None  # kế thừa qua chunks

    def flush():
        nonlocal chunk_idx, buf_paras, buf_pages
        if not buf_paras:
            return
        text = '\n\n'.join(buf_paras).strip()
        topic = _topic_from_chunk(text, fallback_heading=last_section_heading)
        if len(text) < min_chars and chunks:
            prev = chunks[-1]
            prev['context'] = (prev['context'] + '\n\n' + text).strip()
            prev['pages'] = sorted(set(prev['pages'] + buf_pages))
            prev['topic'] = _topic_from_chunk(prev['context'], fallback_heading=last_section_heading)
        else:
            chunks.append({
                'doc_id': f'pdf_{chunk_idx:03d}',
                'pages': sorted(set(buf_pages)),
                'topic': topic,
                'context': text,
            })
            chunk_idx += 1
        buf_paras = []
        buf_pages = []

    for p in pages:
        for para in re.split(r'\n\s*\n', p['text']):
            para = para.strip()
            if not para:
                continue

            # Track last meaningful section heading (không phải chương)
            first_line = para.split('\n', 1)[0]
            h = detect_heading(first_line)
            if h and not _COARSE_HEADING_PAT.match(h):
                last_section_heading = _clean_one_line(h)

            # Heading break: nếu paragraph mở đầu bằng heading mới → flush chunk cũ
            if respect_headings and h and buf_paras:
                flush()

            buf_size = sum(len(x) for x in buf_paras) + len(para)
            if buf_size > max_chars:
                flush()
            buf_paras.append(para)
            buf_pages.append(p['page'])
            if sum(len(x) for x in buf_paras) >= target_chars:
                flush()
    flush()
    return chunks


# Heading "chương" được coi là quá thô — bỏ qua khi pick topic
_COARSE_HEADING_PAT = re.compile(r'^(Chương|CHƯƠNG|Chapter)\s+\d+', re.IGNORECASE)
_TOPIC_PHRASE_PATTERNS = [
    re.compile(r'\b(Bài\s+toán\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Thuật\s+toán\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Phương\s+pháp\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Kỹ\s+thuật\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Nguyên\s+lý\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Định\s+lý\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Ví\s+dụ\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Việc\s+phân\s+nhánh\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Tình\s+huống\s+phân\s+nhánh\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Ngăn\s+cấm\s+[^.:\n]{5,110})', re.IGNORECASE),
    re.compile(r'\b(Trong\s+ma\s+trận\s+rút\s+gọn\s+[^.:\n]{5,110})', re.IGNORECASE),
]

_CONTENT_TOPIC_PATTERNS = [
    (re.compile(r'\bnguyên\s+lý\s+nhân\b|\b(?:qui|quy)\s+tắc\s+nhân\b', re.IGNORECASE), 'Nguyên lý nhân'),
    (re.compile(r'\bnguyên\s+lý\s+cộng\b|\b(?:qui|quy)\s+tắc\s+cộng\b', re.IGNORECASE), 'Nguyên lý cộng'),
    (re.compile(r'\bnguyên\s+lý\s+bù\s+trừ\b|\binclusion[-\s]+exclusion\b', re.IGNORECASE), 'Nguyên lý bù trừ'),
    (re.compile(r'\btổ\s+hợp\s+lặp\b', re.IGNORECASE), 'Tổ hợp lặp'),
    (re.compile(r'\bchỉnh\s+hợp\s+lặp\b', re.IGNORECASE), 'Chỉnh hợp lặp'),
]


def _topic_phrase_from_text(text: str) -> Optional[str]:
    sample = _clean_one_line(strip_markdown(text))[:1400]
    for pat, topic in _CONTENT_TOPIC_PATTERNS:
        if pat.search(sample):
            return topic
    for pat in _TOPIC_PHRASE_PATTERNS:
        m = pat.search(sample)
        if m:
            return _clean_topic_candidate(m.group(1))
    return None


_INSTRUCTION_PREFIX = re.compile(
    r'^\s*(?:hãy\s+(?:tìm|tính|chứng\s+minh|giải|xác\s+định|nêu)|'
    r'tìm\s+(?:nghiệm|giá\s+trị|công\s+thức)|'
    r'tính\s+(?:giá\s+trị|tổng|tích|đạo\s+hàm)|'
    r'giải\s+(?:phương\s+trình|hệ|bất\s+phương\s+trình)|'
    r'chứng\s+minh|xác\s+định|biểu\s+diễn|liệt\s+kê)\b[^.]*?[:\.]',
    re.IGNORECASE,
)


def _clean_topic_candidate(s: str) -> str:
    s = _clean_one_line(s)
    # Bỏ số bài/section ở đầu: "48.", "Bài 12:", "1.2.3"
    s = re.sub(r'^\s*(?:Bài|Câu|Mục|Section|Ex(?:ercise)?)\s*\d+[\.:]?\s*',
               '', s, flags=re.IGNORECASE)
    s = re.sub(r'^\s*\d+(?:\.\d+)*[\.:)]\s*', '', s)
    # Bỏ công thức/ký hiệu bị dính ở đầu dòng trước phần chữ tự nhiên.
    s = re.sub(r'^[^A-Za-zÀ-ỹĐđ]+', '', s).strip(' ,;:-')
    # Detect instruction-style topic ("Hãy tìm...", "Tính...", "Cho...")
    # — đây là tiêu đề bài tập, không phải topic. Nếu sau prefix còn nội dung
    # ý nghĩa (>= 15 chars) thì giữ phần đó; nếu không thì trả "" → caller fallback.
    m = _INSTRUCTION_PREFIX.match(s)
    if m:
        tail = s[m.end():].strip()
        if len(tail) >= 15:
            s = tail
        else:
            return ''  # caller dùng fallback
    # Cũng reject nếu topic bắt đầu bằng "Hãy ..." nhưng pattern không match
    # (ví dụ thiếu colon ở cuối):
    # "Cho ..." là fact statement (Cho tam giác ABC...), giữ lại.
    # Chỉ reject các verb mệnh lệnh thuần.
    if re.match(r'^(?:hãy|tính|chứng\s+minh|giải|liệt\s+kê|biểu\s+diễn)\s+\S+',
                s, re.IGNORECASE):
        return ''
    s = re.sub(r'\s+', ' ', s).strip()
    if s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s[:120]


def _is_good_topic_candidate(s: str) -> bool:
    s = _clean_topic_candidate(s)
    if len(s) < 24:
        return False
    words = re.findall(r'[A-Za-zÀ-ỹĐđ]{2,}', s)
    if len(words) < 5:
        return False
    letters = sum(1 for ch in s if ch.isalpha())
    symbols = sum(1 for ch in s if not ch.isalnum() and not ch.isspace())
    return letters >= 0.55 * max(1, len(s)) and symbols <= 0.25 * max(1, len(s))


def _topic_from_chunk(text: str, fallback_heading: Optional[str] = None) -> str:
    """Pick topic:
    1. Subsection heading trong chunk (1.2, Bài X, Mục X…)
    2. fallback_heading = last_section_heading kế thừa từ chunk trước (ưu tiên hơn câu đầu)
    3. Câu đầu tiên đủ dài (>= 8 từ) — chỉ khi không có heading nào
    Không dùng 'Chương X' (quá thô)."""
    plain_text = strip_markdown(text)
    lines = [l.strip() for l in plain_text.splitlines() if l.strip()]
    # 1. Subsection heading trong chunk
    for line in lines[:10]:
        if _COARSE_HEADING_PAT.match(line):
            continue
        h = detect_heading(line)
        if h:
            return _clean_one_line(h)[:120]
    # 1b. Chủ đề được nêu trong nội dung đầu chunk, hữu ích khi PDF không có heading rõ.
    phrase = _topic_phrase_from_text(plain_text)
    if phrase:
        return phrase
    # 2. Kế thừa heading section gần nhất
    if fallback_heading:
        return fallback_heading[:120]
    # 3. Câu đầu tiên đủ dài — chỉ khi không có heading nào
    for line in lines:
        if _COARSE_HEADING_PAT.match(line):
            continue
        if _is_good_topic_candidate(line):
            return _clean_topic_candidate(line)
    return 'Chưa rõ chủ đề'


def infer_topic_from_context(text: str, fallback_heading: Optional[str] = None) -> str:
    """Public wrapper used by Planner when loaded chunks have weak topic labels."""
    return _topic_from_chunk(text, fallback_heading=fallback_heading)


def _clean_one_line(s: str) -> str:
    s = s.replace('\n', ' ').strip()
    return _MULTI_SPACE.sub(' ', s)


def _single_document_chunk(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    text = '\n\n'.join(p['text'] for p in pages if p.get('text')).strip()
    if not text:
        return []
    return [{
        'doc_id': 'pdf_000',
        'pages': [p['page'] for p in pages],
        'topic': _topic_from_chunk(text),
        'context': text,
        '_chunking_mode': 'single_document',
    }]


# ==== Public API ====

def parse_pdf(pdf_path: str,
              target_chars: int = 1000,
              max_chars: int = 1800,
              filter_low_quality: bool = True,
              chunk_page_threshold: int = 100,
              force_chunk: bool = False) -> List[Dict[str, Any]]:
    """End-to-end: PDF → dataset units.

    Uses pymupdf4llm for Markdown extraction (preserves headings, tables, formulas).
    Falls back to plain text extraction if pymupdf4llm fails.

    Default policy:
    - PDF <= chunk_page_threshold pages: keep as one document, no chunking.
    - PDF > chunk_page_threshold pages or force_chunk=True: chunk by target_chars.
    """
    # Try markdown extraction first
    md_text = extract_markdown(pdf_path)

    pages = extract_text_per_page(pdf_path)
    num_pages = len(pages)

    extraction_mode = 'plain_text'
    if md_text and len(md_text) > 200:
        extraction_mode = 'markdown'
        # Use markdown: split into pseudo-pages by markdown headings or page breaks
        print(f'    [extraction] using pymupdf4llm markdown ({len(md_text)} chars)')
        pages = _markdown_to_pages(md_text, num_pages)
    else:
        print(f'    [extraction] fallback to plain text')

    pages = clean_pages(pages)
    if not force_chunk and num_pages <= chunk_page_threshold:
        print(f'    [chunking] {num_pages} pages <= {chunk_page_threshold}: no chunking')
        chunks = _single_document_chunk(pages)
        for c in chunks:
            c['_extraction_mode'] = extraction_mode
        return chunks

    print(f'    [chunking] {num_pages} pages > {chunk_page_threshold}: chunking')
    chunks = chunk_pages(pages, target_chars=target_chars, max_chars=max_chars)
    for c in chunks:
        c['_chunking_mode'] = 'chunked'
        c['_extraction_mode'] = extraction_mode
    if filter_low_quality:
        before = len(chunks)
        chunks = [c for c in chunks if not _is_low_quality_chunk(c['context'])]
        # Đánh số lại doc_id sau filter
        for i, c in enumerate(chunks):
            c['doc_id'] = f'pdf_{i:03d}'
        if before != len(chunks):
            print(f'    [filter] Loại {before - len(chunks)}/{before} chunk chất lượng thấp')
    return chunks


def _markdown_to_pages(md_text: str, num_pages: int) -> List[Dict[str, Any]]:
    """Split markdown text into page-like units for downstream chunking.

    pymupdf4llm inserts page breaks as '-----' or similar. We split on those,
    or fall back to splitting by major headings (##).
    """
    # pymupdf4llm uses \n-----\n as page separator
    page_sep = re.compile(r'\n-{3,}\n')
    parts = page_sep.split(md_text)

    if len(parts) <= 1:
        # No page separators found — split by ## headings
        heading_split = re.split(r'\n(?=## )', md_text)
        parts = heading_split if len(heading_split) > 1 else [md_text]

    pages = []
    for i, part in enumerate(parts):
        text = part.strip()
        if text:
            pages.append({'page': i + 1, 'text': text})
    return pages


def to_input_dataset(chunks: List[Dict[str, Any]],
                     source_name: str = '') -> Dict[str, Any]:
    """Chuyển list chunks → format dataset giống data/math_input.json."""
    chunking_mode = (
        chunks[0].get('_chunking_mode', 'chunked') if chunks else 'empty'
    )
    extraction_mode = (
        chunks[0].get('_extraction_mode', 'plain_text') if chunks else 'unknown'
    )
    total_chars = sum(len(c['context']) for c in chunks)
    out: Dict[str, Any] = {
        'metadata': {
            'source': source_name,
            'parsed_from_pdf': True,
            'num_chunks': len(chunks),
            'num_units': len(chunks),
            'chunking_mode': chunking_mode,
            'extraction_mode': extraction_mode,
            'total_chars': total_chars,
        }
    }
    for c in chunks:
        out[c['doc_id']] = {
            'topic': c['topic'],
            'pages': c['pages'],
            'context': c['context'],
        }
    return out


def parse_pdf_to_dataset(pdf_path: str, **kwargs) -> Dict[str, Any]:
    """Convenience: parse_pdf + to_input_dataset."""
    chunks = parse_pdf(pdf_path, **kwargs)
    return to_input_dataset(chunks, source_name=Path(pdf_path).name)

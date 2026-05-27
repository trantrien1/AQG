"""Build compact, structured clean contexts from raw document chunks."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Dict, List, Optional

from . import config as cfg
from .context_utils import strip_markdown, trim_context_for_generation
from .llm_client import BudgetExceeded, call_llm
from .skills.document import extract_key_passages, summarize_text


MAX_CLEAN_TEXT_CHARS = 1800
MAX_SOURCE_SPANS = 8
MAX_LIST_ITEMS = 8
MAX_EXISTING_QUESTION_SPANS = 6

_KEY_LINE_RE = re.compile(
    r'\b(?:định\s+nghĩa|định\s+lý|hệ\s+quả|công\s+thức|ví\s+dụ|bài\s+toán|'
    r'lời\s+giải|definition|theorem|formula|example|exercise)\b|'
    r'(?:[=≤≥<>]|\\frac|\\sqrt|√|∑|∫|\^|\bmod\b|\bC\s*\()',
    re.IGNORECASE,
)
_DEFINITION_RE = re.compile(r'\b(?:định\s+nghĩa|definition|được\s+gọi\s+là|gọi\s+là)\b', re.I)
_THEOREM_RE = re.compile(r'\b(?:định\s+lý|hệ\s+quả|bổ\s+đề|theorem|lemma|corollary)\b', re.I)
_EXAMPLE_RE = re.compile(r'\b(?:ví\s+dụ|bài\s+toán|lời\s+giải|example|exercise)\b', re.I)
_FORMULA_RE = re.compile(r'(?:[=≤≥<>]|\\frac|\\sqrt|√|∑|∫|\^|\bmod\b|\bC\s*\(|\bn!\b)')
_PAGE_LINE_RE = re.compile(r'^\s*(?:trang\s*)?\d+\s*$', re.I)
_DOT_LEADER_RE = re.compile(r'\.{6,}')
_OPTION_LINE_RE = re.compile(r'^\s*[A-Da-d]\s*[\.\)]\s+\S+')
_INLINE_OPTIONS_RE = re.compile(r'\bA\s*[\.\)]\s+.+?\bB\s*[\.\)]\s+.+?\bC\s*[\.\)]\s+.+?\bD\s*[\.\)]\s+', re.S)
_QUESTION_MARKER_RE = re.compile(
    r'(?i)(?:^|(?<=[\s.;:]))(?:c(?:au|\u00e2u)|b(?:ai|\u00e0i)|question|exercise)\s*\d{1,4}\s*[\.:)]?'
)
_QUESTION_COMMAND_FOLD_RE = re.compile(
    r'\b(?:hoi|chon|dap an|phuong an|dung sai|khach quan|trac nghiem|'
    r'bao nhieu|lua chon|xet tinh|khang dinh)\b'
)
_CONCEPT_OR_SOLUTION_FOLD_RE = re.compile(
    r'\b(?:cong thuc|dinh nghia|dinh ly|he qua|nguyen ham|tich phan|'
    r'ta co|suy ra|loi giai|phuong trinh|do do|ap dung)\b'
)


_SYSTEM = (
    'Bạn là bộ lọc ngữ cảnh cho hệ thống sinh câu hỏi Toán. '
    'Chỉ làm sạch, cấu trúc hóa và trích xuất thông tin có trong nguồn. '
    'Không thêm kiến thức ngoài, không tự sửa công thức, không giải thêm bài toán.'
)

_USER = '''\
Từ chunk Toán thô dưới đây, tạo clean context ngắn và có cấu trúc để sinh câu hỏi MCQ.

Quy tắc bắt buộc:
- Không thêm sự kiện/công thức/định nghĩa không có trong nguồn.
- Giữ ký hiệu toán; nếu OCR mờ thì ghi vào questionable_skills hoặc source_spans, không tự đoán.
- clean_text phải ngắn gọn, bám nguồn, không paraphrase quá mạnh.
- source_spans phải là trích đoạn nguyên văn hoặc gần nguyên văn từ chunk thô.

Chunk id: {chunk_id}
Topic hiện có: {topic}
Draft deterministic:
{draft}

Raw chunk:
{raw}

Trả về JSON một dòng đúng schema:
{{"title":"...","topic":"...","subtopics":[],"clean_text":"...","key_definitions":[],"key_formulas":[],"key_theorems":[],"worked_examples":[],"questionable_skills":[],"misconceptions":[],"math_objects":[],"source_spans":[],"quality":{{"is_usable":true,"noise_level":"low","math_density":0.0,"generation_value":0.0}}}}
Không bọc markdown, không thêm chú thích.'''


def dataset_fingerprint(dataset: Dict[str, Any]) -> str:
    h = hashlib.sha256()
    for chunk_id, chunk in _iter_chunks(dataset):
        h.update(chunk_id.encode('utf-8', errors='ignore'))
        h.update(str(chunk.get('topic', '')).encode('utf-8', errors='ignore'))
        h.update(str(chunk.get('context', '')).encode('utf-8', errors='ignore'))
    return h.hexdigest()[:16]


def build_clean_contexts(
    dataset: Dict[str, Any],
    *,
    source_name: str = '',
    use_llm: bool = cfg.CLEAN_CONTEXT_USE_LLM,
) -> Dict[str, Any]:
    contexts: Dict[str, Any] = {
        'metadata': {
            'source': source_name or (dataset.get('metadata') or {}).get('source', ''),
            'dataset_fingerprint': dataset_fingerprint(dataset),
            'builder': 'chunk_context_builder',
            'llm_enabled': bool(use_llm and cfg.has_llm_api_key()),
        }
    }
    for chunk_id, chunk in _iter_chunks(dataset):
        contexts[chunk_id] = clean_context_for_chunk(chunk_id, chunk, use_llm=use_llm)
    contexts['metadata']['num_contexts'] = len(contexts) - 1
    type_counts: Dict[str, int] = {}
    for key, value in contexts.items():
        if key == 'metadata':
            continue
        if isinstance(value, dict):
            ctype = str(value.get('chunk_type') or 'unknown')
            type_counts[ctype] = type_counts.get(ctype, 0) + 1
    contexts['metadata']['chunk_type_distribution'] = type_counts
    return contexts


def attach_clean_contexts(dataset: Dict[str, Any], clean_contexts: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {'metadata': dict(dataset.get('metadata') or {})}
    meta = clean_contexts.get('metadata') or {}
    out['metadata']['clean_contexts'] = {
        'available': True,
        'num_contexts': meta.get('num_contexts', 0),
        'dataset_fingerprint': meta.get('dataset_fingerprint', ''),
        'chunk_type_distribution': meta.get('chunk_type_distribution', {}),
    }
    for key, value in dataset.items():
        if key == 'metadata':
            continue
        if not isinstance(value, dict) or 'context' not in value:
            out[key] = value
            continue
        doc = dict(value)
        raw_context = doc.get('raw_context') or doc.get('context') or ''
        clean = clean_contexts.get(key)
        if isinstance(clean, dict):
            doc['raw_context'] = raw_context
            doc['clean_context'] = clean
            doc['context'] = render_clean_context(clean)
            doc['topic'] = clean.get('topic') or doc.get('topic') or ''
        out[key] = doc
    return out


def clean_context_for_chunk(
    chunk_id: str,
    chunk: Dict[str, Any],
    neighbors: Optional[List[Dict[str, Any]]] = None,
    *,
    use_llm: bool = True,
) -> Dict[str, Any]:
    raw = str(chunk.get('raw_context') or chunk.get('context') or '')
    topic = str(chunk.get('topic') or '')
    deterministic = _deterministic_clean_context(chunk_id, topic, raw)
    if not use_llm or not cfg.has_llm_api_key() or not deterministic['quality']['is_usable']:
        return deterministic
    try:
        improved = _llm_clean_context(chunk_id, topic, raw, deterministic)
    except BudgetExceeded:
        raise
    except Exception:
        return deterministic
    return _merge_clean_context(chunk_id, topic, deterministic, improved)


def render_clean_context(clean: Dict[str, Any]) -> str:
    parts: List[str] = []
    title = clean.get('title') or clean.get('topic') or ''
    if title:
        parts.append(f'Title: {title}')
    topic = clean.get('topic') or ''
    if topic and topic != title:
        parts.append(f'Topic: {topic}')
    chunk_type = clean.get('chunk_type') or ''
    if chunk_type:
        parts.append(f'Chunk type: {chunk_type}')
        if chunk_type == 'exercise':
            parts.append(
                'Use note: source contains existing exercises; generate new numbers/situations, do not paraphrase them.'
            )
    for label, key in (
        ('Key definitions', 'key_definitions'),
        ('Key formulas', 'key_formulas'),
        ('Key theorems', 'key_theorems'),
        ('Worked examples', 'worked_examples'),
        ('Questionable skills', 'questionable_skills'),
        ('Misconceptions', 'misconceptions'),
        ('Math objects', 'math_objects'),
        ('Source quote candidates', 'source_spans'),
    ):
        items = _string_list(clean.get(key))[:MAX_LIST_ITEMS]
        if items:
            parts.append(label + ':\n' + '\n'.join(f'- {item}' for item in items))
    clean_text = str(clean.get('clean_text') or '').strip()
    if clean_text:
        parts.append('Clean context text:\n' + clean_text)
    return '\n\n'.join(parts).strip()


def _iter_chunks(dataset: Dict[str, Any]):
    for key, value in dataset.items():
        if key != 'metadata' and isinstance(value, dict) and 'context' in value:
            yield key, value


def _deterministic_clean_context(chunk_id: str, topic: str, raw: str) -> Dict[str, Any]:
    text = _normalize_text(raw)
    chunk_type = classify_chunk_text(text)
    existing_question_spans = _existing_question_spans(text)
    extraction_text = (
        _strip_existing_questions_for_generation(text)
        if chunk_type == 'exercise' else text
    )
    key_lines = _key_lines(extraction_text)
    definitions = _pick_by_regex(key_lines, _DEFINITION_RE)
    formulas = _pick_by_regex(key_lines, _FORMULA_RE)
    theorems = _pick_by_regex(key_lines, _THEOREM_RE)
    examples = _pick_by_regex(key_lines, _EXAMPLE_RE)
    source_spans = _source_spans(extraction_text, key_lines)
    if chunk_type == 'exercise':
        source_spans = [s for s in source_spans if not _looks_like_existing_question(s)]
    clean_text = trim_context_for_generation(
        '\n\n'.join(key_lines[:12]) or summarize_text(extraction_text, MAX_CLEAN_TEXT_CHARS),
        {'topic': topic},
        max_chars=MAX_CLEAN_TEXT_CHARS,
    )
    if not clean_text:
        clean_text = extraction_text[:MAX_CLEAN_TEXT_CHARS].strip()
    if chunk_type == 'exercise':
        clean_text = _remove_overlapping_source_text(clean_text, existing_question_spans)
        source_spans = [
            s for s in source_spans
            if not _overlaps_existing_question(s, existing_question_spans)
        ][:MAX_SOURCE_SPANS]
    math_density = _math_density(text)
    noise_level = _noise_level(raw, text)
    generation_value = _generation_value(clean_text, key_lines, math_density, noise_level)
    if chunk_type == 'exercise':
        generation_value *= 0.45
    return {
        'chunk_id': chunk_id,
        'chunk_type': chunk_type,
        'existing_question_spans': existing_question_spans,
        'title': topic or _first_good_line(text),
        'topic': topic or _first_good_line(text) or 'Chưa rõ chủ đề',
        'subtopics': [],
        'clean_text': clean_text,
        'key_definitions': definitions,
        'key_formulas': formulas,
        'key_theorems': theorems,
        'worked_examples': examples,
        'questionable_skills': _questionable_skills(text),
        'misconceptions': [],
        'math_objects': _math_objects(text),
        'source_spans': source_spans,
        'quality': {
            'is_usable': bool(clean_text and (len(clean_text) >= 80 or bool(key_lines)) and noise_level != 'high'),
            'noise_level': noise_level,
            'math_density': round(math_density, 3),
            'generation_value': round(generation_value, 3),
        },
    }


def _llm_clean_context(chunk_id: str, topic: str, raw: str, draft: Dict[str, Any]) -> Dict[str, Any]:
    user = _USER.format(
        chunk_id=chunk_id,
        topic=topic or '(không rõ)',
        draft=json.dumps(draft, ensure_ascii=False)[:3500],
        raw=strip_markdown(raw)[:4500],
    )
    response = call_llm(_SYSTEM, user, model=cfg.JUDGE_MODEL, temperature=0.1, max_tokens=1400, retries=2)
    raw_json = re.sub(r'^```(?:json)?\s*|\s*```$', '', response.strip())
    try:
        obj = json.loads(raw_json)
    except Exception:
        m = re.search(r'\{.*\}', raw_json, re.DOTALL)
        if not m:
            raise ValueError('clean context JSON not found')
        obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError('clean context JSON is not an object')
    return obj


def _merge_clean_context(chunk_id: str, topic: str, fallback: Dict[str, Any], obj: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(fallback)
    for key in (
        'title', 'topic', 'clean_text', 'subtopics', 'key_definitions', 'key_formulas',
        'key_theorems', 'worked_examples', 'questionable_skills', 'misconceptions',
        'math_objects', 'source_spans', 'quality', 'chunk_type', 'existing_question_spans',
    ):
        if key in obj and obj[key] not in (None, '', []):
            out[key] = obj[key]
    out['chunk_id'] = chunk_id
    if out.get('chunk_type') not in {'theory', 'example', 'exercise'}:
        out['chunk_type'] = fallback.get('chunk_type') or 'theory'
    out['topic'] = str(out.get('topic') or topic or fallback.get('topic') or 'Chưa rõ chủ đề')[:140]
    out['title'] = str(out.get('title') or out['topic'])[:160]
    out['clean_text'] = strip_markdown(str(out.get('clean_text') or fallback.get('clean_text') or ''))[:MAX_CLEAN_TEXT_CHARS]
    if out.get('chunk_type') == 'exercise':
        out['clean_text'] = _strip_existing_questions_for_generation(out['clean_text'])[:MAX_CLEAN_TEXT_CHARS]
    for key in ('subtopics', 'key_definitions', 'key_formulas', 'key_theorems', 'worked_examples', 'questionable_skills', 'misconceptions', 'math_objects', 'source_spans'):
        out[key] = _string_list(out.get(key))[:MAX_LIST_ITEMS]
    if out.get('chunk_type') == 'exercise':
        out['source_spans'] = [
            item for item in out.get('source_spans', [])
            if (
                not _looks_like_existing_question(item)
                and not _overlaps_existing_question(item, out.get('existing_question_spans') or [])
            )
        ][:MAX_SOURCE_SPANS]
        out['clean_text'] = _remove_overlapping_source_text(
            out['clean_text'],
            out.get('existing_question_spans') or [],
        )[:MAX_CLEAN_TEXT_CHARS]
    out['existing_question_spans'] = _string_list(out.get('existing_question_spans'))[:MAX_EXISTING_QUESTION_SPANS]
    quality = out.get('quality') if isinstance(out.get('quality'), dict) else {}
    fallback_q = fallback.get('quality') or {}
    noise = quality.get('noise_level') if quality.get('noise_level') in {'low', 'medium', 'high'} else fallback_q.get('noise_level', 'medium')
    out['quality'] = {
        'is_usable': bool(quality.get('is_usable', fallback_q.get('is_usable', True))) and bool(out['clean_text']),
        'noise_level': noise,
        'math_density': _safe_float(quality.get('math_density'), fallback_q.get('math_density', 0.0)),
        'generation_value': _safe_float(quality.get('generation_value'), fallback_q.get('generation_value', 0.0)),
    }
    return out


def _normalize_text(text: str) -> str:
    s = strip_markdown(text)
    lines: List[str] = []
    for raw in s.splitlines():
        line = raw.strip()
        if not line:
            if lines and lines[-1] != '':
                lines.append('')
            continue
        if _PAGE_LINE_RE.match(line) or _DOT_LEADER_RE.search(line):
            continue
        line = re.sub(r'^[•●▪▫–—-]\s*', '- ', line)
        line = re.sub(r'\s+', ' ', line).strip()
        lines.append(line)
    merged: List[str] = []
    for line in lines:
        if not line:
            if merged and merged[-1] != '':
                merged.append('')
            continue
        if merged and merged[-1] and _should_join(merged[-1], line):
            merged[-1] = f'{merged[-1]} {line}'.strip()
        else:
            merged.append(line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(merged)).strip()


def _fold_ascii(text: str) -> str:
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    norm = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in norm if not unicodedata.combining(ch)).lower()


def classify_chunk_text(text: str) -> str:
    """Classify clean-context risk without LLM: theory, example, or exercise."""
    folded = _fold_ascii(text)
    option_lines = sum(1 for line in text.splitlines() if _OPTION_LINE_RE.search(line))
    inline_options = 1 if _INLINE_OPTIONS_RE.search(text) else 0
    question_markers = len(re.findall(r'\b(?:cau|c.u|bai|b.i|question|exercise)\s*\d+[\.:)]?', folded))
    exercise_markers = len(re.findall(
        r'\b(?:chon|dap an|trac nghiem|phuong an|bai tap|exercise|multiple choice)\b',
        folded,
    ))
    example_markers = len(re.findall(
        r'\b(?:vi du|loi giai|bai toan mau|example|worked example)\b',
        folded,
    ))
    theory_markers = len(re.findall(
        r'\b(?:dinh nghia|dinh ly|he qua|cong thuc|nhan xet|chu y|theorem|definition|formula)\b',
        folded,
    ))

    if option_lines >= 3 or inline_options or question_markers >= 2 or (
        question_markers >= 1
        and (
            exercise_markers >= 1
            or _QUESTION_COMMAND_FOLD_RE.search(folded)
            or len(text) >= 120
        )
    ):
        return 'exercise'
    if example_markers >= 1 and option_lines < 3:
        return 'example'
    if theory_markers >= 1 or _FORMULA_RE.search(text):
        return 'theory'
    return 'theory'


def _existing_question_spans(text: str) -> List[str]:
    spans: List[str] = []
    markers = list(_QUESTION_MARKER_RE.finditer(text or ''))
    for i, marker in enumerate(markers):
        start = marker.start()
        next_start = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        end = min(next_start, start + 420)
        s = re.sub(r'\s+', ' ', text[start:end]).strip()
        if s and _looks_like_existing_question(s):
            spans.append(s[:420])
        if len(spans) >= MAX_EXISTING_QUESTION_SPANS:
            return _dedupe(spans)

    blocks: List[List[str]] = []
    current: List[str] = []
    for line in text.splitlines():
        folded = _fold_ascii(line)
        starts_question = bool(re.match(r'\s*(?:cau|c.u|bai|b.i|question|exercise)\s*\d+[\.:)]?', folded))
        if starts_question and current:
            blocks.append(current)
            current = []
        if starts_question or current:
            current.append(line)
    if current:
        blocks.append(current)
    for block in blocks:
        s = re.sub(r'\s+', ' ', ' '.join(block)).strip()
        if not s:
            continue
        folded = _fold_ascii(s)
        if _INLINE_OPTIONS_RE.search(s) or re.search(r'\b(?:chon|dap an|phuong an)\b', folded):
            spans.append(s[:420])
        elif re.search(r'\b(?:cau|c.u|bai|b.i)\s*\d+', folded):
            spans.append(s[:420])
        if len(spans) >= MAX_EXISTING_QUESTION_SPANS:
            break
    return _dedupe(spans)


def _strip_existing_questions_for_generation(text: str) -> str:
    """Keep formulas/context signals but remove full exercise stems/options."""
    kept: List[str] = []
    skip_block = False
    text = _INLINE_OPTIONS_RE.sub('', text or '')
    paragraphs = re.split(r'\n\s*\n+', text)
    for para in paragraphs:
        if _has_question_marker(para):
            kept.extend(_salvage_learning_fragments(para))
            skip_block = False
            continue
        for raw in para.splitlines():
            line = raw.strip()
            if not line:
                skip_block = False
                continue
            folded = _fold_ascii(line)
            if _has_question_marker(line):
                skip_block = True
                kept.extend(_salvage_learning_fragments(line))
                continue
            if _OPTION_LINE_RE.search(line) or re.search(r'\b(?:dap an|chon phuong an|chon dap an)\b', folded):
                continue
            if skip_block and not (
                _FORMULA_RE.search(line)
                or _CONCEPT_OR_SOLUTION_FOLD_RE.search(folded)
            ):
                continue
            kept.append(line)
    cleaned = '\n'.join(kept)
    cleaned = _INLINE_OPTIONS_RE.sub('', cleaned)
    return re.sub(r'\n{3,}', '\n\n', cleaned).strip()

def _has_question_marker(text: str) -> bool:
    if not text:
        return False
    if _QUESTION_MARKER_RE.search(text):
        return True
    folded = _fold_ascii(text)
    return re.search(r'\b(?:cau|c.u|bai|b.i|question|exercise)\s*\d+[\.:)]?', folded) is not None

def _salvage_learning_fragments(text: str) -> List[str]:
    """Return formula/concept fragments from an exercise block, not the stem."""
    out: List[str] = []
    for raw in re.split(r'(?<=[.!?])\s+|\n+', text or ''):
        line = raw.strip()
        if not line:
            continue
        folded = _fold_ascii(line)
        if _looks_like_existing_question(line):
            continue
        if _QUESTION_COMMAND_FOLD_RE.search(folded) and not _CONCEPT_OR_SOLUTION_FOLD_RE.search(folded):
            continue
        if not (_FORMULA_RE.search(line) or _CONCEPT_OR_SOLUTION_FOLD_RE.search(folded)):
            continue
        scrubbed = _scrub_prompt_like_text(line)
        if scrubbed and not _looks_like_existing_question(scrubbed):
            out.append(scrubbed)
    return _dedupe(out)[:MAX_LIST_ITEMS]


def _looks_like_existing_question(text: str) -> bool:
    folded = _fold_ascii(text)
    return bool(
        _has_question_marker(text)
        or _INLINE_OPTIONS_RE.search(text)
        or _QUESTION_COMMAND_FOLD_RE.search(folded)
    )


def _scrub_prompt_like_text(line: str) -> str:
    line = re.sub(r'^\s*(?:Câu|Bài|C.u|B.i|Question|Exercise)\s*\d+[\.:)]?\s*', '', line, flags=re.I)
    line = _INLINE_OPTIONS_RE.sub('', line)
    return line.strip()


def _should_join(prev: str, line: str) -> bool:
    if len(prev) < 120 and not re.search(r'[.!?:;)]$', prev):
        return True
    if _FORMULA_RE.search(prev) and _FORMULA_RE.search(line) and len(line) < 100:
        return True
    if re.match(r'^[,.;:=+\-*/^≤≥<>)]', line):
        return True
    return False


def _key_lines(text: str) -> List[str]:
    items: List[str] = []
    for unit in re.split(r'\n+|(?<=[.!?])\s+', text):
        s = re.sub(r'\s+', ' ', unit).strip()
        if 12 <= len(s) <= 420 and _KEY_LINE_RE.search(s):
            items.append(s)
        if len(items) >= 24:
            break
    if not items:
        items = extract_key_passages(text, max_items=12)
    return _dedupe(items)


def _pick_by_regex(lines: List[str], pattern: re.Pattern[str]) -> List[str]:
    return [line for line in lines if pattern.search(line)][:MAX_LIST_ITEMS]


def _source_spans(text: str, key_lines: List[str]) -> List[str]:
    spans = key_lines[:MAX_SOURCE_SPANS]
    if len(spans) < 3:
        for para in re.split(r'\n\s*\n+', text):
            p = re.sub(r'\s+', ' ', para).strip()
            if 40 <= len(p) <= 320:
                spans.append(p)
            if len(spans) >= MAX_SOURCE_SPANS:
                break
    return _dedupe(spans)[:MAX_SOURCE_SPANS]

def _remove_overlapping_source_text(text: str, existing_spans: List[str]) -> str:
    if not text or not existing_spans:
        return text or ''
    kept: List[str] = []
    for line in re.split(r'\n+|(?<=[.!?])\s+', text):
        s = re.sub(r'\s+', ' ', line).strip()
        if not s:
            continue
        if _overlaps_existing_question(s, existing_spans):
            continue
        kept.append(s)
    return '\n'.join(_dedupe(kept)).strip()

def _overlaps_existing_question(text: str, existing_spans: List[str],
                                min_ratio: float = 0.62) -> bool:
    tokens = _content_tokens_for_overlap(text)
    if len(tokens) < 5:
        return False
    for span in existing_spans or []:
        span_tokens = _content_tokens_for_overlap(str(span or ''))
        if len(span_tokens) < 5:
            continue
        containment = len(tokens & span_tokens) / max(1, len(tokens))
        if containment >= min_ratio:
            return True
    return False

def _content_tokens_for_overlap(text: str) -> set[str]:
    folded = _fold_ascii(text)
    stop = {
        'cau', 'bai', 'hoi', 'cho', 'chon', 'dap', 'an', 'dung', 'sai',
        'mot', 'cac', 'trong', 'sau', 'la', 'co', 'voi', 'duoc', 'hay',
        'tinh', 'tim', 'phuong', 'page', 'summary', 'context',
    }
    return {
        tok for tok in re.findall(r'[a-z0-9]{3,}', folded)
        if tok not in stop
    }


def _math_density(text: str) -> float:
    if not text:
        return 0.0
    hits = len(re.findall(r'(?:[=≤≥<>]|\\frac|\\sqrt|√|∑|∫|\^|\bmod\b|\bC\s*\(|\d)', text))
    return min(1.0, hits / max(20.0, len(text) / 35.0))


def _noise_level(raw: str, clean: str) -> str:
    if not raw.strip() or len(clean) < 50:
        return 'high'
    dot_ratio = raw.count('.') / max(1, len(raw))
    weird = sum(1 for ch in raw if ord(ch) == 0xfffd or ch == '\x00') / max(1, len(raw))
    private_use = sum(1 for ch in raw if unicodedata.category(ch) == 'Co') / max(1, len(raw))
    alpha = sum(1 for ch in clean if ch.isalpha())
    symbol = sum(1 for ch in clean if not ch.isalnum() and not ch.isspace())
    if (
        dot_ratio > 0.18
        or weird > 0.01
        or private_use > 0.05
        or (alpha > 0 and symbol / alpha > 0.7)
    ):
        return 'high'
    if dot_ratio > 0.08 or private_use > 0.02 or (alpha > 0 and symbol / alpha > 0.35):
        return 'medium'
    return 'low'


def _generation_value(clean_text: str, key_lines: List[str], math_density: float, noise_level: str) -> float:
    score = 0.25 if len(clean_text) >= 180 else 0.0
    score += min(0.35, len(key_lines) * 0.04)
    score += min(0.25, math_density * 0.4)
    score += {'low': 0.15, 'medium': 0.08, 'high': -0.2}.get(noise_level, 0.0)
    return max(0.0, min(1.0, score))


def _questionable_skills(text: str) -> List[str]:
    out: List[str] = []
    folded = text.lower()
    patterns = [
        ('nhận diện định nghĩa/công thức', r'định\s+nghĩa|công\s+thức'),
        ('áp dụng định lý', r'định\s+lý|hệ\s+quả'),
        ('tính toán theo ví dụ', r'ví\s+dụ|lời\s+giải'),
        ('suy luận với ký hiệu toán', r'[=≤≥<>]|\^|\bmod\b'),
    ]
    for label, pat in patterns:
        if re.search(pat, folded, re.I):
            out.append(label)
    return out[:MAX_LIST_ITEMS]


def _math_objects(text: str) -> List[str]:
    candidates = re.findall(r'\b(?:ma trận|đồ thị|cây|tập hợp|hoán vị|chỉnh hợp|tổ hợp|xác suất|mệnh đề|hàm số|phương trình|vector|không gian)\b', text, re.I)
    return _dedupe([c.lower() for c in candidates])[:MAX_LIST_ITEMS]


def _first_good_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if 12 <= len(s) <= 140 and sum(ch.isalpha() for ch in s) >= len(s) * 0.45:
            return s
    return ''


def _dedupe(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        s = re.sub(r'\s+', ' ', str(item)).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, dict):
            text = item.get('text') or item.get('name') or item.get('description') or item.get('id') or json.dumps(item, ensure_ascii=False)
        else:
            text = str(item)
        text = re.sub(r'\s+', ' ', text).strip()
        if text:
            out.append(text[:420])
    return _dedupe(out)


def _safe_float(value: Any, fallback: Any = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return float(fallback)
        except (TypeError, ValueError):
            return 0.0

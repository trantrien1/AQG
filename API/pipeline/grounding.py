"""Grounding & Quality Judge (mục 16).

Kiểm tra:
1. Grounding: mọi sự kiện trong stem/explanation có trong source_chunks không.
2. Quality: rubric chấm tổng quát (rõ ràng, đúng cognitive_level, etc.).
3. NLI: prob(answer | context) − prob(distractor | context) > margin.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict

from . import config as cfg
from .llm_client import call_llm


def _parse_json_score(text: str, key: str, default: float = 0.5) -> float:
    try:
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
        obj = json.loads(text)
        return float(obj.get(key, default))
    except Exception:
        m = re.search(rf'"{key}"\s*:\s*([0-9.]+)', text)
        return float(m.group(1)) if m else default


_NUMBER_RE = re.compile(r'(?<![\w.])-?\d+(?:[.,]\d+)?(?![\w.])')
_SAFE_GENERATED_NUMBERS = {'0', '1', '2'}


def _normalize_number_token(token: str) -> str:
    return token.replace(',', '.').strip()


def unsupported_stem_numbers(context: str, response: Dict[str, Any]) -> list[str]:
    """Return numeric literals present in the stem but absent from source context."""
    stem = response.get('question_text', '') or ''
    stem_nums = {
        _normalize_number_token(x)
        for x in _NUMBER_RE.findall(stem)
    } - _SAFE_GENERATED_NUMBERS
    if not stem_nums:
        return []
    ctx_nums = {
        _normalize_number_token(x)
        for x in _NUMBER_RE.findall(context or '')
    }
    return sorted(n for n in stem_nums if n not in ctx_nums)


def directional_contradiction(context: str, response: Dict[str, Any]) -> str | None:
    """Catch simple local contradictions around increase/decrease/no-change claims."""
    answer = (response.get('answer_text', '') or '').lower()
    stem = (response.get('question_text', '') or '').lower()
    ctx = _normalize_quote_text(context).lower()

    quantity_words = r'(tổng\s+chi\s+phí|chi\s+phí|độ\s+dài|giá\s+trị)'
    no_change = r'không\s+(?:bị\s+)?(?:thay\s+đổi|đổi)'
    answer_claims_quantity_unchanged = (
        re.search(quantity_words + r'.{0,50}' + no_change, answer)
        or re.search(no_change + r'.{0,50}' + quantity_words, answer)
    )
    stem_asks_quantity = re.search(quantity_words, stem) is not None
    context_says_quantity_changes = (
        re.search(quantity_words + r'.{0,80}(giảm|tăng)', ctx)
        or re.search(r'(giảm|tăng).{0,80}' + quantity_words, ctx)
    )
    if answer_claims_quantity_unchanged and stem_asks_quantity and context_says_quantity_changes:
        return 'answer says a quantity is unchanged while context says it changes'

    compact_ctx = re.sub(r'\s+', '', ctx)
    text = f'{stem}\n{answer}'
    weakens_strict_bound = (
        '>f' in compact_ctx
        and (
            re.search(r'(>=|≥)\s*f', text)
            or re.search(r'lớn\s+hơn\s+hoặc\s+bằng.{0,30}f', text)
        )
    )
    if weakens_strict_bound:
        return 'answer/stem weakens strict pruning condition > f to >= f'
    return None


_GROUNDING_SYS = (
    'Bạn là chuyên gia kiểm tra grounding cho đề kiểm tra Toán. '
    'Bạn HIỂU rõ kiến thức Toán nền (đại số, đạo hàm, tích phân, lượng giác, '
    'tổ hợp, xác suất, hình học, logic, đồ thị) là kiến thức phổ thông; KHÔNG '
    'yêu cầu mọi biến đổi đại số, đạo hàm/tích phân cơ bản, tính toán nền '
    'phải xuất hiện nguyên văn trong ngữ cảnh.'
)

_GROUNDING_USER = '''Chấm grounding của câu hỏi Toán so với ngữ cảnh tài liệu.

NGUYÊN TẮC MATH-AWARE:
- Câu hỏi PHẢI bám CHỦ ĐỀ / ĐỊNH NGHĨA / ĐỊNH LÝ / VÍ DỤ / CÔNG THỨC chính trong ngữ cảnh.
- Cho phép dùng kiến thức Toán nền phổ thông (biến đổi đại số, đạo hàm/tích phân cơ bản, lượng giác, hằng đẳng thức, tính toán) MÀ KHÔNG cần xuất hiện verbatim trong ngữ cảnh.
- Cho phép thay số/đặt ví dụ minh họa miễn là đúng dạng bài tài liệu đang dạy.
- KHÔNG cap điểm chỉ vì source quote là paraphrase nhẹ — nếu nội dung quote khớp ý ngữ cảnh thì xem như có chứng cứ.

CHỈ TRỪ ĐIỂM MẠNH (grounding < 0.5) khi:
1. Câu hỏi hỏi NGOÀI chủ đề/khái niệm tài liệu đề cập.
2. Dùng định lý / công thức ĐẶC THÙ / phi-cơ-bản KHÔNG có trong ngữ cảnh.
3. Đáp án hoặc lời giải MÂU THUẪN với ngữ cảnh.
4. Source quote không liên quan tới ngữ cảnh.
5. Hoàn toàn không có căn cứ topic/skill chính trong tài liệu.

Cho điểm 0..1 dựa trên 4 sub-score (mỗi cái 0..1):
- topic_support: chủ đề/định nghĩa chính được hỗ trợ trong ngữ cảnh
- formula_support: công thức/định lý dùng được hỗ trợ HOẶC là kiến thức Toán nền phổ thông
- consistency: không mâu thuẫn với ngữ cảnh
- quote_relevance: source quote thật sự liên quan

Ngữ cảnh:
{context}

Câu hỏi: {question}
Đáp án: {answer}
Giải thích: {explanation}
Source quote: {source_quote}

Trả về JSON đúng schema:
{{
  "topic_support": <float 0..1>,
  "formula_support": <float 0..1>,
  "consistency": <float 0..1>,
  "quote_relevance": <float 0..1>,
  "grounding": <float 0..1 — aggregate>,
  "issues": "<mô tả ngắn>"
}}'''


_QUALITY_SYS = 'Bạn là chuyên gia chấm chất lượng MCQ giáo dục.'

_QUALITY_USER = '''Chấm chất lượng câu MCQ sau theo rubric:
- Rõ ràng, không mơ hồ
- Đúng mức nhận thức yêu cầu
- Đáp án và lời giải nhất quán, đúng toán học
- Distractor có lý, không tầm thường
- Chỉ có MỘT đáp án đúng. Nếu một distractor cũng đúng, đúng trong trường hợp biên, hoặc làm câu hỏi mơ hồ thì quality <= 0.5

Chủ đề: {topic}
Mức nhận thức yêu cầu: {cognitive_level}

Câu hỏi: {question}
Đáp án: {answer}
Giải thích: {explanation}
Distractors:
{distractors}

Trả về JSON: {{"quality": <float 0..1>}}'''


_QUALITY_AUDIT_CRITERIA = '''\

Tiêu chí audit bắt buộc:
1. Format MCQ hợp lệ: stem không chứa A/B/C/D, có 1 đáp án đúng và đúng 3 distractor.
2. Ngôn ngữ: tiếng Việt rõ ràng, không lẫn markdown/code/cú pháp Python ở phần hiển thị.
3. Ngữ pháp: câu tự nhiên, không mơ hồ, không hỏi nhiều ý cùng lúc.
4. Liên quan nội dung gốc: stem, đáp án và giải thích phải bám trực tiếp topic/ngữ cảnh đã được grounding.
5. Tính đơn trị: chỉ một đáp án đúng; mọi distractor phải sai nhưng hợp lý.

Penalty:
- Nếu sai format hoặc có nhiều hơn một đáp án đúng: quality <= 0.4.
- Nếu không liên quan topic hoặc dùng kiến thức ngoài ngữ cảnh: quality <= 0.5.
- Nếu distractor quá lộ, trùng nghĩa với đáp án, hoặc không cùng loại với đáp án: quality <= 0.65.
'''


_NLI_SYS = 'Bạn là chuyên gia fact-checking. Đánh giá khả năng claim được hỗ trợ bởi document.'

_NLI_USER = '''Cho document, đánh giá xác suất (0..1) claim đúng và được hỗ trợ.

Document: {document}

Claim: {claim}

Trả về JSON: {{"prob": <float 0..1>}}'''


def quote_appears_in_context(quote: str, context: str,
                              min_overlap_ratio: float = 0.7) -> bool:
    """True nếu quote nằm sát trong context. Cho phép sai khác whitespace nhỏ.
    `min_overlap_ratio` để fallback khi quote không khớp 100%."""
    return find_supported_quote(quote, context, min_overlap_ratio) is not None


def _normalize_quote_text(text: str) -> str:
    text = text.strip().strip('"“”')
    # Strip markdown formatting for matching
    text = re.sub(r'\*{1,2}([^*]+?)\*{1,2}', r'\1', text)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'==>.*?<==', '', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s+([,.;:)\]}])', r'\1', text)
    text = re.sub(r'([({\[])\s+', r'\1', text)
    return text.strip()


# ==== Math symbol normalization ====
# Equate common math notations so paraphrase doesn't break grounding match.
_MATH_NORMALIZATION_TABLE = [
    # Unicode super/subscripts → ASCII
    ('²', '^2'), ('³', '^3'), ('⁴', '^4'), ('⁵', '^5'),
    ('⁶', '^6'), ('⁷', '^7'), ('⁸', '^8'), ('⁹', '^9'),
    ('₀', '_0'), ('₁', '_1'), ('₂', '_2'), ('₃', '_3'), ('₄', '_4'),
    # Binary operators / signs
    ('×', '*'), ('·', '*'), ('÷', '/'), ('−', '-'), ('–', '-'), ('—', '-'),
    # Equal-ish
    ('≡', '='), ('≈', '='), ('≃', '='), ('≅', '='),
    # Inequality
    ('≤', '<='), ('≥', '>='), ('≠', '!='),
    # Arrows
    ('→', '->'), ('⇒', '=>'), ('⟹', '=>'), ('⇔', '<=>'),
    # Greek letters (most common subset)
    ('π', 'pi'), ('Π', 'pi'), ('θ', 'theta'), ('Θ', 'theta'),
    ('α', 'alpha'), ('β', 'beta'), ('γ', 'gamma'), ('δ', 'delta'),
    ('λ', 'lambda'), ('μ', 'mu'), ('φ', 'phi'), ('Φ', 'phi'),
    ('σ', 'sigma'), ('Σ', 'sigma'), ('ω', 'omega'), ('Ω', 'omega'),
    ('∞', 'inf'), ('√', 'sqrt'), ('∑', 'sum'), ('∏', 'prod'),
    ('∫', 'int'), ('∂', 'd'),
    # Common notation aliases (for matching only)
    ('**', '^'),
]


def _normalize_math(text: str) -> str:
    """Normalize math notation for fuzzy matching. Idempotent."""
    if not text:
        return ''
    s = text
    for old, new in _MATH_NORMALIZATION_TABLE:
        s = s.replace(old, new)
    # Collapse spaces around operators so "x + 1" == "x+1" for matching
    s = re.sub(r'\s*([+\-*/^=<>])\s*', r'\1', s)
    s = re.sub(r'\s+', ' ', s)
    return s.strip().lower()


def _quote_tokens(text: str) -> list[str]:
    return re.findall(r'[A-Za-zÀ-ỹĐđ0-9]+', text.lower())


_TRACE_STOPWORDS = {
    'của', 'cho', 'với', 'khi', 'thì', 'một', 'các', 'những', 'được',
    'không', 'đúng', 'sai', 'đáp', 'án', 'the', 'and', 'for', 'with',
}


def distractor_context_trace(context: str, response: Dict[str, Any],
                             min_shared_tokens: int = 2) -> Dict[str, Any]:
    """Lightweight soft check: distractors should reuse source terms."""
    ctx_tokens = {
        t for t in _quote_tokens(context or '')
        if len(t) >= 3 and t not in _TRACE_STOPWORDS
    }
    details = []
    all_passed = True
    for i, d in enumerate(response.get('distractors', []), start=1):
        text = d.get('distractor_text', '') or ''
        tokens = {
            t for t in _quote_tokens(text)
            if len(t) >= 3 and t not in _TRACE_STOPWORDS
        }
        shared = sorted(tokens & ctx_tokens)
        ok = len(shared) >= min_shared_tokens
        if not ok:
            all_passed = False
        details.append({
            'index': i,
            'shared_tokens': shared[:8],
            'shared_count': len(shared),
            'passed': ok,
        })
    return {'passed': all_passed, 'details': details}


def _candidate_quote_spans(context: str) -> list[str]:
    text = _normalize_quote_text(context)
    parts = [
        p.strip()
        for p in re.split(r'(?<=[.!?])\s+|\n+', text)
        if len(p.strip()) >= 15
    ]
    spans: list[str] = []
    for i, part in enumerate(parts):
        spans.append(part)
        if i + 1 < len(parts):
            merged = f'{part} {parts[i + 1]}'.strip()
            if len(merged) <= 320:
                spans.append(merged)
    return spans


def find_supported_quote(quote: str, context: str,
                         min_overlap_ratio: float = 0.55) -> str | None:
    """Return a short context span supporting quote, or None.

    Math-aware fuzzy match:
    1. Try exact match after whitespace+markdown normalization.
    2. Try math-normalized match (x² == x^2, − == -, π == pi).
    3. Token-overlap fallback (Jaccard-style) over candidate spans.
    """
    if not quote or not context:
        return None
    q = _normalize_quote_text(quote)
    ctx = _normalize_quote_text(context)

    # Stage 1 — exact substring after whitespace normalization
    if q and q in ctx:
        return q

    # Stage 2 — math-normalized substring match (handles x² vs x^2 etc.)
    q_math = _normalize_math(q)
    ctx_math = _normalize_math(ctx)
    if q_math and len(q_math) >= 8 and q_math in ctx_math:
        # Find the matching span in original ctx (best-effort) and return that
        # original substring so the formatter shows source-preserving quote.
        idx = ctx_math.find(q_math)
        # Map back approximately by length proportion — good enough for display.
        approx_start = max(0, idx)
        approx_end = min(len(ctx), idx + len(q_math) + 30)
        return ctx[approx_start:approx_end].strip() or q

    # Stage 3 — token-overlap fallback over candidate spans
    q_tokens = _quote_tokens(q)
    if len(q_tokens) < 4:
        # Very short quote — only accept if math-normalized exact matched above.
        return None
    q_token_set = set(q_tokens)
    best_span = None
    best_score = 0.0
    for span in _candidate_quote_spans(context):
        if not (15 <= len(span) <= 320):
            continue
        s_tokens = set(_quote_tokens(span))
        if not s_tokens:
            continue
        score = len(q_token_set & s_tokens) / max(1, len(q_token_set))
        if score > best_score:
            best_score = score
            best_span = span
    if best_span and best_score >= min_overlap_ratio:
        return best_span
    return None


def quote_match_info(quote: str, context: str,
                     min_overlap_ratio: float = 0.55) -> Dict[str, Any]:
    """Detailed quote match — used to emit reject_reason='quote_mismatch'.

    Returns:
        {
          "match_type": "exact" | "math_normalized" | "fuzzy" | "failed",
          "quote_score": 0..1,
          "matched_span": <span or None>,
        }
    """
    if not quote or not context:
        return {'match_type': 'failed', 'quote_score': 0.0, 'matched_span': None}
    q = _normalize_quote_text(quote)
    ctx = _normalize_quote_text(context)
    if q and q in ctx:
        return {'match_type': 'exact', 'quote_score': 1.0, 'matched_span': q}
    q_math = _normalize_math(q)
    ctx_math = _normalize_math(ctx)
    if q_math and len(q_math) >= 8 and q_math in ctx_math:
        return {'match_type': 'math_normalized', 'quote_score': 0.9, 'matched_span': q}
    q_tokens = _quote_tokens(q)
    if len(q_tokens) < 4:
        return {'match_type': 'failed', 'quote_score': 0.0, 'matched_span': None}
    q_token_set = set(q_tokens)
    best_span = None
    best_score = 0.0
    for span in _candidate_quote_spans(context):
        if not (15 <= len(span) <= 320):
            continue
        s_tokens = set(_quote_tokens(span))
        if not s_tokens:
            continue
        score = len(q_token_set & s_tokens) / max(1, len(q_token_set))
        if score > best_score:
            best_score = score
            best_span = span
    if best_span and best_score >= min_overlap_ratio:
        return {
            'match_type': 'fuzzy',
            'quote_score': round(best_score, 3),
            'matched_span': best_span,
        }
    return {
        'match_type': 'failed',
        'quote_score': round(best_score, 3),
        'matched_span': None,
    }


def _with_skill(system: str, skill_instructions: str = '') -> str:
    skill_instructions = (skill_instructions or '').strip()
    if not skill_instructions:
        return system
    return f'{system}\n\nKỸ NĂNG ÁP DỤNG:\n{skill_instructions}'


def judge_grounding(
    context: str,
    response: Dict[str, Any],
    skill_instructions: str = '',
) -> float:
    """Math-aware grounding score.

    Soft penalty (not a hard cap) when source quote can't be matched to
    context. Aggregates the 4 sub-scores returned by the JUDGE_MODEL when
    available; otherwise falls back to legacy single-score JSON.
    """
    user = _GROUNDING_USER.format(
        context=context,
        question=response['question_text'],
        answer=response['answer_text'],
        explanation=response.get('answer_explanation_text', ''),
        source_quote=response.get('source_quote_text', '') or '(không có)',
    )
    raw = call_llm(_with_skill(_GROUNDING_SYS, skill_instructions),
                   user, model=cfg.JUDGE_MODEL,
                   temperature=0.0, max_tokens=300)

    raw_text = (raw or '').strip()
    raw_text = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw_text)
    try:
        obj = json.loads(raw_text)
    except Exception:
        m = re.search(r'\{.*\}', raw_text, re.DOTALL)
        try:
            obj = json.loads(m.group(0)) if m else {}
        except Exception:
            obj = {}

    base = float(obj.get('grounding') if isinstance(obj.get('grounding'), (int, float)) else _parse_json_score(raw_text, 'grounding', default=0.5))
    sub_scores = {
        k: float(obj.get(k))
        for k in ('topic_support', 'formula_support', 'consistency', 'quote_relevance')
        if isinstance(obj.get(k), (int, float))
    }
    if sub_scores:
        # When sub-scores exist, use weighted aggregate — topic_support and
        # consistency matter most for math grounding.
        weights = {'topic_support': 0.4, 'consistency': 0.3,
                   'formula_support': 0.15, 'quote_relevance': 0.15}
        agg = sum(sub_scores.get(k, base) * w for k, w in weights.items())
        # If LLM returned both, take the average to avoid surprises
        base = (base + agg) / 2

    # Quote handling: detect match type, soft penalty (not hard cap) for paraphrase
    quote = response.get('source_quote_text', '')
    quote_meta = quote_match_info(quote, context) if quote else {
        'match_type': 'failed', 'quote_score': 0.0, 'matched_span': None,
    }
    response['_quote_match_type'] = quote_meta['match_type']
    response['_quote_score'] = quote_meta['quote_score']
    response['_quote_in_context'] = quote_meta['match_type'] != 'failed'
    if quote_meta['matched_span']:
        response['source_quote_text'] = quote_meta['matched_span']

    # Penalty schedule (additive, not capping):
    #   exact            : no penalty
    #   math_normalized  : -0.02
    #   fuzzy            : -0.05 (was -0.0; now soft)
    #   failed (no quote): -0.10 (was hard cap to 0.5)
    #   failed (had quote but mismatch): -0.15 (was hard cap to 0.4)
    if not quote:
        base = max(0.0, base - 0.10)
    elif quote_meta['match_type'] == 'failed':
        base = max(0.0, base - 0.15)
    elif quote_meta['match_type'] == 'fuzzy':
        base = max(0.0, base - 0.05)
    elif quote_meta['match_type'] == 'math_normalized':
        base = max(0.0, base - 0.02)

    unsupported = unsupported_stem_numbers(context, response)
    response['_unsupported_stem_numbers'] = unsupported
    response['_grounding_subscores'] = sub_scores
    response['_grounding_issues'] = str(obj.get('issues') or '')[:300]
    return max(0.0, min(1.0, base))


def judge_quality(topic: str, cognitive_level: str, response: Dict[str, Any]) -> float:
    distractors = '\n'.join(
        f"- {d['distractor_text']} ({d.get('distractor_category_text','')})"
        for d in response.get('distractors', [])
    )
    user = _QUALITY_USER.format(
        topic=topic,
        cognitive_level=cognitive_level,
        question=response['question_text'],
        answer=response['answer_text'],
        explanation=response.get('answer_explanation_text', ''),
        distractors=distractors,
    ) + _QUALITY_AUDIT_CRITERIA
    raw = call_llm(_QUALITY_SYS, user, model=cfg.JUDGE_MODEL,
                   temperature=0.0, max_tokens=200)
    return _parse_json_score(raw, 'quality', default=0.5)


def judge_nli(document: str, claim: str) -> float:
    user = _NLI_USER.format(document=document, claim=claim)
    raw = call_llm(_NLI_SYS, user, model=cfg.JUDGE_MODEL,
                   temperature=0.0, max_tokens=100)
    return _parse_json_score(raw, 'prob', default=0.5)


# ==== Multi-trait rubric scoring (RMTS — NAACL 2025) ====

_MULTI_TRAIT_SYS = (
    'Bạn là chuyên gia chấm chất lượng MCQ Toán theo nhiều chiều. '
    'VIẾT RATIONALE NGẮN trước, rồi mới cho điểm — không đảo ngược thứ tự.'
)


_MULTI_TRAIT_USER = '''Đánh giá MCQ sau theo 5 tiêu chí, mỗi tiêu chí cho ĐIỂM 0..1 và RATIONALE ngắn 1 câu.

Tiêu chí:
1. clarity: stem rõ ràng, không mơ hồ, không hỏi nhiều ý.
2. cognitive_depth: chiều sâu tư duy phù hợp (mục tiêu khó {difficulty_target}).
3. bloom_alignment: stem + đáp án + distractor phải đúng mức Bloom "{cognitive_level}".
   - Nhận biết: chỉ nhớ/nhận diện sự kiện, định nghĩa.
   - Thông hiểu: giải thích, so sánh, nhận diện tính chất.
   - Vận dụng: tính toán, áp dụng công thức vào tình huống cụ thể.
   - Vận dụng cao: nhiều bước, suy luận sâu, tích hợp nhiều khái niệm, có bẫy misconception.
   Nếu lệch (ví dụ: yêu cầu Vận dụng cao nhưng câu chỉ là Nhận biết) → score thấp.
4. distractor_plausibility: 3 distractor đều SAI nhưng HỢP LÝ — học sinh dễ chọn nhầm.
5. answer_uniqueness: chỉ MỘT đáp án đúng; không distractor nào cũng đúng/đúng biên.

Câu hỏi: {question}
Đáp án đúng: {answer}
Giải thích: {explanation}
Distractors:
{distractors}

Trả về JSON đúng schema (rationale TRƯỚC score):
{{
 "clarity": {{"rationale":"...", "score":0.0}},
 "cognitive_depth": {{"rationale":"...", "score":0.0}},
 "bloom_alignment": {{"rationale":"...", "score":0.0}},
 "distractor_plausibility": {{"rationale":"...", "score":0.0}},
 "answer_uniqueness": {{"rationale":"...", "score":0.0}}
}}
Không bọc markdown.'''


def judge_multi_trait(topic: str, cognitive_level: str, difficulty_target: float,
                      response: Dict[str, Any],
                      skill_instructions: str = '') -> Dict[str, Any]:
    """RMTS-style: rationale-first, score-after, per trait.

    Trả dict {trait: {rationale, score}} cho 4 tiêu chí, plus aggregate
    `quality` = mean(scores).
    """
    distractors = '\n'.join(
        f"- {d['distractor_text']} ({d.get('distractor_category_text','')})"
        for d in response.get('distractors', [])
    )
    user = _MULTI_TRAIT_USER.format(
        cognitive_level=cognitive_level,
        difficulty_target=difficulty_target,
        question=response.get('question_text', ''),
        answer=response.get('answer_text', ''),
        explanation=response.get('answer_explanation_text', ''),
        distractors=distractors,
    )
    raw = call_llm(_with_skill(_MULTI_TRAIT_SYS, skill_instructions),
                   user, model=cfg.JUDGE_MODEL,
                   temperature=0.0, max_tokens=400)
    raw = (raw or '').strip()
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw)
    try:
        obj = json.loads(raw)
    except Exception:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        try:
            obj = json.loads(m.group(0)) if m else {}
        except Exception:
            obj = {}

    traits: Dict[str, Any] = {}
    scores: list[float] = []
    for key in ('clarity', 'cognitive_depth', 'bloom_alignment',
                'distractor_plausibility', 'answer_uniqueness'):
        info = obj.get(key) if isinstance(obj, dict) else None
        if isinstance(info, dict):
            score = info.get('score', 0.5)
            try:
                score = float(score)
            except Exception:
                score = 0.5
            score = max(0.0, min(1.0, score))
            traits[key] = {
                'score': score,
                'rationale': str(info.get('rationale', '')).strip()[:300],
            }
            scores.append(score)
        else:
            traits[key] = {'score': 0.5, 'rationale': ''}
            scores.append(0.5)
    aggregate = sum(scores) / len(scores) if scores else 0.5
    return {'traits': traits, 'quality': aggregate}

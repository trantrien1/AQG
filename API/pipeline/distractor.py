"""DistractorWriter — Stage 2 của pipeline 3-stage (CoE/EMNLP-2024 KNN).

Nhận stem + answer + reasoning từ QuestionWriter, sinh 3 distractor gắn với
misconception cụ thể. Tách concern: tập trung vào ĐỘ ĐÁNH LỪA và GẮN VỚI LỖI.

Khi không có inferred_misconceptions từ slot, fallback về `distractor_bank`.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from . import config as cfg
from . import distractor_bank
from .context_utils import strip_markdown
from .parsing import _extract, _sympy_to_natural
from .llm_client import BudgetExceeded, call_llm


_STOPWORDS = {
    'cua', 'của', 'cho', 'voi', 'với', 'khi', 'thi', 'thì', 'la', 'là',
    'mot', 'một', 'cac', 'các', 'nhung', 'những', 'duoc', 'được', 'khong',
    'không', 'dung', 'đúng', 'sai', 'dap', 'đáp', 'an', 'án',
}

def _clean_distractor_text(text: str, max_len: int = cfg.DISTRACTOR_OPTION_MAX_CHARS) -> str:
    """Keep distractor display text as a concise answer, not a derivation."""
    s = _sympy_to_natural(text or '')
    s = re.sub(r'\s+', ' ', s).strip().strip('"“”')
    if len(s) <= max_len:
        return s
    markers = [' do đó ', ' suy ra ', ' nên ', ' vậy ', ' = ']
    low = s.lower()
    for marker in markers:
        idx = low.rfind(marker)
        if idx >= 0:
            tail = s[idx + len(marker):].strip(' .;:')
            if 1 <= len(tail) <= max_len and re.search(r'[\dA-Za-zÀ-ỹ]', tail):
                return tail
    cut = max(s.rfind('.', 0, max_len), s.rfind(';', 0, max_len), s.rfind(',', 0, max_len))
    if cut < 40:
        cut = s.rfind(' ', 0, max_len)
    if cut < 40:
        cut = max_len
    return s[:cut].strip(' .;:,')

def _strip_latex_math_delimiters(text: str) -> str:
    s = (text or '').strip()
    if s.startswith(r'\(') and s.endswith(r'\)'):
        s = s[2:-2].strip()
    if s.startswith('$') and s.endswith('$'):
        s = s.strip('$').strip()
    return s


def _format_misconceptions(slot: Dict[str, Any]) -> str:
    items = _select_misconceptions(slot, k=6)
    if items:
        return '\n'.join(_format_one_misconception(m) for m in items)
    return '(không có)'


def _normalise_misconception(m: Dict[str, Any], i: int) -> Dict[str, str]:
    return {
        'id': str(m.get('id') or f'm_{i}').strip(),
        'wrong_form': str(m.get('wrong_form') or '').strip(),
        'rationale': str(m.get('rationale') or '').strip(),
    }


def _select_misconceptions(slot: Dict[str, Any], k: int = 3) -> List[Dict[str, str]]:
    seen = set()
    out: List[Dict[str, str]] = []
    inferred = slot.get('inferred_misconceptions') or []
    for i, raw in enumerate(inferred):
        if not isinstance(raw, dict):
            continue
        item = _normalise_misconception(raw, i)
        mid = item['id'] or item['wrong_form']
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(item)
        if len(out) >= k:
            return out
    items = distractor_bank.get_misconceptions(
        topic=slot.get('topic', ''), k=6,
        seed=hash(slot.get('slot_id', '')) & 0xffff,
    )
    for i, raw in enumerate(items, start=len(out)):
        item = _normalise_misconception(raw, i)
        mid = item['id'] or item['wrong_form']
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(item)
        if len(out) >= k:
            break
    return out


def _format_one_misconception(m: Dict[str, str]) -> str:
    return f"- [{m.get('id', '')}] {m.get('wrong_form', '')} — {m.get('rationale', '')}"


def _context_excerpt(
    context: str,
    candidate: Dict[str, Any],
    max_len: int = cfg.DISTRACTOR_CONTEXT_MAX_CHARS,
) -> str:
    quote = (candidate.get('source_quote_text') or '').strip()
    context = strip_markdown(context or '').strip()
    if quote and quote in context:
        start = max(0, context.find(quote) - 500)
        return context[start:start + max_len].strip()
    if quote:
        return quote[:max_len]
    return context[:max_len]

def _answer_shape_instruction(answer: str) -> str:
    """Prompt hint that keeps distractors in the same answer format."""
    ans = _strip_latex_math_delimiters(_sympy_to_natural(answer or '')).strip()
    compact = re.sub(r'\s+', '', ans)
    if re.fullmatch(r'[-+−]?\d+(?:[.,]\d+)?(?:/\d+(?:[.,]\d+)?)?', compact):
        shape = 'số thuần'
    elif (
        re.search(r'\\(?:frac|sqrt|binom|int|sum|prod|lim)\b', ans)
        or (
            re.fullmatch(r'[\dA-Za-zÀ-ỹĐđ\s+\-−*/^().,=]+', ans)
            and re.search(r'[+\-−*/^=()]', ans)
        )
    ):
        shape = 'biểu thức/công thức toán'
    elif re.fullmatch(r'[\[{(].*[\]})]', ans):
        shape = 'tập hợp/bộ giá trị'
    else:
        shape = 'cụm từ hoặc mệnh đề'
    return (
        f'Dạng đáp án đúng: {shape}. Distractor text phải cùng dạng này, '
        'ngắn gọn, tự đứng được, không kèm lời giải.'
    )

def _format_repair_feedback(feedback: Optional[List[str]]) -> str:
    if not feedback:
        return ''
    summarized = '\n'.join(f'- {item[:220]}' for item in feedback[-5:] if item)
    if not summarized:
        return ''
    return (
        '\n\nFeedback tu vong kiem tra truoc can sua trong distractor:\n'
        f'{summarized}\n'
        '- Neu bi option_text_sanity/iwf_format_consistency: chi tra ve text ngan, cung dang voi dap an dung.\n'
        '- Neu bi multi_answer/answer_uniqueness: moi distractor phai sai ro rang trong dung dieu kien cua stem.\n'
        '- Neu bi distractor_plausibility: tao loi sai hop ly gan voi misconception, khong tao dap an qua lo.\n'
    )


def _customization_directive_block(slot: Dict[str, Any]) -> str:
    gc_dict = slot.get('_generation_config') or {}
    if not gc_dict:
        return ''
    try:
        from .customization import GenerationConfig
        gc = GenerationConfig(**{
            k: v for k, v in gc_dict.items()
            if k in GenerationConfig.__dataclass_fields__
        })
    except Exception:
        return ''
    directive = gc.distractor_directive()
    if not directive:
        return ''
    return f'\n\nYêu cầu tùy chỉnh khi sinh distractor:\n{directive}\n'

def _is_plain_number(text: str) -> bool:
    compact = re.sub(
        r'\s+',
        '',
        _strip_latex_math_delimiters(_sympy_to_natural(text or '')),
    )
    return bool(re.fullmatch(r'[-+−]?\d+(?:[.,]\d+)?(?:/\d+(?:[.,]\d+)?)?', compact))

def _coerce_distractor_format(d: Dict[str, str], answer: str) -> Dict[str, str]:
    """Best-effort repair for numeric answers: keep option text numeric too."""
    if not _is_plain_number(answer):
        return d
    text = (d.get('distractor_text') or '').strip()
    if _is_plain_number(text):
        return d
    num_re = r'[-+−]?\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?'
    leading = re.match(rf'^\s*({num_re})\b', text)
    if leading:
        chosen = leading.group(1)
    elif '=' in text:
        tail_nums = re.findall(num_re, text.rsplit('=', 1)[-1])
        chosen = tail_nums[-1] if tail_nums else ''
    else:
        nums = re.findall(num_re, text)
        chosen = nums[0] if nums else ''
    if chosen:
        d = dict(d)
        d['distractor_text'] = re.sub(r'\s+', '', chosen)
    return d


def _forbidden_phrases(candidate: Dict[str, Any], limit: int = 12) -> List[str]:
    answer = _sympy_to_natural(candidate.get('answer_text', '') or '').strip()
    explanation = _sympy_to_natural(candidate.get('answer_explanation_text', '') or '')
    phrases: List[str] = []
    if 2 <= len(answer) <= 80:
        phrases.append(answer)

    text = f'{answer} {explanation}'
    mathish = re.findall(
        r'(?:[-+−]?\d+(?:[.,/]\d+)?(?:\^\d+)?|[A-Za-zÀ-ỹ]\w*\s*=\s*[^,.;]+)',
        text,
    )
    for token in mathish:
        token = token.strip()
        if 2 <= len(token) <= 60:
            phrases.append(token)

    for word in re.findall(r'[A-Za-zÀ-ỹĐđ]{4,}', answer.lower()):
        if word not in _STOPWORDS:
            phrases.append(word)

    out = []
    seen = set()
    for phrase in phrases:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(phrase)
        if len(out) >= limit:
            break
    return out


def _token_set(text: str) -> set[str]:
    return {
        t.lower()
        for t in re.findall(r'[A-Za-zÀ-ỹĐđ0-9]+', text or '')
        if len(t) > 1
    }


def _jaccard(a: str, b: str) -> float:
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _select_diverse(distractors: List[Dict[str, str]], target: int = 3) -> List[Dict[str, str]]:
    selected: List[Dict[str, str]] = []
    seen_text = set()
    seen_category = set()
    for d in distractors:
        text = re.sub(r'\s+', ' ', d.get('distractor_text', '')).strip()
        if not text:
            continue
        text_key = text.lower()
        if text_key in seen_text:
            continue
        category = (d.get('distractor_category_text') or '').strip().lower()
        if category and category in seen_category:
            continue
        if any(_jaccard(text, old.get('distractor_text', '')) >= 0.65 for old in selected):
            continue
        seen_text.add(text_key)
        if category:
            seen_category.add(category)
        selected.append(d)
        if len(selected) >= target:
            break
    return selected


def parse_distractor_response(text: str) -> List[Dict[str, str]]:
    """Parse output của Stage 2 — list 3 distractor."""
    distractors: List[Dict[str, str]] = []
    # Split theo "Distractor N:" hoặc "Distractor:" (chấp nhận biến thể)
    blocks = re.split(r'\n\s*Distractor\s*\d*\s*:\s*\n?', '\n' + text)
    for b in blocks:
        if not b.strip():
            continue
        cat = _extract(b, 'category:', 'explanation:')
        expl = _extract(b, 'explanation:', 'text:')
        # text: kéo dài đến cuối block — dùng regex đa dòng
        m = re.search(r'text\s*:\s*(.+?)(?:\n\s*Distractor|\Z)', b, re.DOTALL | re.IGNORECASE)
        d_text = m.group(1).strip() if m else ''
        if d_text:
                distractors.append({
                    'distractor_category_text': cat.strip(),
                    'distractor_explanation_text': _sympy_to_natural(expl.strip()),
                    'distractor_text': _clean_distractor_text(d_text),
                })
    return distractors[:3]


class DistractorWriter:
    """Stage 2: sinh 3 distractor gắn với misconception."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        skill_instructions: str = '',
    ):
        self.model = model_name or cfg.GENERATOR_MODEL
        self.system_prompt = cfg.DISTRACTOR_SYSTEM_PROMPT
        self.skill_instructions = skill_instructions.strip()
        if self.skill_instructions:
            self.system_prompt += f'\n\nKỸ NĂNG ÁP DỤNG:\n{self.skill_instructions}'

    def _build_prompt(self, candidate: Dict[str, Any],
                      slot: Dict[str, Any],
                      context: str = '',
                      feedback: Optional[List[str]] = None) -> str:
        forbidden = _forbidden_phrases(candidate)
        context_block = _context_excerpt(context, candidate)
        shape_hint = _answer_shape_instruction(candidate.get('answer_text', ''))
        customization = _customization_directive_block(slot)
        return cfg.DISTRACTOR_USER_PROMPT.format(
            question=candidate['question_text'],
            answer=candidate['answer_text'],
            explanation=candidate.get('answer_explanation_text', ''),
            misconceptions=_format_misconceptions(slot),
        ) + (
            '\n\nNgữ cảnh/quote nguồn để giữ trace cho distractor:\n'
            f'{context_block or "(không có)"}'
            '\n\nCụm liên quan đáp án cần tránh sao chép vào distractor:\n'
            + ('; '.join(forbidden) if forbidden else '(không có)')
            + customization
            + '\n\nRàng buộc text distractor: mỗi text tối đa 120 ký tự, là một đáp án hoàn chỉnh, '
            f'thực tế ưu tiên <= {cfg.DISTRACTOR_OPTION_MAX_CHARS} ký tự cho câu Toán; '
            'không viết lời giải dài trong text và không để câu bị cắt cụt.\n'
            + shape_hint
            + _format_repair_feedback(feedback)
        ) + '\n\n' + cfg.DISTRACTOR_OUTPUT_FORMAT

    def _build_single_prompt(
        self,
        candidate: Dict[str, Any],
        misconception: Dict[str, str],
        context: str = '',
        feedback: Optional[List[str]] = None,
    ) -> str:
        forbidden = _forbidden_phrases(candidate)
        context_block = _context_excerpt(context, candidate)
        shape_hint = _answer_shape_instruction(candidate.get('answer_text', ''))
        return (
            'Sinh CHÍNH XÁC 1 distractor cho câu hỏi sau, theo ĐÚNG misconception được giao.\n\n'
            f'Đề bài: {candidate["question_text"]}\n'
            f'Đáp án ĐÚNG: {candidate["answer_text"]}\n'
            f'Giải thích đáp án đúng: {candidate.get("answer_explanation_text", "")}\n\n'
            f'Misconception bắt buộc:\n{_format_one_misconception(misconception)}\n\n'
            'Ngữ cảnh/quote nguồn để giữ trace cho distractor:\n'
            f'{context_block or "(không có)"}\n\n'
            'Cụm liên quan đáp án cần tránh sao chép vào distractor:\n'
            f'{("; ".join(forbidden) if forbidden else "(không có)")}\n\n'
            'Yêu cầu: distractor phải sai, hợp lý, cùng kiểu với đáp án đúng, '
            'không phải mảnh câu cụt, không kèm lời giải trong text. '
            f'Mỗi text ưu tiên <= {cfg.DISTRACTOR_OPTION_MAX_CHARS} ký tự.\n'
            f'{shape_hint}\n\n'
            f'{_format_repair_feedback(feedback)}\n'
            'Trả về đúng định dạng:\n\n'
            'Distractor 1:\n'
            f'category: {misconception.get("id", "")}\n'
            'explanation: <vì sao distractor này sai>\n'
            'text: <nội dung distractor hiển thị cho học sinh>\n\n'
            'Không thêm markdown.'
        )

    def write(self, candidate: Dict[str, Any], slot: Dict[str, Any],
              context: str = '', max_attempts: int = 2,
              feedback: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """Trả về 3 distractor đã parse, hoặc list rỗng nếu fail toàn bộ attempts."""
        misconceptions = _select_misconceptions(slot, k=3)
        for attempt in range(max_attempts):
            prompt = self._build_prompt(candidate, slot, context, feedback=feedback)
            try:
                raw = call_llm(self.system_prompt, prompt, model=self.model)
                parsed = [
                    _coerce_distractor_format(d, candidate.get('answer_text', ''))
                    for d in parse_distractor_response(raw)
                ]
                ds = _select_diverse(parsed)
                if len(ds) == 3:
                    return ds
            except BudgetExceeded:
                raise
            except Exception as e:
                print(f'  [distractor slot {slot.get("slot_id", "?")} batch attempt {attempt}] error: {e}')

            generated: List[Dict[str, str]] = []
            for misconception in misconceptions:
                prompt = self._build_single_prompt(
                    candidate, misconception, context, feedback=feedback,
                )
                try:
                    raw = call_llm(self.system_prompt, prompt, model=self.model)
                    parsed = parse_distractor_response(raw)
                    if parsed:
                        d = _coerce_distractor_format(parsed[0], candidate.get('answer_text', ''))
                        if not d.get('distractor_category_text'):
                            d['distractor_category_text'] = misconception.get('id', '')
                        generated.append(d)
                except BudgetExceeded:
                    raise
                except Exception as e:
                    print(
                        f'  [distractor slot {slot.get("slot_id", "?")} '
                        f'misconception {misconception.get("id", "?")}] error: {e}'
                    )
                    continue

            ds = _select_diverse(generated)
            if len(ds) == 3:
                return ds

        return []

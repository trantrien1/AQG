"""Independent Verification Target Builder.

Lỗ hổng của tầng kiểm chứng cũ: Writer sinh CẢ lời giải LẪN biểu thức kiểm
chứng. Verifier so hai thứ đó với nhau nên chỉ đo được *sự nhất quán nội bộ*;
một lỗi mô hình hoá sai-nhất-quán (hiểu sai đề rồi viết biểu thức theo đúng
cách hiểu sai đó) lọt qua với nhãn "verified".

Module này dựng một **mục tiêu kiểm chứng độc lập**: một tác nhân khác giải lại
bài toán CHỈ từ đề bài và tài liệu nguồn, rồi nộp một biểu thức máy đọc được.
Ràng buộc độc lập được ép ở chỗ dựng prompt (:func:`build_independent_prompt`):
tác nhân này KHÔNG được thấy đáp án Writer chọn, KHÔNG thấy lời giải của Writer,
KHÔNG thấy biểu thức kiểm chứng của Writer và KHÔNG thấy danh sách phương án —
nên nó không thể neo theo (anchor) đáp án đang cần kiểm.

Giá trị nó nộp về được đánh giá bằng SymPy ở đây (deterministic), chứ không tin
lời tác nhân tự khai. Ngoài ra bản thân tác nhân độc lập cũng phải TỰ NHẤT QUÁN:
biểu thức máy đọc và đáp án nó viết ra phải khớp nhau thì mục tiêu mới được coi
là *dứt khoát* (``definite``). Bất nhất → inconclusive → phân xử rơi về nhánh
không có bằng chứng độc lập thay vì bác oan một câu đúng.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# Tăng khi prompt của tác nhân độc lập đổi — ghi vào run manifest.
INDEPENDENT_PROMPT_VERSION = '1.0.0'

#: Tên hàm/hằng được phép xuất hiện trong biểu thức độc lập. parse_expr chạy với
#: đúng bảng này làm global_dict nên tên ngoài danh sách (vd ``__import__``)
#: không phân giải được.
_ALLOWED_NAMES = (
    'integrate', 'diff', 'solve', 'limit', 'summation', 'Sum', 'product',
    'sqrt', 'exp', 'log', 'ln', 'sin', 'cos', 'tan', 'cot', 'asin', 'acos',
    'atan', 'sinh', 'cosh', 'tanh', 'Abs', 'floor', 'ceiling', 'factorial',
    'binomial', 'gcd', 'lcm', 'Rational', 'Integer', 'Float', 'pi', 'E', 'oo',
    'Max', 'Min', 'root', 'simplify', 'expand', 'factor', 'nsimplify', 'Eq',
    're', 'im', 'sign', 'atan2', 'Piecewise', 'Symbol',
)


@dataclass
class IndependentTarget:
    """Mục tiêu kiểm chứng suy ra độc lập với biểu thức của Writer."""

    #: Đã thực sự chạy cơ chế này chưa (False khi bị tắt qua ablation).
    attempted: bool = False
    #: Có giá trị số dứt khoát để đối chiếu với đáp án key hay không.
    definite: bool = False
    #: Biểu thức có thực sự BẮT MÁY TÍNH gì không, hay chỉ là một hằng số trần.
    #: Khi tác nhân độc lập nộp về đúng một con số (hay gặp ở câu đếm/tập hợp),
    #: SymPy chỉ đọc lại con số đó — không có phép suy dẫn nào diễn ra. Sự
    #: "trùng khớp" khi ấy là hai model cùng khẳng định một số, KHÔNG phải một
    #: phép tính lại được máy kiểm. Trạng thái INDEPENDENTLY_VERIFIED đòi cờ này.
    derivation: bool = False
    #: Giá trị số của mục tiêu độc lập.
    value: Optional[float] = None
    #: Biểu thức máy đọc mà tác nhân độc lập nộp về.
    expression: str = ''
    #: Đáp án dạng hiển thị mà tác nhân độc lập viết ra (dùng để tự đối chiếu).
    stated_answer: str = ''
    #: Giá trị số đọc được từ ``stated_answer``.
    stated_value: Optional[float] = None
    #: 'llm_resolver' | 'panel' | 'disabled' | 'unavailable' | 'error'
    #: | 'not_applicable'. 'error' = lời gọi model KHÔNG chạy được (timeout,
    #: 5xx...) — khác 'unavailable' (model trả lời nhưng không dùng được). Gộp
    #: hai thứ này từng làm câu gặp lỗi hạ tầng bị đếm là "không kiểm được".
    source: str = 'disabled'
    detail: str = ''
    #: Model đã dùng — ghi lại để biết mục tiêu có khác họ model với Writer không.
    model: str = ''
    #: Họ model (xem `pipeline.model_family`).
    family: str = ''
    prompt_version: str = INDEPENDENT_PROMPT_VERSION
    errors: List[str] = field(default_factory=list)
    # ---- Hội đồng (chỉ có khi gộp từ nhiều thành viên) ----
    #: Kết quả từng thành viên (dict), theo thứ tự cấu hình.
    panel: List[Dict[str, Any]] = field(default_factory=list)
    #: Giá trị của MỌI thành viên có kết quả dứt khoát — tầng phân xử dùng để
    #: phát hiện bất đồng kể cả khi chưa đạt đồng thuận.
    definite_values: List[float] = field(default_factory=list)
    #: Luật đồng thuận đã áp ('all' hoặc số k) và số thành viên cùng giá trị.
    consensus_rule: str = ''
    agreeing: int = 0
    #: Có thành viên nào không chạy được (lỗi hạ tầng) không.
    incomplete: bool = False

    def to_dict(self) -> Dict[str, Any]:
        out = {
            'attempted': self.attempted,
            'definite': self.definite,
            'derivation': self.derivation,
            'value': self.value,
            'expression': self.expression[:400],
            'stated_answer': self.stated_answer[:200],
            'stated_value': self.stated_value,
            'source': self.source,
            'detail': self.detail[:300],
            'model': self.model,
            'family': self.family,
            'prompt_version': self.prompt_version,
            'errors': [str(e)[:160] for e in self.errors[:3]],
            'incomplete': self.incomplete,
        }
        if self.panel:
            out.update({
                'panel': [dict(m) for m in self.panel],
                'definite_values': list(self.definite_values),
                'consensus_rule': self.consensus_rule,
                'agreeing': self.agreeing,
            })
        return out


# ============ Đánh giá biểu thức (thuần SymPy, không LLM) ============

def evaluate_independent_expression(expr_text: str) -> tuple[Optional[float], str]:
    """Đánh giá biểu thức máy đọc → (giá trị, mô tả). Không bao giờ raise.

    Trả ``(None, lý do)`` khi biểu thức còn biến tự do, không phải số thực hữu
    hạn, hoặc không parse được — những trường hợp đó KHÔNG được coi là bằng
    chứng độc lập.
    """
    text = _normalize_expression(expr_text)
    if not text:
        return None, 'biểu thức rỗng'
    try:
        import sympy
        from sympy.parsing.sympy_parser import (
            parse_expr, standard_transformations, implicit_multiplication,
        )
    except Exception as exc:  # pragma: no cover - sympy luôn có trong deps
        return None, f'không import được sympy: {exc}'

    allowed: Dict[str, Any] = {}
    for name in _ALLOWED_NAMES:
        obj = getattr(sympy, name, None)
        if obj is not None:
            allowed[name] = obj
    allowed['ln'] = sympy.log
    for var in ('x', 'y', 'z', 't', 'u', 'n', 'k', 'm', 'a', 'b', 'c', 'h', 'r'):
        allowed.setdefault(var, sympy.Symbol(var))

    try:
        expr = parse_expr(
            text,
            local_dict={},
            global_dict=allowed,
            transformations=standard_transformations + (implicit_multiplication,),
            evaluate=True,
        )
    except Exception as exc:
        return None, f'parse lỗi: {exc}'

    try:
        if getattr(expr, 'free_symbols', None):
            return None, f'còn biến tự do {sorted(str(s) for s in expr.free_symbols)}'
        value = complex(sympy.N(expr, 30))
    except Exception as exc:
        return None, f'không tính được giá trị số: {exc}'

    if abs(value.imag) > 1e-9:
        return None, f'giá trị phức {value}'
    real = value.real
    if real != real or abs(real) == float('inf'):
        return None, 'giá trị không hữu hạn'
    return float(real), f'{text} = {_fmt(real)}'


def _xor_to_bitwise(text: str) -> str:
    """Đánh giá XOR cấp bit trước khi giao cho SymPy.

    SymPy không có toán tử XOR số nguyên, nên biểu thức dạng ``45 ^ 27`` phải
    được rút gọn ở đây. Chỉ xử lý trường hợp cả hai vế đều là số nguyên tường
    minh — phức tạp hơn thì trả nguyên trạng để lớp trên báo không đánh giá được
    thay vì đoán bừa.
    """
    def _fold(m: 're.Match') -> str:
        try:
            return str(int(m.group(1)) ^ int(m.group(2)))
        except ValueError:
            return m.group(0)

    previous = None
    while previous != text:
        previous = text
        text = re.sub(r'\b(\d+)\s*\^\s*(\d+)\b', _fold, text)
    return text


def is_derivation(expr_text: Any) -> bool:
    """Biểu thức có bắt máy tính toán gì không, hay chỉ là một hằng số trần.

    ``'6'``, ``'-3'``, ``'47/3'``, ``'2.5'`` → False: tác nhân độc lập chỉ khẳng
    định một con số và SymPy đọc lại đúng con số đó. Không có phép tính nào được
    kiểm, nên sự trùng khớp chỉ là hai model cùng nói một số.

    ``'binomial(4,3)'``, ``'3*5'``, ``'integrate(...)'`` → True: có ít nhất một
    phép toán mà CAS thực sự thực hiện.
    """
    text = _normalize_expression(expr_text)
    if not text:
        return False
    return not re.fullmatch(r'[-+]?\s*\d+(?:\.\d+)?\s*(?:/\s*\d+(?:\.\d+)?\s*)?',
                            text)


def _normalize_expression(expr_text: Any) -> str:
    """Chuẩn hoá biểu thức LLM nộp về trước khi parse."""
    if expr_text is None:
        return ''
    if isinstance(expr_text, (int, float)) and not isinstance(expr_text, bool):
        return repr(expr_text)
    text = str(expr_text).strip()
    if not text:
        return ''
    text = text.replace('\\(', ' ').replace('\\)', ' ').replace('$', ' ')
    # '^' là luỹ thừa trong ký hiệu toán thông thường, NHƯNG là XOR cấp bit
    # trong bài toán rời rạc — và Python cũng hiểu '^' là XOR. Đổi mù quáng
    # thành '**' làm hỏng mọi biểu thức XOR (45 ^ 27 thành 45**27). Chỉ đổi
    # khi biểu thức không có dấu hiệu nhị phân/bit nào.
    if not re.search(r'(?i)\bxor\b|\b0b[01]+|\b2\s*\*\*|bit', text):
        text = text.replace('^', '**')
    else:
        text = _xor_to_bitwise(text)
    text = text.replace('−', '-').replace('·', '*').replace('×', '*')
    # ``ln`` là alias của log; ``e`` đứng một mình là số Euler.
    text = re.sub(r'\bln\b', 'log', text)
    return text.strip()


def parse_answer_value(answer_text: str) -> Optional[float]:
    """Đọc giá trị số từ một đáp án hiển thị (có thể là LaTeX).

    Dùng lại parser LaTeX→số của VerifierAgent; import cục bộ để tránh vòng
    import (verifier_agent import ngược module này).
    """
    try:
        from .agents.verifier_agent import _expected_from_answer
    except Exception:  # pragma: no cover
        return None
    try:
        value = _expected_from_answer(answer_text)
    except Exception:
        return None
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def values_agree(a: Any, b: Any, rel_tol: float = 1e-4, abs_tol: float = 1e-6) -> bool:
    try:
        af, bf = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(af - bf) <= max(abs_tol, abs(bf) * rel_tol)


# ============ Prompt cho tác nhân độc lập ============

_INDEPENDENT_SYSTEM = (
    'Bạn là một hệ thống đại số máy tính có kèm suy luận. Nhiệm vụ DUY NHẤT: '
    'giải lại một bài toán từ đầu và nộp về biểu thức máy đọc được để máy tự '
    'tính lại kết quả. Bạn KHÔNG được đưa ra đáp án đề xuất nào từ trước, và '
    'KHÔNG được đoán theo dạng đáp án "đẹp".'
)


def build_independent_prompt(stem: str, *, givens: str = '') -> str:
    """Prompt giải lại bài toán, ĐÃ bịt mọi thông tin đến từ Writer.

    Người gọi có trách nhiệm chỉ truyền vào ``stem`` (đề bài) và, nếu cần, phần
    dữ kiện trích từ tài liệu nguồn. Không truyền đáp án, lời giải, biểu thức
    kiểm chứng hay danh sách phương án — nếu truyền, tính độc lập mất hết ý
    nghĩa và toàn bộ cơ chế này quay về đúng lỗ hổng cũ.
    """
    givens_block = f'\n\nDữ kiện kèm theo:\n{givens.strip()}\n' if givens.strip() else ''
    return f"""Giải bài toán sau HOÀN TOÀN TỪ ĐẦU. Bạn không được cho biết đáp án
đề xuất, cũng không có danh sách phương án — hãy tự tính.

ĐỀ BÀI:
{stem.strip()}{givens_block}

Yêu cầu output:
1. Tự đọc đề, tự xác định đại lượng cần tìm, tự lập biểu thức từ CÁC DỮ KIỆN
   TRONG ĐỀ (không dùng bất kỳ kết quả nào cho sẵn).
2. Nộp về một biểu thức SymPy tính ra kết quả cuối, dùng cú pháp máy đọc:
   *, /, ** , sqrt(), pi, sin(), cos(), log(), factorial(), binomial(),
   integrate(f, (x, a, b)), diff(f, x), solve(...), limit(f, x, a).
   Biểu thức phải RA MỘT SỐ CỤ THỂ — không còn biến tự do.
3. Nếu bài toán KHÔNG có kết quả số duy nhất (câu khái niệm, chứng minh, hỏi
   phát biểu đúng/sai...), đặt "computable": false và để expression rỗng.
   TUYỆT ĐỐI không bịa một con số cho có.

Chỉ trả về DUY NHẤT một JSON object, không markdown, không chữ ngoài JSON:
{{"computable": true|false,
  "quantity": "<đại lượng cần tìm, một dòng>",
  "expression": "<biểu thức SymPy ra số cuối, hoặc \\"\\" nếu computable=false>",
  "answer": "<kết quả cuối ở dạng gọn, vd 47/3 hoặc 576*sqrt(2)*pi/5>"}}"""


# ============ Builder ============

def build_independent_target(
    stem: str,
    *,
    call_fn: Callable[[str, str], str],
    model: str = '',
    givens: str = '',
    reraise: tuple = (),
) -> IndependentTarget:
    """Chạy tác nhân độc lập rồi đánh giá kết quả bằng SymPy.

    ``call_fn(system, user) -> str`` được tiêm từ ngoài vào để module này không
    phụ thuộc trực tiếp vào LLM client (test chạy được với một hàm giả).

    ``reraise`` là các loại lỗi phải nổi lên cho người gọi (sai key, hết hạn
    mức...). Trước đây mọi lỗi đều bị nuốt ở đây, nên một đợt 401 biến hàng loạt
    câu thành "không kiểm chứng được" trong khi thực ra cơ chế không hề chạy.
    Lỗi còn lại (timeout, 5xx) được ghi ``source='error'`` để đếm riêng.
    """
    from .model_family import model_family
    target = IndependentTarget(attempted=True, source='llm_resolver', model=model,
                               family=model_family(model) if model else '')
    if not str(stem or '').strip():
        target.source = 'unavailable'
        target.detail = 'stem rỗng'
        return target

    try:
        raw = call_fn(_INDEPENDENT_SYSTEM, build_independent_prompt(stem, givens=givens))
    except Exception as exc:
        if reraise and isinstance(exc, reraise):
            raise
        target.source = 'error'
        target.incomplete = True
        target.detail = f'gọi model thất bại: {exc}'
        target.errors.append(str(exc))
        return target

    payload = _first_json_object(raw)
    if not isinstance(payload, dict):
        target.source = 'unavailable'
        target.detail = 'không đọc được JSON từ tác nhân độc lập'
        return target

    if payload.get('computable') is False:
        target.source = 'not_applicable'
        target.detail = 'tác nhân độc lập báo bài toán không có kết quả số duy nhất'
        return target

    target.expression = str(payload.get('expression') or '')
    target.stated_answer = str(payload.get('answer') or '')

    value, detail = evaluate_independent_expression(target.expression)
    target.detail = detail
    if value is None:
        target.detail = f'biểu thức độc lập không đánh giá được ({detail})'
        return target

    stated = parse_answer_value(target.stated_answer)
    if stated is None:
        stated, stated_detail = evaluate_independent_expression(target.stated_answer)
        if stated is None:
            target.detail = (
                f'{detail}; nhưng không đọc được đáp án tự khai '
                f'("{target.stated_answer[:60]}": {stated_detail})'
            )
    target.stated_value = stated

    # Tác nhân độc lập phải TỰ NHẤT QUÁN mới được tin: biểu thức máy đọc và đáp
    # án nó viết ra phải cùng một số. Bất nhất nghĩa là chính nó cũng đang lẫn
    # lộn — dùng làm bằng chứng bác bỏ sẽ tái lập đúng lỗi ta đang muốn sửa.
    if stated is None:
        target.definite = False
        return target
    if not values_agree(value, stated):
        target.definite = False
        target.detail = (
            f'tác nhân độc lập tự mâu thuẫn: biểu thức cho {_fmt(value)} '
            f'nhưng đáp án tự khai là {_fmt(stated)}'
        )
        return target

    target.value = value
    target.definite = True
    target.derivation = is_derivation(target.expression)
    if not target.derivation:
        target.detail = (
            f'{detail}; nhưng biểu thức chỉ là hằng số trần — không có phép '
            f'tính nào được máy kiểm, nên không đủ để gọi là xác nhận độc lập'
        )
    return target


def disabled_target(reason: str = 'independent verification disabled') -> IndependentTarget:
    return IndependentTarget(attempted=False, source='disabled', detail=reason)


# ============ Hội đồng nhiều solver ============

def consensus_size(rule: Any, n_members: int) -> int:
    """Số thành viên phải cùng giá trị theo luật ``rule`` ('all' hoặc số k)."""
    n = max(1, int(n_members))
    text = str(rule if rule is not None else 'all').strip().lower()
    if text in ('', 'all'):
        return n
    try:
        k = int(text)
    except ValueError:
        return n
    return max(1, min(k, n))


def aggregate_panel(
    members: List[IndependentTarget],
    consensus: Any = 'all',
) -> IndependentTarget:
    """Gộp kết quả của nhiều solver độc lập thành MỘT mục tiêu.

    Đồng thuận (``definite=True``) khi có một cụm giá trị trùng nhau đạt đủ
    ``consensus_size`` thành viên và không có cụm nào khác lớn bằng nó. Cụm đó
    tính là có suy dẫn khi ít nhất một thành viên của nó nộp một phép tính thật
    (không phải hằng số trần): CAS đã chạy lại được một con đường tới giá trị,
    các thành viên còn lại xác nhận giá trị đó từ nguồn khác.

    Giá trị dứt khoát của MỌI thành viên được giữ trong ``definite_values`` để
    tầng phân xử bắt được bất đồng ngay cả khi không đạt đồng thuận — luật gắn
    cờ nhạy hơn luật xác nhận là có chủ đích.

    Một thành viên thì trả lại chính nó (hành vi cũ, không đổi shape dữ liệu).
    """
    members = [m for m in members if m is not None]
    if not members:
        return disabled_target('hội đồng giải độc lập rỗng')
    if len(members) == 1:
        single = members[0]
        single.definite_values = (
            [single.value] if single.definite and single.value is not None else [])
        single.agreeing = 1 if single.definite else 0
        single.consensus_rule = str(consensus)
        return single

    n = len(members)
    k = consensus_size(consensus, n)
    definite = [m for m in members if m.definite and m.value is not None]
    clusters: List[List[IndependentTarget]] = []
    for m in definite:
        for cluster in clusters:
            if values_agree(m.value, cluster[0].value):
                cluster.append(m)
                break
        else:
            clusters.append([m])
    best = max(clusters, key=len) if clusters else []
    families = []
    for m in members:
        if m.family and m.family not in families:
            families.append(m.family)

    agg = IndependentTarget(
        attempted=any(m.attempted for m in members),
        source='panel',
        model='+'.join(m.model or '?' for m in members),
        family='+'.join(families),
        panel=[m.to_dict() for m in members],
        definite_values=[float(m.value) for m in definite],
        consensus_rule=str(consensus),
        agreeing=len(best),
        incomplete=any(m.incomplete or m.source == 'error' for m in members),
        errors=[e for m in members for e in m.errors][:3],
    )
    values_text = ', '.join(
        f'{(m.model or "?").rsplit("/", 1)[-1]}={_fmt(m.value)}' for m in definite)
    tied = sum(1 for c in clusters if len(c) == len(best)) > 1
    if best and len(best) >= k and not tied:
        head = next((m for m in best if m.derivation), best[0])
        agg.definite = True
        agg.value = float(head.value)
        agg.expression = head.expression
        agg.stated_answer = head.stated_answer
        agg.stated_value = head.stated_value
        agg.derivation = any(m.derivation for m in best)
        agg.detail = (f'{len(best)}/{n} solver cùng cho {_fmt(head.value)}'
                      + (f' ({values_text})' if len(definite) > len(best) else ''))
        if not agg.derivation:
            agg.detail += '; không thành viên nào nộp phép tính thật'
        return agg

    agg.definite = False
    reason = ('các cụm giá trị hoà nhau' if tied and best
              else f'{len(best)}/{n} đồng ý, cần {k}')
    agg.detail = (f'hội đồng chưa đồng thuận ({reason})'
                  + (f'; giá trị dứt khoát: {values_text}' if values_text else ''))
    return agg


def _first_json_object(text: Any) -> Optional[Dict[str, Any]]:
    """Trích object JSON đầu tiên trong text (chịu được code fence/chữ thừa)."""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if stripped.startswith('```'):
        stripped = re.sub(r'^```[a-zA-Z]*\s*|\s*```$', '', stripped).strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = stripped.find('{')
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                fragment = stripped[start:i + 1]
                try:
                    parsed = json.loads(fragment)
                    return parsed if isinstance(parsed, dict) else None
                except Exception:
                    return None
    return None


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f'{number:.6g}'

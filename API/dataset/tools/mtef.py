"""Chuyển công thức MathType (OLE "Equation Native", MTEF v5) sang LaTeX.

Tài liệu Word soạn bằng MathType lưu mỗi công thức thành một đối tượng OLE
`word/embeddings/oleObjectN.bin`. Trong đó stream "Equation Native" gồm 28 byte
header rồi đến thân MTEF v5: một chuỗi bản ghi (LINE, CHAR, TMPL, PILE,
MATRIX, ...) lồng nhau, mỗi danh sách con kết thúc bằng END.

Đặc tả: https://docs.wiris.com/en/mathtype/mathtype_desktop/mathtype-sdk/mtef5

Chỉ hỗ trợ MTEF v5 (MathType 5 trở lên). Công thức Equation Editor 3.0
(MTEF v3) trả về ``None`` để bên gọi đánh dấu thiếu.
"""
from __future__ import annotations

import io
import re
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Union

import olefile

# ---------------------------------------------------------------------------
# Bản ghi
# ---------------------------------------------------------------------------

END, LINE, CHAR, TMPL, PILE, MATRIX, EMBELL, RULER = range(8)
FONT_STYLE_DEF, SIZE, FULL, SUB, SUB2, SYM, SUBSYM = range(8, 15)
COLOR, COLOR_DEF, FONT_DEF, EQN_PREFS, ENCODING_DEF = range(15, 20)
FUTURE = 100

OPT_NUDGE = 0x08
OPT_CHAR_EMBELL = 0x01
OPT_CHAR_ENC_CHAR_8 = 0x04
OPT_CHAR_ENC_CHAR_16 = 0x10
OPT_CHAR_ENC_NO_MTCODE = 0x20
OPT_LINE_NULL = 0x01
OPT_LP_RULER = 0x02
OPT_LINE_LSPACE = 0x04

FN_TEXT, FN_FUNCTION, FN_VARIABLE = 1, 2, 3
FN_VECTOR = 7
FN_MTEXTRA = 11
FN_TEXT_FE = 12
FN_EXPAND, FN_MARKER, FN_SPACE = 22, 23, 24


class MtefError(ValueError):
    pass


@dataclass
class Char:
    typeface: int
    code: Optional[int]
    embells: List[int] = field(default_factory=list)


@dataclass
class Line:
    children: List['Node'] = field(default_factory=list)
    null: bool = False


@dataclass
class Tmpl:
    selector: int
    variation: int
    children: List['Node'] = field(default_factory=list)


@dataclass
class Pile:
    halign: int
    children: List['Node'] = field(default_factory=list)


@dataclass
class Matrix:
    rows: int
    cols: int
    h_just: int
    children: List['Node'] = field(default_factory=list)


Node = Union[Char, Line, Tmpl, Pile, Matrix]


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def u8(self) -> int:
        if self.pos >= len(self.data):
            raise MtefError('unexpected end of MTEF data')
        b = self.data[self.pos]
        self.pos += 1
        return b

    def u16(self) -> int:
        if self.pos + 2 > len(self.data):
            raise MtefError('unexpected end of MTEF data')
        (v,) = struct.unpack_from('<H', self.data, self.pos)
        self.pos += 2
        return v

    def uint(self) -> int:
        """Số nguyên không dấu MTEF v5: 1 byte, hoặc 0xFF theo sau 2 byte."""
        b = self.u8()
        return self.u16() if b == 0xFF else b

    def cstr(self) -> bytes:
        end = self.data.find(b'\x00', self.pos)
        if end < 0:
            raise MtefError('unterminated string')
        s = self.data[self.pos:end]
        self.pos = end + 1
        return s

    def skip(self, n: int) -> None:
        self.pos += n

    def nudge(self) -> None:
        dx, dy = self.u8(), self.u8()
        if dx == 128 and dy == 128:
            self.skip(4)


class _Parser:
    def __init__(self, body: bytes):
        self.r = _Reader(body)

    def parse(self) -> List[Node]:
        r = self.r
        version = r.u8()
        if version != 5:
            raise MtefError(f'unsupported MTEF version {version}')
        r.skip(4)          # platform, product, version, sub-version
        r.cstr()           # application key
        r.u8()             # equation options
        nodes: List[Node] = []
        while not r.eof():
            tag = r.u8()
            if tag == END:
                continue
            node = self._record(tag)
            if node is not None:
                nodes.append(node)
        return nodes

    def _list(self) -> List[Node]:
        out: List[Node] = []
        while True:
            tag = self.r.u8()
            if tag == END:
                return out
            node = self._record(tag)
            if node is not None:
                out.append(node)

    def _ruler(self) -> None:
        r = self.r
        n = r.u8()
        r.skip(3 * n)

    def _record(self, tag: int) -> Optional[Node]:
        r = self.r
        if tag == LINE:
            opts = r.u8()
            if opts & OPT_NUDGE:
                r.nudge()
            if opts & OPT_LINE_LSPACE:
                r.uint()
            if opts & OPT_LP_RULER:
                self._expect_ruler()
            if opts & OPT_LINE_NULL:
                return Line(null=True)
            return Line(self._list())
        if tag == CHAR:
            opts = r.u8()
            if opts & OPT_NUDGE:
                r.nudge()
            typeface = r.u8() - 128
            code = None
            if not opts & OPT_CHAR_ENC_NO_MTCODE:
                code = r.u16()
            if opts & OPT_CHAR_ENC_CHAR_8:
                r.u8()
            if opts & OPT_CHAR_ENC_CHAR_16:
                r.u16()
            embells: List[int] = []
            if opts & OPT_CHAR_EMBELL:
                embells = [n for n in self._list() if isinstance(n, int)]
            return Char(typeface, code, embells)
        if tag == TMPL:
            opts = r.u8()
            if opts & OPT_NUDGE:
                r.nudge()
            selector = r.u8()
            b1 = r.u8()
            variation = b1
            if b1 & 0x80:
                variation = (b1 & 0x7F) | (r.u8() << 8)
            r.u8()  # template-specific options
            return Tmpl(selector, variation, self._list())
        if tag == PILE:
            opts = r.u8()
            if opts & OPT_NUDGE:
                r.nudge()
            halign = r.u8()
            r.u8()  # valign
            if opts & OPT_LP_RULER:
                self._expect_ruler()
            return Pile(halign, self._list())
        if tag == MATRIX:
            opts = r.u8()
            if opts & OPT_NUDGE:
                r.nudge()
            r.u8()  # valign
            h_just = r.u8()
            r.u8()  # v_just
            rows, cols = r.u8(), r.u8()
            r.skip(((rows + 1) * 2 + 7) // 8)
            r.skip(((cols + 1) * 2 + 7) // 8)
            return Matrix(rows, cols, h_just, self._list())
        if tag == EMBELL:
            opts = r.u8()
            if opts & OPT_NUDGE:
                r.nudge()
            return r.u8()  # type: ignore[return-value]  (gom vào Char.embells)
        if tag == RULER:
            self._ruler()
            return None
        if tag == FONT_STYLE_DEF:
            r.uint()
            r.u8()
            return None
        if tag == SIZE:
            lsize = r.u8()
            if lsize == 101:
                r.u16()
            elif lsize == 100:
                r.u8()
                r.u16()
            else:
                r.u8()
            return None
        if tag in (FULL, SUB, SUB2, SYM, SUBSYM):
            return None
        if tag == COLOR:
            r.uint()
            return None
        if tag == COLOR_DEF:
            opts = r.u8()
            r.skip(2 * (4 if opts & 0x01 else 3))
            if opts & 0x04:
                r.cstr()
            return None
        if tag == FONT_DEF:
            r.uint()
            r.cstr()
            return None
        if tag == EQN_PREFS:
            r.u8()
            self._dimension_array(r.uint())
            self._dimension_array(r.uint())
            for _ in range(r.uint()):
                if r.u8():
                    r.u8()
            return None
        if tag == ENCODING_DEF:
            r.cstr()
            return None
        if tag >= FUTURE:
            r.skip(r.uint())
            return None
        raise MtefError(f'unknown record {tag} at {r.pos - 1}')

    def _expect_ruler(self) -> None:
        # MathType ghi ruler ngay sau LINE/PILE, có hoặc không kèm mã RULER.
        if self.r.data[self.r.pos:self.r.pos + 1] == bytes([RULER]):
            self.r.u8()
        self._ruler()

    def _dimension_array(self, count: int) -> None:
        """Mảng kích thước mã hoá nibble: [đơn vị][chữ số...][0xF] lặp ``count`` lần."""
        done = 0
        expect_unit = True
        while done < count:
            b = self.r.u8()
            for nib in (b >> 4, b & 0x0F):
                if done >= count:
                    break
                if expect_unit:
                    expect_unit = False
                elif nib == 0x0F:
                    done += 1
                    expect_unit = True


# ---------------------------------------------------------------------------
# OLE -> thân MTEF
# ---------------------------------------------------------------------------

def mtef_body_from_ole(data: bytes) -> Optional[bytes]:
    """Thân MTEF từ một file oleObject*.bin; None nếu không phải MathType."""
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except OSError:
        return None
    try:
        if not ole.exists('Equation Native'):
            return None
        raw = ole.openstream('Equation Native').read()
    finally:
        ole.close()
    if len(raw) < 28:
        return None
    cb_hdr = struct.unpack_from('<H', raw, 0)[0]
    cb_size = struct.unpack_from('<I', raw, 8)[0]
    return raw[cb_hdr:cb_hdr + cb_size]


_WMF_SIG = b'AppsMFCC'
_WMF_VENDOR = b'Design Science, Inc.\x00'


def mtef_body_from_picture(data: bytes) -> Optional[bytes]:
    """Thân MTEF nhúng trong ảnh WMF/EMF do MathType xuất ("dán dạng ảnh").

    MathType ghi công thức vào các bản ghi chú thích: chữ ký ``AppsMFCC``,
    2 byte cờ, 4 byte tổng độ dài, 4 byte độ dài đoạn này, rồi dữ liệu. Công
    thức dài bị chia thành nhiều đoạn nối tiếp.
    """
    chunks: List[bytes] = []
    total = None
    pos = data.find(_WMF_SIG)
    while pos >= 0:
        start = pos + len(_WMF_SIG) + 10
        if start > len(data):
            break
        total_len, cur_len = struct.unpack_from('<II', data, start - 8)
        total = total if total is not None else total_len
        # Độ dài không tính chuỗi tên hãng đứng đầu mỗi đoạn.
        if data.startswith(_WMF_VENDOR, start):
            start += len(_WMF_VENDOR)
        chunks.append(data[start:start + cur_len])
        pos = data.find(_WMF_SIG, start + cur_len)
    if not chunks:
        return None
    blob = b''.join(chunks)
    if total is not None:
        blob = blob[:total]
    return blob or None


def parse(body: bytes) -> List[Node]:
    return _Parser(body).parse()


# ---------------------------------------------------------------------------
# Sinh LaTeX
# ---------------------------------------------------------------------------

FUNCTIONS = {
    'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'sinh', 'cosh', 'tanh', 'coth',
    'arcsin', 'arccos', 'arctan', 'ln', 'log', 'lg', 'exp', 'lim', 'max',
    'min', 'sup', 'inf', 'det', 'deg', 'gcd', 'arg', 'dim', 'ker',
}

ASCII_ESCAPES = {
    '{': r'\{', '}': r'\}', '%': r'\%', '#': r'\#', '&': r'\&', '_': r'\_',
    '$': r'\$', '\\': r'\backslash ', '~': r'\sim ',
}

SYMBOLS = {
    # Hy Lạp
    'α': r'\alpha', 'β': r'\beta', 'γ': r'\gamma', 'δ': r'\delta',
    'ε': r'\varepsilon', 'ϵ': r'\epsilon', 'ζ': r'\zeta', 'η': r'\eta',
    'θ': r'\theta', 'ϑ': r'\vartheta', 'ι': r'\iota', 'κ': r'\kappa',
    'λ': r'\lambda', 'μ': r'\mu', 'ν': r'\nu', 'ξ': r'\xi', 'π': r'\pi',
    'ϖ': r'\varpi', 'ρ': r'\rho', 'ϱ': r'\varrho', 'σ': r'\sigma',
    'ς': r'\varsigma', 'τ': r'\tau', 'υ': r'\upsilon', 'φ': r'\varphi',
    'ϕ': r'\phi', 'χ': r'\chi', 'ψ': r'\psi', 'ω': r'\omega',
    'Γ': r'\Gamma', 'Δ': r'\Delta', 'Θ': r'\Theta', 'Λ': r'\Lambda',
    'Ξ': r'\Xi', 'Π': r'\Pi', 'Σ': r'\Sigma', 'Υ': r'\Upsilon',
    'Φ': r'\Phi', 'Ψ': r'\Psi', 'Ω': r'\Omega',
    # Phép toán, quan hệ
    '−': '-', '–': '-', '±': r'\pm', '∓': r'\mp', '×': r'\times',
    '÷': r'\div', '·': r'\cdot', '⋅': r'\cdot', '∙': r'\cdot', '∘': r'\circ',
    '°': r'^{\circ}', '≤': r'\le', '≥': r'\ge', '≠': r'\ne', '≈': r'\approx',
    '≡': r'\equiv', '∼': r'\sim', '≅': r'\cong', '∝': r'\propto',
    '≪': r'\ll', '≫': r'\gg', '⩽': r'\leqslant', '⩾': r'\geqslant',
    '∈': r'\in', '∉': r'\notin', '∋': r'\ni', '⊂': r'\subset',
    '⊃': r'\supset', '⊆': r'\subseteq', '⊇': r'\supseteq', '∪': r'\cup',
    '∩': r'\cap', '∖': r'\setminus', '∅': r'\varnothing', '∀': r'\forall',
    '∃': r'\exists', '¬': r'\neg', '∧': r'\wedge', '∨': r'\vee',
    '∞': r'\infty', '∂': r'\partial', '∇': r'\nabla', '√': r'\surd',
    '∫': r'\int', '∬': r'\iint', '∭': r'\iiint', '∮': r'\oint',
    '∑': r'\sum', '∏': r'\prod', '⊥': r'\perp', '∥': r'\parallel',
    '∠': r'\angle', '△': r'\triangle', '∆': r'\Delta', '′': "'", '″': "''",
    '…': r'\ldots', '⋯': r'\cdots', '⋮': r'\vdots', '⋱': r'\ddots',
    '→': r'\to', '←': r'\leftarrow', '↔': r'\leftrightarrow',
    '⇒': r'\Rightarrow', '⇐': r'\Leftarrow', '⇔': r'\Leftrightarrow',
    '↑': r'\uparrow', '↓': r'\downarrow', '↗': r'\nearrow',
    '↘': r'\searrow', '⟶': r'\longrightarrow', '⟹': r'\Longrightarrow',
    '⟺': r'\Leftrightarrow', '↦': r'\mapsto',
    '〈': r'\langle', '〉': r'\rangle', '⟨': r'\langle', '⟩': r'\rangle',
    '‖': r'\|', '⌊': r'\lfloor', '⌋': r'\rfloor', '⌈': r'\lceil',
    '⌉': r'\rceil', 'ℝ': r'\mathbb{R}', 'ℕ': r'\mathbb{N}',
    'ℤ': r'\mathbb{Z}', 'ℚ': r'\mathbb{Q}', 'ℂ': r'\mathbb{C}',
    'ℓ': r'\ell', 'ℏ': r'\hbar', '℘': r'\wp', 'ℑ': r'\Im', 'ℜ': r'\Re',
    'ℵ': r'\aleph', '∗': '*', '⁄': '/', '∣': r'\mid', '⊕': r'\oplus',
    '⊗': r'\otimes', '♦': r'\diamond', '□': r'\square', '■': r'\blacksquare',
    ' ': '~',
}

# Khoảng trắng MathType (vùng riêng 0xEF00..) và dấu canh lề.
SPACES = {
    0xEF00: '', 0xEF01: r'\,', 0xEF02: r'\,', 0xEF03: r'\:',
    0xEF04: r'\;', 0xEF05: r'\quad ', 0xEF06: '', 0xEF07: r'\,',
    0xEF08: r'\!', 0x2009: r'\,', 0x200A: r'\,', 0x2002: r'\;',
    0x2003: r'\quad ', 0x200B: '', 0x2006: r'\,', 0x2005: r'\,',
    0x2004: r'\;', 0x2008: r'\,',
}
SPACES_CHARS = {chr(c) for c in SPACES}

FENCE = {
    '(': '(', ')': ')', '[': '[', ']': ']', '{': r'\{', '}': r'\}',
    '|': '|', '‖': r'\|', '〈': r'\langle', '〉': r'\rangle',
    '⟨': r'\langle', '⟩': r'\rangle', '⌊': r'\lfloor', '⌋': r'\rfloor',
    '⌈': r'\lceil', '⌉': r'\rceil', '⟦': '[', '⟧': ']', '/': '/',
}

# Ngoặc mặc định theo loại mẫu, dùng khi glyph nằm ở vùng riêng MathType
# (vd dấu giá trị tuyệt đối là 0xEC07/0xEC08).
FENCE_BY_SELECTOR = {
    0: (r'\langle', r'\rangle'), 1: ('(', ')'), 2: (r'\{', r'\}'),
    3: ('[', ']'), 4: ('|', '|'), 5: (r'\|', r'\|'),
    6: (r'\lfloor', r'\rfloor'), 7: (r'\lceil', r'\rceil'),
    8: ('[', ']'),
}

EMBELL_WRAP = {
    2: r'\dot{%s}', 3: r'\ddot{%s}', 4: r'\dddot{%s}', 8: r'\tilde{%s}',
    9: r'\hat{%s}', 10: r'\not{%s}', 11: r'\overrightarrow{%s}',
    12: r'\overleftarrow{%s}', 13: r'\overleftrightarrow{%s}',
    14: r'\overrightarrow{%s}', 15: r'\overleftarrow{%s}',
    16: r'\bcancel{%s}', 17: r'\overline{%s}', 19: r'\overset{\frown}{%s}',
    20: r'\overset{\smile}{%s}', 29: r'\underline{%s}',
    30: r'\utilde{%s}', 33: r'\underrightarrow{%s}',
    34: r'\underleftarrow{%s}', 35: r'\underleftrightarrow{%s}',
}
EMBELL_SUFFIX = {5: "'", 6: "''", 18: "'''", 7: '`'}

HALIGN = {1: 'l', 2: 'c', 3: 'r', 4: 'l', 5: 'r'}

_CTRL_WORD_END = re.compile(r'\\[A-Za-z]+$')


class UnsupportedTemplate(MtefError):
    pass


def _join(parts: List[str]) -> str:
    out = ''
    for p in parts:
        if not p:
            continue
        if out and p[0].isalpha() and _CTRL_WORD_END.search(out):
            out += ' '
        out += p
    return out


def _is_empty(node: Optional[Node]) -> bool:
    return node is None or (isinstance(node, Line) and (node.null or not node.children))


def _char_text(code: Optional[int]) -> str:
    if code is None:
        return ''
    try:
        return chr(code)
    except ValueError:
        return ''


def _escape_text(s: str) -> str:
    return ''.join(ASCII_ESCAPES.get(c, c) if c in '{}%#&_$\\' else c for c in s)


class _Latex:
    def __init__(self, strict: bool = False):
        self.strict = strict
        self.unknown: List[str] = []

    def nodes(self, nodes: List[Node]) -> str:
        parts: List[str] = []
        i = 0
        while i < len(nodes):
            n = nodes[i]
            if isinstance(n, Char) and not n.embells and n.typeface in (
                    FN_FUNCTION, FN_TEXT, FN_TEXT_FE):
                # Gom chuỗi ký tự cùng kiểu (tên hàm / chữ thường) thành một từ.
                j = i
                word = ''
                while (j < len(nodes) and isinstance(nodes[j], Char)
                       and not nodes[j].embells
                       and nodes[j].typeface == n.typeface):
                    word += _char_text(nodes[j].code)
                    j += 1
                parts.append(self._word(word, n.typeface))
                i = j
                continue
            parts.append(self.node(n))
            i += 1
        return _join(parts)

    def _word(self, word: str, typeface: int) -> str:
        if typeface == FN_FUNCTION:
            m = re.fullmatch(r'([A-Za-z]+)', word)
            if not m:
                return self._plain(word)
            if word in FUNCTIONS:
                return '\\' + word + ' '
            # "sinx", "lnx": tên hàm dính biến
            for fn in sorted(FUNCTIONS, key=len, reverse=True):
                if word.startswith(fn) and len(word) > len(fn):
                    return '\\' + fn + ' ' + word[len(fn):]
            return r'\operatorname{%s}' % word
        # chữ thường trong công thức
        if not word.strip():
            return '~' if word else ''
        if re.fullmatch(r'[A-Za-z0-9]+', word):
            return r'\mathrm{%s}' % word
        # Ký hiệu toán (π, ≤, ...) không dùng được trong \text: tách ra ngoài.
        parts: List[str] = []
        run = ''
        for c in word:
            if c in SYMBOLS or c in SPACES_CHARS:
                if run:
                    parts.append(r'\text{%s}' % _escape_text(run))
                    run = ''
                parts.append(self._symbol(ord(c), FN_VARIABLE))
            else:
                run += c
        if run:
            parts.append(r'\text{%s}' % _escape_text(run))
        return _join(parts)

    def _plain(self, word: str) -> str:
        return _join([self._symbol(ord(c), FN_VARIABLE) for c in word])

    def _symbol(self, code: Optional[int], typeface: int) -> str:
        if code is None:
            return ''
        if code in SPACES:
            return SPACES[code]
        if typeface == FN_MARKER:
            return ''
        if typeface == FN_SPACE:
            return r'\,' if code else ''
        c = _char_text(code)
        if not c:
            return ''
        if c in ASCII_ESCAPES:
            return ASCII_ESCAPES[c]
        if c in SYMBOLS:
            return SYMBOLS[c]
        if 0xE000 <= code <= 0xF8FF:
            # Vùng riêng MathType chưa có trong bảng: bỏ qua nhưng ghi lại.
            self.unknown.append(f'U+{code:04X}')
            return ''
        if typeface == FN_VECTOR and c.isalpha():
            return r'\mathbf{%s}' % c
        if c == ' ':
            return ''
        return c

    def node(self, n: Node) -> str:
        if isinstance(n, Char):
            s = self._symbol(n.code, n.typeface)
            if n.typeface in (FN_TEXT, FN_TEXT_FE, FN_FUNCTION) and s and s[0].isalpha():
                s = self._word(s, n.typeface)
            for e in n.embells:
                if e in EMBELL_SUFFIX:
                    s += EMBELL_SUFFIX[e]
                elif e in EMBELL_WRAP:
                    s = EMBELL_WRAP[e] % s
            return s
        if isinstance(n, Line):
            return '' if n.null else self.nodes(n.children)
        if isinstance(n, Pile):
            lines = [self.node(c) for c in n.children]
            if len(lines) == 1:
                return lines[0]
            col = HALIGN.get(n.halign, 'l')
            return r'\begin{array}{%s} %s \end{array}' % (col, r' \\ '.join(lines))
        if isinstance(n, Matrix):
            cells = [self.node(c) for c in n.children]
            cols = max(1, n.cols)
            rows = [' & '.join(cells[k:k + cols]) for k in range(0, len(cells), cols)]
            spec = HALIGN.get(n.h_just, 'c') * cols
            return r'\begin{array}{%s} %s \end{array}' % (spec, r' \\ '.join(rows))
        if isinstance(n, Tmpl):
            return self.tmpl(n)
        return ''

    # ------------------------------------------------------------------
    def tmpl(self, t: Tmpl) -> str:
        slots = [c for c in t.children if not isinstance(c, Char)]
        chars = [c for c in t.children if isinstance(c, Char)]

        def slot(i: int) -> str:
            return self.node(slots[i]) if i < len(slots) else ''

        sel, var = t.selector, t.variation
        if sel <= 9:
            return self._fence(sel, var, slot(0), chars)
        if sel == 10:  # căn
            idx = slot(1)
            if var & 1 and idx:
                return r'\sqrt[%s]{%s}' % (idx, slot(0))
            return r'\sqrt{%s}' % slot(0)
        if sel == 11:  # phân số
            if var & 0x02:
                return '{%s}/{%s}' % (slot(0), slot(1))
            return r'\frac{%s}{%s}' % (slot(0), slot(1))
        if sel == 12:
            return r'\underline{%s}' % slot(0)
        if sel == 13:
            return r'\overline{%s}' % slot(0)
        if sel == 14:  # mũi tên có chữ
            name = 'Rightarrow' if var & 0x01 else 'rightarrow'
            if var & 0x10 and var & 0x20:
                name = 'Leftrightarrow' if var & 0x01 else 'leftrightarrow'
            elif var & 0x10:
                name = 'Leftarrow' if var & 0x01 else 'leftarrow'
            top, bottom = slot(0), slot(1)
            below = '[%s]' % bottom if bottom else ''
            return r'\x%s%s{%s}' % (name, below, top)
        if sel == 15:  # tích phân
            count = var & 0x03 or 1
            if var & 0x0C:
                op = r'\oint' if count == 1 else r'\oiint'
            else:
                op = {1: r'\int', 2: r'\iint', 3: r'\iiint'}[count]
            return self._bigop(op, slots, limits=bool(var & 0x40))
        if 16 <= sel <= 22:
            op = {16: r'\sum', 17: r'\prod', 18: r'\coprod', 19: r'\bigcup',
                  20: r'\bigcap'}.get(sel)
            if op is None:
                op = _join([self.node(c) for c in chars]) or r'\sum'
            return self._bigop(op, slots, limits=sel in (16, 17, 18, 19, 20, 22))
        if sel == 23:  # lim
            out = slot(0)
            if slot(1):
                out += '_{%s}' % slot(1)
            if slot(2):
                out += '^{%s}' % slot(2)
            return out
        if sel == 24:
            if var & 0x01:
                return r'\overbrace{%s}^{%s}' % (slot(0), slot(1))
            return r'\underbrace{%s}_{%s}' % (slot(0), slot(1))
        if sel == 25:
            if var & 0x01:
                return r'\overline{%s}' % slot(0)
            return r'\underline{%s}' % slot(0)
        if sel == 26:  # chia dài
            return _join([self.node(s) for s in slots])
        if sel in (27, 28, 29):
            sub = slot(0)
            sup = slot(1)
            out = ''
            if sub:
                out += '_{%s}' % sub
            if sup:
                out += '^{%s}' % sup
            if var & 0x01:  # chỉ số đứng trước
                out = '{}' + out
            return out
        if sel == 30:
            return r'\left\langle %s \middle| %s \right\rangle' % (slot(0), slot(1))
        if sel == 31:  # vectơ
            left, right, under, harpoon = var & 1, var & 2, var & 4, var & 8
            pos = 'under' if under else 'over'
            if harpoon:
                name = pos + ('leftharpoon' if left and not right else 'rightharpoon')
            elif left and right:
                name = pos + 'leftrightarrow'
            elif left:
                name = pos + 'leftarrow'
            else:
                name = pos + 'rightarrow'
            return '\\%s{%s}' % (name, slot(0))
        if sel == 32:
            return r'\widetilde{%s}' % slot(0)
        if sel == 33:
            return r'\widehat{%s}' % slot(0)
        if sel == 34:
            return r'\overset{\frown}{%s}' % slot(0)
        if sel == 35:
            return slot(0)
        if sel == 36:
            return r'\cancel{%s}' % slot(0)
        if sel == 37:
            return r'\boxed{%s}' % slot(0)
        if self.strict:
            raise UnsupportedTemplate(f'template {sel} variation {var}')
        self.unknown.append(f'tmpl{sel}')
        return _join([self.node(s) for s in slots])

    def _fence(self, sel: int, var: int, main: str, chars: List[Char]) -> str:
        glyphs = [_char_text(c.code) for c in chars]
        if sel == 9 or len(glyphs) == 2:
            left = glyphs[0] if glyphs else ''
            right = glyphs[1] if len(glyphs) > 1 else ''
        elif len(glyphs) == 1:
            if var & 0x01 and not var & 0x02:
                left, right = glyphs[0], ''
            elif var & 0x02 and not var & 0x01:
                left, right = '', glyphs[0]
            else:
                left, right = glyphs[0], ''
        else:
            left = right = ''
        default = FENCE_BY_SELECTOR.get(sel, ('.', '.'))
        lf = FENCE.get(left, default[0]) if left else '.'
        rf = FENCE.get(right, default[1]) if right else '.'
        if lf == '.' and rf == '.':
            return main
        return r'\left%s %s \right%s' % (lf, main, rf)

    def _bigop(self, op: str, slots: List[Node], limits: bool) -> str:
        main = self.node(slots[0]) if slots else ''
        lower = self.node(slots[1]) if len(slots) > 1 else ''
        upper = self.node(slots[2]) if len(slots) > 2 else ''
        out = op + (r'\limits' if limits and (lower or upper) and op not in (
            r'\sum', r'\prod', r'\coprod', r'\bigcup', r'\bigcap') else '')
        if lower:
            out += '_{%s}' % lower
        if upper:
            out += '^{%s}' % upper
        return _join([out, ' ', main]) if main else out


_SPLIT_FN = re.compile(
    r'(?:\\operatorname\{([a-z]+)\}|(?<![\\A-Za-z])([a-z]))\\mathrm\{([a-z0-9]+)\}')


def _merge_split_function(m: re.Match) -> str:
    r"""'\operatorname{s}\mathrm{inx}' (tên hàm gõ lẫn hai kiểu chữ) -> '\sin x'."""
    prefix = m.group(1) or m.group(2)
    word = prefix + m.group(3)
    for fn in sorted(FUNCTIONS, key=len, reverse=True):
        # tên hàm phải vắt qua cả hai phần (không gộp "d\mathrm{x}")
        if word.startswith(fn) and len(fn) > len(prefix):
            rest = word[len(fn):]
            return '\\' + fn + ' ' + rest
    return m.group(0)


def _tidy(s: str) -> str:
    s = _SPLIT_FN.sub(_merge_split_function, s)
    s = re.sub(r'[ ]{2,}', ' ', s)
    s = re.sub(r' +([)\]},;.])', r'\1', s)
    s = re.sub(r'([(\[{]) +', r'\1', s)
    s = s.strip()
    # Không để lại "\" lẻ ở cuối (vd "\ " bị cắt khoảng trắng).
    if re.search(r'(?<!\\)(\\\\)*\\$', s):
        s = s[:-1].rstrip()
    return s


@dataclass
class Converted:
    latex: Optional[str]
    error: str = ''
    unknown: List[str] = field(default_factory=list)


def ole_to_latex(data: bytes) -> Converted:
    body = mtef_body_from_ole(data)
    if body is None:
        return Converted(None, 'not_mathtype')
    return body_to_latex(body)


def picture_to_latex(data: bytes) -> Converted:
    body = mtef_body_from_picture(data)
    if body is None:
        return Converted(None, 'not_mathtype')
    return body_to_latex(body)


def body_to_latex(body: bytes) -> Converted:
    if not body or body[0] != 5:
        return Converted(None, f'mtef_v{body[0] if body else 0}')
    try:
        tree = parse(body)
    except MtefError as exc:
        return Converted(None, f'parse: {exc}')
    gen = _Latex()
    latex = _tidy(gen.nodes(tree))
    return Converted(latex, '', gen.unknown)

"""Đọc file .docx thành danh sách đoạn văn, công thức MathType thay bằng $LaTeX$.

Mỗi đoạn là một ``Para``: chữ (có ``\\t`` cho tab, ``\\n`` cho xuống dòng),
danh sách ảnh hình vẽ trong đoạn, và số công thức không chuyển được. Đoạn trong
bảng được trả về theo thứ tự đọc (hàng → ô → đoạn), đánh dấu ``in_table``.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from lxml import etree

try:
    from . import mtef
except ImportError:  # chạy trực tiếp như script
    import mtef  # type: ignore

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
O = '{urn:schemas-microsoft-com:office:office}'
V = '{urn:schemas-microsoft-com:vml}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'

EQ_MISSING = '[[CÔNG_THỨC_LỖI]]'

# Bảng mã TCVN3 (ABC) -> Unicode, dùng cho font ".VnTime", ".VnArial"...
# Font kết thúc bằng "H" (".VnTimeH") là font chữ hoa: cùng mã nhưng hiển thị
# in hoa.
_TCVN3 = dict(zip(
    '¸µ¶·¹¨¾»¼½Æ©ÊÇÈÉË®ÐÌÎÏÑªÕÒÓÔÖÝ×ØÜÞãßáâä«èåæçé¬íêëìîóïñòô­øõö÷ùýúûüþ¡¢§£¤¥¦',
    'áàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵĂÂĐÊÔƠƯ'))


def tcvn3_to_unicode(text: str, uppercase: bool = False) -> str:
    out = ''.join(_TCVN3.get(c, c) for c in text)
    return out.upper() if uppercase else out


def _legacy_font(run) -> Optional[str]:
    rpr = run.find(W + 'rPr')
    fonts = rpr.find(W + 'rFonts') if rpr is not None else None
    if fonts is None:
        return None
    name = fonts.get(W + 'ascii') or fonts.get(W + 'hAnsi') or ''
    return name if name.lower().startswith('.vn') else None


@dataclass
class Para:
    text: str
    images: List[str] = field(default_factory=list)
    eq_failed: int = 0
    in_table: bool = False
    style: str = ''
    # Chữ cái phương án (A-D) tô đỏ — cách tài liệu đánh dấu đáp án đúng.
    red_letters: List[str] = field(default_factory=list)


@dataclass
class DocStats:
    equations: int = 0
    eq_failed: int = 0
    equations_from_pictures: int = 0
    errors: Dict[str, int] = field(default_factory=dict)


class DocxReader:
    def __init__(self, path: str):
        self.path = path
        self.zip = zipfile.ZipFile(path)
        self.rels = self._rels()
        self.stats = DocStats()
        self._cache: Dict[str, Optional[str]] = {}
        self._pic_cache: Dict[str, Optional[str]] = {}
        self._abstract, self._nums, self._style_num = self._numbering()
        self._counters: Dict[str, List[int]] = {}
        self._seen_nums: set = set()

    def _rels(self) -> Dict[str, str]:
        root = etree.fromstring(self.zip.read('word/_rels/document.xml.rels'))
        out = {}
        for rel in root:
            target = rel.get('Target', '')
            if rel.get('TargetMode') == 'External':
                continue
            out[rel.get('Id')] = posixpath.normpath(posixpath.join('word', target))
        return out

    def _xml(self, name: str):
        try:
            return etree.fromstring(self.zip.read(name))
        except KeyError:
            return None

    def _numbering(self):
        abstract: Dict[str, Dict[int, tuple]] = {}
        nums: Dict[str, tuple] = {}
        style_num: Dict[str, tuple] = {}
        root = self._xml('word/numbering.xml')
        if root is not None:
            for a in root.findall(W + 'abstractNum'):
                levels = {}
                for lvl in a.findall(W + 'lvl'):
                    def val(tag, default=''):
                        el = lvl.find(W + tag)
                        return el.get(W + 'val', default) if el is not None else default
                    levels[int(lvl.get(W + 'ilvl', '0'))] = (
                        int(val('start', '1') or 1), val('numFmt', 'decimal'),
                        val('lvlText', ''))
                abstract[a.get(W + 'abstractNumId')] = levels
            for n in root.findall(W + 'num'):
                ab = n.find(W + 'abstractNumId')
                overrides = {}
                for ov in n.findall(W + 'lvlOverride'):
                    so = ov.find(W + 'startOverride')
                    if so is not None:
                        overrides[int(ov.get(W + 'ilvl', '0'))] = int(so.get(W + 'val'))
                if ab is not None:
                    nums[n.get(W + 'numId')] = (ab.get(W + 'val'), overrides)
        styles = self._xml('word/styles.xml')
        if styles is not None:
            for st in styles.findall(W + 'style'):
                np_ = st.find(W + 'pPr/' + W + 'numPr')
                if np_ is None:
                    continue
                nid = np_.find(W + 'numId')
                il = np_.find(W + 'ilvl')
                if nid is not None:
                    style_num[st.get(W + 'styleId')] = (
                        nid.get(W + 'val'), int(il.get(W + 'val')) if il is not None else 0)
        return abstract, nums, style_num

    def _num_label(self, num_id: str, ilvl: int) -> str:
        """Nhãn đánh số tự động của đoạn (vd "Câu 12."), rỗng nếu là bullet."""
        if num_id in ('', '0') or num_id not in self._nums:
            return ''
        ab_id, overrides = self._nums[num_id]
        levels = self._abstract.get(ab_id, {})
        counters = self._counters.setdefault(ab_id, [0] * 9)
        if num_id not in self._seen_nums:
            self._seen_nums.add(num_id)
            for lv, start in overrides.items():
                counters[lv] = start - 1
                for deeper in range(lv + 1, 9):
                    counters[deeper] = 0
        start, fmt, text = levels.get(ilvl, (1, 'decimal', ''))
        if counters[ilvl] == 0:
            counters[ilvl] = start - 1
        counters[ilvl] += 1
        for deeper in range(ilvl + 1, 9):
            counters[deeper] = 0
        if fmt in ('bullet', 'none') or not text:
            return ''

        def fmt_num(n: int, f: str) -> str:
            if f == 'upperLetter':
                return chr(64 + (n - 1) % 26 + 1)
            if f == 'lowerLetter':
                return chr(96 + (n - 1) % 26 + 1)
            if f in ('upperRoman', 'lowerRoman'):
                vals = [(10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]
                out, k = '', n
                for v, sym in vals:
                    while k >= v:
                        out, k = out + sym, k - v
                return out if f == 'upperRoman' else out.lower()
            return str(n)

        def repl(m):
            lv = int(m.group(1)) - 1
            lfmt = levels.get(lv, (1, 'decimal', ''))[1]
            return fmt_num(counters[lv] or 1, lfmt)

        return re.sub(r'%(\d)', repl, text)

    def read_media(self, name: str) -> bytes:
        return self.zip.read(name)

    # ------------------------------------------------------------------
    def _equation(self, rid: Optional[str]) -> Optional[str]:
        target = self.rels.get(rid or '')
        if not target:
            return None
        if target not in self._cache:
            self.stats.equations += 1
            conv = mtef.ole_to_latex(self.zip.read(target))
            if conv.latex is None:
                self.stats.eq_failed += 1
                key = conv.error.split(':')[0]
                self.stats.errors[key] = self.stats.errors.get(key, 0) + 1
            self._cache[target] = conv.latex
        return self._cache[target]

    def paragraphs(self) -> Iterator[Para]:
        root = etree.fromstring(self.zip.read('word/document.xml'))
        body = root.find(W + 'body')
        yield from self._block(body, in_table=False)

    def _block(self, el, in_table: bool) -> Iterator[Para]:
        for child in el:
            if child.tag == W + 'p':
                yield self._para(child, in_table)
            elif child.tag == W + 'tbl':
                for cell in child.iter(W + 'tc'):
                    for p in cell.findall(W + 'p'):
                        yield self._para(p, True)
            elif child.tag == W + 'sdt':
                content = child.find(W + 'sdtContent')
                if content is not None:
                    yield from self._block(content, in_table)

    def _para(self, p, in_table: bool) -> Para:
        out: List[str] = []
        images: List[str] = []
        failed = 0
        style = ''
        red_letters: List[str] = []
        num_id, ilvl = '', 0
        ppr = p.find(W + 'pPr')
        if ppr is not None:
            ps = ppr.find(W + 'pStyle')
            if ps is not None:
                style = ps.get(W + 'val', '')
                num_id, ilvl = self._style_num.get(style, ('', 0))
            np_ = ppr.find(W + 'numPr')
            if np_ is not None:
                nid = np_.find(W + 'numId')
                il = np_.find(W + 'ilvl')
                if nid is not None:
                    num_id = nid.get(W + 'val')
                if il is not None:
                    ilvl = int(il.get(W + 'val'))
        label = self._num_label(num_id, ilvl) if num_id else ''
        if label:
            out.append(label + ' ')

        legacy = {'font': None}

        def visit(node) -> None:
            nonlocal failed
            tag = node.tag
            if tag == W + 't':
                txt = node.text or ''
                if legacy['font']:
                    txt = tcvn3_to_unicode(txt, legacy['font'].lower().endswith('h'))
                out.append(txt)
                return
            if tag == W + 'r':
                rpr = node.find(W + 'rPr')
                color = rpr.find(W + 'color') if rpr is not None else None
                if color is not None and color.get(W + 'val', '').upper() == 'FF0000':
                    txt = ''.join(t.text or '' for t in node.findall(W + 't'))
                    found = re.findall(r'(?<![A-Za-zÀ-ỹ])([A-D])\s*\.', txt)
                    if not found:
                        # chữ cái tô đỏ, dấu chấm nằm ở run sau
                        found = re.findall(r'^\s*([A-D])\s*$', txt)
                    red_letters.extend(found)
                legacy['font'] = _legacy_font(node)
                for c in node:
                    visit(c)
                legacy['font'] = None
                return
            if tag == W + 'tab':
                out.append('\t')
                return
            if tag in (W + 'br', W + 'cr'):
                out.append('\n')
                return
            if tag == W + 'object':
                ole = node.find('.//' + O + 'OLEObject')
                if ole is not None:
                    latex = self._equation(ole.get(R + 'id'))
                    if latex is not None:
                        if latex:
                            out.append('$' + latex + '$')
                        return
                    if ole.get('ProgID', '').startswith('Equation'):
                        # Công thức không đọc được (vd Equation Editor 3.0):
                        # thử ảnh xem trước, không được thì đánh dấu thiếu.
                        n_before = len(out)
                        preview: List[str] = []
                        for im in node.iter(V + 'imagedata'):
                            self._add_image(im.get(R + 'id'), preview, out)
                        if preview:
                            del out[n_before:]
                            failed += 1
                            out.append(EQ_MISSING)
                            images.extend(preview)
                        elif len(out) == n_before:
                            failed += 1
                            out.append(EQ_MISSING)
                        return
                # đối tượng không phải công thức: lấy ảnh xem trước
                for im in node.iter(V + 'imagedata'):
                    self._add_image(im.get(R + 'id'), images, out)
                return
            if tag == MC + 'AlternateContent':
                # Choice và Fallback là hai bản của cùng một nội dung.
                choice = node.find(MC + 'Choice')
                if choice is None:
                    choice = node.find(MC + 'Fallback')
                if choice is not None:
                    for c in choice:
                        visit(c)
                return
            if tag == W + 'drawing':
                for blip in node.iter(A + 'blip'):
                    self._add_image(blip.get(R + 'embed'), images, out)
                self._textboxes(node, in_table, out, images)
                return
            if tag == W + 'pict':
                for im in node.iter(V + 'imagedata'):
                    self._add_image(im.get(R + 'id'), images, out)
                self._textboxes(node, in_table, out, images)
                return
            if tag in (M + 'oMath', M + 'oMathPara'):
                out.append('[[OMML]]')
                return
            if tag in (W + 'del', W + 'delText', W + 'instrText'):
                return
            for c in node:
                visit(c)

        for c in p:
            if c.tag == W + 'pPr':
                continue
            visit(c)
        return Para(''.join(out), images, failed, in_table, style, red_letters)

    def _textboxes(self, node, in_table: bool, out: List[str],
                   images: List[str]) -> None:
        """Chữ trong hộp văn bản (thường là nhãn trên hình vẽ)."""
        for tb in node.iter(W + 'txbxContent'):
            for q in tb.findall(W + 'p'):
                sub = self._para(q, in_table)
                if sub.text.strip():
                    out.append(' ' + sub.text.strip() + ' ')
                images.extend(sub.images)

    def _add_image(self, rid: Optional[str], images: List[str], out: List[str]) -> None:
        target = self.rels.get(rid or '')
        if not target:
            return
        if target.lower().endswith(('.wmf', '.emf')):
            # Công thức MathType dán dạng ảnh vẫn mang dữ liệu MTEF.
            if target not in self._pic_cache:
                conv = mtef.picture_to_latex(self.zip.read(target))
                if conv.latex is not None:
                    self.stats.equations_from_pictures += 1
                self._pic_cache[target] = conv.latex
            latex = self._pic_cache[target]
            if latex is not None:
                if latex:
                    out.append('$' + latex + '$')
                return
        images.append(target)
        out.append(f'[[HÌNH:{posixpath.basename(target)}]]')

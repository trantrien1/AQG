"""Tách câu hỏi từ đề thi thử Toán THPT (nhiều định dạng) thành dataset JSONL.

    python dataset/tools/build_exams.py --src "dataset/De_thi_nhieu_dang_format" --out dataset/export/exams

Ba dạng câu hỏi (trường ``type``):
    mcq           4 phương án A–D, một đáp án (Phần I, và đề 50 câu kiểu cũ)
    true_false    4 mệnh đề a)–d), mỗi mệnh đề Đúng/Sai (Phần II)
    short_answer  đáp số là một số (Phần III)

Chỉ giữ câu có lời giải; câu chỉ có đáp án bị bỏ qua (đếm trong build_report.json).

Các định dạng tài liệu nhận dạng được:
    inline  mỗi câu gồm đề, rồi tiêu đề "Lời giải"/"Hướng dẫn"/"HD giải", rồi lời giải
            (đề phát triển minh họa 2024 đánh dấu đáp án bằng "*A."; file đáp án chi
            tiết chép lại đề và tô đỏ đáp án).
    keyed   phần đề riêng; đáp án ở bảng và lời giải đánh số "Câu N" theo từng phần,
            nằm sau dòng "ĐÁP ÁN"/"LỜI GIẢI" hoặc ở một file riêng.

Công cụ này chỉ dùng lại (import) ``docx_text``, ``mtef`` và ``build_dataset``,
không sửa các module đó. Độ khó, chủ đề và kết quả rà soát tay lấy từ
``dataset/labels/exams.tsv``.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_dataset import (  # noqa: E402
    DIFFICULTY_NAMES, OMML_MARK, RE_FIGURE_REF, RE_IMAGE, RE_IMAGE_MD, _mask_math,
    _read_tsv, clean, export_image, split_options)
from docx_text import EQ_MISSING, W, DocxReader, Para, tcvn3_to_unicode  # noqa: E402

# ---------------------------------------------------------------------------
# Danh sách đề
# ---------------------------------------------------------------------------


@dataclass
class Exam:
    key: str
    title: str
    file: str                       # file đề (hoặc file đáp án có chép lại đề)
    layout: str                     # 'inline' | 'keyed'
    solution_file: Optional[str] = None
    archive: Optional[str] = None   # file .rar chứa ``file``/``solution_file`` (mẫu glob)
    year: Optional[int] = None


PART_NAMES = {
    0: 'Trắc nghiệm nhiều phương án (đề 50 câu)',
    1: 'Phần I – Trắc nghiệm nhiều phương án',
    2: 'Phần II – Trắc nghiệm đúng sai',
    3: 'Phần III – Trắc nghiệm trả lời ngắn',
}
PART_TYPES = {0: 'mcq', 1: 'mcq', 2: 'true_false', 3: 'short_answer'}


def exam_list(src: Path) -> Tuple[List[Exam], List[Tuple[str, str]]]:
    """Các đề được dùng, và các file bỏ qua kèm lý do."""
    exams: List[Exam] = []
    for f in sorted(src.glob('DE *-MINH HOA TOAN 2024.docx'),
                    key=lambda p: int(re.search(r'DE (\d+)', p.name).group(1))):
        n = int(re.search(r'DE (\d+)', f.name).group(1))
        exams.append(Exam(f'mh24-{n:02d}', f'Phát triển đề minh họa 2024 – đề {n}',
                          f.name, 'inline', year=2024))
    exams += [
        Exam('nghean26-l2', 'Sở GD&ĐT Nghệ An – khảo sát lớp 12 đợt 2, 2025–2026',
             '-2026-mon-Toan-So-GD-Nghe-An-Lan-2.docx', 'keyed', year=2026),
        Exam('thainguyen26-l2', 'Sở GD&ĐT Thái Nguyên – thi thử lần 2, 2026',
             '-2026-mon-Toan-So-GD-Thai-Nguyen-Lan-2.docx', 'keyed', year=2026),
        Exam('thanhhoa26-l2', 'Sở GD&ĐT Thanh Hóa – thi thử lần 2, 2026',
             '-2026-mon-Toan-So-GD-Thanh-Hoa-lan-2.docx', 'keyed', year=2026),
        Exam('camau26-l1', 'Sở GD&ĐT Cà Mau – thi thử lần 1, 2026',
             '-2026-monToan-So-GD-Ca-Mau-lan-1.docx', 'keyed', year=2026),
        Exam('danang26-l1', 'Sở GD&ĐT Đà Nẵng – thi thử lần 1, 2026',
             '-2026-monToan-So-GD-Da-Nang-lan-1.docx', 'keyed', year=2026),
        Exam('camau26-vd', 'Sở GD&ĐT Cà Mau – hướng dẫn giải các câu vận dụng, thi thử 2026',
             'Cà Mau - HD CÁC CÂU VD DETHITHU_2026.docx', 'inline', year=2026),
        Exam('dqham26', 'THPT Dương Quảng Hàm (Hưng Yên) – thi thử lần 2, 2026',
             'THPT DƯƠNG QUẢNG HÀM.docx', 'keyed',
             solution_file='ĐÁP ÁN THAM KHẢO.docx', year=2026),
        Exam('tqbuu26', 'THPT Tạ Quang Bửu – khảo sát lớp 12, 2026',
             'Đề khảo sát Tạ Quang Bửu.docx', 'keyed',
             solution_file='Đáp án và lời giải chi tiết Đề khảo sát 12 Tạ Quang Bửu.docx',
             year=2026),
        Exam('thoxuan5-26', 'THPT Thọ Xuân 5 (Thanh Hóa) – khảo sát lớp 12, 2025–2026',
             'ĐÁP ÁN*.docx', 'inline',
             archive='2026-Toan-thpt-tho-xuan-5-thanh-hoa.rar', year=2026),
    ]
    for n in (6, 7, 8, 9, 10):
        exams.append(Exam(f'thithu25-{n:02d}', f'Đề thi thử 2025 – đề số {n}',
                          f'*ĐÁP ÁN CHI TIẾT ĐỀ SỐ {n}.docx', 'inline',
                          archive='5De-Thi-Thu-Toan-2025-word.rar', year=2025))
    skipped = [
        ('Toán_Cà_Mau-Ma_de_0123.docx', 'chỉ có đề, không có lời giải'),
        ('Cà Mau - HD CÁC CÂU VD DETHITHU_2026 (1).docx', 'bản sao giống hệt file không có "(1)"'),
        ('0102-2026-cum-cac-truong-thpt-chuyen-phu-tho.rar', 'chỉ có bảng đáp án, không có lời giải'),
        ('ĐỀ-Đáp án L3-lien-truong-thpt-chuyen-qnam-cu.pdf', 'bản quét, chỉ có bảng đáp án'),
        ('DE 31-MINH HOA TOAN 2024.docx.pdf', 'bản PDF của file .docx cùng tên'),
        ('Đề khảo sát Tạ Quang Bửu.docx', 'dùng làm phần đề; lời giải ở file đáp án'),
        ('*.txt', 'quảng cáo của trang chia sẻ tài liệu'),
    ]
    return exams, skipped


# ---------------------------------------------------------------------------
# Đọc docx, giữ vị trí ô bảng
# ---------------------------------------------------------------------------


class TableAwareReader(DocxReader):
    """``DocxReader`` ghi thêm ``table_pos = (bảng, hàng, ô)`` cho đoạn trong bảng.

    Chỉ ghi đè ``_block``; thứ tự đoạn giống hệt ``DocxReader``.
    """

    def __init__(self, path: str):
        super().__init__(path)
        self._table_ids: Dict[object, int] = {}

    def _block(self, el, in_table: bool) -> Iterator[Para]:
        for child in el:
            if child.tag == W + 'p':
                para = self._para(child, in_table)
                para.table_pos = None
                yield para
            elif child.tag == W + 'tbl':
                for cell in child.iter(W + 'tc'):
                    pos = self._cell_pos(cell)
                    for p in cell.findall(W + 'p'):
                        para = self._para(p, True)
                        para.table_pos = pos
                        yield para
            elif child.tag == W + 'sdt':
                content = child.find(W + 'sdtContent')
                if content is not None:
                    yield from self._block(content, in_table)

    @staticmethod
    def _children(el, tag: str) -> list:
        """Con trực tiếp có thẻ ``tag``, kể cả con bọc trong w:sdt."""
        out = []
        for c in el:
            if c.tag == tag:
                out.append(c)
            elif c.tag == W + 'sdt':
                content = c.find(W + 'sdtContent')
                if content is not None:
                    out.extend(x for x in content if x.tag == tag)
        return out

    def _cell_pos(self, cell) -> Optional[Tuple[int, int, int]]:
        row = cell.getparent()
        while row is not None and row.tag != W + 'tr':
            row = row.getparent()
        tbl = row.getparent() if row is not None else None
        while tbl is not None and tbl.tag != W + 'tbl':
            tbl = tbl.getparent()
        if row is None or tbl is None:
            return None
        rows = self._children(tbl, W + 'tr')
        cells = self._children(row, W + 'tc')
        # Khoá là chính phần tử: giữ tham chiếu để proxy lxml không bị tạo lại.
        tid = self._table_ids.setdefault(tbl, len(self._table_ids))
        return (tid, rows.index(row) if row in rows else -1,
                cells.index(cell) if cell in cells else -1)


# Chữ Kirin trông giống chữ Latinh (vd "а)" gõ nhầm bằng bàn phím Nga).
_LOOKALIKE = str.maketrans('аеорсухАВЕКМНОРСТХ', 'aeopcyxABEKMHOPCTX')


@dataclass
class Line:
    text: str
    table: Optional[Tuple[int, int, int]]
    red: List[str]
    eq_failed: int = 0

    @property
    def in_table(self) -> bool:
        return self.table is not None


def read_lines(reader: DocxReader) -> List[Line]:
    """Đoạn văn → dòng (tách tại xuống dòng mềm), chuẩn hoá NFC."""
    lines: List[Line] = []
    for p in reader.paragraphs():
        text = unicodedata.normalize('NFC', p.text).translate(_LOOKALIKE)
        pos = getattr(p, 'table_pos', None)
        for k, part in enumerate(text.split('\n')):
            lines.append(Line(part, pos, list(p.red_letters), p.eq_failed if k == 0 else 0))
    return lines


# ---------------------------------------------------------------------------
# Nhận dạng dòng
# ---------------------------------------------------------------------------

RE_PART = re.compile(r'^\s*PH[ẦA]N\s+(III|II|I|[123])(?![A-Za-zÀ-ỹ])', re.I)
RE_Q = re.compile(r'^\s*Câu\s*(\d{1,2})(?:\.\d)?\s*[.:]?\s*')
# Tiêu đề lời giải; phần còn lại của dòng (nếu có) là câu đầu của lời giải.
RE_SOL_HEAD = re.compile(
    r'^\s*(?:Lời\s*giải(?:\s*chi\s*tiết)?|LỜI\s*GIẢI|Hướng\s*dẫn(?:\s*giải)?|HƯỚNG\s*DẪN(?:\s*GIẢI)?'
    r'|HD\s*giải|HD\s*:|Giải\s*:|Giải\s*$|Phần\s*giải\s*chi\s*tiết)\s*[:.]?\s*')
# Hết phần đề (bố cục keyed): dòng viết hoa, ngoài bảng.
RE_END_QUESTIONS = re.compile(
    r'^[\s\-–—.]*(HẾT|ĐÁP ÁN|BẢNG ĐÁP ÁN|LỜI GIẢI|HƯỚNG DẪN GIẢI|HƯỚNG DẪN CHẤM)\b')
RE_STAR = re.compile(r'\*\s*(?=[A-D]\s*[.)])')
RE_AUTHOR_LEVEL = re.compile(r'^\s*\(\s*(NB|TH|VDC|VD)\s*\)\s*:?\s*')
RE_STMT_MARK = re.compile(r'(?:(?<=[\s\x00\x01.;\]])|^)([a-d])\)\s*')
RE_LOST_TEXT = re.compile(r'\\text\{[^}]*\?[^}]*\}')

ROMAN = {'I': 1, 'II': 2, 'III': 3, '1': 1, '2': 2, '3': 3}


def part_of(line: Line) -> Optional[int]:
    if line.in_table:
        return None
    m = RE_PART.match(line.text)
    return ROMAN[m.group(1).upper()] if m else None


# ---------------------------------------------------------------------------
# Bảng: dựng lại lưới ô, hiển thị dạng bảng Markdown
# ---------------------------------------------------------------------------


def table_grid(lines: List[Line]) -> List[List[str]]:
    cells: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    for ln in lines:
        _, r, c = ln.table
        if ln.text.strip():
            cells[(r, c)].append(ln.text.strip())
    if not cells:
        return []
    n_rows = max(r for r, _ in cells) + 1
    n_cols = max(c for _, c in cells) + 1
    return [[' '.join(cells.get((r, c), [])) for c in range(n_cols)] for r in range(n_rows)]


RE_MARK_START = re.compile(r'^\s*\*?\s*(?:[A-D]\s*[.)]|[a-d]\))')


def render(lines: List[Line]) -> str:
    """Ghép dòng thành chữ; bảng dữ liệu thành bảng Markdown.

    Bảng chỉ để dàn trang phương án/mệnh đề (ô bắt đầu bằng "A." hay "a)") được
    trải ra thành dòng thường để tách phương án như bình thường.
    """
    out: List[str] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if not ln.in_table:
            out.append(ln.text)
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].in_table and lines[j].table[0] == ln.table[0]:
            j += 1
        grid = table_grid(lines[i:j])
        filled = [c for row in grid for c in row if c.strip()]
        if filled and all(RE_MARK_START.match(c) for c in filled):
            out.extend(filled)
        elif len(filled) <= 1 or max(len(r) for r in grid) == 1:
            out.extend(filled)           # bảng một cột: khung trang trí
        elif grid:
            rows = [r for r in grid if any(c.strip() for c in r)]
            n = max(len(r) for r in rows)
            md = ['| ' + ' | '.join(c.replace('|', '\\|') or ' ' for c in r + [''] * (n - len(r))) + ' |'
                  for r in rows]
            md.insert(1, '|' + '---|' * n)
            out.append('')
            out.extend(md)
            out.append('')
        i = j
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Bảng đáp án
# ---------------------------------------------------------------------------

RE_QNUM_CELL = re.compile(r'^(?:Câu\s*)?(\d{1,2})\s*\.?$', re.I)


def _cell(s: str) -> str:
    s = s.replace('$', '').replace('\\,', '').replace('~', ' ')
    return re.sub(r'\s+', ' ', s).strip().rstrip('.').strip()


def _tf_value(s: str) -> Optional[str]:
    t = _cell(s)
    t = re.sub(r'^[a-d]\)\s*', '', t)
    low = t.lower()
    if low in ('đ', 'đúng'):
        return 'Đ'
    if low in ('s', 'sai'):
        return 'S'
    return None


def parse_answer(s: str, part: int) -> Optional[str]:
    t = _cell(s)
    if part in (0, 1):
        return t if re.fullmatch(r'[A-D]', t) else None
    if part == 2:
        compact = re.sub(r'[\s,;.]', '', t)
        compact = compact.replace('Đúng', 'Đ').replace('Sai', 'S')
        return compact if re.fullmatch(r'[ĐS]{4}', compact) else None
    m = re.fullmatch(r'(-?\d+(?:[.,]\d+)?)(?:\s*[^\d\s].*)?', t)
    return m.group(1) if m else None


def keys_from_table(grid: List[List[str]], part: int) -> Dict[int, str]:
    """Đọc cặp (số câu, đáp án) từ một bảng; hỗ trợ bảng ngang, dọc, nhiều cặp cột."""
    found: Dict[int, str] = {}
    n_rows = len(grid)

    def cell(r: int, c: int) -> str:
        return grid[r][c] if 0 <= r < n_rows and 0 <= c < len(grid[r]) else ''

    def qnum(r: int, c: int) -> Optional[int]:
        m = RE_QNUM_CELL.match(_cell(cell(r, c)))
        return int(m.group(1)) if m else None

    def tf_right(r: int, c: int) -> Optional[str]:
        one = parse_answer(cell(r, c + 1), 2)
        if one:
            return one
        vals = [_tf_value(cell(r, c + k)) for k in range(1, 5)]
        return ''.join(vals) if all(vals) else None

    def is_header_row(r: int) -> bool:
        return _cell(cell(r, 0)).lower() in ('câu', 'câu\\mã đề') or all(
            qnum(r, c) is not None for c in range(len(grid[r])) if cell(r, c).strip())

    # Bảng ngang: một hàng số câu (≥ 3 số tăng dần), đáp án ở hàng ngay dưới.
    for r in range(n_rows):
        cols = [(c, qnum(r, c)) for c in range(len(grid[r])) if qnum(r, c) is not None]
        nums = [n for _, n in cols]
        if len(cols) >= 3 and nums == sorted(nums) and len(set(nums)) == len(nums) \
                and is_header_row(r) and r + 1 < n_rows:
            for c, n in cols:
                ans = parse_answer(cell(r + 1, c), part)
                if ans:
                    found.setdefault(n, ans)
    if found:
        return found
    # Bảng dọc: cột số câu, đáp án ở (các) ô bên phải cùng hàng.
    for r in range(n_rows):
        for c in range(len(grid[r])):
            n = qnum(r, c)
            if n is None:
                continue
            ans = tf_right(r, c) if part == 2 else parse_answer(cell(r, c + 1), part)
            if ans:
                found.setdefault(n, ans)
    return found


def is_key_table(grid: List[List[str]]) -> bool:
    """Bảng đáp án: có ô tiêu đề "Câu" (hoặc ≥ 3 ô "Câu N") và đọc được ≥ 3 cặp câu–đáp án."""
    cells = [_cell(c) for row in grid for c in row]
    header = any(c.lower() in ('câu', 'câu\\mã đề', 'câu hỏi', 'câu/mã đề') for c in cells)
    header = header or sum(bool(re.fullmatch(r'Câu\s*\d{1,2}', c)) for c in cells) >= 3
    if not header:
        return False
    return any(len(keys_from_table(grid, p)) >= (2 if p == 2 else 3) for p in (1, 2, 3)) \
        or any(c.lower() in ('đáp án', 'đa', 'chọn') for c in cells)


def collect_tables(lines: List[Line]) -> List[Tuple[int, List[List[str]]]]:
    """Mọi bảng trong dãy dòng, kèm phần (I/II/III) của tiêu đề gần nhất phía trước."""
    out: List[Tuple[int, List[List[str]]]] = []
    part = 0
    i = 0
    while i < len(lines):
        ln = lines[i]
        p = part_of(ln)
        if p:
            part = p
        if not ln.in_table:
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].in_table and lines[j].table[0] == ln.table[0]:
            j += 1
        out.append((part, table_grid(lines[i:j])))
        i = j
    return out


def answer_tables(lines: List[Line]) -> Dict[Tuple[int, int], str]:
    keys: Dict[Tuple[int, int], str] = {}
    for part, grid in collect_tables(lines):
        if not grid:
            continue
        parts = [part] if part else [1, 2, 3]
        for p in parts:
            got = keys_from_table(grid, p)
            if len(got) >= 3 or (p == 2 and len(got) >= 2):
                for n, a in got.items():
                    keys.setdefault((p, n), a)
                break
    return keys


# ---------------------------------------------------------------------------
# Tách khối câu hỏi
# ---------------------------------------------------------------------------


@dataclass
class Block:
    part: int
    number: int
    lines: List[Line] = field(default_factory=list)


# Dòng kết thúc câu cuối cùng: "--- HẾT ---", "BẢNG ĐÁP ÁN", "ĐÁP ÁN THAM KHẢO".
RE_CLOSE_BLOCK = re.compile(
    r'^[^A-Za-zÀ-ỹ0-9$]*HẾT[^A-Za-zÀ-ỹ0-9$]*$'
    r'|^\s*(?:BẢNG\s+ĐÁP\s+ÁN|ĐÁP\s+ÁN(?:\s+THAM\s+KHẢO)?)\s*[.:]?\s*$')


def split_blocks(lines: List[Line]) -> Tuple[List[Block], List[Line]]:
    """Chia dãy dòng thành khối "Câu N" theo phần.

    Trả thêm các dòng không thuộc câu nào (tiêu đề, bảng đáp án) để đọc bảng đáp án
    mà không lẫn bảng số liệu nằm trong đề hay lời giải.
    """
    blocks: List[Block] = []
    loose: List[Line] = []
    part = 0
    cur: Optional[Block] = None
    key_table: Dict[int, bool] = {}
    for i, ln in enumerate(lines):
        if ln.in_table:
            tid = ln.table[0]
            if tid not in key_table:
                j = i
                while j < len(lines) and lines[j].in_table and lines[j].table[0] == tid:
                    j += 1
                key_table[tid] = is_key_table(table_grid(lines[i:j]))
            if key_table[tid]:
                loose.append(ln)     # bảng đáp án nằm lọt giữa các câu
                continue
        p = part_of(ln)
        if p:
            part = p
            cur = None
            loose.append(ln)
            continue
        if not ln.in_table and RE_CLOSE_BLOCK.match(ln.text):
            cur = None
            loose.append(ln)
            continue
        m = RE_Q.match(ln.text) if not ln.in_table else None
        if m:
            n = int(m.group(1))
            same = [b for b in blocks if b.part == part]
            if same and n <= same[-1].number and part in (1, 2):
                part += 1        # đánh số lại từ 1 mà không có tiêu đề phần
            cur = Block(part, n)
            blocks.append(cur)
            rest = ln.text[m.end():]
            cur.lines.append(Line(rest, None, ln.red, ln.eq_failed))
            continue
        if cur is not None:
            cur.lines.append(ln)
        else:
            loose.append(ln)
    return blocks, loose


def question_region(lines: List[Line]) -> Tuple[List[Line], List[Line]]:
    """Bố cục keyed: (phần đề, phần đáp án/lời giải) chia tại dòng "HẾT"/"ĐÁP ÁN"..."""
    seen_question = False
    for i, ln in enumerate(lines):
        if not ln.in_table and RE_Q.match(ln.text):
            seen_question = True
        if seen_question and not ln.in_table and RE_END_QUESTIONS.match(ln.text):
            return lines[:i], lines[i:]
    return lines, []


def _plain(text: str) -> str:
    text = re.sub(r'\$[^$]*\$|!\[hình\]\([^)]*\)|\[\[[^\]]*\]\]', ' ', text)
    return re.sub(r'[^0-9a-zà-ỹ]+', '', text.lower())


def repeats_question(text: str, parsed: 'Parsed') -> bool:
    """``text`` bắt đầu bằng chính đề bài (bỏ công thức, dấu câu)."""
    a, b = _plain(text), _plain(parsed.question)
    n = min(40, len(b))
    return n >= 10 and a[:n] == b[:n]


def split_at_header(lines: List[Line]) -> Tuple[List[Line], Optional[List[Line]]]:
    """(phần đề, phần lời giải) chia tại tiêu đề lời giải đầu tiên; None nếu không có."""
    for i, ln in enumerate(lines):
        if ln.in_table:
            continue
        m = RE_SOL_HEAD.match(ln.text)
        if m:
            rest = ln.text[m.end():]
            if len(rest) < 200:
                sol = ([Line(rest, None, ln.red)] if rest.strip() else []) + lines[i + 1:]
                return lines[:i], sol
    return lines, None


# ---------------------------------------------------------------------------
# Đề: phương án / mệnh đề / đáp số ghi trong đề
# ---------------------------------------------------------------------------


def split_statements(text: str) -> Optional[Tuple[str, List[str]]]:
    """Tách "... a) x b) y c) z d) w" thành (phần trước a, [x, y, z, w])."""
    masked, _ = _mask_math(text)
    positions = []
    start = 0
    for letter in 'abcd':
        found = None
        for m in RE_STMT_MARK.finditer(masked, start):
            if m.group(1) == letter:
                found = m
                break
        if not found:
            return None
        positions.append(found)
        start = found.end()
    head = text[:positions[0].start()]
    stmts = []
    for i, m in enumerate(positions):
        end = positions[i + 1].start() if i + 1 < len(positions) else len(text)
        stmts.append(clean(text[m.end():end]).rstrip(';').strip())
    return head, stmts


RE_SA_KEY = re.compile(
    r'(?:Đáp\s*số|Đáp\s*án(?:\s*là)?|Trả\s*lời|Kết\s*quả(?:\s*là)?)\s*[:.]?\s*'
    r'(?:Trả\s*lời\s*:\s*)?\$?\s*(-?\d+(?:[.,]\d+)?)(?:\s*\.?\s*\$)?', re.I)


@dataclass
class Parsed:
    question: str = ''
    choices: List[str] = field(default_factory=list)
    key: Optional[str] = None           # đáp án ghi trong phần đề (dấu *, chữ đỏ, "Trả lời:")
    key_how: Optional[str] = None
    problems: List[str] = field(default_factory=list)


# Dòng nhãn đáp án lọt vào phần đề: "Đáp án" (tiêu đề bảng), "Giải KQ: Đ-S-Đ-S."
RE_KEY_LABEL = re.compile(r'^\s*(?:Đáp\s*án|(?:Giải\s*)?KQ)\s*[:.]?\s*(?:[ĐS][\s,;.\-–]*){0,4}\.?\s*$')
RE_KQ_TF = re.compile(r'KQ\s*:?\s*([ĐS])\W*([ĐS])\W*([ĐS])\W*([ĐS])')


def parse_question(lines: List[Line], part: int) -> Parsed:
    out = Parsed()
    kq = None
    kept = []
    for ln in lines:
        if not ln.in_table and RE_KEY_LABEL.match(ln.text):
            m = RE_KQ_TF.search(ln.text)
            kq = ''.join(m.groups()) if m else kq
            continue
        kept.append(ln)
    lines = kept
    text = render(lines)
    if part in (0, 1):
        stars = []
        masked, _ = _mask_math(text)
        for m in RE_STAR.finditer(masked):
            stars.append(masked[m.end()])
        # xoá dấu * (đếm ngược để giữ vị trí)
        for m in reversed(list(RE_STAR.finditer(masked))):
            text = text[:m.start()] + text[m.end():]
        split = split_options(text)
        if split:
            head, choices = split
            out.question = clean(head)
            out.choices = [f'{k}. {v}' for k, v in zip('ABCD', choices)]
            if len(set(choices)) < 4:
                out.problems.append('duplicate_choices')
        else:
            out.question = clean(text)
            out.problems.append('no_choices')
        red = sorted({r for ln in lines for r in ln.red})
        if len(set(stars)) == 1:
            out.key, out.key_how = stars[0], 'star'
        elif len(red) == 1:
            out.key, out.key_how = red[0], 'red_mark'
        if len(set(stars)) > 1:
            out.problems.append('multiple_stars')
    elif part == 2:
        split = split_statements(text)
        if split:
            head, stmts = split
            out.question = clean(head)
            out.choices = [f'{k}) {v}' for k, v in zip('abcd', stmts)]
        else:
            out.question = clean(text)
            out.problems.append('no_statements')
        if kq:
            out.key, out.key_how = kq, 'text'
    else:
        m = None
        for m in RE_SA_KEY.finditer(text):
            pass
        if m and m.start() > len(text) * 0.5:
            out.key, out.key_how = m.group(1), 'text'
            text = text[:m.start()] + text[m.end():]
            text = re.sub(r'\$\s*\.?\s*\$|\$\s*\$', '', text)
        out.question = clean(text)
    return out


# ---------------------------------------------------------------------------
# Lời giải: đáp án ghi trong lời giải
# ---------------------------------------------------------------------------

RE_CHOOSE = re.compile(
    r'(?:Chọn|Đáp\s*án(?:\s*đúng)?(?:\s*là)?|Phương\s*án\s*đúng(?:\s*là)?)\s*(?:đáp\s*án\s*)?[:.#]?\s*'
    r'([A-D])(?![A-Za-zÀ-ỹ0-9(\'])\s*[.:]?')
RE_TF_LINE = re.compile(r'Đáp\s*án\s*(?:câu\s*\d+\s*)?:\s*([ĐS])\s*[,;]?\s*([ĐS])\s*[,;]?\s*([ĐS])\s*[,;]?\s*([ĐS])')
RE_TF_INLINE = re.compile(r'\(?([a-d])[).]\s*(Đúng|Sai|ĐÚNG|SAI)\b')
# Đầu một ý: "a)", "a.", "(a)", "Ý a)", "Mệnh đề a)"
RE_STMT_SEG = re.compile(r'^\s*(?:[ÝýYy]\s*|[Mm]ệnh\s*đề\s*|MỆNH\s*ĐỀ\s*|Câu\s*)?\(?([a-d])\s*[).]\s*')
_V = r'(không\s+)?(đúng|sai)(?![a-zà-ỹ])'
RE_VERDICT = re.compile(
    r'(?:Kết\s*luận\s*:?\s*(?:\(?[a-d]\)\s*)?'
    r'|Mệnh\s*đề(?:\s*\(?[a-d]\))?\s*(?:này\s*|đã\s*cho\s*|trên\s*)?(?:là\s*)?'
    r'|(?:nên|vậy|do\s*đó|suy\s*ra|⇒|=>|->|→|\\Rightarrow\$?)\s*'
    r'(?:mệnh\s*đề\s*|ý\s*|khẳng\s*định\s*|câu\s*)?(?:\(?[a-d]\)?\s*)?(?:là\s*)?\(?\s*'
    r'|^\s*\(?[a-d][).]\s*|Chọn\s*)' + _V, re.I)
RE_VERDICT_ALONE = re.compile(r'^\s*' + _V + r'\s*[.:!]?\s*$', re.I)
RE_LETTER_CELL = re.compile(r'^\(?([a-d])\s*[).]?$')


def _norm_tf(word: str, neg: Optional[str]) -> str:
    val = word.lower() == 'đúng'
    if neg:
        val = not val
    return 'Đ' if val else 'S'


def _tf_tables(lines: List[Line]) -> Dict[str, List[str]]:
    """Bảng kết luận trong lời giải: hàng "a) b) c) d)" + hàng Đúng/Sai, hoặc ô "a) Đúng"."""
    verdicts: Dict[str, List[str]] = defaultdict(list)
    i = 0
    while i < len(lines):
        if not lines[i].in_table:
            i += 1
            continue
        tid = lines[i].table[0]
        j = i
        while j < len(lines) and lines[j].in_table and lines[j].table[0] == tid:
            j += 1
        grid = table_grid(lines[i:j])
        for r, row in enumerate(grid):
            for c, cell in enumerate(row):
                t = _cell(cell)
                m = RE_TF_INLINE.fullmatch(t) or re.fullmatch(r'\(?([a-d])[).]\s*(Đ|S)', t)
                if m:
                    verdicts[m.group(1)].append(_tf_value(m.group(2)))
                    continue
                m = RE_LETTER_CELL.match(t)
                if not m:
                    continue
                below = _tf_value(grid[r + 1][c]) if r + 1 < len(grid) and c < len(grid[r + 1]) else None
                right = _tf_value(row[c + 1]) if c + 1 < len(row) else None
                if below or right:
                    verdicts[m.group(1)].append(below or right)
        i = j
    return verdicts


def tf_from_solution(sol_lines: List[Line]) -> Tuple[Optional[str], List[str]]:
    """Đọc Đúng/Sai từng mệnh đề trong lời giải. Trả (chuỗi "ĐĐSS" hoặc None, cảnh báo)."""
    text = '\n'.join(ln.text for ln in sol_lines)
    m = None
    for m in RE_TF_LINE.finditer(text):
        pass
    if m:
        return ''.join(m.groups()), []
    verdicts = _tf_tables(sol_lines)
    cur: Optional[str] = None
    for ln in sol_lines:
        if ln.in_table:
            continue
        t = ln.text
        # "Kết luận: a) Đúng; b) Sai; ..."
        pairs = RE_TF_INLINE.findall(t)
        if len(pairs) >= 2:
            for letter, word in pairs:
                verdicts[letter].append(_norm_tf(word, None))
            continue
        sm = RE_STMT_SEG.match(t)
        if sm:
            cur = sm.group(1).lower()
        if cur is None:
            continue
        vs = list(RE_VERDICT.finditer(t))
        if vs:
            v = vs[-1]
            verdicts[cur].append(_norm_tf(v.group(2), v.group(1)))
        elif RE_VERDICT_ALONE.match(t):
            v = RE_VERDICT_ALONE.match(t)
            verdicts[cur].append(_norm_tf(v.group(2), v.group(1)))
    warn = []
    out = ''
    for letter in 'abcd':
        vals = verdicts.get(letter, [])
        if not vals:
            return None, [f'tf_missing_{letter}']
        if len(set(vals)) > 1:
            warn.append(f'tf_conflict_{letter}')
        out += vals[-1]
    return out, warn


def mcq_from_solution(text: str) -> Optional[str]:
    found = [m.group(1) for m in RE_CHOOSE.finditer(text)]
    if not found:
        return None
    return found[0] if len(set(found)) == 1 else 'conflict:' + ''.join(sorted(set(found)))


def sa_from_solution(text: str) -> Optional[str]:
    m = None
    for m in RE_SA_KEY.finditer(text):
        pass
    return m.group(1) if m else None


RE_SA_KEY_LINE = re.compile(
    r'^\s*(?:(?:Trả\s*lời|Đáp\s*án|Đáp\s*số)\s*[:.]?\s*)+\$?\s*-?\d+(?:[.,]\d+)?\s*\.?\s*\$?'
    r'\s*[.]?\s*(?:[^\d\s$][^.\n]{0,25}\.?)?\s*$', re.I)


def norm_short_answer(v: str) -> str:
    """Dấu thập phân kiểu Việt: "3.67" → "3,67" (giữ "1.500" vì có thể là dấu nghìn)."""
    v = v.strip()
    return v.replace('.', ',') if re.fullmatch(r'-?\d+\.\d{1,2}', v) else v


def strip_key_lines(text: str, part: int) -> str:
    """Bỏ dòng chỉ ghi đáp án ("Chọn B.", "Đáp án: A.", "Trả lời: 12") khỏi lời giải."""
    if part == 3:
        lines = text.split('\n')
        while lines and (not lines[0].strip() or re.fullmatch(r'\s*[:.]\s*', lines[0])
                         or RE_SA_KEY_LINE.match(lines[0])):
            lines.pop(0)
        text = '\n'.join(lines)
    out = []
    for ln in text.split('\n'):
        t = ln.strip()
        if part in (0, 1):
            if re.fullmatch(r'(?:Chọn|Đáp\s*án)\s*(?:đáp\s*án\s*)?[:.#]?\s*[A-D]\s*[.:]?', t):
                continue
            ln = re.sub(r'[,.]?\s*(?:c|C)họn\s*(?:đáp\s*án\s*)?#?\s*[A-D]\s*\.?\s*$', '', ln)
            ln = re.sub(r'^\s*Chọn\s*(?:đáp\s*án\s*)?#?\s*[A-D]\s*[.:]\s*', '', ln)
        if part == 2 and re.fullmatch(r'Đáp\s*án\s*(?:câu\s*\d+\s*)?:\s*[ĐS ,;.]+', t):
            continue
        out.append(ln)
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# Ghép đề + lời giải + đáp án thành bản ghi
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    exam: Exam
    part: int
    number: int
    parsed: Parsed
    solution_lines: List[Line]
    table_key: Optional[str] = None
    author_level: Optional[str] = None
    eq_failed: int = 0
    source_file: str = ''


def _norm_q(text: str) -> str:
    text = re.sub(r'!\[hình\]\([^)]*\)|\[\[HÌNH:[^\]]*\]\]', '', text)
    text = re.sub(r'\\left|\\right|\\,|\\;|~', '', text)
    return re.sub(r'[\s.,:;]+', '', text).lower()


def same_question(repeat: str, parsed: Parsed) -> bool:
    """Đoạn ``repeat`` (đề chép lại trong lời giải) có phải chính đề ``parsed``."""
    a, b = _norm_q(repeat), _norm_q(parsed.question)
    n = min(150, len(b))
    return n >= 15 and a[:n] == b[:n]


def drop_repeated_question(sol: List[Line], parsed: Parsed) -> Tuple[List[Line], str]:
    """Bỏ các dòng đầu lời giải chép lại đề (và phương án/mệnh đề ngay sau đó)."""
    # đề đã dựng bảng Markdown; dòng gốc thì chưa: bỏ ký hiệu bảng trước khi so độ dài
    need = len(_norm_q(re.sub(r'-{3,}|\|', '', parsed.question)))
    k, acc = 0, ''
    while k < len(sol) and len(_norm_q(acc)) < need:
        acc += sol[k].text
        k += 1
    if len(_norm_q(acc)) - need > 25:
        return sol, ''     # câu đầu lời giải nhắc lại đề rồi viết tiếp: giữ nguyên
    while k < len(sol) and (not sol[k].text.strip() or RE_MARK_START.match(sol[k].text)):
        k += 1
    return sol[k:], render(sol[:k])


def solution_of_inline(block: Block, part: int
                       ) -> Tuple[Parsed, List[Line], Optional[str], Optional[str]]:
    """(đề, lời giải, mức độ tác giả ghi, đoạn đề chép lại trong lời giải nếu có)."""
    q_lines, sol = split_at_header(block.lines)
    if sol is None and part in (0, 1):
        # Không có tiêu đề: phần sau khi đủ 4 phương án là lời giải ("Chọn A ...").
        for k in range(1, len(q_lines) + 1):
            if split_options(render(q_lines[:k])) and k < len(q_lines):
                nxt = q_lines[k].text.strip()
                if nxt and not RE_MARK_START.match(nxt):
                    q_lines, sol = q_lines[:k], q_lines[k:]
                    break
    parsed = parse_question(q_lines, part)
    sol = sol or []
    repeat = None
    # Đề chép lại trong lời giải rồi mới đến "Lời giải" lần hai (đề minh họa 2024).
    again_q, again_sol = split_at_header(sol)
    if again_sol is not None and (not render(again_q).strip() or split_options(render(again_q))
                                  or split_statements(render(again_q))):
        sol = again_sol
        repeat = render(again_q) if render(again_q).strip() else None
    elif sol and same_question(render(sol), parsed):
        # Đề chép lại mà không có "Lời giải" lần hai: bỏ phần đề + phương án chép lại.
        sol, repeat = drop_repeated_question(sol, parsed)
    author = None
    if sol:
        m = RE_AUTHOR_LEVEL.match(sol[0].text)
        if m:
            author = m.group(1)
            rest = sol[0].text[m.end():]
            sol = ([Line(rest, None, [])] if rest.strip() else []) + sol[1:]
    return parsed, sol, author, repeat


def candidates_inline(exam: Exam, lines: List[Line], source_file: str) -> List[Candidate]:
    """Câu kiểu inline. Lời giải được gắn lại theo đề chép lại trong lời giải.

    Có file bị lệch: khối "Câu N" chứa đề câu N nhưng lời giải (kèm đề chép lại) của
    câu N−1. Lời giải có đề chép lại được gắn vào đúng câu đó; lời giải không có đề
    chép lại chỉ dùng khi câu chưa có lời giải nào được xác định như vậy.
    """
    blocks, loose = split_blocks(lines)
    tables = answer_tables(loose)
    entries = [solution_of_inline(b, b.part) for b in blocks]
    chosen: Dict[int, Tuple[List[Line], Optional[str], bool, int]] = {}
    for i, (parsed, sol, author, repeat) in enumerate(entries):
        target, identified = i, False
        if repeat is not None:
            if same_question(repeat, parsed):
                identified = True
            else:
                same_part = [k for k, b in enumerate(blocks) if b.part == blocks[i].part]
                hits = [k for k in same_part if same_question(repeat, entries[k][0])]
                if len(hits) == 1:
                    target, identified = hits[0], True
        prev = chosen.get(target)
        if prev is None or (identified and not prev[2]):
            chosen[target] = (sol, author, identified, i)
    out = []
    for i, b in enumerate(blocks):
        parsed = entries[i][0]
        sol, author, identified, origin = chosen.get(i, ([], None, False, i))
        if origin != i:
            parsed.problems.append('solution_realigned')
        out.append(Candidate(exam, b.part, b.number, parsed, sol,
                             table_key=tables.get((b.part, b.number)),
                             author_level=author,
                             eq_failed=sum(ln.eq_failed for ln in b.lines),
                             source_file=source_file))
    return out


def candidates_keyed(exam: Exam, q_lines: List[Line], s_lines: List[Line],
                     source_file: str) -> List[Candidate]:
    s_blocks, loose = split_blocks(s_lines)
    tables = answer_tables(loose)
    sol_blocks: Dict[Tuple[int, int], List[Line]] = {}
    for b in s_blocks:
        sol_blocks.setdefault((b.part, b.number), b.lines)
    out = []
    for b in split_blocks(q_lines)[0]:
        parsed = parse_question(b.lines, b.part)
        sol = sol_blocks.get((b.part, b.number), [])
        # Lời giải chép lại đề rồi mới có tiêu đề "Lời giải": bỏ phần đề chép lại.
        # Tiêu đề nằm giữa lời giải (vd "Giải" trước một ý) thì giữ nguyên.
        pre, after = split_at_header(sol)
        if after is not None and (not render(pre).strip() or repeats_question(render(pre), parsed)):
            sol = after
        elif sol and same_question(render(sol), parsed):
            sol = drop_repeated_question(sol, parsed)[0]
        out.append(Candidate(exam, b.part, b.number, parsed, sol,
                             table_key=tables.get((b.part, b.number)),
                             eq_failed=sum(ln.eq_failed for ln in b.lines + sol),
                             source_file=source_file))
    return out


# Dòng quảng cáo của trang chia sẻ tài liệu chèn vào cuối lời giải.
RE_AD_LINE = re.compile(
    r'tailieuchuan|vnteach|tải\s*(?:bản\s*word|tài\s*liệu)\s*trên\s*website|bản\s*word\s*phát\s*hành'
    r'|chia\s*sẻ\s*bởi\s*website|https?://\S+|www\.\S+\.\w+', re.I)
# Tên trang chia sẻ gõ trong ô công thức ngay cuối câu dẫn (đề 33 câu 23): chỉ bỏ ô đó.
RE_AD_INLINE = re.compile(r'[ \t]*\$\s*(?:\\(?:text|mathrm)\{)?\s*tailieudoc\.vn\s*\}?\s*\$', re.I)
# Chữ TCVN3 (font .VnTime) lọt vào \text{} của công thức: ký tự của bảng TCVN3
# không phải chữ Việt Unicode, đứng sát chữ Latinh (vd "nghiÖm", "ch½n").
_TCVN3_ODD = ''.join(sorted(set('¸µ¶·¹¨¾»¼½Æ©ÊÇÈÉË®ÐÌÎÏÑªÕÒÓÔÖÝ×ØÜÞãßáâä«èåæçé¬íêëìîóïñòô­øõö÷ùýúûüþ¡¢§£¤¥¦')
                            - set('àáâãèéêìíòóôõùúýÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝ×÷')))
RE_TCVN3_WORD = re.compile('[A-Za-z][%s]|[%s][A-Za-z]' % (re.escape(_TCVN3_ODD), re.escape(_TCVN3_ODD)))
# Chữ ký người soạn dính cuối dòng lời giải (bộ đề phát triển minh họa 2024, đề 18–26).
RE_SIGNATURE = re.compile(r'[ \t]*\bVân\s+Phan[ \t]*$', re.M)
# Macro định dạng của file gốc biến "c." cuối câu thành nhãn phương án: "lập đượ<TAB>C." (đề 18).
RE_BROKEN_C = re.compile(r'\bđượ\s+C\.')
# Dấu chấm câu gõ trong MathType ra "\cdot" cuối công thức: "$\sqrt{6}\cdot$" -> "$\sqrt{6}$."
RE_TRAILING_CDOT = re.compile(r'\s*\\cdot\s*\$(?=[ \t]*(?:\n|$))')
# Hai dấu chấm cuối dòng do gõ thừa ("x=2..", đề 23); chừa "\right.." của LaTeX.
RE_DOUBLE_DOT = re.compile(r'(?<!\\right)(?<!\\left)(?<=[0-9A-Za-zÀ-ỹ)}])\.\.(?=[ \t]*(?:\n|$))')
# Chuỗi "\n" viết thành chữ trong file gốc (đề 30 câu 25), khác các lệnh LaTeX \ne, \neq, \nabla...
RE_LITERAL_NL = re.compile(r'(?<!\\)\\n(?=[A-ZĐÀ-Ỹ$\[(]|[à-ỹ])')


def tidy_text(text: str) -> str:
    """Bỏ dòng quảng cáo, chữ ký; đổi chữ TCVN3 trong \\text{} sang Unicode."""
    text = RE_AD_INLINE.sub('', text)
    text = '\n'.join(ln for ln in text.split('\n') if not RE_AD_LINE.search(ln))
    text = RE_BROKEN_C.sub('được.', RE_SIGNATURE.sub('', text))
    text = RE_DOUBLE_DOT.sub('.', RE_TRAILING_CDOT.sub('$.', text))
    # dòng chỉ có dấu chấm (cuối mỗi lời giải của đề 27)
    text = re.sub(r'\n[ \t]*\.[ \t]*(?=\n|$)', '', text)
    if RE_LITERAL_NL.search(text):
        # ô bảng dán nguyên dạng chữ: "[* … \n … |"
        text = RE_LITERAL_NL.sub('\n', text)
        text = re.sub(r'^\[\*\s*', '', text)
        lines = text.split('\n')
        k = max((i for i, ln in enumerate(lines) if RE_IMG_MD1.sub('', RE_IMAGE.sub('', ln)).strip()),
                default=-1)
        if k >= 0 and not lines[k].lstrip().startswith('|'):
            lines[k] = re.sub(r'\s*\|\s*$', '', lines[k])
        text = '\n'.join(lines)

    def fix(m: re.Match) -> str:
        body = m.group(1)
        return '\\text{%s}' % (tcvn3_to_unicode(body) if RE_TCVN3_WORD.search(body) else body)

    return re.sub(r'\\text\{([^{}]*)\}', fix, text).strip()


# Mẫu tích phân MathType có ô cận để trống (chỉ chứa "\,") ra "\int\limits^{\,}"; cận thật
# gõ tiếp bằng chỉ số nên "\int\limits^{\,}_{0}^{1}" có hai chỉ số trên (KaTeX báo lỗi).
RE_EMPTY_LIMITS = re.compile(r'\\limits\^\{\\,\}(?=\s*_)')
RE_EMPTY_SUP = re.compile(r'(?:\\limits)?\^\{\\,\}')
# Dấu "\" của phép trừ tập hợp gõ ở chế độ chữ: "\mathbb{R}\text{\backslash}" (KaTeX không dựng được).
RE_TEXT_BACKSLASH = re.compile(r'\\text\{\s*\\backslash\s*\}')


def tidy_latex(text: str) -> str:
    """Bỏ chỉ số trên rỗng ^{\\,}, sửa \\text{\\backslash}; chạy sau đính chính để cột old khớp chữ gốc."""
    text = RE_TEXT_BACKSLASH.sub(r'\\backslash ', text)
    return RE_EMPTY_SUP.sub(' ', RE_EMPTY_LIMITS.sub(r'\\limits', text))


# Bảng tiêu đề đề thi (sở GD, kỳ thi) của đề kế tiếp lọt vào cuối lời giải khi ghép file (đề 24).
RE_EXAM_HEADER = re.compile(r'SỞ\s*(?:GD|GIÁO\s*DỤC)|ĐỀ\s*(?:KSCL|KHẢO\s*SÁT|THI\s*THỬ)|THI\s*THỬ\s*LẦN'
                            r'|Môn\s*thi\s*:', re.I)


def strip_header_tables(text: str) -> str:
    """Bỏ các bảng Markdown chứa tiêu đề đề thi."""
    lines = text.split('\n')
    out: List[str] = []
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith('|'):
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].lstrip().startswith('|'):
            j += 1
        if not RE_EXAM_HEADER.search('\n'.join(lines[i:j])):
            out.extend(lines[i:j])
        i = j
    return '\n'.join(out)


def has_real_solution(text: str) -> bool:
    """Lời giải có nội dung: không rỗng, không chỉ là hình, "Chọn A" hay một cái tên."""
    t = RE_IMG_MD1.sub('', RE_IMAGE.sub('', text))
    t = re.sub(r'(?i)\bchọn\W*[A-D]\b', '', t)
    core = re.sub(r'[\s.:;,#*\-–]', '', t)
    if not core:
        return False
    return len(core) >= 15 or '$' in t or bool(re.search(r'\d', t))


def drop_option_lines(text: str, choices: List[str]) -> str:
    """Bỏ các dòng lời giải chỉ chép lại đúng 4 phương án của đề."""
    if len(choices) != 4:
        return text
    want = [_norm_q(c[3:]) for c in choices]
    lines = text.split('\n')
    out, i = [], 0
    while i < len(lines):
        hit = False
        for span in (1, 2, 3, 4):
            chunk = '\n'.join(lines[i:i + span])
            got = split_options(chunk) if RE_MARK_START.match(lines[i]) else None
            if got and not got[0].strip() and [_norm_q(x) for x in got[1]] == want:
                i += span
                hit = True
                break
        if not hit:
            out.append(lines[i])
            i += 1
    return '\n'.join(out)


# Lời giải dạng "Phương pháp: … Cách giải: …": khối "Phương pháp:" thứ hai sau "Cách giải:"
# là lời giải của câu khác bị đặt nhầm chỗ trong file gốc (vd đề 15: lời giải câu 50 nằm
# cuối lời giải câu 49, trước cả đề câu 50).
RE_METHOD_HEAD = re.compile(r'^\s*Phương\s*pháp(?:\s*giải)?\s*:')
RE_WORKING_HEAD = re.compile(r'^\s*Cách\s*giải\s*:')


def cut_foreign_tail(lines: List[Line]) -> Tuple[List[Line], bool]:
    """Bỏ từ khối "Phương pháp:" thứ hai (đứng sau một "Cách giải:") trở đi."""
    seen_working = False
    for i, ln in enumerate(lines):
        if ln.in_table:
            continue
        if RE_WORKING_HEAD.match(ln.text):
            seen_working = True
        elif seen_working and RE_METHOD_HEAD.match(ln.text):
            return lines[:i], True
    return lines, False


# ---------------------------------------------------------------------------
# Đính chính: sửa lỗi gõ, chữ rác của file gốc ngay khi build (file .docx giữ nguyên)
# ---------------------------------------------------------------------------

ERRATA_NEWLINE = '⏎'   # ký hiệu xuống dòng trong cột old/new


def load_errata(path: Optional[Path]) -> Dict[str, List[Dict[str, str]]]:
    """TSV cột id, field, old, new, note; field là question, solution, choice:A…D hoặc choice:a…d.

    ``old`` phải xuất hiện đúng một lần trong trường đó (so trên chữ đã chuẩn hoá, công thức
    dạng LaTeX, hình dạng [[HÌNH:…]]).
    """
    errata: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    if not path or not path.exists():
        return errata
    with open(path, encoding='utf-8', newline='') as fh:
        for row in csv.DictReader(fh, delimiter='\t', quoting=csv.QUOTE_NONE):
            if (row.get('id') or '').strip():
                errata[row['id'].strip()].append(
                    {k: (row.get(k) or '').replace(ERRATA_NEWLINE, '\n') for k in ('field', 'old', 'new', 'note')})
    return errata


def apply_errata(item_id: str, texts: Dict[str, str], rows: List[Dict[str, str]],
                 warnings: List[str]) -> List[Dict[str, str]]:
    done = []
    for r in rows:
        field = r['field']
        if field not in texts:
            warnings.append(f"{item_id}: đính chính trỏ tới trường không có: {field}")
            continue
        n = texts[field].count(r['old']) if r['old'] else 0
        if n != 1:
            warnings.append(f"{item_id}: chuỗi cần sửa xuất hiện {n} lần trong {field}: {r['old'][:50]!r}")
            continue
        texts[field] = texts[field].replace(r['old'], r['new'])
        done.append(dict(r))
    return done


def finalize(c: Candidate, errata: Optional[Dict[str, List[Dict[str, str]]]] = None,
             errata_warnings: Optional[List[str]] = None) -> Tuple[Optional[Dict], str]:
    """Bản ghi, hoặc (None, lý do bỏ)."""
    part = c.part
    qtype = PART_TYPES[part]
    sol_lines, tail_cut = cut_foreign_tail(c.solution_lines)
    sol_text = render(sol_lines)
    flags = list(c.parsed.problems)
    if tail_cut:
        flags.append('solution_tail_cut')

    # --- đáp án: bảng > dấu trong đề > lời giải; lệch nhau thì gắn cờ
    text_key: Optional[str] = None
    tf_warn: List[str] = []
    if qtype == 'mcq':
        text_key = mcq_from_solution(sol_text)
    elif qtype == 'true_false':
        text_key, tf_warn = tf_from_solution(sol_lines)
    else:
        text_key = sa_from_solution(sol_text)
    sources = []
    if c.table_key:
        sources.append(('table', c.table_key))
    if c.parsed.key:
        sources.append((c.parsed.key_how, c.parsed.key))
    if text_key and not text_key.startswith('conflict:'):
        sources.append(('solution', text_key))
    if qtype == 'short_answer':
        sources = [(h, norm_short_answer(v)) for h, v in sources]
    answer, how = (sources[0][1], sources[0][0]) if sources else (None, None)
    if text_key and text_key.startswith('conflict:'):
        flags.append('answer_conflict_in_solution')
    vals = {_same_answer(v, qtype) for _, v in sources}
    if len(vals) > 1:
        flags.append('answer_conflict_' + '_'.join(f'{h}={v}' for h, v in sources))
    if qtype == 'true_false':
        flags += [w for w in tf_warn if not w.startswith('tf_missing') or not answer]
    if answer is None:
        flags.append('no_answer')

    question = tidy_text(c.parsed.question)
    choices = [tidy_text(x) for x in c.parsed.choices]
    solution = tidy_text(clean(strip_header_tables(strip_key_lines(drop_option_lines(sol_text, choices), part))))
    pid = {0: '', 1: 'p1-', 2: 'p2-', 3: 'p3-'}[part]
    item_id = f'{c.exam.key}-{pid}{c.number:02d}'
    corrections: List[Dict[str, str]] = []
    if errata and item_id in errata:
        texts = {'question': question, 'solution': solution}
        texts.update({'choice:' + ch[:1]: ch for ch in choices})
        corrections = apply_errata(item_id, texts, errata[item_id],
                                   errata_warnings if errata_warnings is not None else [])
        question, solution = texts['question'], texts['solution']
        choices = [texts['choice:' + ch[:1]] for ch in choices]
        if corrections:
            flags.append('text_corrected')
    question, solution = tidy_latex(question), tidy_latex(solution)
    choices = [tidy_latex(x) for x in choices]
    if not has_real_solution(solution):
        return None, 'solution_only_image' if RE_IMAGE.search(solution) else 'no_solution'

    if re.match(r'\s*Chưa\s+có\s+câu\s+hỏi', question, re.I):
        return None, 'placeholder'
    if c.eq_failed:
        flags.append('formula_missing')
    if any(OMML_MARK in s or EQ_MISSING in s for s in (question, *choices, solution)):
        flags.append('omml_unconverted' if any(OMML_MARK in s for s in (question, *choices, solution))
                     else 'formula_missing')
    if any(RE_LOST_TEXT.search(s) for s in (question, *choices, solution)):
        flags.append('formula_text_lost')
    if any(s.count('$') % 2 for s in (question, *choices, solution)):
        flags.append('math_delimiter_broken')
    if qtype != 'short_answer' and any(not re.sub(r'^[A-Da-d][.)]\s*', '', x).strip() for x in choices):
        flags.append('empty_choice')
    if not question.strip():
        flags.append('no_question')

    images = []
    for s in (question, *choices, solution):
        images += RE_IMAGE.findall(s)
    item = {
        'id': item_id,
        'type': qtype,
        'question': question,
        'choices': choices,
        'answer': answer,
        'solution': solution,
        'topic': None,
        'subtopic': None,
        'difficulty': None,
        'author_difficulty': DIFFICULTY_NAMES.get(c.author_level) if c.author_level else None,
        'section': PART_NAMES[part],
        'source': {'exam': c.exam.title, 'file': c.source_file,
                   'part': part or None, 'question_number': c.number},
        'answer_source': how,
        'images': images,
        'flags': sorted(set(flags), key=flags.index),
        'review_note': None,
        'corrections': corrections,
    }
    return item, ''


RE_IMG_MD1 = re.compile(r'!\[hình\]\([^)]*\)')
RE_WORDISH = re.compile(r'[0-9A-Za-zÀ-ỹ$]')


def inline_images(text: str) -> int:
    """Số hình nằm lọt giữa câu (có chữ cả hai bên trên cùng dòng).

    Công thức dán dạng ảnh (không có dữ liệu MathType) trông như vậy; hình minh hoạ
    thì thường đứng riêng dòng hoặc ở đầu/cuối đoạn.
    """
    n = 0
    for line in text.split('\n'):
        for m in RE_IMG_MD1.finditer(line):
            before = RE_IMG_MD1.sub('', line[:m.start()])
            after = RE_IMG_MD1.sub('', line[m.end():])
            if RE_WORDISH.search(before) and RE_WORDISH.search(after):
                n += 1
    return n


# "Trong hình chữ nhật ABCD", "trong hình tròn" là tên hình học, không phải lời dẫn tới hình vẽ.
RE_SHAPE_NAME = re.compile(r'\s*(?:chữ\s*nhật|vuông|thang|thoi|bình\s*hành|tròn|chóp|lăng\s*trụ|nón|trụ|cầu'
                           r'|hộp|lập\s*phương|tứ\s*diện|đa\s*diện|phẳng|quạt)', re.I)


def refers_to_figure(text: str) -> bool:
    return any(not RE_SHAPE_NAME.match(text, m.end()) for m in RE_FIGURE_REF.finditer(text))


# Lời giải lập luận trên hình vẽ/đồ thị dạng ảnh: bỏ ảnh là mất bước chính.
RE_GRAPH_CUE = re.compile(r'(?:dựa\s*vào|từ|quan\s*sát|căn\s*cứ\s*vào)\s*(?:hình|đồ\s*thị)|vẽ\s*hình', re.I)
# Lời giải dẫn tới bảng biến thiên/bảng xét dấu dạng ảnh: các mốc và kết luận vẫn có bằng chữ.
RE_TABLE_CUE = re.compile(r'bảng\s*biến\s*thiên|\bBBT\b|bảng\s*xét\s*dấu|\bBXD\b', re.I)


def strip_solution_images(item: Dict) -> None:
    item['solution'] = re.sub(r'\n{3,}', '\n\n', RE_IMAGE_MD.sub('', item['solution'])).strip()
    for flag in ('figure_removed_from_solution',
                 *(('table_removed_from_solution',) if RE_TABLE_CUE.search(item['solution']) else ())):
        if flag not in item['flags']:
            item['flags'].append(flag)


def apply_exam_figure_policy(item: Dict) -> None:
    """Quy tắc hình của ``build_dataset.apply_figure_policy``, thêm hai điểm.

    - Công thức dán dạng ảnh: không được xoá ảnh khỏi lời giải (sẽ mất công thức);
      gắn ``formula_as_image``.
    - Cụm "trong hình chữ nhật…" không tính là lời dẫn tới hình vẽ.
    - Lời giải có ảnh và lập luận "dựa vào/từ đồ thị…": coi như cần hình (``figure_in_solution``).
    - Ảnh bảng biến thiên/bảng xét dấu bị bỏ: vẫn dùng được, gắn ``table_removed_from_solution``.
    """
    stem = item['question'] + '\n' + '\n'.join(item['choices'])
    if inline_images(item['solution']) >= 2 or inline_images(stem) >= 2:
        item['flags'].append('formula_as_image')
        if RE_IMAGE_MD.search(stem) or refers_to_figure(stem):
            item['flags'].append('figure_in_question')
        return
    if RE_IMAGE_MD.search(stem) or refers_to_figure(stem):
        item['flags'].append('figure_in_question')
        return
    solution = item['solution']
    has_image = bool(RE_IMAGE_MD.search(solution))
    if refers_to_figure(solution) or (has_image and RE_GRAPH_CUE.search(solution)):
        item['flags'].append('figure_in_solution')
    elif has_image:
        strip_solution_images(item)


def _same_answer(v: str, qtype: str) -> str:
    if qtype == 'short_answer':
        return v.replace('.', ',').rstrip('0').rstrip(',') if ',' in v or '.' in v else v
    return v


# ---------------------------------------------------------------------------
# Nhãn tay: độ khó, chủ đề, rà soát
# ---------------------------------------------------------------------------

TOPICS: Dict[str, Tuple[str, Dict[str, str]]] = {
    'HS': ('Ứng dụng đạo hàm và khảo sát hàm số', {
        'DB': 'Tính đơn điệu', 'CT': 'Cực trị', 'MM': 'Giá trị lớn nhất, nhỏ nhất',
        'TC': 'Tiệm cận', 'DT': 'Đồ thị và bảng biến thiên', 'TG': 'Tương giao, số nghiệm',
        'TT': 'Tiếp tuyến', 'TU': 'Bài toán tối ưu, thực tế'}),
    'DH': ('Đạo hàm', {'QT': 'Quy tắc tính đạo hàm', 'YN': 'Ý nghĩa của đạo hàm'}),
    'ML': ('Lũy thừa, mũ và logarit', {
        'LT': 'Lũy thừa và logarit', 'HS': 'Hàm số mũ, hàm số logarit',
        'PT': 'Phương trình mũ, logarit', 'BPT': 'Bất phương trình mũ, logarit',
        'TT': 'Bài toán thực tế (lãi suất, tăng trưởng)'}),
    'NH': ('Nguyên hàm', {'NH': 'Nguyên hàm'}),
    'TP': ('Tích phân', {'TP': 'Tính tích phân', 'HA': 'Tích phân hàm ẩn'}),
    'UD': ('Ứng dụng tích phân', {
        'DT': 'Diện tích hình phẳng', 'TT': 'Thể tích', 'TTe': 'Bài toán thực tế'}),
    'SP': ('Số phức', {
        'PT': 'Khái niệm và phép toán', 'PTr': 'Phương trình trên tập số phức',
        'MD': 'Tập hợp điểm, cực trị môđun'}),
    'KD': ('Khối đa diện', {'KN': 'Khái niệm, tính chất khối đa diện', 'TT': 'Thể tích khối đa diện'}),
    'TX': ('Mặt nón, mặt trụ, mặt cầu', {'NON': 'Mặt nón, khối nón', 'TRU': 'Mặt trụ, khối trụ',
                                          'CAU': 'Mặt cầu, khối cầu'}),
    'OX': ('Phương pháp tọa độ trong không gian', {
        'TD': 'Tọa độ điểm, vectơ', 'MP': 'Phương trình mặt phẳng', 'DT': 'Phương trình đường thẳng',
        'MC': 'Phương trình mặt cầu', 'GK': 'Góc, khoảng cách, vị trí tương đối',
        'TTe': 'Bài toán thực tế'}),
    'VT': ('Vectơ trong không gian', {'VT': 'Vectơ trong không gian'}),
    'HK': ('Quan hệ song song, vuông góc trong không gian', {
        'QH': 'Quan hệ song song, vuông góc', 'GOC': 'Góc', 'KC': 'Khoảng cách'}),
    'XS': ('Tổ hợp và xác suất', {
        'TH': 'Quy tắc đếm, hoán vị, chỉnh hợp, tổ hợp', 'CD': 'Xác suất cổ điển',
        'DK': 'Xác suất có điều kiện, công thức Bayes'}),
    'TK': ('Thống kê', {'TT': 'Số đặc trưng đo xu thế trung tâm',
                        'PT': 'Số đặc trưng đo mức độ phân tán'}),
    'DS': ('Dãy số, cấp số cộng, cấp số nhân', {
        'CSC': 'Cấp số cộng', 'CSN': 'Cấp số nhân', 'DS': 'Dãy số'}),
    'LG': ('Lượng giác', {'CT': 'Giá trị lượng giác, công thức', 'PT': 'Phương trình lượng giác',
                          'HS': 'Hàm số lượng giác'}),
    'GH': ('Giới hạn, hàm số liên tục', {'GH': 'Giới hạn, hàm số liên tục'}),
    'OXY': ('Phương pháp tọa độ trong mặt phẳng', {'OXY': 'Đường thẳng, đường tròn, conic'}),
    'BPT': ('Bất phương trình bậc nhất hai ẩn', {'BPT': 'Bài toán tối ưu tuyến tính'}),
}

BLOCKING_FLAGS = ('no_answer', 'no_choices', 'no_statements', 'no_question', 'formula_missing',
                  'duplicate', 'duplicate_choices', 'figure_in_question', 'figure_in_solution',
                  'omml_unconverted', 'multiple_stars', 'formula_as_image',
                  'math_delimiter_broken', 'empty_choice',
                  # từ rà soát tay (dataset/labels/exams.tsv)
                  'key_wrong', 'key_suspect', 'source_corrupted', 'segmentation_error',
                  'figure_implicit', 'solution_wrong', 'solution_trivial',
                  # lỗi gõ trong lời giải (sai số/ký hiệu trung gian), lập luận và kết quả vẫn đúng
                  'solution_typo')


def topic_names(code: str) -> Tuple[str, str]:
    top, _, sub = code.partition('.')
    name, subs = TOPICS[top]
    sub = sub or next(iter(subs))
    return name, subs[sub]


# Cụm trong ngoặc trỏ tới hình, còn lại trong đề sau khi bỏ hình: "(tham khảo hình vẽ)",
# "( xem hình vẽ bên)", "(minh họa như hình bên dưới)", "(như hình vẽ)".
RE_FIGURE_ASIDE = re.compile(
    r'[ \t]*\(\s*(?:(?:tham\s*khảo|xem|minh\s*h(?:ọa|oạ))\s*)?(?:như\s*)?hình(?:\s*vẽ)?'
    r'(?:\s*minh\s*h(?:ọa|oạ))?(?:\s*bên)?(?:\s*dưới)?\s*\)', re.I)


def apply_labels(items: List[Dict], path: Path) -> List[str]:
    """Gắn độ khó, chủ đề và cờ rà soát theo ``id`` (cột: id, level, topic, flag, answer, note).

    ``answer`` chỉ điền khi đáp án không đọc được tự động hoặc hai nguồn lệch nhau
    mà lời giải cho biết rõ đáp án; khi đó các cờ lệch/thiếu đáp án được gỡ.
    ``flag`` = ``figure_optional``: hình chỉ minh hoạ, cả đề lẫn lời giải đọc được bằng chữ;
    ảnh được bỏ khỏi đề và lời giải (vẫn còn trong ``images``), cùng các cụm như
    "(tham khảo hình vẽ)" trong đề. Lời giải cần hình để hiểu
    thì ghi thêm ``figure_in_solution`` sau ``figure_optional``.
    """
    by_id = {it['id']: it for it in items}
    warnings: List[str] = []
    for row in _read_tsv(path):
        it = by_id.get(row['id'])
        if it is None:
            warnings.append(f"{row['id']}: không có trong dataset")
            continue
        if row.get('level'):
            it['difficulty'] = DIFFICULTY_NAMES[row['level']]
        if row.get('topic'):
            try:
                it['topic'], it['subtopic'] = topic_names(row['topic'])
            except KeyError:
                warnings.append(f"{row['id']}: mã chủ đề lạ {row['topic']}")
        if row.get('answer'):
            it['answer'] = row['answer']
            it['answer_source'] = 'manual'
            it['flags'] = [f for f in it['flags']
                           if not f.startswith(('answer_conflict', 'tf_conflict', 'tf_missing'))
                           and f != 'no_answer']
        for flag in filter(None, (row.get('flag') or '').split(',')):
            if flag == 'keep':
                # giữ câu này làm bản chính dù trùng một câu xuất hiện trước
                it['flags'] = [f for f in it['flags'] if f != 'duplicate']
                it['duplicate_of'] = None
                continue
            if flag == 'figure_optional':
                it['flags'] = [f for f in it['flags'] if f not in ('figure_in_question', 'figure_in_solution')]
                if RE_IMAGE_MD.search(it['question']):
                    it['question'] = re.sub(r'\n{3,}', '\n\n', RE_IMAGE_MD.sub('', it['question'])).strip()
                    if 'figure_removed_from_question' not in it['flags']:
                        it['flags'].append('figure_removed_from_question')
                it['question'] = RE_FIGURE_ASIDE.sub('', it['question'])
                if RE_IMAGE_MD.search(it['solution']):
                    strip_solution_images(it)
                for k, c in enumerate(it['choices']):
                    if not RE_IMAGE_MD.search(c):
                        continue
                    rest = RE_IMAGE_MD.sub('', c).strip()
                    if re.sub(r'^[A-Da-d][.)]\s*', '', rest):
                        # hình dàn trang lọt vào cuối phương án (vd đề 26 câu 39)
                        it['choices'][k] = rest
                    else:
                        warnings.append(f"{row['id']}: figure_optional nhưng phương án là hình")
            if flag.startswith('duplicate:'):
                # cùng một bài ở file khác (khác cách viết nên không bắt được tự động)
                it['duplicate_of'] = flag.split(':', 1)[1]
                if it['duplicate_of'] not in by_id:
                    warnings.append(f"{row['id']}: duplicate_of {it['duplicate_of']} không tồn tại")
                flag = 'duplicate'
            if flag not in it['flags']:
                it['flags'].append(flag)
        if row.get('note'):
            it['review_note'] = row['note']
    return warnings


def is_usable(item: Dict) -> bool:
    n_choices = {'mcq': 4, 'true_false': 4, 'short_answer': 0}[item['type']]
    return (len(item['choices']) == n_choices and bool(item['answer'])
            and not any(f in BLOCKING_FLAGS or f.startswith(('answer_conflict', 'tf_conflict'))
                        for f in item['flags']))


def _norm_text(text: str) -> str:
    """Bỏ khác biệt trình bày: hình, $...$, \\mathrm{log} với \\log, ngoặc, dấu câu."""
    text = re.sub(r'!\[hình\]\([^)]*\)', '', text)
    text = re.sub(r'\\(?:mathrm|text|operatorname|mathbf|mathit)(?![a-zA-Z])', '', text)
    text = re.sub(r'\\left|\\right|\\[,;!]|~', '', text)
    return re.sub(r'[\s$\\{}.,;:]', '', text).lower()


def _norm_key(item: Dict) -> str:
    """Khoá so trùng: đề + tập phương án (không phụ thuộc thứ tự phương án).

    Nhiều file "phát triển đề minh họa" dùng lại cùng một câu nhưng xáo phương án.
    """
    choices = sorted(_norm_text(re.sub(r'^[A-Da-d][.)]\s*', '', c)) for c in item['choices'])
    return _norm_text(item['question']) + '|' + '|'.join(choices)


def mark_duplicates(items: List[Dict]) -> None:
    first: Dict[str, str] = {}
    for it in items:
        key = _norm_key(it)
        if key in first:
            it['duplicate_of'] = first[key]
            it['flags'].append('duplicate')
        else:
            first[key] = it['id']
            it['duplicate_of'] = None


# ---------------------------------------------------------------------------
# File nén
# ---------------------------------------------------------------------------


def _extractor() -> Optional[List[str]]:
    for exe in ('UnRAR', 'unrar', r'C:\Program Files\WinRAR\UnRAR.exe', '7z',
                r'C:\Program Files\7-Zip\7z.exe'):
        path = shutil.which(exe) or (exe if os.path.isfile(exe) else None)
        if path:
            return [path, 'x', '-y'] if '7z' in os.path.basename(path).lower() else [path, 'x', '-o+', '-inul']
    return None


def resolve(src: Path, pattern: str, archive: Optional[str], cache: Path) -> Optional[Path]:
    if archive is None:
        p = src / pattern
        return p if p.exists() else None
    target = cache / Path(archive).stem
    if not target.exists():
        cmd = _extractor()
        if cmd is None:
            return None
        target.mkdir(parents=True)
        if os.path.basename(cmd[0]).lower().startswith('7z'):
            subprocess.run(cmd + [str(src / archive), f'-o{target}'], check=True,
                           stdout=subprocess.DEVNULL)
        else:
            subprocess.run(cmd + [str(src / archive), str(target) + os.sep], check=True)
    for f in sorted(target.rglob('*.docx')):
        if fnmatch.fnmatch(unicodedata.normalize('NFC', f.name), unicodedata.normalize('NFC', pattern)):
            return f
    return None


# ---------------------------------------------------------------------------


SOL_IMAGE = 'loigiai/'


def build(src: Path, out: Path, labels: Optional[Path], errata_path: Optional[Path] = None) -> Dict:
    exams, skipped_files = exam_list(src)
    errata = load_errata(errata_path)
    errata_warnings: List[str] = []
    img_dir = out / 'images'
    img_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(tempfile.mkdtemp(prefix='exams_'))
    items: List[Dict] = []
    report: Dict = {'exams': [], 'skipped_files': [dict(file=f, reason=r) for f, r in skipped_files]}
    dropped = Counter()
    try:
        for ex in exams:
            qpath = resolve(src, ex.file, ex.archive, cache)
            if qpath is None:
                report['exams'].append({'exam': ex.key, 'error': f'không tìm thấy {ex.file}'})
                continue
            reader = TableAwareReader(str(qpath))
            lines = read_lines(reader)
            spath = None
            sol_reader = None
            if ex.layout == 'inline':
                cands = candidates_inline(ex, lines, qpath.name)
            else:
                if ex.solution_file:
                    spath = resolve(src, ex.solution_file, ex.archive, cache)
                    q_lines = question_region(lines)[0]
                    sol_reader = TableAwareReader(str(spath))
                    s_lines = read_lines(sol_reader)
                    # Hình của file lời giải: tên riêng để không trùng hình cùng tên của file đề.
                    for ln in s_lines:
                        ln.text = ln.text.replace('[[HÌNH:', '[[HÌNH:' + SOL_IMAGE)
                else:
                    q_lines, s_lines = question_region(lines)
                cands = candidates_keyed(ex, q_lines, s_lines, qpath.name)
            kept = 0
            per_reason = Counter()
            for c in cands:
                item, reason = finalize(c, errata, errata_warnings)
                if item is None:
                    per_reason[reason] += 1
                    dropped[reason] += 1
                    continue
                mapping = {}
                for name in item['images']:
                    if name in mapping:
                        continue
                    if name.startswith(SOL_IMAGE):
                        mapping[name] = export_image(sol_reader, name[len(SOL_IMAGE):],
                                                     img_dir, item['id'])
                    else:
                        mapping[name] = export_image(reader, name, img_dir, item['id'])

                def sub(text: str) -> str:
                    return RE_IMAGE.sub(lambda m: f'![hình](images/{mapping[m.group(1)]})', text)

                item['question'] = sub(item['question'])
                item['choices'] = [sub(x) for x in item['choices']]
                item['solution'] = sub(item['solution'])
                item['images'] = [f'images/{v}' for v in mapping.values()]
                apply_exam_figure_policy(item)
                items.append(item)
                kept += 1
            report['exams'].append({
                'exam': ex.key, 'title': ex.title, 'file': qpath.name,
                'solution_file': spath.name if spath else None,
                'questions_found': len(cands), 'kept': kept, 'dropped': dict(per_reason),
            })
    finally:
        shutil.rmtree(cache, ignore_errors=True)
    mark_duplicates(items)
    report['label_warnings'] = apply_labels(items, labels) if labels and labels.exists() else []
    known = {it['id'] for it in items}
    errata_warnings += [f'{i}: đính chính cho câu không có trong dataset' for i in errata if i not in known]
    report['errata_warnings'] = errata_warnings
    report['corrected_items'] = sum(1 for it in items if it.get('corrections'))
    flags = Counter()
    for it in items:
        flags.update(f.split('_table=')[0] if f.startswith('answer_conflict') else f for f in it['flags'])
        it['usable'] = is_usable(it)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'questions.jsonl', 'w', encoding='utf-8') as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + '\n')
    usable = [it for it in items if it['usable']]
    report.update({
        'total': len(items),
        'dropped': dict(dropped),
        'usable': len(usable),
        'by_type': dict(Counter(it['type'] for it in items)),
        'usable_by_type': dict(Counter(it['type'] for it in usable)),
        'answer_source': dict(Counter(it['answer_source'] for it in items)),
        'difficulty': dict(Counter(it['difficulty'] for it in usable)),
        'flags': dict(flags),
    })
    with open(out / 'build_report.json', 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', required=True, help='thư mục chứa đề (.docx, .rar)')
    ap.add_argument('--out', default='dataset/export/exams')
    ap.add_argument('--labels', default='dataset/labels/exams.tsv',
                    help='TSV nhãn tay: id, level, topic, flag, answer, note')
    ap.add_argument('--errata', default='dataset/labels/exams_errata.tsv',
                    help='TSV đính chính chữ: id, field, old, new, note (⏎ là xuống dòng)')
    args = ap.parse_args()
    report = build(Path(args.src), Path(args.out), Path(args.labels), Path(args.errata))
    summary = {k: v for k, v in report.items() if k not in ('exams', 'skipped_files')}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

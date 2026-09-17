"""Tách câu hỏi trắc nghiệm từ các file .docx thành dataset JSONL.

    python dataset/tools/build_dataset.py --src "dataset/<thư mục docx>" --out dataset/export

Mỗi câu hỏi ra một dòng JSON:

    {"id": "int_0001", "question": "...", "choices": ["A. ...", ...],
     "answer": "B", "solution": "...", "topic": "Nguyên hàm",
     "subtopic": "Nguyên hàm từng phần", "difficulty": "Vận dụng", ...}

Độ khó và các lỗi phát hiện khi rà soát bằng tay lấy từ ``dataset/labels``.

Công thức MathType được chuyển sang LaTeX đặt trong ``$...$``. Hình vẽ được
chép ra ``<out>/images/`` và thay bằng ``![hình](images/<tên>)`` trong chữ.

Cấu trúc tài liệu nhận dạng được:
    Câu N. <đề>            (hoặc số câu do Word tự đánh)
    A. ...  B. ...  C. ...  D. ...   (một hoặc nhiều dòng, có thể nằm cùng dòng đề)
    Hướng dẫn giải / Lời giải
    Chọn X. <lời giải>
Đề không có lời giải lấy đáp án từ chữ cái phương án tô đỏ.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import posixpath
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx_text import EQ_MISSING, DocxReader, Para  # noqa: E402

# ---------------------------------------------------------------------------
# Chủ đề theo file (số thứ tự đứng đầu tên file)
# ---------------------------------------------------------------------------

FILE_TOPICS: Dict[int, Tuple[str, str]] = {
    3: ('Nguyên hàm', 'Định nghĩa, tính chất và nguyên hàm cơ bản'),
    4: ('Nguyên hàm', 'Nguyên hàm đổi biến'),
    5: ('Nguyên hàm', 'Nguyên hàm từng phần'),
    6: ('Tích phân', 'Định nghĩa, tính chất tích phân'),
    7: ('Tích phân', 'Tích phân đổi biến số'),
    8: ('Tích phân', 'Tích phân từng phần'),
    9: ('Tích phân', 'GTLN, GTNN và bất đẳng thức tích phân'),
    10: ('Tích phân', 'Tích phân hàm ẩn'),
    11: ('Tích phân', 'Tích phân hàm ẩn'),
    12: ('Tích phân', 'Tích phân hàm ẩn'),
    13: ('Ứng dụng tích phân', 'Diện tích hình phẳng'),
    14: ('Ứng dụng tích phân', 'Diện tích hình phẳng có đồ thị'),
    15: ('Ứng dụng tích phân', 'Thể tích vật thể'),
    16: ('Ứng dụng tích phân', 'Bài toán thực tế về thể tích'),
    17: ('Ứng dụng tích phân', 'Ứng dụng thực tế và liên môn'),
    18: ('Nguyên hàm, tích phân và ứng dụng', 'Đề kiểm tra'),
}

RE_QUESTION = re.compile(r'^\s*Câu\s*(\d+)\s*[.:]\s*', re.I)
RE_SOLUTION_HEAD = re.compile(
    r'^\s*(Hướng\s+dẫn\s+giải|Lời\s+giải|Giải)\s*[:.]?\s*', re.I)
RE_CHOOSE = re.compile(r'Chọn\s*(?:đáp\s*án\s*)?([A-D])\b\s*[.:]?\s*')
RE_MATH = re.compile(r'\$[^$]*\$')
RE_IMAGE = re.compile(r'\[\[HÌNH:([^\]]+)\]\]')
# Nhãn phương án: đứng đầu, sau khoảng trắng, sau công thức/hình đã che,
# hoặc sau dấu chấm/ngoặc đóng ("...$.A. 3").
RE_OPTION_MARK = re.compile(r'(?:(?<=[\s\x00\x01.\]])|^)([A-D])\s*[.)]\s*')
RE_LEADING_IMAGES = re.compile(r'^(?:\s*\[\[HÌNH:[^\]]+\]\])+\s*')
# Tiêu đề của đề kế tiếp trong file đề kiểm tra, bị dính vào câu cuối đề trước.
RE_EXAM_HEADER = re.compile(r'^\s*ĐỀ\s+KIỂM\s+TRA\s+\d+.*$', re.M)
OMML_MARK = '[[OMML]]'


# ---------------------------------------------------------------------------
# Tiện ích chữ
# ---------------------------------------------------------------------------

def _mask_math(text: str) -> Tuple[str, List[str]]:
    """Thay các đoạn $...$ bằng ký hiệu giữ chỗ cùng độ dài để regex không chạm vào."""
    spans: List[str] = []

    def repl(m: re.Match) -> str:
        spans.append(m.group(0))
        return '\x00' * len(m.group(0))

    masked = RE_MATH.sub(repl, text)
    masked = RE_IMAGE.sub(lambda m: '\x01' * len(m.group(0)), masked)
    return masked, spans


def clean(text: str) -> str:
    # Word l\u01b0u l\u1eabn d\u1ea5u t\u1ed5 h\u1ee3p ("a" + d\u1ea5u s\u1eafc) v\u00e0 d\u1ea5u d\u1ef1ng s\u1eb5n; \u0111\u01b0a v\u1ec1 NFC \u0111\u1ec3
    # regex ti\u1ebfng Vi\u1ec7t (vd. "h\u00ecnh v\u1ebd") kh\u1edbp \u0111\u01b0\u1ee3c.
    text = unicodedata.normalize('NFC', text)
    text = text.replace('\t', ' ').replace('\u00a0', ' ')
    text = re.sub(r'[ ]{2,}', ' ', text)
    text = re.sub(r' *\n *', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    # "$a$$b$" do hai công thức liền nhau: gộp lại cho gọn.
    # Chèn khoảng trắng để "\Rightarrow$$f" không thành "\Rightarrowf".
    text = re.sub(r'\$\$(?=\S)', ' ', text)
    return text.strip()


def _is_heading(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 90 or '$' in t or '[[' in t:
        return False
    if RE_QUESTION.match(t) or RE_OPTION_MARK.match(t):
        return False
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 4:
        return False
    return sum(c.isupper() for c in letters) / len(letters) > 0.8


def split_options(text: str) -> Optional[Tuple[str, List[str]]]:
    """Tách "... A. x B. y C. z D. w" thành (phần trước A, [x, y, z, w]).

    Các nhãn phải xuất hiện đúng thứ tự A→B→C→D và nằm ngoài công thức.
    """
    masked, _ = _mask_math(text)
    positions = []
    start = 0
    for letter in 'ABCD':
        found = None
        for m in RE_OPTION_MARK.finditer(masked, start):
            if m.group(1) == letter:
                found = m
                break
        if not found:
            # Lỗi đánh máy "A. B. C. C.": nhận nhãn thứ tư bất kỳ sau C.
            if letter == 'D' and len(positions) == 3:
                later = list(RE_OPTION_MARK.finditer(masked, start))
                if len(later) == 1:
                    found = later[0]
            if not found:
                return None
        positions.append(found)
        start = found.end()
    head = text[:positions[0].start()]
    opts = []
    for i, m in enumerate(positions):
        end = positions[i + 1].start() if i + 1 < len(positions) else len(text)
        opt = clean(text[m.end():end])
        if opt.endswith('.') and not opt.endswith('..'):
            opt = opt[:-1].rstrip()
        opts.append(opt)
    return head, opts


# ---------------------------------------------------------------------------
# Tách câu hỏi
# ---------------------------------------------------------------------------

@dataclass
class RawQuestion:
    number: int
    section: str
    stem: List[str] = field(default_factory=list)
    options: List[str] = field(default_factory=list)
    solution: List[str] = field(default_factory=list)
    phase: str = 'stem'
    red_letters: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    eq_failed: int = 0


def _has_all_options(text: str) -> bool:
    return split_options(text) is not None


def segment(paras: List[Para]) -> List[RawQuestion]:
    questions: List[RawQuestion] = []
    cur: Optional[RawQuestion] = None
    section = ''
    pending_prefix = ''  # hình neo ngay trước "Câu N."

    for p in paras:
        text = p.text
        stripped = text.strip()
        if not stripped:
            continue
        # Hình neo ở đầu đoạn rồi mới đến "Câu N."
        lead = re.match(r'^((?:\s*\[\[HÌNH:[^\]]+\]\])+)\s*(Câu\s*\d+.*)$', stripped, re.S)
        if lead:
            pending_prefix = lead.group(1)
            stripped = lead.group(2)

        m = RE_QUESTION.match(stripped)
        if m:
            cur = RawQuestion(int(m.group(1)), section)
            questions.append(cur)
            rest = stripped[m.end():]
            if pending_prefix:
                rest = rest + '\n' + pending_prefix.strip()
                pending_prefix = ''
            cur.stem.append(rest)
            cur.red_letters += p.red_letters
            cur.eq_failed += p.eq_failed
            continue
        pending_prefix = ''

        if _is_heading(stripped) and not p.in_table:
            section = re.sub(r'\s+', ' ', stripped).strip(' .:')
            cur = None
            continue
        if cur is None:
            continue

        cur.eq_failed += p.eq_failed
        lead_img = RE_LEADING_IMAGES.match(stripped)
        body = stripped[lead_img.end():] if lead_img else stripped
        head = RE_SOLUTION_HEAD.match(body)
        if head and cur.phase != 'solution' and len(body) - head.end() < 200:
            if lead_img:  # hình neo trước tiêu đề thuộc về đề bài
                cur.stem.append(lead_img.group(0).strip())
            cur.phase = 'solution'
            rest = body[head.end():]
            if rest:
                cur.solution.append(rest)
            continue
        if cur.phase != 'solution' and RE_CHOOSE.match(body):
            # "Chọn X" không có tiêu đề "Hướng dẫn giải" phía trước
            if lead_img:
                cur.stem.append(lead_img.group(0).strip())
            cur.phase = 'solution'
            cur.solution.append(body)
            continue

        if cur.phase == 'solution' and head and not body[head.end():].strip():
            continue  # tiêu đề "Hướng dẫn giải" lặp lại
        if not body.strip() and cur.phase == 'options':
            cur.stem.append(stripped)  # đoạn chỉ có hình: hình của đề bài
            continue

        masked_body, _ = _mask_math(body)
        starts_option = bool(RE_OPTION_MARK.match(masked_body))
        if cur.phase == 'stem':
            if starts_option and masked_body.startswith('A'):
                cur.phase = 'options'
                cur.options.append(stripped)
            else:
                cur.stem.append(stripped)
            cur.red_letters += p.red_letters
        elif cur.phase == 'options':
            if _has_all_options('\n'.join(cur.options)) and not starts_option:
                # Đủ A-D mà không có tiêu đề lời giải: phần sau là lời giải.
                cur.phase = 'solution'
                cur.solution.append(stripped)
            else:
                cur.options.append(stripped)
                cur.red_letters += p.red_letters
        else:
            cur.solution.append(stripped)
    return questions


@dataclass
class Item:
    data: Dict
    problems: List[str]


def finalize(raw: RawQuestion, topic: str, subtopic: str, source: str) -> Item:
    problems: List[str] = []
    stem_text = '\n'.join(raw.stem)
    opt_text = '\n'.join(raw.options)
    choices: Optional[List[str]] = None
    stem = stem_text
    if opt_text:
        split = split_options(opt_text)
        if split:
            before, choices = split
            if before.strip():
                stem = stem_text + '\n' + before
    else:
        # phương án nằm chung dòng với đề
        split = split_options(stem_text)
        if split:
            stem, choices = split
    if choices is None:
        problems.append('no_choices')
        choices = []

    solution_lines = list(raw.solution)
    answer = None
    answer_from = None
    if solution_lines:
        m = RE_CHOOSE.search(solution_lines[0])
        if m and m.start() < 5:
            answer = m.group(1)
            answer_from = 'chon'
            solution_lines[0] = solution_lines[0][m.end():]
    if answer is None:
        for i, line in enumerate(solution_lines):
            m = RE_CHOOSE.search(line)
            if m:
                answer = m.group(1)
                answer_from = 'chon'
                solution_lines[i] = line[:m.start()] + line[m.end():]
                break
    red = sorted(set(raw.red_letters))
    if answer is None and len(red) == 1:
        answer = red[0]
        answer_from = 'red_mark'
    elif answer and len(red) == 1 and red[0] != answer:
        problems.append(f'answer_conflict_red_{red[0]}')
    if answer is None:
        problems.append('no_answer')

    solution = clean(RE_EXAM_HEADER.sub('', '\n'.join(solution_lines)))
    stem = clean(stem)
    if not solution:
        problems.append('no_solution')
    if raw.eq_failed:
        problems.append('formula_missing')
    if any(OMML_MARK in part for part in (stem, *choices, solution)):
        problems.append('omml_unconverted')
    if len(choices) == 4 and len(set(choices)) < 4:
        problems.append('duplicate_choices')

    images = []
    for part in (stem, *choices, solution):
        images += RE_IMAGE.findall(part)

    data = {
        'id': '',
        'question': stem,
        'choices': [f'{k}. {v}' for k, v in zip('ABCD', choices)],
        'answer': answer,
        'solution': solution,
        'topic': topic,
        'subtopic': subtopic,
        'difficulty': None,
        'section': raw.section,
        'source': {'file': source, 'question_number': raw.number},
        'answer_source': answer_from,
        'images': images,
        'flags': problems,
        'review_note': None,
    }
    return Item(data, problems)


# ---------------------------------------------------------------------------
# Hình
# ---------------------------------------------------------------------------

def export_image(reader: DocxReader, media_name: str, out_dir: Path, stem: str) -> str:
    """Chép hình ra ``out_dir``; WMF/EMF chuyển sang PNG nếu Pillow đọc được."""
    data = reader.read_media('word/media/' + media_name)
    digest = hashlib.sha1(data).hexdigest()[:10]
    ext = media_name.rsplit('.', 1)[-1].lower()
    if ext in ('wmf', 'emf'):
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(data))
            img.load(dpi=150) if hasattr(img, 'load') else None
            name = f'{stem}_{digest}.png'
            img.save(out_dir / name)
            return name
        except Exception:
            pass
    if ext == 'jpeg':
        ext = 'jpg'
    name = f'{stem}_{digest}.{ext}'
    (out_dir / name).write_bytes(data)
    return name


# ---------------------------------------------------------------------------

BLOCKING_FLAGS = ('no_answer', 'no_choices', 'formula_missing', 'duplicate',
                  'duplicate_choices', 'figure_in_question', 'figure_in_solution',
                  'omml_unconverted',
                  # từ rà soát thủ công (dataset/labels/review.tsv)
                  'key_wrong', 'key_suspect', 'source_corrupted',
                  'segmentation_error', 'figure_implicit')

DIFFICULTY_NAMES = {'NB': 'Nhận biết', 'TH': 'Thông hiểu',
                    'VD': 'Vận dụng', 'VDC': 'Vận dụng cao'}


def _read_tsv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with open(path, encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh, delimiter='\t'))


def apply_labels(items: List[Dict], labels_dir: Path) -> List[str]:
    """Gắn độ khó và cờ rà soát thủ công theo ``id``.

    Mỗi dòng nhãn ghi kèm số file và số câu; nếu không khớp với bản ghi (id bị
    lệch do đổi cách tách câu) thì bỏ qua dòng đó và trả về cảnh báo.
    """
    by_id = {it['id']: it for it in items}
    warnings: List[str] = []

    def target(row: Dict[str, str]) -> Optional[Dict]:
        it = by_id.get(row['id'])
        if it is None:
            warnings.append(f"{row['id']}: không có trong dataset")
            return None
        src = it['source']
        if (src['file'].split()[0] != row['file']
                or str(src['question_number']) != row['question_number']):
            warnings.append(f"{row['id']}: nhãn ghi file {row['file']} câu "
                            f"{row['question_number']}, bản ghi là "
                            f"{src['file'].split()[0]} câu {src['question_number']}")
            return None
        return it

    for row in _read_tsv(labels_dir / 'difficulty.tsv'):
        it = target(row)
        if it is not None:
            it['difficulty'] = DIFFICULTY_NAMES[row['level']]
    for row in _read_tsv(labels_dir / 'review.tsv'):
        it = target(row)
        if it is not None:
            it['flags'].append(row['flag'])
            it['review_note'] = row['note']
    return warnings

# Chữ nhắc tới hình: hình vẽ bằng shape của Word không xuất được thành ảnh nên
# đề vẫn nhắc "như hình vẽ" dù không có ảnh nào.
RE_FIGURE_REF = re.compile(
    r'hình\s*vẽ|hình\s*bên|như\s*hình|trên\s*hình|trong\s*hình|hình\s*dưới'
    r'|hình\s*sau|hình\s*minh\s*họa|đồ\s*thị\s*(?:như|ở|trong|bên)'
    r'|(?:cho|có)\s*bởi\s*hình|miền\s*tô|phần\s*tô|gạch\s*chéo|hình\s*\d',
    re.I)
RE_IMAGE_MD = re.compile(r'!\[hình\]\([^)]*\)\n?')


def apply_figure_policy(item: Dict) -> None:
    """Chỉ giữ câu giải được bằng chữ.

    - Đề/phương án có hình hoặc nhắc tới hình: gắn ``figure_in_question``.
    - Lời giải nhắc tới hình: gắn ``figure_in_solution``.
    - Lời giải có hình minh hoạ nhưng không nhắc tới: bỏ hình, giữ câu.
    Bản ghi vẫn giữ nguyên hình trong ``images`` để dùng cho mô hình đọc ảnh.
    """
    stem = item['question'] + '\n' + '\n'.join(item['choices'])
    if RE_IMAGE_MD.search(stem) or RE_FIGURE_REF.search(stem):
        item['flags'].append('figure_in_question')
        return
    solution = item['solution']
    if RE_FIGURE_REF.search(solution):
        item['flags'].append('figure_in_solution')
    elif RE_IMAGE_MD.search(solution):
        item['solution'] = RE_IMAGE_MD.sub('', solution).strip()
        item['flags'].append('figure_removed_from_solution')


def is_usable(item: Dict) -> bool:
    """Đủ 4 phương án, có đáp án chắc chắn, không thiếu công thức, không trùng."""
    return (len(item['choices']) == 4 and bool(item['answer'])
            and not any(f in BLOCKING_FLAGS or f.startswith('answer_conflict')
                        for f in item['flags']))


def _norm_key(item: Dict) -> str:
    text = item['question'] + '|' + '|'.join(item['choices'])
    text = re.sub(r'!\[hình\]\([^)]*\)', '', text)
    text = re.sub(r'\\left|\\right|\\,|\\;|~|\s+', '', text).lower()
    return hashlib.sha1(text.encode('utf-8')).hexdigest()


def mark_duplicates(items: List[Dict]) -> None:
    """Câu trùng nguyên văn (đề + phương án) ở nhiều file: giữ câu đầu tiên."""
    first: Dict[str, str] = {}
    for it in items:
        key = _norm_key(it)
        if key in first:
            it['duplicate_of'] = first[key]
            it['flags'].append('duplicate')
        else:
            first[key] = it['id']
            it['duplicate_of'] = None


def build(src: Path, out: Path, id_prefix: str,
          labels_dir: Optional[Path] = None) -> Dict:
    files = sorted(src.glob('*.docx'), key=lambda f: int(f.name.split()[0]))
    img_dir = out / 'images'
    img_dir.mkdir(parents=True, exist_ok=True)
    items: List[Dict] = []
    report = {'files': [], 'flags': Counter()}
    for f in files:
        order = int(f.name.split()[0])
        if order not in FILE_TOPICS:
            continue
        topic, subtopic = FILE_TOPICS[order]
        reader = DocxReader(str(f))
        paras = list(reader.paragraphs())
        raws = segment(paras)
        kept = 0
        for raw in raws:
            item = finalize(raw, topic, subtopic, f.name)
            idx = len(items) + 1
            qid = f'{id_prefix}_{idx:04d}'
            item.data['id'] = qid
            # đổi tham chiếu hình sang file đã xuất
            mapping = {}
            for name in item.data['images']:
                base = posixpath.basename(name)
                if base not in mapping:
                    mapping[base] = export_image(reader, base, img_dir, qid)

            def sub(text: str) -> str:
                return RE_IMAGE.sub(
                    lambda m: f'![hình](images/{mapping[m.group(1)]})', text)

            item.data['question'] = sub(item.data['question'])
            item.data['choices'] = [sub(c) for c in item.data['choices']]
            item.data['solution'] = sub(item.data['solution'])
            item.data['images'] = [f'images/{v}' for v in mapping.values()]
            apply_figure_policy(item.data)
            items.append(item.data)
            kept += 1
        report['files'].append({
            'file': f.name, 'questions': kept,
            'equations': reader.stats.equations,
            'equations_from_pictures': reader.stats.equations_from_pictures,
            'equations_failed': reader.stats.eq_failed,
        })
    mark_duplicates(items)
    report['label_warnings'] = apply_labels(items, labels_dir) if labels_dir else []
    report['flags'] = Counter()
    for it in items:
        report['flags'].update(it['flags'])
        it['usable'] = is_usable(it)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'questions.jsonl', 'w', encoding='utf-8') as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + '\n')
    report['total'] = len(items)
    report['usable'] = sum(1 for it in items if is_usable(it))
    report['difficulty'] = dict(Counter(
        it['difficulty'] for it in items if it['usable']))
    report['flags'] = dict(report['flags'])
    with open(out / 'build_report.json', 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', required=True, help='thư mục chứa các file .docx')
    ap.add_argument('--out', default='dataset/export')
    ap.add_argument('--id-prefix', default='int')
    ap.add_argument('--labels', default='dataset/labels',
                    help='thư mục chứa difficulty.tsv và review.tsv')
    args = ap.parse_args()
    report = build(Path(args.src), Path(args.out), args.id_prefix,
                   Path(args.labels))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Gộp bộ Nguyên hàm – Tích phân và bộ đề thi thử thành một dataset.

    python dataset/tools/merge_datasets.py

Đầu vào (mặc định):
    dataset/export/                      bộ Nguyên hàm – Tích phân (build_dataset.py)
    dataset/export/exams/                bộ đề thi thử (build_exams.py)
    dataset/labels/integral_errata.tsv   đính chính chữ cho bộ Nguyên hàm – Tích phân
    dataset/labels/merge.tsv             sửa đáp án, gỡ/gắn cờ, chủ đề, độ khó sau khi gộp
Đầu ra: dataset/export/combined/ gồm questions.jsonl, images/ và build_report.json.

Hai bộ dùng chung một schema: câu của bộ Nguyên hàm – Tích phân được thêm
``collection``, ``type = "mcq"``, ``author_difficulty = null``, ``corrections`` và
``source.exam``/``source.part``. Câu phần "Đề kiểm tra" của sách được xếp lại vào một
trong ba chủ đề Nguyên hàm / Tích phân / Ứng dụng tích phân. Câu trùng giữa hai bộ (cùng
đề và tập phương án) được gắn ``duplicate``.

Công cụ này chỉ import ``build_exams`` và ``build_dataset``, không sửa hai module đó.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_dataset import DIFFICULTY_NAMES, _read_tsv  # noqa: E402
from build_exams import TOPICS, _norm_key, _norm_text, apply_errata, is_usable, load_errata  # noqa: E402

INTEGRAL = 'nguyen_ham_tich_phan'
EXAMS = 'de_thi_thu'
BOOK_TITLE = 'Giải tích 12 – Nguyên hàm, Tích phân và Ứng dụng (Nguyễn Quốc Hoàn)'
TEST_TOPIC = 'Nguyên hàm, tích phân và ứng dụng'   # chủ đề cũ của phần "Đề kiểm tra" trong sách
FIELDS = ['id', 'collection', 'type', 'question', 'choices', 'answer', 'solution', 'topic', 'subtopic',
          'difficulty', 'author_difficulty', 'section', 'source', 'answer_source', 'images', 'flags',
          'review_note', 'corrections', 'duplicate_of', 'usable']

# Xếp chủ đề cho câu "Đề kiểm tra": bài toán ứng dụng trước, rồi tích phân xác định, còn lại
# là nguyên hàm (đề kiểm tra của chương chỉ gồm ba chủ đề này).
RE_APPLIED = re.compile(
    r'diện\s*tích|thể\s*tích|quay\s*(?:quanh|xung)|hình\s*phẳng|vận\s*tốc|quãng\s*đường|chuyển\s*động'
    r'|gia\s*tốc|khối\s*tròn\s*xoay|doanh\s*thu|lợi\s*nhuận|chi\s*phí', re.I)
RE_DEFINITE = re.compile(r'\\int\\limits_|\\int_')


def test_item_topic(question: str) -> str:
    if RE_APPLIED.search(question):
        return 'UD'
    if RE_DEFINITE.search(question):
        return 'TP'
    return 'NH'


def load_jsonl(path: Path) -> List[Dict]:
    with open(path, encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


def fix_integral(items: List[Dict], errata: Dict[str, List[Dict[str, str]]],
                 warnings: List[str]) -> int:
    """Áp đính chính chữ; câu có lời giải rỗng sau khi sửa được gắn ``no_solution``."""
    fixed = 0
    known = {it['id'] for it in items}
    warnings += [f'{i}: đính chính cho câu không có trong bộ Nguyên hàm – Tích phân'
                 for i in errata if i not in known]
    for it in items:
        it.setdefault('corrections', [])
        rows = errata.get(it['id'])
        if not rows:
            continue
        texts = {'question': it['question'], 'solution': it['solution']}
        texts.update({'choice:' + c[:1]: c for c in it['choices']})
        done = apply_errata(it['id'], texts, rows, warnings)
        it['question'], it['solution'] = texts['question'], texts['solution']
        it['choices'] = [texts['choice:' + c[:1]] for c in it['choices']]
        it['corrections'] = done
        if done:
            fixed += 1
            it['flags'].append('text_corrected')
        has_solution = bool(it['solution'].strip())
        if not has_solution and 'no_solution' not in it['flags']:
            it['flags'].append('no_solution')
        elif has_solution and 'no_solution' in it['flags']:
            it['flags'].remove('no_solution')
    return fixed


def from_integral(it: Dict) -> Dict:
    topic = it['topic']
    moved = None
    if topic == TEST_TOPIC:
        moved = test_item_topic(it['question'])
        topic = TOPICS[moved][0]
    out = dict(it, collection=INTEGRAL, type='mcq', topic=topic, author_difficulty=None,
               source={'exam': BOOK_TITLE, 'file': it['source']['file'], 'part': None,
                       'question_number': it['source']['question_number']})
    out['_moved'] = moved
    return out


def apply_merge_labels(items: List[Dict], path: Path) -> Tuple[int, List[str]]:
    """Nhãn sau khi gộp (cột id, answer, unflag, flag, topic, level, note), cho câu của cả hai bộ.

    ``answer``: đáp án đúng (``answer_source = manual``); ``unflag``/``flag``: cờ gỡ/gắn, cách
    nhau dấu phẩy, ``duplicate:<id>`` để đánh dấu trùng; ``topic``: mã chủ đề của
    build_exams (NH, TP, UD, …), chỉ đổi ``topic``; ``level``: NB/TH/VD/VDC; ``note``:
    ``review_note`` mới.
    """
    by_id = {it['id']: it for it in items}
    warnings: List[str] = []
    n = 0
    for row in _read_tsv(path) if path and path.exists() else []:
        it = by_id.get(row['id'])
        if it is None:
            warnings.append(f"{row['id']}: không có trong dataset gộp")
            continue
        n += 1
        if row.get('answer'):
            it['answer'] = row['answer']
            it['answer_source'] = 'manual'
            it['flags'] = [f for f in it['flags']
                           if not f.startswith(('answer_conflict', 'tf_conflict', 'tf_missing'))
                           and f != 'no_answer']
        for flag in filter(None, (row.get('unflag') or '').split(',')):
            if flag in it['flags']:
                it['flags'].remove(flag)
            else:
                warnings.append(f"{row['id']}: không có cờ {flag} để gỡ")
        for flag in filter(None, (row.get('flag') or '').split(',')):
            if flag.startswith('duplicate:'):
                target = flag.split(':', 1)[1]
                if target not in by_id:
                    warnings.append(f"{row['id']}: duplicate_of {target} không tồn tại")
                it['duplicate_of'] = target
                flag = 'duplicate'
            if flag not in it['flags']:
                it['flags'].append(flag)
        if row.get('topic'):
            if row['topic'] in TOPICS:
                it['topic'] = TOPICS[row['topic']][0]
            else:
                warnings.append(f"{row['id']}: mã chủ đề lạ {row['topic']}")
        if row.get('level'):
            it['difficulty'] = DIFFICULTY_NAMES[row['level']]
        if row.get('note'):
            it['review_note'] = row['note']
    return n, warnings


def mark_cross_duplicates(items: List[Dict]) -> List[Tuple[str, str]]:
    """Câu trùng khoá (đề + tập phương án) mà chưa bị đánh dấu trong bộ của nó.

    Bản chính: dùng được, rồi có lời giải, rồi đứng trước (sách trước đề thi).
    """
    order = {it['id']: k for k, it in enumerate(items)}
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for it in items:
        if 'duplicate' in it['flags'] or len(_norm_text(it['question'])) < 15:
            continue
        groups[_norm_key(it)].append(it)
    added = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda it: (not is_usable(it), not it['solution'].strip(), order[it['id']]))
        for it in members[1:]:
            it['flags'].append('duplicate')
            it['duplicate_of'] = members[0]['id']
            added.append((it['id'], members[0]['id']))
    return added


def copy_images(src: Path, dst: Path, seen: Dict[str, str], tag: str) -> int:
    n = 0
    for f in sorted(src.glob('*')):
        if f.name in seen:
            raise SystemExit(f'Trùng tên ảnh {f.name} giữa {seen[f.name]} và {tag}')
        seen[f.name] = tag
        shutil.copy2(f, dst / f.name)
        n += 1
    return n


def summary(items: List[Dict]) -> Dict:
    use = [it for it in items if it['usable']]
    return {
        'total': len(items),
        'usable': len(use),
        'usable_by_type': dict(Counter(it['type'] for it in use)),
        'difficulty': dict(Counter(it['difficulty'] for it in use)),
        'usable_without_solution': sum(1 for it in use if not it['solution'].strip()),
        'topics': dict(Counter(it['topic'] for it in use).most_common()),
    }


def merge(integral_dir: Path, exams_dir: Path, out: Path, errata_path: Path, labels_path: Path) -> Dict:
    integral = load_jsonl(integral_dir / 'questions.jsonl')
    exams = load_jsonl(exams_dir / 'questions.jsonl')
    warnings: List[str] = []
    fixed = fix_integral(integral, load_errata(errata_path), warnings)
    items = [from_integral(it) for it in integral] + [dict(it, collection=EXAMS) for it in exams]
    ids = Counter(it['id'] for it in items)
    dup_ids = [i for i, c in ids.items() if c > 1]
    if dup_ids:
        raise SystemExit(f'id trùng giữa hai bộ: {dup_ids[:10]}')
    moved = Counter(TOPICS[it['_moved']][0] for it in items if it.get('_moved'))
    n_labels, label_warnings = apply_merge_labels(items, labels_path)
    added = mark_cross_duplicates(items)
    for it in items:
        it['usable'] = is_usable(it)
    items = [{k: it[k] for k in FIELDS} for it in items]

    for src in (integral_dir, exams_dir):
        if out.resolve() == src.resolve() or out.resolve() in src.resolve().parents:
            raise SystemExit(f'--out {out} trùng hoặc chứa thư mục nguồn {src}')
    if out.exists():
        shutil.rmtree(out)
    (out / 'images').mkdir(parents=True)
    seen: Dict[str, str] = {}
    n_images = copy_images(integral_dir / 'images', out / 'images', seen, INTEGRAL)
    n_images += copy_images(exams_dir / 'images', out / 'images', seen, EXAMS)
    with open(out / 'questions.jsonl', 'w', encoding='utf-8') as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + '\n')

    flags = Counter()
    for it in items:
        flags.update(f.split('_table=')[0] if f.startswith('answer_conflict') else f for f in it['flags'])
    report = summary(items)
    report.update({
        'images': n_images,
        'by_collection': {c: summary([it for it in items if it['collection'] == c]) for c in (INTEGRAL, EXAMS)},
        'flags': dict(flags.most_common()),
        'integral_corrected_items': fixed,
        'integral_test_items_topic': dict(moved),
        'merge_labels_applied': n_labels,
        'duplicates_added': [{'id': a, 'duplicate_of': b} for a, b in added],
        'warnings': warnings + label_warnings,
        'sources': {
            INTEGRAL: json.load(open(integral_dir / 'build_report.json', encoding='utf-8')),
            EXAMS: json.load(open(exams_dir / 'build_report.json', encoding='utf-8')),
        },
    })
    with open(out / 'build_report.json', 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--integral', default='dataset/export')
    ap.add_argument('--exams', default='dataset/export/exams')
    ap.add_argument('--out', default='dataset/export/combined')
    ap.add_argument('--errata', default='dataset/labels/integral_errata.tsv')
    ap.add_argument('--labels', default='dataset/labels/merge.tsv')
    args = ap.parse_args()
    report = merge(Path(args.integral), Path(args.exams), Path(args.out), Path(args.errata), Path(args.labels))
    print(json.dumps({k: v for k, v in report.items() if k not in ('sources', 'flags')},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""Ghép kết quả audit thủ công thành file nhãn ground-truth cho eval_metrics.

Correctness của một đáp án KHÔNG do pipeline tự chấm. Nó đến từ ngoài: một lần
tái tính độc lập bằng CAS (người viết biểu thức từ dữ kiện đề), hoặc chuyên gia
người. Script này chỉ làm việc ghép: đọc bảng phán quyết theo THỨ TỰ CÂU trong
run rồi gắn vào đúng `question_id`.

Đầu vào (`--verdicts`) là JSON do người tạo::

    {"source": "cas_audit",
     "note": "SymPy re-derivation from problem givens, 2026-07-24",
     "verdicts": {"3": {"key_correct": false, "note": "CAS 165, key 204"},
                  "6": {"key_correct": false, "note": "CAS 43/3, key 47/3"}},
     "default_key_correct": true,
     "unlabelled": [1, 8, 10, 30, 31]}

`default_key_correct` áp cho mọi câu KHÔNG nằm trong `verdicts` và KHÔNG nằm
trong `unlabelled`. Đặt nó null nếu chưa audit hết — khi đó chỉ những câu ghi
tường minh mới có nhãn, phần còn lại để trống thay vì mặc định là đúng.

Cách chạy::

    python scripts/make_ground_truth.py \
        --run report/bench/20260724-b1-postparse \
        --verdicts report/bench/20260724-b1-postparse/cas_verdicts.json \
        --out report/bench/20260724-b1-postparse/ground_truth_cas.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def load_run_questions(run_dir: Path) -> List[Dict[str, Any]]:
    """Đọc câu hỏi theo ĐÚNG thứ tự file (tên file sort) rồi thứ tự trong file.

    Thứ tự này phải khớp với thứ tự người audit đã đánh số, nếu không nhãn sẽ
    gắn nhầm câu.
    """
    questions: List[Dict[str, Any]] = []
    for path in sorted(run_dir.glob('b1_*.json')):
        if path.name == 'b1_summary.json':
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        for q in data.get('questions') or []:
            questions.append({'question_id': q.get('question_id'),
                              'stem': q.get('stem', ''),
                              'source_file': path.name})
    return questions


def main() -> int:
    ap = argparse.ArgumentParser(description='Build ground-truth label file')
    ap.add_argument('--run', required=True, help='thư mục run (chứa b1_*.json)')
    ap.add_argument('--verdicts', required=True, help='JSON phán quyết do người tạo')
    ap.add_argument('--out', required=True, help='file nhãn output')
    args = ap.parse_args()

    run_dir = Path(args.run)
    questions = load_run_questions(run_dir)
    verdicts_doc = json.loads(Path(args.verdicts).read_text(encoding='utf-8'))
    verdicts = {str(k): v for k, v in (verdicts_doc.get('verdicts') or {}).items()}
    unlabelled = {str(x) for x in (verdicts_doc.get('unlabelled') or [])}
    default = verdicts_doc.get('default_key_correct', None)
    source = verdicts_doc.get('source') or 'cas_audit'

    unknown = sorted(set(verdicts) - {str(i + 1) for i in range(len(questions))})
    if unknown:
        print(f'LỖI: phán quyết trỏ tới câu không tồn tại trong run: {unknown}')
        return 2

    labels: Dict[str, Any] = {}
    for index, q in enumerate(questions, start=1):
        key = str(index)
        qid = q['question_id']
        if not qid:
            continue
        if key in verdicts:
            entry = verdicts[key]
            labels[qid] = {
                'key_correct': bool(entry.get('key_correct')),
                'source': entry.get('source') or source,
                'note': str(entry.get('note') or ''),
                'run_index': index,
            }
        elif key in unlabelled or default is None:
            continue
        else:
            labels[qid] = {
                'key_correct': bool(default),
                'source': source,
                'note': 'audit độc lập khớp đáp án key',
                'run_index': index,
            }

    payload = {
        'source': source,
        'note': verdicts_doc.get('note', ''),
        'run': str(run_dir),
        'labelled': len(labels),
        'total_questions': len(questions),
        'labels': labels,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding='utf-8')
    wrong = sum(1 for v in labels.values() if not v['key_correct'])
    print(f'[ground-truth] {len(labels)}/{len(questions)} câu có nhãn '
          f'({wrong} key sai) -> {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

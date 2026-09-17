"""Đọc dataset và chia tập.

    python -m mcqft.data --source trantrien1/vi-math12-integral-mcq --out /content/data

Ghi ra ``items.jsonl`` (chỉ câu ``usable``), ``split.json`` (id -> train/val/test)
và ``stats.md``. Hai thí nghiệm A và B đọc cùng thư mục này nên dùng cùng tập.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Sequence, Set

DATASET_REPO = 'trantrien1/vi-math12-integral-mcq'
SPLIT_SEED = 20260917
LEVELS = ('Nhận biết', 'Thông hiểu', 'Vận dụng', 'Vận dụng cao')


def read_jsonl(path: str) -> List[Dict]:
    with open(path, encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: str, rows: Iterable[Dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + '\n')


def load_items(source: str, token: Optional[str] = None) -> List[Dict]:
    """``source`` là đường dẫn ``questions.jsonl`` hoặc tên repo dataset trên HF."""
    if os.path.exists(source):
        path = source
    else:
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(source, 'questions.jsonl', repo_type='dataset',
                               token=token)
    items = [it for it in read_jsonl(path) if it.get('usable')]
    missing = [it['id'] for it in items if it.get('difficulty') not in LEVELS]
    if missing:
        raise ValueError(f'{len(missing)} câu usable chưa có độ khó, ví dụ {missing[:5]}')
    return items


# ---------------------------------------------------------------------------
# Câu gần trùng
# ---------------------------------------------------------------------------

_RE_NOISE = re.compile(
    r'\\left|\\right|\\limits|\\(?:mathrm|text|operatorname|mathbf)\b|\\[,;!]|[~${}]|\s+')
_RE_MATH = re.compile(r'\$([^$]*)\$')
_RE_LETTER = re.compile(r'^\s*[A-D]\s*[.)]\s*')


def normalize(text: str) -> str:
    return _RE_NOISE.sub('', text).lower()


def shingles(text: str, n: int = 5) -> Set[str]:
    s = normalize(text)
    if len(s) <= n:
        return {s}
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def item_text(item: Dict) -> str:
    return item['question'] + '\n' + '\n'.join(item['choices'])


class _Signature:
    def __init__(self, item: Dict):
        self.text = shingles(item_text(item))
        math = normalize(''.join(_RE_MATH.findall(item['question'])))
        self.math = shingles(math, 3) if len(math) >= 8 else set()
        self.choices = {normalize(_RE_LETTER.sub('', c)) for c in item['choices']}


def same_problem(a: _Signature, b: _Signature, threshold: float = 0.8) -> bool:
    """Hai câu là một bài (có thể khác lời dẫn).

    - chữ của đề + phương án giống nhau từ ``threshold``; hoặc
    - công thức trong đề giống nhau từ 0,7 (3-gram); hoặc
    - chung vài phương án và công thức trong đề giống nhau phần nào.
    """
    if jaccard(a.text, b.text) >= threshold:
        return True
    m = jaccard(a.math, b.math)
    if m >= 0.7:
        return True
    common = a.choices & b.choices
    size = sum(len(c) for c in common)
    if len(common) >= 3:
        return size >= 12 or m >= 0.3
    return len(common) == 2 and size >= 16 and m >= 0.5


def near_duplicate_groups(items: Sequence[Dict], threshold: float = 0.8) -> List[List[int]]:
    """Gom các câu cùng một bài (xem ``same_problem``).

    Dataset đã bỏ câu trùng nguyên văn; còn lại các bản chép lại có sửa lời dẫn
    (thường giữa chuyên đề và đề kiểm tra). Để chúng ở cùng một tập thì điểm
    test không bị thổi phồng vì mô hình đã thấy gần như cùng câu khi train.
    Gộp nhầm hai bài khác nhau chỉ làm chúng về cùng một tập nên luật được
    đặt rộng tay.
    """
    sigs = [_Signature(it) for it in items]
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if find(i) != find(j) and same_problem(sigs[i], sigs[j], threshold):
                parent[find(i)] = find(j)
    groups: Dict[int, List[int]] = defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(i)
    return sorted(groups.values(), key=lambda g: min(g))


def split_items(items: Sequence[Dict], seed: int = SPLIT_SEED,
                threshold: float = 0.8) -> Dict[str, str]:
    """Chia 80/5/15 theo nhóm câu gần trùng, phân tầng theo (chủ đề, độ khó).

    Trong mỗi tầng, các nhóm được xáo theo ``seed`` rồi rải lần lượt theo mẫu 20
    vị trí (3 test, 1 val, 16 train). Bộ đếm chạy liên tục qua các tầng nên tầng
    nhỏ cũng góp vào đúng tỉ lệ chung.
    """
    groups = near_duplicate_groups(items, threshold)
    strata: Dict[tuple, List[List[int]]] = defaultdict(list)
    for g in groups:
        first = items[g[0]]
        strata[(first['topic'], first['difficulty'])].append(g)
    rng = random.Random(seed)
    pattern = {0: 'test', 7: 'test', 14: 'test', 10: 'val'}
    split: Dict[str, str] = {}
    k = 0
    for key in sorted(strata):
        bucket = strata[key]
        rng.shuffle(bucket)
        for g in bucket:
            name = pattern.get(k % 20, 'train')
            for i in g:
                split[items[i]['id']] = name
            k += 1
    return split


def stats_markdown(items: Sequence[Dict], split: Dict[str, str],
                   groups: int) -> str:
    counts = Counter(split.values())
    lines = [f'Tổng {len(items)} câu, {groups} nhóm sau khi gom câu gần trùng.', '',
             '| Tập | Số câu | Có lời giải | ' + ' | '.join(LEVELS) + ' |',
             '|---|---|---|' + '---|' * len(LEVELS)]
    for name in ('train', 'val', 'test'):
        sub = [it for it in items if split[it['id']] == name]
        lv = Counter(it['difficulty'] for it in sub)
        sol = sum(1 for it in sub if it['solution'].strip())
        lines.append(f'| {name} | {counts[name]} | {sol} | '
                     + ' | '.join(str(lv[level]) for level in LEVELS) + ' |')
    return '\n'.join(lines) + '\n'


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', default=DATASET_REPO,
                    help='questions.jsonl hoặc repo dataset trên Hugging Face')
    ap.add_argument('--out', required=True)
    ap.add_argument('--seed', type=int, default=SPLIT_SEED)
    ap.add_argument('--dup-threshold', type=float, default=0.8)
    args = ap.parse_args()

    items = load_items(args.source, token=os.environ.get('HF_TOKEN'))
    split = split_items(items, args.seed, args.dup_threshold)
    n_groups = len(near_duplicate_groups(items, args.dup_threshold))
    os.makedirs(args.out, exist_ok=True)
    write_jsonl(os.path.join(args.out, 'items.jsonl'), items)
    with open(os.path.join(args.out, 'split.json'), 'w', encoding='utf-8') as fh:
        json.dump({'seed': args.seed, 'dup_threshold': args.dup_threshold,
                   'split': split}, fh, ensure_ascii=False, indent=0)
    md = stats_markdown(items, split, n_groups)
    with open(os.path.join(args.out, 'stats.md'), 'w', encoding='utf-8') as fh:
        fh.write(md)
    print(md)


def load_split(data_dir: str) -> Dict[str, List[Dict]]:
    items = read_jsonl(os.path.join(data_dir, 'items.jsonl'))
    with open(os.path.join(data_dir, 'split.json'), encoding='utf-8') as fh:
        split = json.load(fh)['split']
    out: Dict[str, List[Dict]] = {'train': [], 'val': [], 'test': []}
    for it in items:
        out[split[it['id']]].append(it)
    return out


if __name__ == '__main__':
    main()

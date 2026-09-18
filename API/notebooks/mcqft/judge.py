"""Giải mù các câu do mô hình soạn bằng một mô hình KHÁC HỌ (mặc định phi-4).

    python -m mcqft.judge --data /content/data --preds A=/content/exp_a/preds \
        --preds B=/content/exp_b/preds --out /content/judge

Giám khảo chỉ thấy đề và 4 phương án, không thấy đáp án. Câu sinh ra được tính là
"khớp" khi giám khảo chọn đúng chữ cái mà mô hình soạn ghi là đáp án. Giám khảo
cũng giải các câu test thật: độ chính xác trên đó cho biết trần của chỉ số này
(giám khảo tự sai bao nhiêu).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time
from collections import Counter
from typing import Dict, List, Optional, Tuple

from .data import load_split, read_jsonl, write_jsonl
from .infer import render
from .metrics import extract_answer, parse_generated
from .prompts import solve_messages


def collect(data_dir: str, preds: List[Tuple[str, str]]) -> List[Dict]:
    """Các câu cần giải: câu test thật + mọi câu sinh ra đọc được."""
    jobs = [{'key': f"real/{it['id']}", 'item': it}
            for it in load_split(data_dir)['test']]
    for exp, folder in preds:
        paths = sorted(glob.glob(os.path.join(folder, '*.gen.jsonl'))
                       + glob.glob(os.path.join(folder, '*.gen_ctx.jsonl')))
        for path in paths:
            system = os.path.basename(path)[:-len('.jsonl')]
            for row in read_jsonl(path):
                rec, errors = parse_generated(row['text'])
                if errors or rec['answer'] is None:
                    continue
                jobs.append({'key': f"{exp}/{system}/{row['id']}/{row['sample']}",
                             'item': dict(rec, id=row['id'])})
    return jobs


def majority(letters: List[Optional[str]]) -> Optional[str]:
    votes = Counter(x for x in letters if x)
    if not votes:
        return None
    (top, n), *rest = votes.most_common()
    if rest and rest[0][1] == n:
        return None  # hoà phiếu: coi như không kết luận
    return top


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', default='microsoft/phi-4')
    ap.add_argument('--revision', default=None)
    ap.add_argument('--data', required=True)
    ap.add_argument('--preds', action='append', required=True, help='TÊN=thư mục preds')
    ap.add_argument('--out', required=True)
    ap.add_argument('--votes', type=int, default=1,
                    help='>1: lấy mẫu nhiều lần (nhiệt độ 0.6) rồi bầu đa số')
    ap.add_argument('--max-model-len', type=int, default=16384)
    ap.add_argument('--gpu-util', type=float, default=0.88)
    ap.add_argument('--seed', type=int, default=0)
    args = ap.parse_args()

    from vllm import LLM, SamplingParams

    preds = [tuple(p.split('=', 1)) for p in args.preds]
    jobs = collect(args.data, preds)
    print(f'{len(jobs)} câu cần giải', flush=True)
    llm = LLM(model=args.model, revision=args.revision, tokenizer_revision=args.revision,
              dtype='bfloat16', seed=args.seed, max_model_len=args.max_model_len,
              gpu_memory_utilization=args.gpu_util, enable_prefix_caching=True)
    tok = llm.get_tokenizer()
    if args.votes > 1:
        sp = SamplingParams(n=args.votes, temperature=0.6, top_p=0.95,
                            max_tokens=3072, seed=args.seed)
    else:
        sp = SamplingParams(n=1, temperature=0.0, max_tokens=3072)
    prompts = [render(tok, solve_messages(j['item'])) for j in jobs]
    t0 = time.time()
    outs = llm.generate(prompts, sp)
    secs = time.time() - t0
    rows = []
    for j, res in zip(jobs, outs):
        letters = [extract_answer(o.text) for o in res.outputs]
        rows.append({'key': j['key'], 'pred': majority(letters), 'votes': letters,
                     'key_answer': j['item']['answer'], 'text': res.outputs[0].text})
    os.makedirs(args.out, exist_ok=True)
    write_jsonl(os.path.join(args.out, 'judge.jsonl'), rows)
    real = [r for r in rows if r['key'].startswith('real/')]
    acc = sum(r['pred'] == r['key_answer'] for r in real) / max(1, len(real))
    meta = {'model': args.model, 'revision': args.revision, 'votes': args.votes,
            'jobs': len(rows), 'seconds': round(secs, 1), 'real_accuracy': round(acc, 4)}
    with open(os.path.join(args.out, 'judge_meta.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=1)
    print(meta)


if __name__ == '__main__':
    main()

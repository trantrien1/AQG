"""Sinh đầu ra trên tập test bằng vLLM.

    python -m mcqft.infer --model Qwen/Qwen3-8B --data /content/data \
        --adapter /content/exp_a/adapter --out /content/exp_a/preds

Mỗi hệ được chạy trên cùng các câu test:

- ``base``: mô hình gốc, không ví dụ mẫu;
- ``base_fs<k>``: mô hình gốc với k ví dụ mẫu lấy từ tập train (chỉ tác vụ gen);
- ``lora``: mô hình gốc + adapter (không ví dụ mẫu).

Kết quả: ``<out>/<hệ>.<tác vụ>.jsonl`` và ``<out>/infer_summary.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from typing import Dict, List, Sequence, Tuple

from .data import load_split, write_jsonl
from .prompts import gen_messages, pick_shots, solve_messages

GEN_SAMPLING = dict(temperature=0.7, top_p=0.8, top_k=20, max_tokens=2048)
SOLVE_SAMPLING = dict(temperature=0.0, max_tokens=2048)


def parse_systems(spec: str, has_adapter: bool) -> List[Tuple[str, int, bool]]:
    """"base,base_fs3,lora" -> [(tên, số ví dụ mẫu, dùng adapter)]."""
    out = []
    for name in (s.strip() for s in spec.split(',') if s.strip()):
        if name == 'base':
            out.append((name, 0, False))
        elif name.startswith('base_fs'):
            out.append((name, int(name[len('base_fs'):]), False))
        elif name == 'lora':
            if has_adapter:
                out.append((name, 0, True))
        else:
            raise ValueError(f'hệ không hợp lệ: {name}')
    return out


def plan(splits: Dict[str, List[Dict]], task: str, shots: int,
         seed: int) -> List[Tuple[str, List[Dict]]]:
    """Danh sách (id câu test, hội thoại) cho một hệ và một tác vụ."""
    reqs = []
    for it in splits['test']:
        if task == 'gen':
            ex = pick_shots(it, splits['train'], shots, seed)
            reqs.append((it['id'], gen_messages(it, ex)))
        else:
            reqs.append((it['id'], solve_messages(it)))
    return reqs


def render(tokenizer, messages: Sequence[Dict]) -> str:
    kwargs = dict(tokenize=False, add_generation_prompt=True)
    try:
        return tokenizer.apply_chat_template(list(messages), enable_thinking=False, **kwargs)
    except TypeError:
        return tokenizer.apply_chat_template(list(messages), **kwargs)


def run(llm, tokenizer, reqs, sampling, lora_request=None) -> Tuple[List[Dict], Dict]:
    prompts = [render(tokenizer, m) for _, m in reqs]
    t0 = time.time()
    outs = llm.generate(prompts, sampling, lora_request=lora_request)
    secs = time.time() - t0
    rows, n_out = [], 0
    for (qid, _), res in zip(reqs, outs):
        for k, o in enumerate(res.outputs):
            n_out += len(o.token_ids)
            rows.append({'id': qid, 'sample': k, 'text': o.text,
                         'output_tokens': len(o.token_ids),
                         'finish_reason': o.finish_reason})
    stats = {'prompts': len(prompts), 'seconds': round(secs, 1), 'output_tokens': n_out,
             'output_tokens_per_second': round(n_out / secs, 1) if secs else None}
    return rows, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', required=True)
    ap.add_argument('--revision', default=None)
    ap.add_argument('--data', required=True)
    ap.add_argument('--adapter', default=None)
    ap.add_argument('--out', required=True)
    ap.add_argument('--systems', default='base,base_fs3,lora')
    ap.add_argument('--tasks', default='gen,solve')
    ap.add_argument('--gen-samples', type=int, default=2,
                    help='số câu sinh cho mỗi đề bài test (nhiều hơn -> ước lượng chắc hơn)')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--max-model-len', type=int, default=12288)
    ap.add_argument('--gpu-util', type=float, default=0.88)
    args = ap.parse_args()

    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    splits = load_split(args.data)
    systems = parse_systems(args.systems, bool(args.adapter))
    tasks = [t.strip() for t in args.tasks.split(',') if t.strip()]
    rank = 0
    if args.adapter:
        with open(os.path.join(args.adapter, 'adapter_config.json'), encoding='utf-8') as fh:
            rank = json.load(fh)['r']
    llm = LLM(model=args.model, revision=args.revision, tokenizer_revision=args.revision,
              dtype='bfloat16', seed=args.seed, max_model_len=args.max_model_len,
              gpu_memory_utilization=args.gpu_util, enable_prefix_caching=True,
              enable_lora=bool(args.adapter), max_lora_rank=max(rank, 8), max_loras=1)
    tokenizer = llm.get_tokenizer()
    lora_req = LoRARequest('adapter', 1, args.adapter) if args.adapter else None

    os.makedirs(args.out, exist_ok=True)
    summary = {'model': args.model, 'revision': args.revision, 'adapter': args.adapter,
               'gen_sampling': GEN_SAMPLING, 'gen_samples': args.gen_samples,
               'solve_sampling': SOLVE_SAMPLING, 'runs': {}}
    for name, shots, use_lora in systems:
        for task in tasks:
            if task == 'solve' and shots:
                continue  # few-shot chỉ làm baseline cho tác vụ sinh
            if task == 'gen':
                sp = SamplingParams(n=args.gen_samples, seed=args.seed, **GEN_SAMPLING)
            else:
                sp = SamplingParams(n=1, seed=args.seed, **SOLVE_SAMPLING)
            reqs = plan(splits, task, shots, args.seed)
            rows, stats = run(llm, tokenizer, reqs, sp, lora_req if use_lora else None)
            write_jsonl(os.path.join(args.out, f'{name}.{task}.jsonl'), rows)
            summary['runs'][f'{name}.{task}'] = stats
            print(name, task, stats, flush=True)
    with open(os.path.join(args.out, 'infer_summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()

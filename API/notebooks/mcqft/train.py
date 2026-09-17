"""Huấn luyện LoRA (bf16, không lượng tử hoá) cho Qwen3.

    python -m mcqft.train --model Qwen/Qwen3-8B --data /content/data --out /content/exp_a

Loss chỉ tính trên phần trả lời của trợ lý. Hội thoại được dựng bằng chat
template của chính mô hình với ``enable_thinking=False``, giống hệt lúc suy luận.
Checkpoint có loss val thấp nhất được giữ lại làm adapter cuối.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from typing import Dict, List, Sequence

from .data import load_split
from .prompts import build_examples

TARGET_MODULES = ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']


def render_prompt(tokenizer, messages: Sequence[Dict]) -> str:
    return tokenizer.apply_chat_template(list(messages), tokenize=False,
                                         add_generation_prompt=True,
                                         enable_thinking=False)


def tokenize_example(tokenizer, example: Dict, max_len: int) -> Dict | None:
    """input_ids = prompt + trả lời + <|im_end|>; labels che phần prompt bằng -100."""
    prompt = render_prompt(tokenizer, example['messages'])
    prompt_ids = tokenizer(prompt, add_special_tokens=False)['input_ids']
    answer_ids = tokenizer(example['target'] + tokenizer.eos_token,
                           add_special_tokens=False)['input_ids']
    ids = prompt_ids + answer_ids
    if len(ids) > max_len:
        return None
    return {'input_ids': ids, 'attention_mask': [1] * len(ids),
            'labels': [-100] * len(prompt_ids) + answer_ids}


class PadCollator:
    def __init__(self, pad_id: int, multiple: int = 8):
        self.pad_id = pad_id
        self.multiple = multiple

    def __call__(self, batch: List[Dict]):
        import torch
        width = max(len(b['input_ids']) for b in batch)
        width = int(math.ceil(width / self.multiple) * self.multiple)
        out = {'input_ids': [], 'attention_mask': [], 'labels': []}
        for b in batch:
            pad = width - len(b['input_ids'])
            out['input_ids'].append(b['input_ids'] + [self.pad_id] * pad)
            out['attention_mask'].append(b['attention_mask'] + [0] * pad)
            out['labels'].append(b['labels'] + [-100] * pad)
        return {k: torch.tensor(v) for k, v in out.items()}


def encode_all(tokenizer, examples: Sequence[Dict], max_len: int):
    rows, dropped = [], []
    for ex in examples:
        row = tokenize_example(tokenizer, ex, max_len)
        if row is None:
            dropped.append(ex['id'])
        else:
            rows.append(row)
    return rows, dropped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--model', required=True)
    ap.add_argument('--revision', default=None, help='commit SHA của trọng số (ghim để tái lập)')
    ap.add_argument('--data', required=True, help='thư mục do mcqft.data tạo')
    ap.add_argument('--out', required=True)
    ap.add_argument('--tasks', default='gen,solve')
    ap.add_argument('--shuffle-aug', type=int, default=0,
                    help='số bản xáo phương án thêm cho mỗi câu ở tác vụ solve')
    ap.add_argument('--epochs', type=float, default=3)
    ap.add_argument('--lr', type=float, default=1e-4)
    ap.add_argument('--rank', type=int, default=32)
    ap.add_argument('--alpha', type=int, default=64)
    ap.add_argument('--dropout', type=float, default=0.05)
    ap.add_argument('--use-rslora', action='store_true')
    ap.add_argument('--use-dora', action='store_true')
    ap.add_argument('--batch', type=int, default=4)
    ap.add_argument('--grad-accum', type=int, default=4)
    ap.add_argument('--max-len', type=int, default=3072)
    ap.add_argument('--warmup', type=float, default=0.05)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--no-bf16', action='store_true', help='chạy thử trên CPU')
    ap.add_argument('--max-steps', type=int, default=-1, help='chạy thử')
    args = ap.parse_args()

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (AutoModelForCausalLM, AutoTokenizer, Trainer,
                              TrainingArguments, set_seed)

    set_seed(args.seed)
    os.makedirs(args.out, exist_ok=True)
    tasks = [t.strip() for t in args.tasks.split(',') if t.strip()]
    tok = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    assert tok.eos_token == '<|im_end|>', f'eos_token lạ: {tok.eos_token!r}'
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    splits = load_split(args.data)
    train_ex = build_examples(splits['train'], tasks, args.shuffle_aug, args.seed)
    val_ex = build_examples(splits['val'], tasks, 0, args.seed)
    train_rows, dropped_train = encode_all(tok, train_ex, args.max_len)
    val_rows, dropped_val = encode_all(tok, val_ex, args.max_len)
    n_tokens = sum(len(r['input_ids']) for r in train_rows)
    n_target = sum(sum(1 for x in r['labels'] if x != -100) for r in train_rows)
    print(f'train {len(train_rows)} mẫu ({n_tokens} token, {n_target} token tính loss), '
          f'val {len(val_rows)} mẫu; bỏ vì quá dài: {len(dropped_train) + len(dropped_val)}')

    dtype = torch.float32 if args.no_bf16 else torch.bfloat16
    model = AutoModelForCausalLM.from_pretrained(
        args.model, revision=args.revision, dtype=dtype, attn_implementation='sdpa')
    model.config.use_cache = False
    lora = LoraConfig(r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout,
                      target_modules=TARGET_MODULES, bias='none', task_type='CAUSAL_LM',
                      use_rslora=args.use_rslora, use_dora=args.use_dora)
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    steps_per_epoch = math.ceil(len(train_rows) / (args.batch * args.grad_accum))
    total_steps = args.max_steps if args.max_steps > 0 else math.ceil(steps_per_epoch * args.epochs)
    targs = TrainingArguments(
        output_dir=os.path.join(args.out, 'checkpoints'),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type='cosine',
        warmup_steps=max(1, int(args.warmup * total_steps)),
        weight_decay=0.0,
        bf16=not args.no_bf16,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={'use_reentrant': False},
        eval_strategy='epoch' if args.max_steps <= 0 else 'steps',
        save_strategy='epoch' if args.max_steps <= 0 else 'steps',
        eval_steps=args.max_steps if args.max_steps > 0 else None,
        save_steps=args.max_steps if args.max_steps > 0 else None,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model='eval_loss',
        greater_is_better=False,
        logging_steps=5,
        disable_tqdm=True,  # in từng dòng log thay vì thanh tiến trình (chạy qua subprocess)
        report_to='none',
        seed=args.seed,
        data_seed=args.seed,
        remove_unused_columns=False,
        dataloader_num_workers=2 if not args.no_bf16 else 0,
    )
    trainer = Trainer(model=model, args=targs, train_dataset=train_rows,
                      eval_dataset=val_rows, data_collator=PadCollator(pad_id))

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    result = trainer.train()
    train_seconds = time.time() - t0
    final = trainer.evaluate()

    adapter_dir = os.path.join(args.out, 'adapter')
    trainer.model.save_pretrained(adapter_dir)
    tok.save_pretrained(adapter_dir)

    summary = {
        'model': args.model, 'revision': args.revision, 'tasks': tasks,
        'args': vars(args),
        'train_examples': len(train_rows), 'val_examples': len(val_rows),
        'train_tokens_per_epoch': n_tokens, 'target_tokens_per_epoch': n_target,
        'dropped_too_long': dropped_train + dropped_val,
        'train_seconds': round(train_seconds, 1),
        'train_tokens_per_second': round(n_tokens * args.epochs / train_seconds, 1)
        if args.max_steps <= 0 else None,
        'peak_gpu_mem_gb': round(torch.cuda.max_memory_allocated() / 2**30, 2)
        if torch.cuda.is_available() else None,
        'best_checkpoint': trainer.state.best_model_checkpoint,
        'best_eval_loss': trainer.state.best_metric,
        'final_eval_loss': final.get('eval_loss'),
        'train_loss': result.training_loss,
        'log_history': trainer.state.log_history,
    }
    with open(os.path.join(args.out, 'train_summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != 'log_history'},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()

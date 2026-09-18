"""Sinh câu hỏi từ PDF người dùng tải lên, với Writer là mô hình đã fine-tune.

Ba giai đoạn, mỗi giai đoạn một tiến trình riêng nên không phải giữ nhiều mô
hình trong bộ nhớ cùng lúc (A100 80GB không đủ cho 14B bf16 + model thị giác +
solver cùng lúc):

1. ``prepare`` — model thị giác chép các trang PDF thành chữ (công thức sang
   LaTeX) và trích dàn ý. Cần máy chủ model thị giác.
2. ``draft``   — mô hình fine-tune soạn sẵn một kho câu nháp theo mức độ, dùng
   trích đoạn tài liệu làm ngữ cảnh. Chạy vLLM offline, chiếm GPU một mình.
3. ``generate``— pipeline gốc chạy như thường, chỉ thay Writer bằng kho câu
   nháp đó: phương án nhiễu, giải độc lập, kiểm chứng, chấm, đóng gói đều
   nguyên trạng. Cần máy chủ model thị giác (và solver nếu bật kiểm chứng độc lập).

    python -m mcqft.pipeline_ft prepare  --pdf bai.pdf --out /content/run1
    python -m mcqft.pipeline_ft draft    --prep /content/run1 --model Qwen/Qwen3-14B \
        --adapter /content/expB/adapter --n 10
    python -m mcqft.pipeline_ft generate --prep /content/run1 --n 10

Chế độ ``--online-url`` gọi thẳng máy chủ đang phục vụ base + adapter (bỏ giai
đoạn 2), dùng khi đủ bộ nhớ cho cả hai mô hình.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from typing import Any, Dict, List, Sequence, Tuple

from .data import jaccard, shingles, write_jsonl
from .ft_writer import FineTunedWriter, OnlineDrafter
from .metrics import parse_generated
from .prompts import CONTEXT_CHARS, gen_ctx_messages

TRANSCRIBE_PROMPT = (
    'Chép lại NGUYÊN VĂN nội dung trang tài liệu này thành văn bản thuần.\n'
    '- Giữ đúng chữ tiếng Việt, số liệu, thứ tự các phần.\n'
    '- Mọi công thức viết bằng LaTeX đặt trong $...$.\n'
    '- Bảng ghi thành từng dòng, các ô cách nhau bằng " | ".\n'
    '- Hình vẽ ghi thành một dòng "[Hình: mô tả ngắn]".\n'
    '- KHÔNG giải bài, KHÔNG thêm nhận xét, KHÔNG bỏ sót phần nào.\n'
    'Nếu trang trắng thì trả về đúng "[Trang trắng]".'
)

LEVELS = ('Nhận biết', 'Thông hiểu', 'Vận dụng', 'Vận dụng cao')
_BLOOM_TARGETS = {'Nhận biết': 0.30, 'Thông hiểu': 0.50,
                  'Vận dụng': 0.70, 'Vận dụng cao': 0.85}
COPY_CONTAINMENT = 0.8


def _add_api_root() -> str:
    """Thư mục ``API`` (chứa package ``pipeline``) vào ``sys.path``."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def bloom_distribution(level: str) -> List[Dict[str, Any]]:
    _add_api_root()
    from pipeline import config as cfg
    if level == 'mixed':
        return [dict(item) for item in cfg.DEFAULT_DIFFICULTY_DISTRIBUTION]
    return [{'cognitive_level': level, 'difficulty_target': _BLOOM_TARGETS[level],
             'fraction': 1.0}]


def pick_level(distribution: Sequence[Dict[str, Any]], index: int) -> str:
    """Mức Bloom của câu thứ ``index`` — dùng chính bộ lập lịch của pipeline."""
    _add_api_root()
    from pipeline.direct_pdf.agents.pdf_orchestrator import _pick_cognitive
    return _pick_cognitive(list(distribution), index)


# ---------------------------------------------------------------------------
# Trích đoạn tài liệu
# ---------------------------------------------------------------------------

def build_windows(pages: Sequence[str], max_chars: int = CONTEXT_CHARS) -> List[Dict]:
    """Gộp các trang thành trích đoạn dài tối đa ``max_chars`` ký tự."""
    windows: List[Dict] = []
    current: List[str] = []
    pages_in: List[int] = []
    size = 0

    def flush() -> None:
        nonlocal current, pages_in, size
        if current:
            windows.append({'index': len(windows), 'pages': list(pages_in),
                            'text': '\n\n'.join(current).strip()})
        current, pages_in, size = [], [], 0

    for i, page in enumerate(pages):
        text = (page or '').strip()
        if not text or text == '[Trang trắng]':
            continue
        blocks = [text] if len(text) <= max_chars else [
            text[j:j + max_chars] for j in range(0, len(text), max_chars)]
        for block in blocks:
            if size and size + len(block) > max_chars:
                flush()
            current.append(block)
            pages_in.append(i + 1)
            size += len(block)
    flush()
    return windows


def rank_windows(windows: Sequence[Dict], topic: str) -> List[Dict]:
    """Trích đoạn khớp chủ đề nhất trước (theo số từ chung)."""
    if not topic:
        return list(windows)
    want = shingles(topic, 4)
    return sorted(windows, key=lambda w: -jaccard(want, shingles(w['text'][:4000], 4)))


def containment(text: str, other: str) -> float:
    """Phần của ``text`` nằm trong ``other`` (bắt câu chép lại từ tài liệu)."""
    a, b = shingles(text), shingles(other)
    return len(a & b) / len(a) if a else 0.0


# ---------------------------------------------------------------------------
# 1. prepare
# ---------------------------------------------------------------------------

def cmd_prepare(args: argparse.Namespace) -> None:
    _add_api_root()
    from pipeline import config as cfg
    from pipeline.direct_pdf import attach as attach_mod
    from pipeline.direct_pdf import page_selection
    from pipeline.direct_pdf.outline import extract_outline
    from pipeline.llm_client import call_llm_with_pdf

    model = args.model or cfg.GENERATOR_MODEL
    with open(args.pdf, 'rb') as fh:
        pdf_bytes = fh.read()
    parts = page_selection.cached_page_parts(
        pdf_bytes, os.path.basename(args.pdf), dpi=args.dpi, max_pages=args.max_pages,
        builder=attach_mod.build_pdf_image_content)
    print(f'{len(parts)} trang, model {model}', flush=True)

    def transcribe(job: Tuple[int, Dict]) -> Tuple[int, str]:
        i, part = job
        try:
            raw = call_llm_with_pdf(
                system=cfg.SYSTEM_PROMPT,
                user_content=[{'type': 'text', 'text': TRANSCRIBE_PROMPT}, part],
                model=model, max_tokens=args.page_tokens)
            print(f'  trang {i + 1}: {len(raw)} ký tự', flush=True)
            return i, raw.strip()
        except Exception as exc:
            print(f'  trang {i + 1} lỗi: {exc}', flush=True)
            return i, ''

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pages = [text for _, text in sorted(pool.map(transcribe, enumerate(parts)))]
    outline = None if args.no_outline else extract_outline(parts, model)

    os.makedirs(args.out, exist_ok=True)
    prep = {'pdf': os.path.abspath(args.pdf), 'model': model, 'dpi': args.dpi,
            'max_pages': args.max_pages, 'pages': pages, 'outline': outline,
            'seconds': round(time.time() - t0, 1)}
    with open(os.path.join(args.out, 'prep.json'), 'w', encoding='utf-8') as fh:
        json.dump(prep, fh, ensure_ascii=False, indent=1)
    chars = sum(len(p) for p in pages)
    empty = sum(1 for p in pages if not p.strip())
    print(json.dumps({'pages': len(pages), 'chars': chars, 'empty_pages': empty,
                      'windows': len(build_windows(pages, args.context_chars)),
                      'topics': (outline or {}).get('topics'),
                      'seconds': prep['seconds']}, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------------------
# 2. draft
# ---------------------------------------------------------------------------

def plan_drafts(windows: Sequence[Dict], topics: Sequence[str],
                distribution: Sequence[Dict[str, Any]], total: int) -> List[Dict]:
    """Kế hoạch câu nháp: mức Bloom theo phân bố, chủ đề và trích đoạn rải đều."""
    ranked = {t: rank_windows(windows, t) for t in topics} if topics else {}
    plan: List[Dict] = []
    for i in range(total):
        level = pick_level(distribution, i)
        topic = topics[i % len(topics)] if topics else ''
        pool = ranked.get(topic) or list(windows)
        # xoay vòng trong 3 trích đoạn khớp nhất để câu không bị trùng ngữ cảnh
        take = pool[:3] if topic else pool
        win = take[(i // max(1, len(topics) or 1)) % len(take)]
        plan.append({'index': i, 'level': level, 'topic': topic,
                     'window': win['index'], 'pages': win['pages']})
    return plan


def cmd_draft(args: argparse.Namespace) -> None:
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    from .infer import render

    prep = json.load(open(os.path.join(args.prep, 'prep.json'), encoding='utf-8'))
    windows = build_windows(prep['pages'], args.context_chars)
    if not windows:
        raise SystemExit('Bản chép tài liệu rỗng — chạy lại bước prepare')
    topics = list((prep.get('outline') or {}).get('topics') or [])
    distribution = bloom_distribution(args.bloom)
    total = args.n * args.oversample
    plan = plan_drafts(windows, topics, distribution, total)

    rank = 0
    if args.adapter:
        with open(os.path.join(args.adapter, 'adapter_config.json'), encoding='utf-8') as fh:
            rank = json.load(fh)['r']
    llm = LLM(model=args.model, revision=args.revision, tokenizer_revision=args.revision,
              dtype='bfloat16', seed=args.seed, max_model_len=args.max_model_len,
              gpu_memory_utilization=args.gpu_util, enable_prefix_caching=True,
              enable_lora=bool(args.adapter), max_lora_rank=max(rank, 8), max_loras=1)
    tok = llm.get_tokenizer()
    lora = LoRARequest('adapter', 1, args.adapter) if args.adapter else None
    prompts = [render(tok, gen_ctx_messages(windows[p['window']]['text'], p['level'],
                                            p['topic'])) for p in plan]
    t0 = time.time()
    outs = llm.generate(prompts, SamplingParams(
        n=1, temperature=args.temperature, top_p=0.8, top_k=20,
        max_tokens=args.max_tokens, seed=args.seed), lora_request=lora)
    secs = time.time() - t0

    _add_api_root()
    from pipeline.direct_pdf.generator import _synthetic_slot

    from .ft_writer import rule_issues

    doc_text = '\n\n'.join(p for p in prep['pages'] if p.strip())
    kept: List[Dict] = []
    dropped: Counter = Counter()
    seen: List[set] = []
    for p, res in zip(plan, outs):
        text = res.outputs[0].text
        record, problems = parse_generated(text)
        if problems or record['answer'] is None:
            dropped[f"khuôn: {','.join(problems) or 'thiếu đáp án'}"] += 1
            continue
        stem = record['question']
        window_text = windows[p['window']]['text']
        if containment(stem, window_text) >= COPY_CONTAINMENT:
            dropped['chép lại bài trong tài liệu'] += 1
            continue
        marks = shingles(stem)
        if any(jaccard(marks, s) >= 0.8 for s in seen):
            dropped['trùng câu nháp khác'] += 1
            continue
        if not args.keep_all:
            # Lọc trước bằng chính bộ luật của pipeline: rẻ hơn nhiều so với để
            # câu đi qua Distractor + Critic (mỗi bước một lời gọi model thị giác).
            slot = _synthetic_slot(0, {'cognitive_level': p['level']})
            slot['source_chunk_type'] = 'exercise'
            issues = rule_issues(record, slot, doc_text, args.distractors == 'model')
            if issues:
                dropped[f'luật pipeline: {issues[0]}'] += 1
                continue
        seen.append(marks)
        kept.append(dict(p, text=text, output_tokens=len(res.outputs[0].token_ids)))

    os.makedirs(args.prep, exist_ok=True)
    write_jsonl(os.path.join(args.prep, 'pool.jsonl'), kept)
    by_level = Counter(k['level'] for k in kept)
    summary = {'model': args.model, 'revision': args.revision, 'adapter': args.adapter,
               'planned': total, 'kept': len(kept), 'by_level': dict(by_level),
               'dropped': dict(dropped), 'seconds': round(secs, 1),
               'windows': len(windows), 'topics': topics,
               'output_tokens': sum(k['output_tokens'] for k in kept)}
    with open(os.path.join(args.prep, 'draft_summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    need = Counter(pick_level(distribution, i) for i in range(args.n))
    thin = {lv: (by_level.get(lv, 0), n) for lv, n in need.items() if by_level.get(lv, 0) < n}
    if thin:
        print(f'CẢNH BÁO: kho câu nháp mỏng (có/cần): {thin} — tăng --oversample', flush=True)


# ---------------------------------------------------------------------------
# 3. generate
# ---------------------------------------------------------------------------

def load_pool(path: str) -> Dict[str, List[Dict]]:
    pool: Dict[str, List[Dict]] = defaultdict(list)
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                pool[row['level']].append(row)
    return dict(pool)


def cmd_generate(args: argparse.Namespace) -> None:
    if args.distractors == 'model':
        # Phương án nhiễu của mô hình fine-tune không kèm mô tả lỗi, nên tiêu chí
        # "lỗi khớp giá trị" của Critic không áp dụng được.
        os.environ.setdefault('AQG_ERROR_VALUE_CONSISTENCY_THRESHOLD', '0')
    _add_api_root()
    from pipeline import ablation
    from pipeline import config as cfg
    from pipeline.direct_pdf.agents.pdf_orchestrator import DirectPdfOrchestrator

    prep = json.load(open(os.path.join(args.prep, 'prep.json'), encoding='utf-8'))
    pdf_path = args.pdf or prep['pdf']
    doc_text = '\n\n'.join(p for p in prep['pages'] if p.strip())
    windows = build_windows(prep['pages'], args.context_chars)
    topics = list((prep.get('outline') or {}).get('topics') or [])
    outcomes = list((prep.get('outline') or {}).get('suggested_learning_outcomes') or [])
    distribution = bloom_distribution(args.bloom)
    own_distractors = args.distractors == 'model'

    drafts = None
    drafter = None
    context_for_slot = None
    if args.online_url:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(args.tokenizer or args.online_model)
        drafter = OnlineDrafter(base_url=args.online_url, model=args.online_model,
                                api_key=os.environ.get('VLLM_KEY', 'none'), tokenizer=tok,
                                max_tokens=args.max_tokens, temperature=args.temperature)
        counter = {'i': 0}
        ranked = {t: rank_windows(windows, t) for t in topics} if topics else {}

        def pick_context(slot: Dict) -> Tuple[str, str]:
            """Trích đoạn cho slot kế tiếp: xoay vòng chủ đề rồi xoay trong 3 đoạn khớp nhất."""
            i = counter['i']
            counter['i'] += 1
            topic = topics[i % len(topics)] if topics else ''
            pool = (ranked.get(topic) or windows)[:3] if topic else windows
            return pool[i % len(pool)]['text'], topic

        context_for_slot = pick_context
    else:
        drafts = load_pool(os.path.join(args.prep, 'pool.jsonl'))
        print('kho câu nháp:', {k: len(v) for k, v in drafts.items()}, flush=True)

    writer = FineTunedWriter(doc_text=doc_text, drafts=drafts, drafter=drafter,
                             context_for_slot=context_for_slot,
                             own_distractors=own_distractors, tries=args.tries)
    orchestrator = DirectPdfOrchestrator(model=cfg.GENERATOR_MODEL)
    orchestrator.writer = writer

    def progress(event: Dict[str, Any]) -> None:
        print(f"  [{event.get('stage')}] accepted={event.get('accepted')}/"
              f"{event.get('target')} attempted={event.get('attempted')}", flush=True)

    t0 = time.time()
    guard = (ablation.override(distractor_agent=False) if own_distractors
             else nullcontext())
    with guard:
        result = orchestrator.generate(
            pdf_path=pdf_path, requested_count=args.n, bloom_distribution=distribution,
            progress_callback=progress, learning_outcomes=outcomes,
            include_explanation=not args.no_explanation)
        snapshot = ablation.snapshot()
    secs = time.time() - t0

    out = args.out or os.path.join(args.prep, 'questions')
    os.makedirs(out, exist_ok=True)
    metadata = {
        'mode': 'Direct_PDF_Mode + writer fine-tune',
        'source_pdf_name': os.path.basename(pdf_path),
        'requested_questions': result.requested_count,
        'accepted_questions': result.accepted_count,
        'is_partial': result.is_partial,
        'parse_errors': result.parse_errors,
        'verify_failures': result.verify_failures,
        'writer': {'kind': 'finetuned', 'drafts': args.prep if drafts else None,
                   'online_model': args.online_model, 'stats': writer.stats,
                   'distractors': args.distractors},
        'vision_model': cfg.GENERATOR_MODEL,
        'judge_model': cfg.JUDGE_MODEL,
        'independent_solvers': cfg.INDEPENDENT_SOLVERS or [cfg.INDEPENDENT_VERIFIER_MODEL],
        'ablation': snapshot,
        'seconds': round(secs, 1),
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    with open(os.path.join(out, 'questions.json'), 'w', encoding='utf-8') as fh:
        json.dump({'metadata': metadata, 'questions': result.questions}, fh,
                  ensure_ascii=False, indent=2)
    write_jsonl(os.path.join(out, 'rejected.jsonl'), result.rejected or [])
    summary = dict(metadata)
    summary['status_counts'] = dict(Counter(
        ((q.get('verification') or {}).get('status') or 'unknown')
        for q in result.questions))
    summary['review_status'] = dict(Counter(q.get('review_status')
                                            for q in result.questions))
    summary['levels'] = dict(Counter(q.get('cognitive_level')
                                     for q in result.questions))
    summary['reject_codes'] = dict(Counter(r.get('reject_reason_code')
                                           for r in (result.rejected or [])))
    with open(os.path.join(out, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('prepare', help='chép trang PDF thành chữ + trích dàn ý')
    p.add_argument('--pdf', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--model', default=None, help='model thị giác (mặc định: của pipeline)')
    p.add_argument('--dpi', type=int, default=144)
    p.add_argument('--max-pages', type=int, default=30)
    p.add_argument('--page-tokens', type=int, default=3000)
    p.add_argument('--workers', type=int, default=4)
    p.add_argument('--context-chars', type=int, default=CONTEXT_CHARS)
    p.add_argument('--no-outline', action='store_true')
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser('draft', help='mô hình fine-tune soạn kho câu nháp')
    p.add_argument('--prep', required=True, help='thư mục có prep.json')
    p.add_argument('--model', required=True)
    p.add_argument('--revision', default=None)
    p.add_argument('--adapter', default=None)
    p.add_argument('--n', type=int, required=True, help='số câu cần cuối cùng')
    p.add_argument('--oversample', type=int, default=3)
    p.add_argument('--bloom', default='mixed',
                   choices=['mixed', *LEVELS])
    p.add_argument('--context-chars', type=int, default=CONTEXT_CHARS)
    p.add_argument('--temperature', type=float, default=0.7)
    p.add_argument('--max-tokens', type=int, default=2048)
    p.add_argument('--max-model-len', type=int, default=8192)
    p.add_argument('--gpu-util', type=float, default=0.88)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--distractors', default='pipeline', choices=['pipeline', 'model'],
                   help='phải khớp với bước generate (đổi cách lọc luật)')
    p.add_argument('--keep-all', action='store_true',
                   help='không lọc trước bằng bộ luật của pipeline')
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser('generate', help='chạy pipeline với Writer fine-tune')
    p.add_argument('--prep', required=True)
    p.add_argument('--pdf', default=None, help='mặc định lấy từ prep.json')
    p.add_argument('--out', default=None)
    p.add_argument('--n', type=int, required=True)
    p.add_argument('--bloom', default='mixed', choices=['mixed', *LEVELS])
    p.add_argument('--distractors', default='pipeline', choices=['pipeline', 'model'],
                   help='pipeline: tác nhân nhiễu của pipeline soạn lại 3 phương án; '
                        'model: giữ phương án của mô hình fine-tune')
    p.add_argument('--tries', type=int, default=3, help='số câu nháp thử cho mỗi slot')
    p.add_argument('--no-explanation', action='store_true')
    p.add_argument('--context-chars', type=int, default=CONTEXT_CHARS)
    p.add_argument('--online-url', default=None,
                   help='http://127.0.0.1:8002/v1 — gọi máy chủ đang phục vụ adapter')
    p.add_argument('--online-model', default=None, help='tên model/adapter trên máy chủ đó')
    p.add_argument('--tokenizer', default=None, help='tokenizer cho chế độ online')
    p.add_argument('--temperature', type=float, default=0.7)
    p.add_argument('--max-tokens', type=int, default=2048)
    p.set_defaults(func=cmd_generate)

    args = ap.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()

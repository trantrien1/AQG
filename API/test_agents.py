"""Smoke test cho multi-agent pipeline.

Chạy:
    cd API
    python test_agents.py "Toán rời rạc 1 - 2016-compressed-pages-6.pdf"
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from pipeline import config as cfg
from pipeline.pdf_parser import parse_pdf_to_dataset
from pipeline.blueprint import build_blueprint, summary as bp_summary
from pipeline.llm_client import reset_tracker, get_tracker, BudgetExceeded
from pipeline.agents import OrchestratorAgent, PlanResponse


def main():
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else 'Toán rời rạc 1 - 2016-compressed-pages-6.pdf'
    num_questions = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    num_samples = int(sys.argv[3]) if len(sys.argv) > 3 else cfg.NUM_SAMPLES_PER_SLOT

    print(f'\n{"="*70}')
    print(f'MULTI-AGENT PIPELINE SMOKE TEST')
    print(f'{"="*70}')
    print(f'PDF       : {pdf_path}')
    print(f'Questions : {num_questions}')
    print(f'Samples   : {num_samples}')
    print(f'Budget    : 80k tokens, 60 calls')
    print()

    if not Path(pdf_path).exists():
        print(f'❌ PDF not found: {pdf_path}')
        return 1

    # Budget hạn chế để test không tốn nhiều
    reset_tracker(max_tokens=80_000, max_calls=60)

    # ---- 1. Parse PDF ----
    t0 = time.time()
    print(f'[1/3] Parsing PDF...')
    dataset = parse_pdf_to_dataset(pdf_path, target_chars=1000)
    n_chunks = sum(1 for k in dataset if k != 'metadata')
    print(f'      → {n_chunks} chunks ({time.time() - t0:.1f}s)')

    if n_chunks == 0:
        print('❌ Không trích được chunk nào')
        return 1

    # In topic của vài chunks để check fix topic_extraction
    print(f'\n  Topics (5 chunks đầu):')
    for i, (k, v) in enumerate([(k, v) for k, v in dataset.items() if k != 'metadata'][:5]):
        print(f'    {k}: {v.get("topic", "")[:80]}')

    # ---- 2. Build blueprint ----
    print(f'\n[2/3] Building blueprint ({num_questions} slots)...')
    slots = build_blueprint(dataset, num_questions=num_questions, seed=42)
    print(f'      → {len(slots)} slots')
    for s in slots:
        print(f'        {s["slot_id"]}: {s["cognitive_level"]:14s} '
              f'pattern={s["question_pattern"]:30s} doc={s["doc_id"]}')

    # ---- 3. Run OrchestratorAgent ----
    print(f'\n[3/3] Running OrchestratorAgent (multi-agent)...')
    print(f'      Phase 1: VerifierAgent (sequential, no LLM)')
    print(f'      Phase 2: CriticAgent (parallel × 4 workers, LLM)')
    print(f'      Phase 3: NLI filter (off cho test)')
    print()

    orchestrator = OrchestratorAgent(repair_attempts=1)

    def progress(ratio, msg, n_acc, n_rej):
        print(f'      [{ratio*100:5.1f}%] {msg}  (acc={n_acc}, rej={n_rej})')

    t0 = time.time()
    try:
        result = orchestrator.run(
            dataset=dataset,
            num_questions=num_questions,
            num_samples=num_samples,
            use_nli=False,
            progress_cb=progress,
            plan_resp=PlanResponse(slots=slots, summary=bp_summary(slots)),
            mode='advanced',
        )
    except BudgetExceeded as e:
        print(f'\n❌ Budget exceeded: {e}')
        return 1

    elapsed = time.time() - t0
    cost = get_tracker().report()

    print(f'\n{"="*70}')
    print(f'RESULTS')
    print(f'{"="*70}')
    print(f'Elapsed   : {elapsed:.1f}s')
    print(f'Tokens    : {cost["tokens"]:,} / {cost["max_tokens"]:,}')
    print(f'LLM calls : {cost["calls"]} / {cost["max_calls"]}')
    print(f'Accepted  : {len(result["questions"])} / {num_questions}')
    print(f'Rejected  : {len(result["rejected"])}')

    # Build records y như app.py để test full chain

    print(f'\n{"="*70}')
    print(f'ACCEPTED QUESTIONS')
    print(f'{"="*70}')
    for i, rec in enumerate(result['questions'], 1):
        v = rec['verification']
        j = rec['judging']
        verified_tag = (
            '✓ VERIFIED' if v['verified'] is True
            else '⚠ NEEDS_REVISION' if rec['review_status'] == 'needs_revision'
            else '○ no-verifier'
        )
        print(f'\n  [{i}] {verified_tag}  status={rec["review_status"]}')
        print(f'      slot      : {rec["blueprint_slot_id"]}')
        print(f'      topic     : {rec["topic"][:60]}')
        print(f'      pattern   : {rec.get("tags", [None, ""])[-1]}')
        print(f'      stem      : {rec["stem"][:120]}')
        print(f'      answer_key: {rec["answer_key"]}')
        print(f'      verifier  : engine={v.get("engine")} verified={v.get("verified")}')
        print(f'                  detail={(v.get("detail") or "")[:80]}')
        print(f'      grounding : {j.get("grounding")}')
        print(f'      quality   : {j.get("quality")}')
        # Đếm distractor có error_type
        n_with_et = sum(1 for o in rec['options']
                        if not o.get('is_answer') and o.get('error_type'))
        n_distractors = sum(1 for o in rec['options'] if o['key'] != rec['answer_key'])
        print(f'      distractor error_type: {n_with_et}/{n_distractors} có category')

    if result['rejected']:
        print(f'\n{"="*70}')
        print(f'REJECTED SLOTS')
        print(f'{"="*70}')
        for rec in result['rejected']:
            print(f'\n  {rec.get("blueprint_slot_id")} ({(rec.get("topic") or "")[:50]})')
            print(f'    attempts: {rec.get("attempts")}')
            for log in rec.get('reject_log', [])[-5:]:
                msg = log.get('message') if isinstance(log, dict) else str(log)
                print(f'    - {msg[:120]}')

    # Save raw output để inspect
    out_path = Path('test_agents_output.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({
            'questions': result['questions'],
            'rejected': result['rejected'],
            'cost': cost,
            'elapsed_seconds': elapsed,
        }, f, ensure_ascii=False, indent=2)
    print(f'\n→ Raw output saved: {out_path.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

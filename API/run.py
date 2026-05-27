"""CLI entry point for the multi-agent MCQ generation pipeline."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from pipeline import config as cfg
from pipeline.agents import (
    IngestionRequest,
    OrchestratorAgent,
    PlanRequest,
)
from pipeline.chunk_context_builder import attach_clean_contexts, build_clean_contexts
from pipeline.document_preprocessor import preprocess_dataset
from pipeline.llm_client import get_tracker, reset_tracker


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass


def _count_docs(dataset: Dict[str, Any]) -> int:
    return sum(
        1
        for k, v in dataset.items()
        if k != 'metadata' and isinstance(v, dict) and 'context' in v
    )


def _write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_input_dataset(path: str) -> Dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def _print_long_doc_report(report: Optional[Dict[str, Any]]) -> None:
    if not report or not report.get('is_long'):
        return
    print('\n[long-document]')
    print(f"  Warning: {report.get('warning')}")
    print(f"  chars={report.get('total_chars')} units={report.get('num_units')} "
          f"max_unit_chars={report.get('max_unit_chars')}")
    for step in report.get('steps', []):
        print(f'  - {step}')
    sections = report.get('sections') or []
    if sections:
        print('  Suggested sections:')
        for item in sections[:8]:
            pages = item.get('pages') or []
            page_text = f" pages={pages[:4]}" if pages else ''
            print(f"    * {item.get('topic')}{page_text}")

def _attach_clean_contexts(dataset: Dict[str, Any], source_name: str = '') -> Dict[str, Any]:
    meta = dataset.get('metadata') or {}
    if meta.get('clean_contexts', {}).get('available'):
        return dataset
    clean_contexts = build_clean_contexts(dataset, source_name=source_name or meta.get('source', ''))
    dataset = attach_clean_contexts(dataset, clean_contexts)
    dataset.setdefault('metadata', {})['clean_contexts_payload'] = clean_contexts.get('metadata', {})
    return dataset


def _maybe_preprocess_dataset(args: argparse.Namespace,
                              dataset: Dict[str, Any]) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    if args.no_long_doc_preprocess:
        return _attach_clean_contexts(dataset), None
    processed, report = preprocess_dataset(
        dataset,
        long_doc_chars=args.long_doc_chars,
        too_long_chars=args.too_long_doc_chars,
        max_units=args.max_context_units,
        section_filter=args.section_filter,
    )
    _print_long_doc_report(report)
    if report.get('requires_user_selection') and not args.allow_very_long:
        print('\nTài liệu vượt ngưỡng cho phép. Hãy chạy lại với --section-filter "<mục/chương>" '
              'để xử lý một phần trước, hoặc thêm --allow-very-long để hệ thống tự chọn các đoạn liên quan nhất.')
        sys.exit(2)
    return _attach_clean_contexts(processed), report


def _progress_printer():
    state = {'last_bucket': -1, 'last_msg': ''}

    def cb(ratio: float, msg: str, accepted: int, rejected: int) -> None:
        bucket = int(max(0.0, min(1.0, ratio)) * 20)
        important = ratio <= 0.02 or ratio >= 0.95 or msg != state['last_msg']
        if not important and bucket == state['last_bucket']:
            return
        state['last_bucket'] = bucket
        state['last_msg'] = msg
        print(f'[{ratio * 100:5.1f}%] {msg} | accepted={accepted} rejected={rejected}')

    return cb


def _prepare_dataset(
    args: argparse.Namespace,
    orchestrator: OrchestratorAgent,
) -> tuple[Dict[str, Any], int, Optional[str]]:
    """Load JSON input or parse PDF through IngestionAgent."""
    if args.pdf:
        pdf_path = Path(args.pdf)
        print(f'[0] IngestionAgent parsing PDF: {pdf_path}')
        if not pdf_path.exists():
            sys.exit(f'PDF không tồn tại: {pdf_path}')

        ing_resp = orchestrator.ingestion.run(IngestionRequest(
            pdf_path=str(pdf_path),
            target_chars=args.target_chars,
            filter_low_quality=not args.keep_low_quality_chunks,
            chunk_page_threshold=args.chunk_page_threshold,
            force_chunk=args.force_chunk,
            preprocess_long_documents=not args.no_long_doc_preprocess,
            long_doc_chars=args.long_doc_chars,
            too_long_doc_chars=args.too_long_doc_chars,
            max_context_units=args.max_context_units,
            section_filter=args.section_filter,
            allow_very_long=args.allow_very_long,
        ))
        _print_long_doc_report(ing_resp.preprocessing_report)
        if ing_resp.error == 'LONG_DOCUMENT_REQUIRES_SELECTION':
            print('\nTài liệu vượt ngưỡng cho phép. Hãy chạy lại với --section-filter "<mục/chương>" '
                  'để xử lý một phần trước, hoặc thêm --allow-very-long để hệ thống tự chọn các đoạn liên quan nhất.')
            sys.exit(2)
        if ing_resp.error:
            sys.exit(f'Ingestion failed: {ing_resp.error}')

        dataset = ing_resp.dataset
        n_docs = ing_resp.num_chunks
        save_path = args.save_chunks or 'data/extracted_chunks.json'
        _write_json(save_path, dataset)
        meta = dataset.get('metadata', {})
        print(
            f'    -> {n_docs} dataset unit(s), '
            f'mode={meta.get("chunking_mode", "unknown")}, '
            f'{meta.get("total_chars", 0)} chars'
        )
        print(f'    saved dataset: {save_path}')
        return dataset, n_docs, ing_resp.source_name

    dataset = _load_input_dataset(args.input)
    dataset, _ = _maybe_preprocess_dataset(args, dataset)
    n_docs = _count_docs(dataset)
    print(f'[1] Loaded {n_docs} chunks from {args.input}')
    return dataset, n_docs, dataset.get('metadata', {}).get('source')


def main() -> None:
    _configure_console_encoding()

    parser = argparse.ArgumentParser()
    parser.add_argument('--input', '-i', default='data/math_input.json',
                        help='Chunked JSON dataset; ignored when --pdf is set')
    parser.add_argument('--pdf', default=None,
                        help='PDF path; parsed by IngestionAgent before planning')
    parser.add_argument('--target-chars', type=int, default=1000,
                        help='Target chunk size when PDF is chunked')
    parser.add_argument('--chunk-page-threshold', type=int, default=100,
                        help='Only chunk PDFs with more pages than this threshold')
    parser.add_argument('--force-chunk', action='store_true',
                        help='Always chunk PDF, even when page count is under the threshold')
    parser.add_argument('--save-chunks', default=None,
                        help='Save parsed PDF dataset units to this JSON file')
    parser.add_argument('--chunks-only', action='store_true',
                        help='Only parse PDF and save chunks; do not call LLM')
    parser.add_argument('--keep-low-quality-chunks', action='store_true',
                        help='Do not filter low-quality chunks during PDF ingestion')
    parser.add_argument('--no-long-doc-preprocess', action='store_true',
                        help='Disable long-document warning, splitting, summarization, and relevance selection')
    parser.add_argument('--long-doc-chars', type=int, default=30000,
                        help='Character threshold for long-document preprocessing')
    parser.add_argument('--too-long-doc-chars', type=int, default=120000,
                        help='Character threshold that requires section selection unless --allow-very-long is set')
    parser.add_argument('--max-context-units', type=int, default=40,
                        help='Maximum preprocessed context units passed to generation')
    parser.add_argument('--section-filter', default=None,
                        help='Process only sections/chunks matching this text when a document is very long')
    parser.add_argument('--allow-very-long', action='store_true',
                        help='For very long documents, continue by selecting the most relevant units automatically')
    parser.add_argument('--output', '-o', default='output/questions_math.json')
    parser.add_argument('--num-questions', '-n', type=int, default=12)
    parser.add_argument('--mode', choices=['fast', 'advanced'],
                        default=cfg.DEFAULT_GENERATION_MODE,
                        help='fast (default): internal deterministic plan + merged generator; advanced: rich PlannerAgent flow')
    parser.add_argument('--num-samples', type=int, default=cfg.NUM_SAMPLES_PER_SLOT,
                        help='Candidate count generated per slot')
    parser.add_argument('--repair-attempts', type=int, default=cfg.NUM_REPAIR_ATTEMPTS)
    parser.add_argument('--seed', type=int, default=cfg.DETERMINISTIC_SEED)
    parser.add_argument('--token-budget', type=int, default=cfg.COST_BUDGET_TOKENS)
    parser.add_argument('--call-budget', type=int, default=cfg.COST_BUDGET_CALLS)
    parser.add_argument('--bloom-level', default='mixed',
                        choices=['mixed', 'Nhận biết', 'Thông hiểu', 'Vận dụng', 'Vận dụng cao'],
                        help='Bloom level: "mixed" (mặc định 25/35/30/10) hoặc lock 1 mức')
    parser.add_argument('--no-nli', action='store_true',
                        help='Skip optional NLI filter to reduce judge calls')
    parser.add_argument('--render-visuals', action='store_true',
                        help='Render visual specs to output/visuals after generation')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run ingestion and planning only; do not call LLM')
    args = parser.parse_args()

    if not cfg.has_llm_api_key() and not args.dry_run and not args.chunks_only:
        sys.exit(f'Missing LLM API key: {cfg.missing_llm_api_key_message()}')

    reset_tracker(max_tokens=args.token_budget, max_calls=args.call_budget)
    orchestrator = OrchestratorAgent(repair_attempts=args.repair_attempts)
    missing_skills = orchestrator.missing_skill_references()
    if missing_skills:
        sys.exit(f'Missing pipeline skill folders: {missing_skills}')

    dataset, n_docs, source_name = _prepare_dataset(args, orchestrator)

    if args.chunks_only:
        print('\n[--chunks-only] Stopping after IngestionAgent.')
        return

    # Build distribution từ --bloom-level
    bloom_targets = {
        'Nhận biết': 0.30, 'Thông hiểu': 0.50,
        'Vận dụng': 0.70, 'Vận dụng cao': 0.85,
    }
    if args.bloom_level == 'mixed':
        difficulty_distribution = None
    else:
        difficulty_distribution = [{
            'cognitive_level': args.bloom_level,
            'difficulty_target': bloom_targets[args.bloom_level],
            'fraction': 1.0,
        }]
        print(f'[bloom] tất cả {args.num_questions} câu sẽ ở mức "{args.bloom_level}"')

    plan_resp = None
    if args.mode == 'advanced':
        plan_resp = orchestrator.planner.run(PlanRequest(
            dataset=dataset,
            num_questions=args.num_questions,
            seed=args.seed,
            difficulty_distribution=difficulty_distribution,
        ))
        bp = plan_resp.summary
        print(f'[2] PlannerAgent blueprint: {bp["total"]} slots')
    else:
        bp = {'total': args.num_questions, 'by_cognitive_level': {}, 'by_pattern': {}, 'by_doc': {}}
        print(f'[2] Fast Mode: internal deterministic slots ({args.num_questions})')
    print(f'    by_level:   {bp["by_cognitive_level"]}')
    print(f'    by_pattern: {bp["by_pattern"]}')
    print(f'    dataset units used: {len(bp["by_doc"])}/{n_docs}')

    if args.dry_run:
        print('\n[DRY-RUN] Stopping before generation.')
        return

    out_dir = os.path.join(os.path.dirname(args.output) or '.', 'visuals') if args.render_visuals else None
    t_gen = time.time()
    result = orchestrator.run(
        dataset=dataset,
        num_questions=args.num_questions,
        num_samples=args.num_samples,
        use_nli=not args.no_nli,
        seed=args.seed,
        out_dir=out_dir,
        progress_cb=_progress_printer(),
        difficulty_distribution=difficulty_distribution,
        plan_resp=plan_resp,
        mode=args.mode,
    )
    elapsed = time.time() - t_gen

    out = {
        'metadata': {
            'architecture': 'fast_mode' if args.mode == 'fast' else 'multi_agent',
            'mode': args.mode,
            'agents': (
                [
                    'IngestionAgent', 'QuestionGeneratorAgent',
                    'VerifierAgent', 'FormatterAgent', 'RendererAgent',
                ] if args.mode == 'fast' else [
                    'IngestionAgent', 'PlannerAgent', 'QuestionWriterAgent',
                    'DistractorAgent', 'VerifierAgent', 'CriticAgent',
                    'RefinerAgent', 'FormatterAgent', 'RendererAgent',
                ]
            ),
            'subject': cfg.DEFAULT_SUBJECT,
            'source': source_name,
            'num_chunks': n_docs,
            'llm_provider': cfg.LLM_PROVIDER,
            'generator_model': cfg.GENERATOR_MODEL,
            'judge_model': cfg.JUDGE_MODEL,
            'seed': args.seed,
            'blueprint_summary': result['blueprint_summary'],
            'cost': result.get('cost') or get_tracker().report(),
            'attempts': result.get('attempts'),
            'duration_seconds': elapsed,
            'stopped_reason': result.get('stopped_reason'),
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        },
        'questions': result['questions'],
        'rejected': result['rejected'],
    }
    _write_json(args.output, out)

    print()
    print(f'✓ Saved {args.output}')
    print(f'  Accepted: {len(result["questions"])} / {bp["total"]} '
          f'({100 * len(result["questions"]) / max(1, bp["total"]):.0f}%)')
    print(f'  Rejected: {len(result["rejected"])}')
    if result.get('stopped_reason'):
        print(f'  Stopped: {result["stopped_reason"]}')
    print(f'  Cost: {out["metadata"]["cost"]}')

    render_result = result.get('render_result')
    if render_result:
        print(f'  Rendered visuals: {render_result.rendered_count}, '
              f'skipped: {render_result.skipped_count}')
        if render_result.error:
            print(f'  Render error: {render_result.error}')


if __name__ == '__main__':
    main()

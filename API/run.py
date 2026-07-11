"""CLI entry point for Direct_PDF_Mode MCQ generation."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from pipeline import config as cfg
from pipeline.direct_pdf.runner import run_direct_pdf


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass


_BLOOM_TARGETS: Dict[str, float] = {
    'Nhận biết': 0.30,
    'Thông hiểu': 0.50,
    'Vận dụng': 0.70,
    'Vận dụng cao': 0.85,
}


def _bloom_distribution(level: str) -> List[Dict[str, Any]]:
    if level == 'mixed':
        return [dict(item) for item in cfg.DEFAULT_DIFFICULTY_DISTRIBUTION]
    return [{
        'cognitive_level': level,
        'difficulty_target': _BLOOM_TARGETS[level],
        'fraction': 1.0,
    }]


def main() -> None:
    _configure_console_encoding()

    parser = argparse.ArgumentParser(
        description='Generate MCQs by sending the uploaded PDF directly to the model.',
    )
    parser.add_argument('--pdf', required=True, help='PDF path to read directly')
    parser.add_argument('--output', '-o', default='output/questions_direct_pdf.json')
    parser.add_argument('--num-questions', '-n', type=int, default=12)
    parser.add_argument(
        '--bloom-level',
        default='mixed',
        choices=['mixed', 'Nhận biết', 'Thông hiểu', 'Vận dụng', 'Vận dụng cao'],
        help='Bloom level lock, or mixed for automatic distribution',
    )
    parser.add_argument(
        '--direct-pdf',
        action='store_true',
        help='Kept for backward compatibility; Direct_PDF_Mode is now the only CLI mode.',
    )
    args = parser.parse_args()

    if not os.path.exists(args.pdf):
        sys.exit(f'PDF không tồn tại: {args.pdf}')
    if not cfg.has_llm_api_key():
        sys.exit(f'Missing LLM API key: {cfg.missing_llm_api_key_message()}')

    summary = run_direct_pdf(
        pdf_path=args.pdf,
        requested_count=args.num_questions,
        output_path=args.output,
        bloom_distribution=_bloom_distribution(args.bloom_level),
    )
    print('[Direct_PDF_Mode] summary:')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get('error_code'):
        sys.exit(f'Direct_PDF_Mode error: {summary["error_code"]}')


if __name__ == '__main__':
    main()

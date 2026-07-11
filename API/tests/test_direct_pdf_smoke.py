from __future__ import annotations

import json

from pipeline.direct_pdf.generator import parse_direct_pdf_response
from pipeline.direct_pdf.ingestion import PdfIngestionComponent


def test_direct_pdf_modules_import_without_chunk_pipeline():
    from pipeline.direct_pdf.generator import DirectPdfQuestionGenerator
    from pipeline.direct_pdf.agents.pdf_orchestrator import DirectPdfOrchestrator
    from web.app import app

    assert DirectPdfQuestionGenerator is not None
    assert DirectPdfOrchestrator is not None
    assert app.title == 'AIED-MCQ Backend'

def test_mixed_bloom_uses_default_distribution():
    from pipeline import config as cfg
    from pipeline.direct_pdf.agents.pdf_orchestrator import _pick_cognitive
    from web.jobs import _bloom_distribution

    distribution = _bloom_distribution('mixed', 10)
    expected_levels = {
        item['cognitive_level']
        for item in cfg.DEFAULT_DIFFICULTY_DISTRIBUTION
    }

    assert distribution == cfg.DEFAULT_DIFFICULTY_DISTRIBUTION
    picked_levels = {_pick_cognitive(distribution, i) for i in range(10)}
    assert expected_levels.issubset(picked_levels)

def test_difficulty_level_overrides_mixed_distribution():
    from web.jobs import _bloom_distribution

    easy = _bloom_distribution('mixed', 5, 'easy')
    medium = _bloom_distribution('mixed', 5, 'medium')
    hard = _bloom_distribution('mixed', 5, 'hard')

    assert easy == [{'cognitive_level': 'Nhận biết', 'difficulty_target': 0.30, 'fraction': 1.0}]
    assert medium == [{'cognitive_level': 'Thông hiểu', 'difficulty_target': 0.50, 'fraction': 1.0}]
    assert hard == [{'cognitive_level': 'Vận dụng', 'difficulty_target': 0.70, 'fraction': 1.0}]


def test_parse_direct_pdf_response_accepts_valid_mcq_json():
    raw = {
        'questions': [{
            'question': 'Giá trị của 2 + 3 là bao nhiêu?',
            'options': [
                {'key': 'A', 'text': '4'},
                {'key': 'B', 'text': '5'},
                {'key': 'C', 'text': '6'},
                {'key': 'D', 'text': '7'},
            ],
            'answer_key': 'B',
            'explanation': 'Vì 2 + 3 = 5.',
            'detailed_solution': {
                'steps': [{'title': 'Tính tổng', 'content': '2 + 3 = 5'}],
                'final_answer': '5',
            },
            'source_quote': 'Phép cộng hai số tự nhiên được thực hiện theo quy tắc cộng thông thường.',
            'verifier_payload': {'type': 'numeric_eval', 'payload': {'expr': '2+3', 'expected_numeric': 5}},
        }],
    }

    questions, parse_errors, verify_failures = parse_direct_pdf_response(json.dumps(raw, ensure_ascii=False))

    assert parse_errors == 0
    assert verify_failures == 0
    assert len(questions) == 1
    assert questions[0]['answer_key'] in {'A', 'B', 'C', 'D'}


def test_pdf_validation_reports_missing_file():
    result = PdfIngestionComponent().validate('does-not-exist.pdf')

    assert result.ok is False
    assert result.error_code == 'path_not_found'

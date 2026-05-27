"""Long-document preprocessing orchestrated through reusable skills."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .skills.document import (
    DEFAULT_LONG_DOC_CHARS,
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_UNITS,
    DEFAULT_TARGET_CHARS,
    DEFAULT_TOO_LONG_CHARS,
    ChunkingSkill,
    DocumentClassificationSkill,
    KnowledgeExtractionSkill,
    LongDocumentDetectionSkill,
    NoiseRemovalSkill,
    RelevanceFilteringSkill,
    unit_search_text,
)


def analyze_dataset(dataset: Dict[str, Any],
                    long_doc_chars: int = DEFAULT_LONG_DOC_CHARS,
                    too_long_chars: int = DEFAULT_TOO_LONG_CHARS) -> Dict[str, Any]:
    return LongDocumentDetectionSkill(
        long_doc_chars=long_doc_chars,
        too_long_chars=too_long_chars,
    ).run(dataset)


def preprocess_dataset(
    dataset: Dict[str, Any],
    *,
    long_doc_chars: int = DEFAULT_LONG_DOC_CHARS,
    too_long_chars: int = DEFAULT_TOO_LONG_CHARS,
    target_chars: int = DEFAULT_TARGET_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_units: int = DEFAULT_MAX_UNITS,
    section_filter: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return `(processed_dataset, report)`.

    The report is designed for UI/API feedback: warnings, steps taken, selected
    context units, and suggested sections when the document is very long.
    """
    classification = DocumentClassificationSkill().run(dataset)
    analysis = analyze_dataset(dataset, long_doc_chars, too_long_chars)
    report: Dict[str, Any] = {
        **analysis,
        **classification,
        'requires_user_selection': False,
        'skills_used': [
            'document-classification',
            'long-document-detection',
        ],
        'steps': [],
        'sections': [],
        'selected_units': [],
    }
    if not analysis['is_long']:
        report['steps'].append('skipped: document below long-document threshold')
        dataset.setdefault('metadata', {})['long_document'] = report
        return dataset, report

    if analysis['is_too_long'] and not section_filter:
        report['requires_user_selection'] = True

    chunking = ChunkingSkill(target_chars=target_chars, max_chars=max_chars)
    split_units = chunking.run(dataset)
    report['skills_used'].append('chunking')
    report['steps'].append(f'split into {len(split_units)} candidate units')

    noise_removal = NoiseRemovalSkill()
    extraction = KnowledgeExtractionSkill()
    cleaned_units: List[Dict[str, Any]] = []
    for unit in split_units:
        context = noise_removal.run(unit['context'])
        if len(context.strip()) < 120:
            continue
        unit = {**unit, 'context': context}
        unit.update(extraction.run(context))
        cleaned_units.append(unit)
    report['skills_used'].extend(['noise-removal', 'knowledge-extraction'])
    report['steps'].append(f'cleaned and summarized {len(cleaned_units)} units')

    if section_filter:
        filtered = [
            u for u in cleaned_units
            if section_filter.lower() in unit_search_text(u).lower()
        ]
        if filtered:
            cleaned_units = filtered
            report['steps'].append(f'applied section filter: {section_filter}')

    relevance = RelevanceFilteringSkill(
        max_units=max_units,
        section_filter=section_filter,
    )
    selected = relevance.run(cleaned_units)
    report['skills_used'].append('relevance-filtering')
    report['selected_units'] = [u['doc_id'] for u in selected]
    report['sections'] = _section_suggestions(cleaned_units)
    report['steps'].append(f'selected {len(selected)} relevant units for generation')

    processed = _units_to_dataset(dataset, selected, report)
    return processed, report


def _section_suggestions(units: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    suggestions: List[Dict[str, Any]] = []
    seen = set()
    for unit in units:
        topic = (unit.get('topic') or '').strip()
        if not topic or topic in seen:
            continue
        seen.add(topic)
        suggestions.append({
            'topic': topic,
            'pages': unit.get('pages', []),
            'source_doc_id': unit.get('source_doc_id'),
        })
        if len(suggestions) >= limit:
            break
    return suggestions


def _units_to_dataset(original: Dict[str, Any],
                      units: List[Dict[str, Any]],
                      report: Dict[str, Any]) -> Dict[str, Any]:
    metadata = dict(original.get('metadata') or {})
    metadata['long_document'] = report
    metadata['num_units'] = len(units)
    metadata['num_chunks'] = len(units)
    metadata['total_chars'] = sum(len(u['context']) for u in units)
    metadata['preprocessed'] = True
    out: Dict[str, Any] = {'metadata': metadata}
    for unit in units:
        context_parts = [
            f"Summary: {unit.get('summary', '')}",
            'Key extracts:',
            *[f"- {item}" for item in unit.get('key_extracts') or []],
            'Context:',
            unit['context'],
        ]
        out[unit['doc_id']] = {
            'topic': unit['topic'],
            'pages': unit.get('pages', []),
            'context': '\n'.join(context_parts).strip(),
            'source_doc_id': unit.get('source_doc_id'),
            'summary': unit.get('summary', ''),
            'key_extracts': unit.get('key_extracts') or [],
        }
    return out

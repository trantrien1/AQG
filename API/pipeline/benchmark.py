"""Pipeline benchmark — compute production metrics from a result.json.

Used to compare pipeline-vs-pipeline (e.g. before/after a config change).
Reads only the persisted artifacts in `runs/<job_id>/`, no LLM calls.

Metrics produced:
  - accepted_count / rejected_count / acceptance_rate
  - llm_calls_per_question
  - avg_generation_time_per_question
  - avg_attempts_per_accepted
  - reject_reason_distribution
  - verifier_pass_rate
  - grounding_avg / quote_score_avg / quality_avg
  - duplicate_rate (fraction of rejects classified `duplicate_question`)
  - fast_accept_rate (fraction of accepted via the verifier short-answer path)
  - explanation_quality_avg (heuristic: 1.0 if record has detailed_solution.steps)
  - user_instruction_alignment_avg (avg of judging.quality_traits.user_instruction_alignment if present)

Usage:
    python -m pipeline.benchmark <job_id_a> [<job_id_b> ...]
    # or import:
    from pipeline.benchmark import benchmark_job, compare
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _runs_root() -> Path:
    here = Path(__file__).resolve().parent.parent
    return here / 'runs'


def _read_result(job_id: str, runs_root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    root = runs_root or _runs_root()
    path = root / job_id / 'result.json'
    if not path.exists():
        return None
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _avg(values: Iterable[float]) -> Optional[float]:
    items = [v for v in values if v is not None]
    if not items:
        return None
    return sum(items) / len(items)


def benchmark(result: Dict[str, Any]) -> Dict[str, Any]:
    """Compute metrics for a single result payload."""
    questions: List[Dict[str, Any]] = result.get('questions') or []
    rejected: List[Dict[str, Any]] = result.get('rejected') or []
    accepted_count = len(questions)
    rejected_count = len(rejected)
    total = accepted_count + rejected_count

    # Reject distribution — prefer reject_reason_code, fall back to reject_log[*].reason_code.
    reason_dist: Counter = Counter()
    for r in rejected:
        code = r.get('reject_reason_code')
        if not code:
            log = r.get('reject_log') or []
            for entry in reversed(log):
                if isinstance(entry, dict) and entry.get('reason_code'):
                    code = entry['reason_code']
                    break
        reason_dist[code or 'unknown'] += 1

    # Verifier pass rate over accepted records.
    verifier_pass = sum(
        1 for q in questions
        if (q.get('verification') or {}).get('verified') is True
    )

    fast_accepts = sum(
        1 for q in questions
        if str((q.get('judging') or {}).get('quality_traits', {}).get(
            'clarity', {}).get('rationale', '')).lower().startswith('fast-path')
    )

    grounding_avg = _avg(
        (q.get('judging') or {}).get('grounding') for q in questions
    )
    quality_avg = _avg(
        (q.get('judging') or {}).get('quality') for q in questions
    )
    quote_scores = []
    for q in questions:
        # Production quote_score lives on the candidate; the schema only
        # surfaces source.quote_in_context (bool). When available via earlier
        # judging fields, propagate it; else fall back to bool→{0,1}.
        in_ctx = (q.get('source') or {}).get('quote_in_context')
        if isinstance(in_ctx, bool):
            quote_scores.append(1.0 if in_ctx else 0.0)
    quote_score_avg = _avg(quote_scores)

    duplicate_rejects = reason_dist.get('duplicate_question', 0) + reason_dist.get('duplicate', 0)
    duplicate_rate = (
        duplicate_rejects / rejected_count
        if rejected_count else 0.0
    )

    avg_attempts = _avg(
        (q.get('_attempts') or q.get('attempts')) for q in questions
    )

    explanation_quality = []
    for q in questions:
        ds = q.get('detailed_solution') or {}
        steps = ds.get('steps') or []
        explanation_quality.append(1.0 if len(steps) >= 2 else 0.0)
    explanation_quality_avg = _avg(explanation_quality)

    instruction_alignment = []
    for q in questions:
        traits = (q.get('judging') or {}).get('quality_traits') or {}
        score = traits.get('user_instruction_alignment', {})
        if isinstance(score, dict) and isinstance(score.get('score'), (int, float)):
            instruction_alignment.append(float(score['score']))
    instruction_alignment_avg = _avg(instruction_alignment)

    metadata = result.get('metadata') or {}
    cost = metadata.get('cost') or {}
    total_calls = cost.get('calls')
    if total_calls is None:
        total_calls = cost.get('total_calls')
    duration_seconds = metadata.get('duration_seconds')
    return {
        'accepted_count': accepted_count,
        'rejected_count': rejected_count,
        'total_attempted': total,
        'acceptance_rate': (accepted_count / total) if total else 0.0,
        'llm_calls_per_question': (
            float(total_calls) / accepted_count
            if accepted_count and isinstance(total_calls, (int, float)) else None
        ),
        'avg_generation_time_per_question': (
            float(duration_seconds) / accepted_count
            if accepted_count and isinstance(duration_seconds, (int, float)) else None
        ),
        'avg_attempts_per_accepted': avg_attempts,
        'reject_reason_distribution': dict(reason_dist),
        'verifier_pass_rate': (verifier_pass / accepted_count) if accepted_count else 0.0,
        'fast_accept_rate': (fast_accepts / accepted_count) if accepted_count else 0.0,
        'grounding_avg': grounding_avg,
        'quote_score_avg': quote_score_avg,
        'quality_avg': quality_avg,
        'duplicate_rate': duplicate_rate,
        'explanation_quality_avg': explanation_quality_avg,
        'user_instruction_alignment_avg': instruction_alignment_avg,
        'stopped_reason': metadata.get('stopped_reason'),
        'cost_total_tokens': cost.get('tokens', cost.get('total_tokens')),
        'cost_total_calls': total_calls,
        'duration_seconds': duration_seconds,
    }


def benchmark_job(job_id: str, runs_root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Read runs/<job_id>/result.json and run benchmark()."""
    result = _read_result(job_id, runs_root=runs_root)
    if result is None:
        return None
    metrics = benchmark(result)
    metrics['job_id'] = job_id
    return metrics


def compare(metrics_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Side-by-side comparison of two or more metric dicts.

    Returns:
        {
          "jobs": ["abc", "def"],
          "rows": [{"metric": "acceptance_rate", "values": [0.12, 0.78], "delta": +0.66}, ...]
        }
    """
    if not metrics_list:
        return {'jobs': [], 'rows': []}
    jobs = [m.get('job_id', f'job{i}') for i, m in enumerate(metrics_list)]
    keys = (
        'accepted_count', 'rejected_count', 'acceptance_rate',
        'llm_calls_per_question', 'avg_generation_time_per_question',
        'avg_attempts_per_accepted', 'verifier_pass_rate', 'fast_accept_rate',
        'grounding_avg', 'quote_score_avg', 'quality_avg', 'duplicate_rate',
        'explanation_quality_avg', 'user_instruction_alignment_avg',
        'cost_total_tokens', 'cost_total_calls',
    )
    rows = []
    for k in keys:
        values = [m.get(k) for m in metrics_list]
        # delta = last - first (only when both numeric).
        delta = None
        if (
            isinstance(values[0], (int, float))
            and isinstance(values[-1], (int, float))
        ):
            delta = values[-1] - values[0]
        rows.append({'metric': k, 'values': values, 'delta': delta})
    return {'jobs': jobs, 'rows': rows}


def _print_human(metrics_list: List[Dict[str, Any]]) -> None:
    """Render to stdout. ASCII only; safe for any terminal."""
    cmp = compare(metrics_list)
    job_header = ' | '.join(f'{j:>16}' for j in cmp['jobs'])
    print(f'{"metric":<32} | {job_header} | delta')
    print('-' * (32 + 3 + len(job_header) + 8))
    for row in cmp['rows']:
        vals = ' | '.join(_fmt_value(v) for v in row['values'])
        delta = _fmt_value(row['delta']) if row['delta'] is not None else ''
        print(f'{row["metric"]:<32} | {vals} | {delta}')


def _fmt_value(v: Any) -> str:
    if v is None:
        return f'{"-":>16}'
    if isinstance(v, float):
        return f'{v:>16.4f}'
    return f'{v:>16}'


def main(argv: List[str]) -> int:
    if not argv:
        print('usage: python -m pipeline.benchmark <job_id> [<job_id_2> ...]')
        return 2
    metrics: List[Dict[str, Any]] = []
    for job_id in argv:
        m = benchmark_job(job_id)
        if m is None:
            print(f'WARN: no result.json for job {job_id}')
            continue
        metrics.append(m)
    if not metrics:
        return 1
    _print_human(metrics)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

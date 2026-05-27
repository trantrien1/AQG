"""Smart Practice — interactive practice sessions over a generated bank.

State per session lives at `runs/<job_id>/practice/<session_id>.json`:

    {
      "session_id": "...",
      "job_id": "...",
      "created_at": "...",
      "current_question_id": "q_2026_xxx",
      "served": ["q_..."],            # ids already shown
      "history": [
        {
          "question_id": "...",
          "topic": "...",
          "skill": "...",
          "difficulty": "Vận dụng",
          "answer_chosen": "B",
          "correct_key": "C",
          "is_correct": false,
          "feedback": "like" | "dislike" | null,
          "answered_at": "..."
        }
      ],
      "stats": {
        "answered": 12,
        "correct": 8,
        "streak": 3,
        "by_topic": {"đạo hàm": {"answered": 4, "correct": 2}, ...}
      }
    }

Adaptive next-question rules (see `pick_next`):
  - On a wrong answer: prefer same topic/skill, ≤ current difficulty, and try to
    pick a question that targets a similar misconception.
  - On a correct streak ≥ 2: bump to a higher Bloom band when available.
  - Otherwise: round-robin across topics not yet seen.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


_BLOOM_ORDER = ['Nhận biết', 'Thông hiểu', 'Vận dụng', 'Vận dụng cao']


def _bloom_index(level: Optional[str]) -> int:
    if not level:
        return 1
    try:
        return _BLOOM_ORDER.index(level)
    except ValueError:
        return 1


# ----------------------------------------------------------------------
# Filesystem helpers — match `web.store` conventions but isolated here so
# this module is import-safe from CLI/test contexts.
# ----------------------------------------------------------------------

def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tmp_', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _practice_dir(job_dir: Path) -> Path:
    return job_dir / 'practice'


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


# ----------------------------------------------------------------------
# Session lifecycle
# ----------------------------------------------------------------------

def new_session_id() -> str:
    return secrets.token_hex(6)


def start_session(job_dir: Path, questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a new practice session over the given accepted questions."""
    if not questions:
        raise ValueError('practice requires at least one accepted question')
    sid = new_session_id()
    first = pick_next(questions=questions, served=[], history=[])
    session = {
        'session_id': sid,
        'created_at': _now(),
        'current_question_id': first.get('question_id') if first else None,
        'served': [first['question_id']] if first else [],
        'history': [],
        'stats': {
            'answered': 0,
            'correct': 0,
            'streak': 0,
            'by_topic': {},
        },
    }
    _atomic_write(_practice_dir(job_dir) / f'{sid}.json', session)
    return session


def get_session(job_dir: Path, session_id: str) -> Optional[Dict[str, Any]]:
    return _read_json(_practice_dir(job_dir) / f'{session_id}.json')


def list_sessions(job_dir: Path) -> List[Dict[str, Any]]:
    pdir = _practice_dir(job_dir)
    if not pdir.exists():
        return []
    out: List[Dict[str, Any]] = []
    for p in pdir.iterdir():
        if p.suffix != '.json':
            continue
        s = _read_json(p)
        if s:
            out.append({
                'session_id': s.get('session_id'),
                'created_at': s.get('created_at'),
                'answered': (s.get('stats') or {}).get('answered'),
                'correct': (s.get('stats') or {}).get('correct'),
            })
    out.sort(key=lambda s: s.get('created_at', ''), reverse=True)
    return out


# ----------------------------------------------------------------------
# Answering + feedback
# ----------------------------------------------------------------------

def _question_by_id(questions: List[Dict[str, Any]], qid: str) -> Optional[Dict[str, Any]]:
    for q in questions:
        if q.get('question_id') == qid:
            return q
    return None


def submit_answer(
    job_dir: Path, session_id: str, question_id: str, answer_key: str,
    questions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Record an answer; returns the verdict + the same-question explanation."""
    session = get_session(job_dir, session_id)
    if session is None:
        raise ValueError('session not found')
    if session.get('current_question_id') and session['current_question_id'] != question_id:
        raise ValueError('answer does not match current question')

    q = _question_by_id(questions, question_id)
    if q is None:
        raise ValueError(f'question {question_id} not in this job')

    correct_key = q.get('answer_key')
    is_correct = (answer_key == correct_key)

    explanation = {
        'why_correct': q.get('why_correct') or q.get('explanation_correct') or '',
        'detailed_solution': q.get('detailed_solution') or {},
        'why_others_wrong': q.get('why_others_wrong') or [
            {'option': k, 'reason': v}
            for k, v in (q.get('explanation_per_distractor') or {}).items()
        ],
    }

    history_entry = {
        'question_id': question_id,
        'topic': q.get('topic') or '',
        'skill': (q.get('kc_ids') or [None])[0] if q.get('kc_ids') else None,
        'difficulty': q.get('cognitive_level') or '',
        'answer_chosen': answer_key,
        'correct_key': correct_key,
        'is_correct': is_correct,
        'feedback': None,
        'answered_at': _now(),
    }
    session['history'].append(history_entry)

    stats = session.setdefault('stats', {})
    stats['answered'] = stats.get('answered', 0) + 1
    if is_correct:
        stats['correct'] = stats.get('correct', 0) + 1
        stats['streak'] = stats.get('streak', 0) + 1
    else:
        stats['streak'] = 0

    by_topic = stats.setdefault('by_topic', {})
    bt = by_topic.setdefault(history_entry['topic'] or 'unknown',
                             {'answered': 0, 'correct': 0})
    bt['answered'] += 1
    if is_correct:
        bt['correct'] += 1

    session['current_question_id'] = None
    _atomic_write(_practice_dir(job_dir) / f'{session_id}.json', session)
    return {
        'is_correct': is_correct,
        'correct_key': correct_key,
        'explanation': explanation,
        'session_stats': stats,
    }


def submit_feedback(
    job_dir: Path, session_id: str, question_id: str, feedback: str,
) -> Dict[str, Any]:
    """Attach a like/dislike to the most recent history entry of this question."""
    if feedback not in ('like', 'dislike'):
        raise ValueError("feedback must be 'like' or 'dislike'")
    session = get_session(job_dir, session_id)
    if session is None:
        raise ValueError('session not found')
    history = session.get('history') or []
    for entry in reversed(history):
        if entry.get('question_id') == question_id:
            entry['feedback'] = feedback
            break
    else:
        raise ValueError('question not in session history')
    _atomic_write(_practice_dir(job_dir) / f'{session_id}.json', session)
    return {'ok': True}


# ----------------------------------------------------------------------
# Adaptive next-question selection
# ----------------------------------------------------------------------

def pick_next(
    questions: List[Dict[str, Any]],
    served: List[str],
    history: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the next question to serve, or None if the bank is exhausted.

    Algorithm:
      1. Prefer not-yet-served questions.
      2. After a wrong answer: same topic OR same skill, difficulty ≤ last.
      3. On streak ≥ 2: try to step up Bloom band.
      4. Otherwise: round-robin across topics, prefer topic least-seen so far.
    """
    pool = [q for q in questions if q.get('question_id') not in set(served)]
    if not pool:
        return None

    last = history[-1] if history else None
    streak = 0
    for entry in reversed(history):
        if entry.get('is_correct'):
            streak += 1
        else:
            break

    def _score(q: Dict[str, Any]) -> tuple:
        # Smaller-first by (priority_bucket, then small tie-breakers).
        topic = (q.get('topic') or '').lower()
        diff_idx = _bloom_index(q.get('cognitive_level'))
        if last and not last.get('is_correct'):
            same_topic = topic == (last.get('topic') or '').lower()
            same_skill = False
            last_skill = (last.get('skill') or '')
            if last_skill and last_skill in (q.get('kc_ids') or []):
                same_skill = True
            last_diff = _bloom_index(last.get('difficulty'))
            tighter = diff_idx <= last_diff
            return (
                0 if same_topic else (1 if same_skill else 2),
                0 if tighter else 1,
                diff_idx,
            )
        if streak >= 2:
            # Reward harder questions and rotate topics.
            seen = sum(
                1 for e in history if (e.get('topic') or '').lower() == topic
            )
            return (
                -diff_idx,    # prefer higher Bloom (more negative wins after sort)
                seen,         # prefer fresh topics
                0,
            )
        # Default: prefer least-seen topic, even Bloom mix.
        seen = sum(
            1 for e in history if (e.get('topic') or '').lower() == topic
        )
        return (seen, abs(diff_idx - 1), 0)

    pool.sort(key=_score)
    return pool[0]


def next_question(
    job_dir: Path, session_id: str, questions: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Pick + persist the next question. Returns the question or None."""
    session = get_session(job_dir, session_id)
    if session is None:
        raise ValueError('session not found')
    served = session.get('served') or []
    history = session.get('history') or []
    nxt = pick_next(questions=questions, served=served, history=history)
    if nxt is None:
        session['current_question_id'] = None
        _atomic_write(_practice_dir(job_dir) / f'{session_id}.json', session)
        return None
    qid = nxt.get('question_id')
    served.append(qid)
    session['served'] = served
    session['current_question_id'] = qid
    _atomic_write(_practice_dir(job_dir) / f'{session_id}.json', session)
    return nxt


# ----------------------------------------------------------------------
# Convenience: question stripped of answer for serving to the UI
# ----------------------------------------------------------------------

def public_question(q: Dict[str, Any]) -> Dict[str, Any]:
    """Strip answer/explanation fields the UI shouldn't see before answering."""
    return {
        'question_id': q.get('question_id'),
        'topic': q.get('topic'),
        'cognitive_level': q.get('cognitive_level'),
        'question_type': q.get('question_type'),
        'stem': q.get('stem'),
        'options': [
            {'key': o.get('key'), 'text': o.get('text')}
            for o in (q.get('options') or [])
        ],
        'visual': q.get('visual'),
        'hint': q.get('hint'),
    }

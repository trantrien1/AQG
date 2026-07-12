"""Local SQLite question bank with duplicate detection.

This is intentionally local-first: no users, roles, or audit tables.  It stores
accepted generated questions so teachers can build reusable banks across jobs.
"""
from __future__ import annotations

import json
import math
import re
import secrets
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pipeline import config as cfg
from pipeline.llm_client import call_llm, get_embeddings

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / 'data'
DB_PATH = DATA_DIR / 'question_bank.db'

EXACT_THRESHOLD = 1.0
NEAR_THRESHOLD = 0.85
SEMANTIC_THRESHOLD = 0.82


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _new_id(prefix: str) -> str:
    return f'{prefix}_{secrets.token_hex(6)}'


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS banks (
            bank_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bank_questions (
            bank_question_id TEXT PRIMARY KEY,
            bank_id TEXT NOT NULL REFERENCES banks(bank_id) ON DELETE CASCADE,
            original_question_id TEXT,
            source_job_id TEXT,
            source_pdf_name TEXT,
            question_json TEXT NOT NULL,
            stem_norm TEXT NOT NULL,
            answer_norm TEXT NOT NULL,
            semantic_text TEXT NOT NULL,
            embedding_json TEXT,
            source_pages TEXT,
            source_quote TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_bank_questions_bank
            ON bank_questions(bank_id);
        CREATE INDEX IF NOT EXISTS idx_bank_questions_stem
            ON bank_questions(bank_id, stem_norm);
        """
    )


def _row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return dict(row)


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize('NFD', text)
    return ''.join(ch for ch in decomposed if unicodedata.category(ch) != 'Mn')


def normalize_text(text: Any) -> str:
    value = str(text or '').lower()
    value = value.replace('đ', 'd')
    value = _strip_accents(value)
    value = re.sub(r'\\\(|\\\)|\$|\\[,!;]', ' ', value)
    value = re.sub(r'\\[a-zA-Z]+', ' ', value)
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def _option_answer_text(question: Dict[str, Any]) -> str:
    answer_key = question.get('answer_key')
    for option in question.get('options') or []:
        if option.get('key') == answer_key:
            return str(option.get('text') or '')
    return str(question.get('answer') or question.get('answer_text') or '')


def semantic_text(question: Dict[str, Any]) -> str:
    source = question.get('source') or {}
    parts = [
        question.get('stem') or question.get('question') or '',
        _option_answer_text(question),
        question.get('topic') or '',
        question.get('short_explanation') or question.get('explanation') or question.get('why_correct') or '',
        source.get('quote') if isinstance(source, dict) else '',
    ]
    return '\n'.join(str(p or '') for p in parts if p)


def _question_summary(question: Dict[str, Any]) -> Dict[str, Any]:
    source = question.get('source') or {}
    pages = source.get('pages') if isinstance(source, dict) else None
    quote = source.get('quote') if isinstance(source, dict) else ''
    return {
        'original_question_id': question.get('question_id'),
        'stem_norm': normalize_text(question.get('stem') or question.get('question')),
        'answer_norm': normalize_text(_option_answer_text(question)),
        'semantic_text': semantic_text(question),
        'source_pages': json.dumps(pages or [], ensure_ascii=False),
        'source_quote': str(quote or ''),
    }


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _tokens(text: str) -> set[str]:
    return {t for t in normalize_text(text).split() if len(t) > 1}


def _jaccard(a: str, b: str) -> float:
    ta = _tokens(a)
    tb = _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _sequence_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _load_embedding(value: Any) -> Optional[List[float]]:
    if not value:
        return None
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, list):
        return None
    out: List[float] = []
    for item in data:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            return None
    return out


def _embedding_for_text(text: str) -> Tuple[Optional[List[float]], Optional[str]]:
    # GEMINI_API_KEY tự bật đường embedding Gemini (get_embeddings ưu tiên nó),
    # nên không đòi hỏi key của provider chat trong trường hợp đó.
    if not getattr(cfg, 'GEMINI_API_KEY', '') and not cfg.has_llm_api_key():
        return None, cfg.missing_llm_api_key_message()
    try:
        embeddings = get_embeddings([text])
    except Exception as exc:
        return None, str(exc)
    if not embeddings:
        return None, 'embedding provider returned no vector'
    return [float(v) for v in embeddings[0]], None


def _backfill_embeddings(
    conn: sqlite3.Connection,
    rows: List[Dict[str, Any]],
    max_rows: int = 200,
) -> None:
    """Bù embedding cho các câu lưu từ trước khi cấu hình embedding provider.

    Chạy best-effort ngay trước khi so trùng: câu cũ thiếu vector làm semantic
    check phải rơi về LLM so từng cặp (rất chậm). Lỗi ở đây không chặn việc so
    trùng — chỉ bỏ qua.
    """
    missing = [
        row for row in rows
        if _load_embedding(row.get('embedding_json')) is None
        and str(row.get('semantic_text') or '').strip()
    ][:max_rows]
    if not missing:
        return
    try:
        vectors = get_embeddings([row['semantic_text'] for row in missing])
    except Exception:
        return
    if len(vectors) != len(missing):
        return
    now = _now()
    for row, vector in zip(missing, vectors):
        if not vector:
            continue
        encoded = json.dumps([float(v) for v in vector], ensure_ascii=False)
        row['embedding_json'] = encoded
        conn.execute(
            'UPDATE bank_questions SET embedding_json = ?, updated_at = ? '
            'WHERE bank_question_id = ?',
            (encoded, now, row.get('bank_question_id')),
        )
    conn.commit()


def _llm_semantic_score(new_text: str, existing_text: str) -> Tuple[float, Optional[str]]:
    prompt = (
        'Decide whether two Vietnamese math MCQs test the same underlying idea. '
        'Return only JSON: {"duplicate": true|false, "score": 0.0-1.0}.\n\n'
        f'Question A:\n{new_text[:1200]}\n\n'
        f'Question B:\n{existing_text[:1200]}'
    )
    try:
        raw = call_llm(
            system='You judge semantic duplicate questions for a local question bank.',
            user=prompt,
            max_tokens=120,
        )
    except Exception as exc:
        return 0.0, str(exc)
    match = re.search(r'\{.*\}', raw, flags=re.S)
    if not match:
        return 0.0, 'semantic judge returned non-JSON'
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return 0.0, str(exc)
    try:
        score = float(data.get('score') or 0.0)
    except (TypeError, ValueError):
        score = 1.0 if data.get('duplicate') is True else 0.0
    if data.get('duplicate') is True:
        score = max(score, SEMANTIC_THRESHOLD)
    return max(0.0, min(1.0, score)), None


def list_banks() -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT b.*, COUNT(q.bank_question_id) AS question_count
            FROM banks b
            LEFT JOIN bank_questions q ON q.bank_id = b.bank_id
            GROUP BY b.bank_id
            ORDER BY b.updated_at DESC
            """
        ).fetchall()
        return [_row_dict(row) for row in rows]


def create_bank(name: str, description: str = '') -> Dict[str, Any]:
    name = str(name or '').strip()
    if not name:
        raise ValueError('bank name is required')
    now = _now()
    bank = {
        'bank_id': _new_id('bank'),
        'name': name,
        'description': str(description or '').strip(),
        'created_at': now,
        'updated_at': now,
    }
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO banks(bank_id, name, description, created_at, updated_at)
            VALUES(:bank_id, :name, :description, :created_at, :updated_at)
            """,
            bank,
        )
        conn.commit()
    bank['question_count'] = 0
    return bank


def get_bank(bank_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        bank_row = conn.execute(
            'SELECT * FROM banks WHERE bank_id = ?', (bank_id,)
        ).fetchone()
        if bank_row is None:
            return None
        rows = conn.execute(
            """
            SELECT * FROM bank_questions
            WHERE bank_id = ?
            ORDER BY created_at DESC
            """,
            (bank_id,),
        ).fetchall()
    bank = _row_dict(bank_row)
    questions = []
    for row in rows:
        item = _row_dict(row)
        try:
            question = json.loads(item.pop('question_json'))
        except json.JSONDecodeError:
            question = {}
        item['question'] = question
        questions.append(item)
    bank['question_count'] = len(questions)
    return {'bank': bank, 'questions': questions}


def _existing_questions(conn: sqlite3.Connection, bank_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        'SELECT * FROM bank_questions WHERE bank_id = ?', (bank_id,)
    ).fetchall()
    return [_row_dict(row) for row in rows]


def find_duplicates(
    bank_id: str,
    question: Dict[str, Any],
    embedding: Optional[List[float]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[List[float]]]:
    summary = _question_summary(question)
    embedding_error = None
    if embedding is None:
        embedding, embedding_error = _embedding_for_text(summary['semantic_text'])

    duplicates: List[Dict[str, Any]] = []
    with _connect() as conn:
        existing_rows = _existing_questions(conn, bank_id)
        if embedding is not None:
            _backfill_embeddings(conn, existing_rows)
        for existing in existing_rows:
            reasons: List[Dict[str, Any]] = []
            existing_stem = existing.get('stem_norm') or ''
            exact = summary['stem_norm'] == existing_stem and bool(existing_stem)
            if exact:
                reasons.append({'type': 'exact_stem', 'score': EXACT_THRESHOLD})

            near = max(
                _sequence_similarity(summary['stem_norm'], existing_stem),
                _jaccard(summary['stem_norm'], existing_stem),
            )
            if near >= NEAR_THRESHOLD and not exact:
                reasons.append({'type': 'near_stem', 'score': near})

            answer_same = bool(summary['answer_norm']) and summary['answer_norm'] == existing.get('answer_norm')
            if answer_same and near >= 0.60:
                reasons.append({'type': 'same_answer_similar_stem', 'score': near})

            existing_pages = existing.get('source_pages') or '[]'
            same_pages = existing_pages == summary['source_pages'] and existing_pages not in ('', '[]')
            if same_pages and near >= 0.55:
                reasons.append({'type': 'same_source_pages', 'score': near})

            existing_embedding = _load_embedding(existing.get('embedding_json'))
            semantic_score = _cosine(embedding, existing_embedding) if embedding and existing_embedding else 0.0
            if semantic_score >= SEMANTIC_THRESHOLD:
                reasons.append({'type': 'semantic', 'score': semantic_score})
            elif embedding is None or existing_embedding is None:
                semantic_text_score = _jaccard(summary['semantic_text'], existing.get('semantic_text') or '')
                if not reasons and (near >= 0.25 or semantic_text_score >= 0.22 or answer_same):
                    llm_score, llm_error = _llm_semantic_score(
                        summary['semantic_text'],
                        existing.get('semantic_text') or existing.get('stem_norm') or '',
                    )
                    if llm_error and not embedding_error:
                        embedding_error = llm_error
                    if llm_score >= SEMANTIC_THRESHOLD:
                        reasons.append({'type': 'semantic', 'score': llm_score})

            if reasons:
                try:
                    existing_question = json.loads(existing.get('question_json') or '{}')
                except json.JSONDecodeError:
                    existing_question = {}
                duplicates.append({
                    'bank_question_id': existing.get('bank_question_id'),
                    'original_question_id': existing.get('original_question_id'),
                    'stem': existing_question.get('stem'),
                    'answer_key': existing_question.get('answer_key'),
                    'reasons': reasons,
                    'max_score': max(float(r['score']) for r in reasons),
                })
    duplicates.sort(key=lambda d: d.get('max_score') or 0.0, reverse=True)
    return duplicates, embedding_error, embedding


def check_duplicates(bank_id: str, questions: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    if get_bank(bank_id) is None:
        raise KeyError('bank not found')
    results = []
    embedding_errors = []
    for question in questions:
        duplicates, embedding_error, _embedding = find_duplicates(bank_id, question)
        if embedding_error:
            embedding_errors.append(embedding_error)
        results.append({
            'question_id': question.get('question_id'),
            'stem': question.get('stem'),
            'duplicates': duplicates,
        })
    return {
        'results': results,
        'semantic_enabled': not embedding_errors,
        'embedding_errors': sorted(set(embedding_errors)),
    }


def add_questions(
    bank_id: str,
    questions: Iterable[Dict[str, Any]],
    source_job_id: str = '',
    source_pdf_name: str = '',
    duplicate_action: str = 'skip',
) -> Dict[str, Any]:
    if duplicate_action not in {'skip', 'replace', 'force'}:
        raise ValueError('duplicate_action must be skip|replace|force')
    if get_bank(bank_id) is None:
        raise KeyError('bank not found')

    added: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    replaced: List[Dict[str, Any]] = []
    embedding_errors: List[str] = []

    with _connect() as conn:
        for question in questions:
            summary = _question_summary(question)
            duplicates, embedding_error, embedding = find_duplicates(bank_id, question)
            if embedding_error:
                embedding_errors.append(embedding_error)
            has_duplicates = bool(duplicates)
            if has_duplicates and duplicate_action == 'skip':
                skipped.append({
                    'question_id': question.get('question_id'),
                    'stem': question.get('stem'),
                    'duplicates': duplicates,
                })
                continue
            if has_duplicates and duplicate_action == 'replace':
                duplicate_ids = [d['bank_question_id'] for d in duplicates if d.get('bank_question_id')]
                if duplicate_ids:
                    conn.executemany(
                        'DELETE FROM bank_questions WHERE bank_question_id = ?',
                        [(qid,) for qid in duplicate_ids],
                    )
                    replaced.extend(duplicates)

            now = _now()
            bank_question_id = _new_id('bq')
            conn.execute(
                """
                INSERT INTO bank_questions(
                    bank_question_id, bank_id, original_question_id,
                    source_job_id, source_pdf_name, question_json,
                    stem_norm, answer_norm, semantic_text, embedding_json,
                    source_pages, source_quote, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bank_question_id,
                    bank_id,
                    summary['original_question_id'],
                    source_job_id,
                    source_pdf_name,
                    json.dumps(question, ensure_ascii=False),
                    summary['stem_norm'],
                    summary['answer_norm'],
                    summary['semantic_text'],
                    json.dumps(embedding, ensure_ascii=False) if embedding else None,
                    summary['source_pages'],
                    summary['source_quote'],
                    now,
                    now,
                ),
            )
            added.append({
                'bank_question_id': bank_question_id,
                'question_id': question.get('question_id'),
                'stem': question.get('stem'),
                'duplicates': duplicates,
            })
        conn.execute('UPDATE banks SET updated_at = ? WHERE bank_id = ?', (_now(), bank_id))
        conn.commit()

    return {
        'added': added,
        'skipped': skipped,
        'replaced': replaced,
        'semantic_enabled': not embedding_errors,
        'embedding_errors': sorted(set(embedding_errors)),
    }


def delete_question(bank_id: str, bank_question_id: str) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            'DELETE FROM bank_questions WHERE bank_id = ? AND bank_question_id = ?',
            (bank_id, bank_question_id),
        )
        if cur.rowcount:
            conn.execute('UPDATE banks SET updated_at = ? WHERE bank_id = ?', (_now(), bank_id))
        conn.commit()
        return cur.rowcount > 0


def update_question(bank_id: str, bank_question_id: str, question: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    summary = _question_summary(question)
    embedding, embedding_error = _embedding_for_text(summary['semantic_text'])
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE bank_questions
            SET question_json = ?, stem_norm = ?, answer_norm = ?, semantic_text = ?,
                embedding_json = ?, source_pages = ?, source_quote = ?, updated_at = ?
            WHERE bank_id = ? AND bank_question_id = ?
            """,
            (
                json.dumps(question, ensure_ascii=False),
                summary['stem_norm'],
                summary['answer_norm'],
                summary['semantic_text'],
                json.dumps(embedding, ensure_ascii=False) if embedding else None,
                summary['source_pages'],
                summary['source_quote'],
                now,
                bank_id,
                bank_question_id,
            ),
        )
        if cur.rowcount:
            conn.execute('UPDATE banks SET updated_at = ? WHERE bank_id = ?', (now, bank_id))
        conn.commit()
    if not cur.rowcount:
        return None
    return {'ok': True, 'embedding_error': embedding_error}


def bank_export_payload(bank_id: str) -> Optional[Dict[str, Any]]:
    payload = get_bank(bank_id)
    if payload is None:
        return None
    bank = payload['bank']
    questions = [item['question'] for item in payload['questions']]
    return {'bank': bank, 'questions': questions}

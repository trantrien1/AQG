"""Filesystem-based job store.

Layout per job at `runs/<job_id>/`:
    meta.json     — JobMeta (status, pdf_name, created_at, ...)
    source.pdf    — uploaded PDF (binary)
    config.json   — JobConfig
    status.json   — runtime status updated by progress callback
    result.json   — final compact {questions, metadata}
    debug_rejected.json — rejected/debug records for troubleshooting
    errors.log    — append-only error trace from background task

All writes go through `_atomic_write` to prevent half-written files
being read by polling clients.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# `runs/` lives at API root; this file is API/web/store.py
ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / 'runs'
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Per-job locks to keep status writes from racing with reads on the
# same process. FS-level concurrency is single-process so this is enough.
_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(job_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(job_id)
        if lock is None:
            lock = threading.Lock()
            _locks[job_id] = lock
        return lock


def _atomic_write(path: Path, payload: Any) -> None:
    """Write JSON via temp file + os.replace to make readers see whole content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tmp_', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        # On Windows, os.replace can briefly fail with WinError 5 if another
        # process has the target open while the web UI is polling status.json.
        # Retrying preserves atomic writes without surfacing transient locks.
        last_exc: Optional[OSError] = None
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.05 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
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
    except (json.JSONDecodeError, OSError):
        # Mid-write or truncated; treat as missing for caller.
        return None


# ----------------------------------------------------------------------
# Job lifecycle
# ----------------------------------------------------------------------

def new_job_id() -> str:
    """Match prior format from runs/web_ui_8080.out.log: 10-hex (5 bytes)."""
    return secrets.token_hex(5)


def job_dir(job_id: str) -> Path:
    return RUNS_DIR / job_id


def job_exists(job_id: str) -> bool:
    return (job_dir(job_id) / 'meta.json').exists()


def create_job(pdf_name: str, num_questions: int) -> str:
    job_id = new_job_id()
    d = job_dir(job_id)
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        'job_id': job_id,
        'status': 'pending',
        'pdf_name': pdf_name,
        'num_questions': num_questions,
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    with _lock_for(job_id):
        _atomic_write(d / 'meta.json', meta)
        _atomic_write(d / 'status.json', {
            'status': 'pending',
            'progress': 0.0,
            'message': 'job created',
        })
    return job_id


def save_pdf(job_id: str, content: bytes) -> Path:
    p = job_dir(job_id) / 'source.pdf'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    return p


def get_meta(job_id: str) -> Optional[Dict[str, Any]]:
    return _read_json(job_dir(job_id) / 'meta.json')


def update_meta(job_id: str, **fields: Any) -> Dict[str, Any]:
    with _lock_for(job_id):
        meta = _read_json(job_dir(job_id) / 'meta.json') or {}
        meta.update(fields)
        _atomic_write(job_dir(job_id) / 'meta.json', meta)
        return meta


def list_jobs() -> List[Dict[str, Any]]:
    if not RUNS_DIR.exists():
        return []
    out: List[Dict[str, Any]] = []
    for d in RUNS_DIR.iterdir():
        if not d.is_dir():
            continue
        meta = _read_json(d / 'meta.json')
        if meta:
            out.append(meta)
    out.sort(key=lambda m: m.get('created_at', ''), reverse=True)
    return out


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    'mode': 'Direct_PDF_Mode',
    'direct_pdf': True,
    'num_questions': 12,
    'bloom_level': 'mixed',
    'include_explanation': True,
    'include_visuals': False,
    'question_types': [],
    'topic_filter': [],
    # Smart-Study customization (parsed by pipeline.customization.parse).
    'difficulty': 'mixed',
    'user_instruction': '',
    'focus_topics': [],
    'avoid_topics': [],
    'style': 'default',
    'requires_computation': False,
    'requires_detailed_solution': True,
    'strict_grounding': False,
    'quick_prompts': [],
}


def get_config(job_id: str) -> Dict[str, Any]:
    cfg = _read_json(job_dir(job_id) / 'config.json')
    if cfg is None:
        return DEFAULT_CONFIG.copy()
    merged = DEFAULT_CONFIG.copy()
    merged.update(cfg)
    return merged


def save_config(job_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
    with _lock_for(job_id):
        merged = DEFAULT_CONFIG.copy()
        existing = _read_json(job_dir(job_id) / 'config.json') or {}
        merged.update(existing)
        merged.update(config)
        _atomic_write(job_dir(job_id) / 'config.json', merged)
        return merged


# ----------------------------------------------------------------------
# Prepare phase (two-step upload: /prepare khi chọn file, /start khi bấm Generate)
# ----------------------------------------------------------------------
#
# prepare.json — trạng thái tiền xử lý chạy nền lúc người dùng còn đang chọn
#   config: {status: preparing|ready|error, attachments_ready, num_pages,
#            outline, error}. Tách khỏi status.json để không giẫm lên flow
#   generate (status.json vẫn thuộc về vòng đời sinh câu hỏi).
# attachments_cache.json — các trang PDF đã render (list content part), để
#   generation dùng lại thay vì render lần nữa.

def write_prepare(job_id: str, payload: Dict[str, Any]) -> None:
    with _lock_for(job_id):
        _atomic_write(job_dir(job_id) / 'prepare.json', payload)


def update_prepare(job_id: str, **fields: Any) -> Dict[str, Any]:
    with _lock_for(job_id):
        payload = _read_json(job_dir(job_id) / 'prepare.json') or {}
        payload.update(fields)
        _atomic_write(job_dir(job_id) / 'prepare.json', payload)
        return payload


def get_prepare(job_id: str) -> Optional[Dict[str, Any]]:
    return _read_json(job_dir(job_id) / 'prepare.json')


def save_attachments_cache(job_id: str, parts: List[Dict[str, Any]]) -> None:
    # Không đi qua _lock_for: file có thể vài chục MB (ảnh base64), giữ lock
    # lâu sẽ chặn polling status. Chỉ ghi một lần từ thread prepare nên atomic
    # write là đủ.
    _atomic_write(job_dir(job_id) / 'attachments_cache.json', {'parts': parts})


def load_attachments_cache(job_id: str) -> Optional[List[Dict[str, Any]]]:
    payload = _read_json(job_dir(job_id) / 'attachments_cache.json')
    parts = (payload or {}).get('parts')
    if isinstance(parts, list) and parts:
        return parts
    return None


# ----------------------------------------------------------------------
# Cancellation flag
# ----------------------------------------------------------------------

def request_cancel(job_id: str) -> bool:
    """Mark a job as cancel-requested. Returns False if job missing."""
    if not job_exists(job_id):
        return False
    with _lock_for(job_id):
        path = job_dir(job_id) / 'cancel.flag'
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                encoding='utf-8',
            )
        except OSError:
            return False
        return True


def is_cancel_requested(job_id: str) -> bool:
    return (job_dir(job_id) / 'cancel.flag').exists()


def clear_cancel(job_id: str) -> None:
    with _lock_for(job_id):
        path = job_dir(job_id) / 'cancel.flag'
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass


def clear_result(job_id: str) -> None:
    with _lock_for(job_id):
        for name in ('result.json', 'export.json', 'debug_rejected.json'):
            p = job_dir(job_id) / name
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass


# ----------------------------------------------------------------------
# Status (polling target)
# ----------------------------------------------------------------------

def write_status(job_id: str, status: Dict[str, Any]) -> None:
    with _lock_for(job_id):
        _atomic_write(job_dir(job_id) / 'status.json', status)


def get_status(job_id: str) -> Dict[str, Any]:
    s = _read_json(job_dir(job_id) / 'status.json')
    if s is None:
        meta = get_meta(job_id) or {}
        return {'status': meta.get('status', 'pending')}
    return s


# ----------------------------------------------------------------------
# Result
# ----------------------------------------------------------------------

def save_result(job_id: str, result: Dict[str, Any]) -> None:
    with _lock_for(job_id):
        _atomic_write(job_dir(job_id) / 'result.json', result)


def get_result(job_id: str) -> Optional[Dict[str, Any]]:
    return _read_json(job_dir(job_id) / 'result.json')

def save_debug_rejected(job_id: str, rejected: List[Dict[str, Any]],
                        summary: Optional[Dict[str, Any]] = None) -> None:
    with _lock_for(job_id):
        _atomic_write(job_dir(job_id) / 'debug_rejected.json', {
            'summary': summary or {},
            'rejected': rejected or [],
        })

def get_debug_rejected(job_id: str) -> List[Dict[str, Any]]:
    payload = _read_json(job_dir(job_id) / 'debug_rejected.json')
    if payload and isinstance(payload.get('rejected'), list):
        return payload.get('rejected') or []
    result = _read_json(job_dir(job_id) / 'result.json') or {}
    rejected = result.get('rejected')
    return rejected if isinstance(rejected, list) else []

def get_debug_reject_summary(job_id: str) -> Dict[str, Any]:
    payload = _read_json(job_dir(job_id) / 'debug_rejected.json')
    if payload and isinstance(payload.get('summary'), dict):
        return payload.get('summary') or {}
    return {}


def update_question_review(job_id: str, question_id: str,
                            review_status: str) -> bool:
    """Mutate a question's review_status in result.json. Returns True if found."""
    with _lock_for(job_id):
        result = _read_json(job_dir(job_id) / 'result.json')
        if not result:
            return False
        for q in result.get('questions', []):
            if q.get('question_id') == question_id:
                q['review_status'] = review_status
                q.setdefault('review', {})['status'] = review_status
                q['review']['human_reviewed'] = True
                _atomic_write(job_dir(job_id) / 'result.json', result)
                return True
        return False


# ----------------------------------------------------------------------
# Question feedback (RLHF-style: user 👍/👎 + lý do, dùng để sinh lại)
# ----------------------------------------------------------------------

def get_feedback(job_id: str) -> List[Dict[str, Any]]:
    payload = _read_json(job_dir(job_id) / 'feedback.json')
    items = (payload or {}).get('items')
    return items if isinstance(items, list) else []


def save_feedback_entry(job_id: str, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Upsert một entry feedback theo question_id. Trả danh sách mới."""
    with _lock_for(job_id):
        payload = _read_json(job_dir(job_id) / 'feedback.json') or {}
        items = payload.get('items')
        if not isinstance(items, list):
            items = []
        qid = entry.get('question_id')
        items = [it for it in items
                 if isinstance(it, dict) and it.get('question_id') != qid]
        items.append(entry)
        _atomic_write(job_dir(job_id) / 'feedback.json', {'items': items})
        return items


def delete_feedback_entry(job_id: str, question_id: str) -> bool:
    """Xoá feedback của một câu. Trả True nếu có entry bị xoá."""
    with _lock_for(job_id):
        payload = _read_json(job_dir(job_id) / 'feedback.json') or {}
        items = payload.get('items')
        if not isinstance(items, list):
            return False
        kept = [it for it in items
                if isinstance(it, dict) and it.get('question_id') != question_id]
        if len(kept) == len(items):
            return False
        _atomic_write(job_dir(job_id) / 'feedback.json', {'items': kept})
        return True


# ----------------------------------------------------------------------
# Error log (debugging)
# ----------------------------------------------------------------------

def append_error(job_id: str, message: str) -> None:
    p = job_dir(job_id) / 'errors.log'
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('a', encoding='utf-8') as f:
        f.write(f'[{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}] {message}\n')


def export_path(job_id: str) -> Optional[Path]:
    p = job_dir(job_id) / 'result.json'
    return p if p.exists() else None


def cleanup(job_id: str) -> None:
    d = job_dir(job_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)

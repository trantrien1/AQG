"""PostgreSQL cho đăng nhập: bảng users + sessions.

Jobs và ngân hàng câu hỏi vẫn lưu file (runs/, data/) — DB chỉ phục vụ auth.
Kết nối mở theo từng thao tác (không pool) vì tần suất thấp; phiên đăng nhập
được cache in-memory 60s để middleware không phải query DB mỗi request poll.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import threading
import time
from typing import Optional

import psycopg

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 30 * 24 * 3600  # phiên đăng nhập sống 30 ngày
_PBKDF2_ITERATIONS = 240_000

_session_cache: dict[str, tuple[str, float]] = {}
_session_cache_lock = threading.Lock()
_SESSION_CACHE_TTL = 60.0


def _database_url() -> str:
    # Đọc lazy để chắc chắn pipeline.config đã load .env vào os.environ.
    return os.environ.get('DATABASE_URL', 'postgresql://aqg:aqg@127.0.0.1:5434/aqg')


def _connect() -> psycopg.Connection:
    return psycopg.connect(_database_url(), autocommit=True, connect_timeout=5)


def init_db(max_wait_seconds: float = 30.0) -> bool:
    """Tạo bảng nếu chưa có; retry chờ Postgres khởi động. Trả False nếu DB chưa sẵn sàng."""
    deadline = time.monotonic() + max_wait_seconds
    while True:
        try:
            with _connect() as conn:
                conn.execute(
                    'CREATE TABLE IF NOT EXISTS users ('
                    '  username text PRIMARY KEY,'
                    '  password_hash text NOT NULL,'
                    '  created_at timestamptz NOT NULL DEFAULT now()'
                    ')'
                )
                conn.execute(
                    'CREATE TABLE IF NOT EXISTS sessions ('
                    '  token_hash text PRIMARY KEY,'
                    '  username text NOT NULL REFERENCES users(username) ON DELETE CASCADE,'
                    '  created_at timestamptz NOT NULL DEFAULT now(),'
                    '  expires_at timestamptz NOT NULL'
                    ')'
                )
            return True
        except psycopg.Error as exc:
            if time.monotonic() >= deadline:
                logger.warning('Auth DB chưa sẵn sàng (%s); API sẽ trả 503 cho tới khi DB lên.', exc)
                return False
            time.sleep(1.0)


# ---- Mật khẩu (PBKDF2-SHA256, stdlib — không cần thêm dependency) ----

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), bytes.fromhex(salt), _PBKDF2_ITERATIONS,
    )
    return f'pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}'


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, expected = stored.split('$', 3)
        if algo != 'pbkdf2_sha256':
            return False
        digest = hashlib.pbkdf2_hmac(
            'sha256', password.encode('utf-8'), bytes.fromhex(salt), int(iterations),
        )
        return secrets.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def ensure_admin() -> None:
    """Upsert tài khoản admin từ .env (ADMIN_USERNAME/ADMIN_PASSWORD).

    Đổi ADMIN_PASSWORD trong .env rồi restart backend = đổi mật khẩu.
    """
    username = (os.environ.get('ADMIN_USERNAME') or 'admin').strip()
    password = os.environ.get('ADMIN_PASSWORD') or ''
    if not password:
        logger.warning('ADMIN_PASSWORD chưa đặt trong .env — không seed được tài khoản đăng nhập.')
        return
    with _connect() as conn:
        row = conn.execute(
            'SELECT password_hash FROM users WHERE username = %s', (username,),
        ).fetchone()
        if row is not None and verify_password(password, row[0]):
            return  # mật khẩu không đổi, giữ nguyên hash cũ
        conn.execute(
            'INSERT INTO users (username, password_hash) VALUES (%s, %s) '
            'ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash',
            (username, hash_password(password)),
        )
        # Mật khẩu đổi thì hủy toàn bộ phiên cũ của user đó.
        conn.execute('DELETE FROM sessions WHERE username = %s', (username,))
    with _session_cache_lock:
        _session_cache.clear()
    logger.info("Đã seed tài khoản đăng nhập '%s'.", username)


# ---- Phiên đăng nhập ----

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def verify_login(username: str, password: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            'SELECT password_hash FROM users WHERE username = %s', (username,),
        ).fetchone()
    return row is not None and verify_password(password, row[0])


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    with _connect() as conn:
        conn.execute(
            'DELETE FROM sessions WHERE expires_at < now()',
        )
        conn.execute(
            'INSERT INTO sessions (token_hash, username, expires_at) '
            "VALUES (%s, %s, now() + %s * interval '1 second')",
            (_token_hash(token), username, SESSION_TTL_SECONDS),
        )
    return token


def get_session_user(token: str) -> Optional[str]:
    """Username của phiên còn hạn, hoặc None. Cache 60s cho các request poll."""
    key = _token_hash(token)
    now = time.monotonic()
    with _session_cache_lock:
        hit = _session_cache.get(key)
        if hit is not None and hit[1] > now:
            return hit[0]
    with _connect() as conn:
        row = conn.execute(
            'SELECT username FROM sessions WHERE token_hash = %s AND expires_at > now()',
            (key,),
        ).fetchone()
    if row is None:
        return None
    with _session_cache_lock:
        _session_cache[key] = (row[0], now + _SESSION_CACHE_TTL)
    return row[0]


def delete_session(token: str) -> None:
    key = _token_hash(token)
    with _session_cache_lock:
        _session_cache.pop(key, None)
    with _connect() as conn:
        conn.execute('DELETE FROM sessions WHERE token_hash = %s', (key,))

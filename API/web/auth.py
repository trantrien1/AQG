"""Đăng nhập bằng session token: POST /auth/login trả token,
client gửi kèm header `Authorization: Bearer <token>` cho mọi request khác.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import psycopg
from fastapi import APIRouter, Body, HTTPException, Request

from . import db

router = APIRouter()

# Các path không cần đăng nhập (middleware trong app.py dùng).
EXEMPT_PATHS = {'/health', '/auth/login'}


def bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get('authorization') or ''
    scheme, _, token = header.partition(' ')
    if scheme.lower() != 'bearer' or not token.strip():
        return None
    return token.strip()


@router.post('/auth/login')
def login(payload: Dict[str, Any] = Body(...)) -> Dict[str, str]:
    username = str(payload.get('username') or '').strip()
    password = str(payload.get('password') or '')
    if not username or not password:
        raise HTTPException(status_code=400, detail='username and password required')
    try:
        if not db.verify_login(username, password):
            raise HTTPException(status_code=401, detail='Sai tên đăng nhập hoặc mật khẩu')
        token = db.create_session(username)
    except psycopg.Error as exc:
        raise HTTPException(status_code=503, detail='Auth database unavailable') from exc
    return {'token': token, 'username': username}


@router.post('/auth/logout')
def logout(request: Request) -> Dict[str, bool]:
    token = bearer_token(request)
    if token:
        try:
            db.delete_session(token)
        except psycopg.Error:
            pass  # DB sập thì phiên cũng không dùng được — coi như đã logout
    return {'ok': True}


@router.get('/auth/me')
def me(request: Request) -> Dict[str, str]:
    # Middleware đã xác thực; username gắn ở request.state.
    return {'username': getattr(request.state, 'username', '')}

"""Ngân sách lượt thử phải cố định được, nếu không phép quét nhiều mô hình sai.

Hệ thống bỏ cuộc sau một số slot hỏng LIÊN TIẾP. Chạy thật thì đúng: tài liệu
không sinh được thì dừng sớm cho đỡ tốn. Nhưng khi so nhiều mô hình, cơ chế đó
cấp cho mô hình yếu ÍT lượt thử hơn mô hình khoẻ — mô hình khoẻ thành công nên
chuỗi hỏng bị reset và nó chạy hết, mô hình yếu bị cắt sau vài lượt. Khi ấy
"giao ra / số câu yêu cầu" của hai ô có hai mẫu số khác nhau và không so được.

Đã xảy ra thật (2026-07-28): ở 20 câu yêu cầu, ngưỡng tự tính là 6 nên hai ô
Qwen chỉ được thử đúng 6 lượt rồi dừng, còn ô gpt-4.1-nano được 18 lượt.
"""
from __future__ import annotations

import importlib
import os

import pytest


def _reload_config(monkeypatch, value):
    if value is None:
        monkeypatch.delenv('AQG_MAX_EMPTY_STREAK', raising=False)
    else:
        monkeypatch.setenv('AQG_MAX_EMPTY_STREAK', str(value))
    from pipeline import config
    return importlib.reload(config)


@pytest.fixture(autouse=True)
def _restore_config():
    yield
    os.environ.pop('AQG_MAX_EMPTY_STREAK', None)
    from pipeline import config
    importlib.reload(config)


def _effective(cfg, requested_count: int) -> int:
    """Đúng biểu thức orchestrator dùng."""
    return (int(getattr(cfg, 'MAX_EMPTY_STREAK', 0))
            or max(4, requested_count // 3))


def test_default_keeps_the_auto_formula(monkeypatch):
    cfg = _reload_config(monkeypatch, None)
    assert cfg.MAX_EMPTY_STREAK == 0
    assert _effective(cfg, 20) == 6
    assert _effective(cfg, 3) == 4
    assert _effective(cfg, 90) == 30


def test_explicit_value_overrides_the_formula(monkeypatch):
    cfg = _reload_config(monkeypatch, 60)
    assert _effective(cfg, 20) == 60
    assert _effective(cfg, 3) == 60


def test_the_same_budget_applies_whatever_the_target(monkeypatch):
    """Điều kiện để so chéo: ngân sách KHÔNG được phụ thuộc số câu yêu cầu."""
    cfg = _reload_config(monkeypatch, 60)
    assert len({_effective(cfg, n) for n in (3, 10, 20, 50)}) == 1


def test_the_bug_this_guards_against(monkeypatch):
    """Không đặt cố định thì ô yếu bị cắt sớm hơn ô khoẻ — mẫu số lệch."""
    cfg = _reload_config(monkeypatch, None)
    budget = _effective(cfg, 20)
    # Ô yếu: hỏng liên tiếp ngay từ đầu -> dừng đúng khi hết ngân sách.
    assert budget == 6
    # Ô khoẻ: thành công ở lượt 3 và 9 -> chuỗi hỏng reset hai lần, nên nó được
    # thử NHIỀU hơn hẳn dù ngân sách danh nghĩa như nhau.
    attempts_strong = 0
    streak = 0
    successes = {3, 9}
    while streak < budget and attempts_strong < 40:
        attempts_strong += 1
        streak = 0 if attempts_strong in successes else streak + 1
    assert attempts_strong > budget

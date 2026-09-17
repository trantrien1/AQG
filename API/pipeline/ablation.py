"""Công tắc bật/tắt độc lập từng cơ chế của pipeline (cho ablation study).

Mỗi cơ chế được đặt tên và có thể tắt riêng lẻ, nên có thể dựng các "arm" tăng
dần từ Single Prompt đến Full System mà không phải fork code. Module này CHỈ
cung cấp công tắc và định nghĩa arm — nó không chạy thí nghiệm và không sinh ra
bất kỳ con số kết quả nào.

Thứ tự ưu tiên khi đọc trạng thái một cơ chế:

1. override trong tiến trình (:func:`override`, dùng trong benchmark/test),
2. biến môi trường ``AQG_ABLATION_<MECHANISM>=0|1``,
3. arm đang chọn (``AQG_ABLATION_ARM``),
4. mặc định của cơ chế (Full System).
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

# ==== Danh mục cơ chế ====
SYMBOLIC_VERIFIER = 'symbolic_verifier'
INDEPENDENT_VERIFICATION = 'independent_verification'
MISCONCEPTION_CATALOGUE = 'misconception_catalogue'
DISTRACTOR_AGENT = 'distractor_agent'
DIFFICULTY_CONTROL = 'difficulty_control'
OUTCOME_SCHEDULER = 'outcome_scheduler'
FEEDBACK_STEERING = 'feedback_steering'
SEMANTIC_DEDUP = 'semantic_dedup'

MECHANISMS: Dict[str, str] = {
    SYMBOLIC_VERIFIER:
        'Kiểm chứng ký hiệu bằng SymPy/NetworkX trên biểu thức của Writer',
    INDEPENDENT_VERIFICATION:
        'Dựng mục tiêu kiểm chứng độc lập rồi phân xử đa nguồn',
    MISCONCEPTION_CATALOGUE:
        'Danh mục sai lầm thường gặp làm hạt giống cho phương án nhiễu',
    DISTRACTOR_AGENT:
        'Tác nhân sinh phương án nhiễu riêng (thay vì để Writer tự sinh)',
    DIFFICULTY_CONTROL:
        'Ràng buộc độ nặng phép tính theo mức độ khó mục tiêu',
    OUTCOME_SCHEDULER:
        'Rải mức Bloom và chuẩn đầu ra vào từng slot',
    FEEDBACK_STEERING:
        'Đưa phản hồi người dùng trong phiên vào prompt lượt sinh sau',
    SEMANTIC_DEDUP:
        'Chống trùng lặp trong cùng lượt sinh: danh sách câu cần né trong prompt '
        '+ cổng loại câu trùng. (Chống trùng theo embedding với ngân hàng câu '
        'hỏi nằm ở tầng web, ngoài phạm vi benchmark sinh câu.)',
}

#: Mặc định = Full System.
_DEFAULTS: Dict[str, bool] = {name: True for name in MECHANISMS}

#: Các arm tăng dần dùng cho ablation. Mỗi arm liệt kê cơ chế BẬT; cơ chế không
#: liệt kê thì tắt. Tên arm được ghi vào run manifest.
ARMS: Dict[str, List[str]] = {
    'single_prompt': [],
    'plus_verifier': [SYMBOLIC_VERIFIER],
    'plus_independent': [SYMBOLIC_VERIFIER, INDEPENDENT_VERIFICATION],
    'plus_distractor': [
        SYMBOLIC_VERIFIER, INDEPENDENT_VERIFICATION,
        DISTRACTOR_AGENT, MISCONCEPTION_CATALOGUE,
    ],
    'plus_difficulty': [
        SYMBOLIC_VERIFIER, INDEPENDENT_VERIFICATION,
        DISTRACTOR_AGENT, MISCONCEPTION_CATALOGUE,
        DIFFICULTY_CONTROL, OUTCOME_SCHEDULER,
    ],
    'full_system': list(MECHANISMS),
}

#: Thứ tự trình bày trong báo cáo ablation.
ARM_ORDER: List[str] = [
    'single_prompt', 'plus_verifier', 'plus_independent',
    'plus_distractor', 'plus_difficulty', 'full_system',
]

_lock = threading.RLock()
_overrides: Dict[str, bool] = {}
_arm: Optional[str] = None


def _env_flag(name: str) -> Optional[bool]:
    raw = os.getenv(f'AQG_ABLATION_{name.upper()}')
    if raw is None:
        return None
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


def current_arm() -> Optional[str]:
    """Arm đang chọn (override trong tiến trình > ``AQG_ABLATION_ARM``)."""
    with _lock:
        if _arm is not None:
            return _arm
    env = (os.getenv('AQG_ABLATION_ARM') or '').strip().lower()
    return env if env in ARMS else None


def is_enabled(mechanism: str) -> bool:
    """Cơ chế `mechanism` có đang bật không."""
    if mechanism not in MECHANISMS:
        raise KeyError(f'unknown mechanism: {mechanism}')
    with _lock:
        if mechanism in _overrides:
            return _overrides[mechanism]
    env = _env_flag(mechanism)
    if env is not None:
        return env
    arm = current_arm()
    if arm is not None:
        return mechanism in ARMS[arm]
    return _DEFAULTS[mechanism]


def snapshot() -> Dict[str, bool]:
    """Trạng thái hiện tại của mọi cơ chế — ghi vào run manifest."""
    return {name: is_enabled(name) for name in MECHANISMS}


def set_arm(arm: Optional[str]) -> None:
    """Chọn arm trong tiến trình. ``None`` = bỏ chọn (quay về env/mặc định)."""
    if arm is not None and arm not in ARMS:
        raise KeyError(f'unknown ablation arm: {arm}')
    global _arm
    with _lock:
        _arm = arm


@contextmanager
def override(arm: Optional[str] = None, **mechanisms: bool) -> Iterator[None]:
    """Đặt tạm arm và/hoặc từng cơ chế trong một block.

    >>> with override(independent_verification=False):
    ...     assert not is_enabled(INDEPENDENT_VERIFICATION)
    """
    for name in mechanisms:
        if name not in MECHANISMS:
            raise KeyError(f'unknown mechanism: {name}')
    global _arm
    with _lock:
        prev_overrides = dict(_overrides)
        prev_arm = _arm
        _overrides.update({k: bool(v) for k, v in mechanisms.items()})
        if arm is not None:
            if arm not in ARMS:
                raise KeyError(f'unknown ablation arm: {arm}')
            _arm = arm
    try:
        yield
    finally:
        with _lock:
            _overrides.clear()
            _overrides.update(prev_overrides)
            _arm = prev_arm


def describe_arm(arm: str) -> Dict[str, bool]:
    """Bảng bật/tắt của một arm (không đổi trạng thái tiến trình)."""
    if arm not in ARMS:
        raise KeyError(f'unknown ablation arm: {arm}')
    enabled = set(ARMS[arm])
    return {name: (name in enabled) for name in MECHANISMS}

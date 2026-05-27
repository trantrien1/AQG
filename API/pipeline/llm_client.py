"""LLM client + cost tracking (mục 21)."""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from . import config as cfg


class CostTracker:
    """Đếm token và số call. Vượt ngưỡng → raise BudgetExceeded."""

    def __init__(self,
                 max_tokens: int = cfg.COST_BUDGET_TOKENS,
                 max_calls: int = cfg.COST_BUDGET_CALLS):
        self.max_tokens = max_tokens
        self.max_calls = max_calls
        self.tokens = 0
        self.calls = 0
        self._lock = threading.Lock()

    def add(self, tokens: int = 0, calls: int = 1):
        with self._lock:
            self.tokens += tokens
            self.calls += calls
            self._check_locked()

    def check(self):
        with self._lock:
            self._check_locked()

    def _check_locked(self):
        if self.max_tokens > 0 and self.tokens > self.max_tokens:
            raise BudgetExceeded(f'Đã dùng {self.tokens} tokens (giới hạn {self.max_tokens})')
        if self.max_calls > 0 and self.calls > self.max_calls:
            raise BudgetExceeded(f'Đã gọi {self.calls} lần (giới hạn {self.max_calls})')

    def report(self) -> Dict[str, int]:
        return {'tokens': self.tokens, 'calls': self.calls,
                'max_tokens': self.max_tokens, 'max_calls': self.max_calls}


class BudgetExceeded(RuntimeError):
    pass


_global_tracker: Optional[CostTracker] = None


def get_tracker() -> CostTracker:
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = CostTracker()
    return _global_tracker


def reset_tracker(max_tokens: Optional[int] = None, max_calls: Optional[int] = None):
    global _global_tracker
    _global_tracker = CostTracker(
        max_tokens=cfg.COST_BUDGET_TOKENS if max_tokens is None else max_tokens,
        max_calls=cfg.COST_BUDGET_CALLS if max_calls is None else max_calls,
    )


# ==== OpenAI/OpenRouter client ====

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        extra_headers = {}
        if cfg.LLM_PROVIDER == 'openrouter' and cfg.OPENROUTER_SITE_URL:
            extra_headers['HTTP-Referer'] = cfg.OPENROUTER_SITE_URL
        if cfg.LLM_PROVIDER == 'openrouter' and cfg.OPENROUTER_SITE_NAME:
            extra_headers['X-Title'] = cfg.OPENROUTER_SITE_NAME
        kwargs: Dict[str, Any] = {
            'api_key': cfg.active_llm_api_key(),
            'timeout': cfg.LLM_TIMEOUT_SECONDS,
        }
        base_url = cfg.active_llm_base_url()
        if base_url:
            kwargs['base_url'] = base_url
        if extra_headers:
            kwargs['default_headers'] = extra_headers
        _client = OpenAI(**kwargs)
    return _client


def call_llm(system: str, user: str, model: str = None,
             temperature: float = cfg.GEN_TEMPERATURE,
             max_tokens: int = cfg.GEN_MAX_TOKENS,
             retries: int = cfg.LLM_RETRIES) -> str:
    """Gọi LLM với retry + cost tracking."""
    tracker = get_tracker()
    tracker.check()
    model = model or cfg.GENERATOR_MODEL
    if not cfg.has_llm_api_key():
        raise RuntimeError(cfg.missing_llm_api_key_message())
    last_err = None
    retries = max(1, int(retries or 1))
    for attempt in range(retries):
        try:
            client = _get_client()
            tracker.add(calls=1)
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user},
                ],
            )
            content = resp.choices[0].message.content or ''
            usage = getattr(resp, 'usage', None)
            tokens = (getattr(usage, 'total_tokens', 0) or 0) if usage else 0
            tracker.add(tokens=tokens, calls=0)
            return content
        except Exception as e:
            last_err = e
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise last_err


def get_embeddings(texts):
    if not cfg.has_llm_api_key():
        raise RuntimeError(cfg.missing_llm_api_key_message())
    client = _get_client()
    resp = client.embeddings.create(model=cfg.EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in resp.data]

"""LLM client + usage tracking."""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, Optional

from . import config as cfg

# Marker trích dẫn của ChatGPT (qua gateway chat2api): block Private-Use-Area
# \ue200filecite\ue202turn0file0\ue202L1-L2\ue201 chèn thẳng vào text trả về.
# Không lọc thì marker lọt vào stem/option/JSON của câu hỏi sinh ra.
_PUA_CITATION_RE = re.compile(
    '\ue200[^\ue200\ue201]*\ue201'  # block trích dẫn trọn vẹn \ue200...\ue201
    '|[\ue000-\uf8ff]'              # ký tự Private-Use-Area lẻ còn sót
)


def _strip_provider_artifacts(text: str) -> str:
    if not text:
        return text
    return _PUA_CITATION_RE.sub('', text)


class CostTracker:
    """Track token and request usage without hard limits."""

    def __init__(self, *_args: Any, **_kwargs: Any):
        self.tokens = 0
        self.calls = 0
        self._lock = threading.Lock()

    def add(self, tokens: int = 0, calls: int = 1):
        with self._lock:
            self.tokens += tokens
            self.calls += calls
            self._check_locked()

    def check(self):
        return None

    def _check_locked(self):
        return None

    def report(self) -> Dict[str, int]:
        return {'tokens': self.tokens, 'calls': self.calls}


class BudgetExceeded(RuntimeError):
    pass

class NonRetryableLLMError(RuntimeError):
    """Provider/config error that should fail fast instead of retrying."""

    def __init__(self, original: Exception):
        self.original = original
        super().__init__(str(original))


class PdfUnsupportedError(RuntimeError):
    """Model/provider does not support PDF/file input — fail fast, no retry (Req 6.1)."""

    def __init__(self, original: Exception):
        self.original = original
        super().__init__(str(original))

def _status_code(exc: Exception) -> Optional[int]:
    status = getattr(exc, 'status_code', None)
    if status is None:
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None) if response is not None else None
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None

def _is_non_retryable(exc: Exception) -> bool:
    if _is_transient_throttle(exc):
        return False
    status = _status_code(exc)
    if status in {400, 401, 403, 404}:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            'model not supported',
            'unsupported model',
            'model does not exist',
            'invalid model',
            'invalid schema',
            'unauthorized',
            'forbidden',
        )
    )


def _reset_after_seconds(exc: Exception) -> Optional[float]:
    """Trích số giây từ marker '(reset after Ns)' của gateway (throttle tạm thời).

    Gateway 9router local trả 400 kèm '(reset after 14s)' khi bị rate-limit ảnh —
    KHÔNG phải lỗi modality thật. Trả None nếu message không có marker này.
    """
    m = re.search(r'reset after\s+(\d+(?:\.\d+)?)\s*s', str(exc).lower())
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _is_transient_throttle(exc: Exception) -> bool:
    """400/429 do rate-limit tạm thời (có '(reset after Ns)' hoặc marker rate-limit).

    Phải retry với backoff, KHÔNG được coi là lỗi vĩnh viễn (PdfUnsupported/non-retryable).
    """
    if _reset_after_seconds(exc) is not None:
        return True
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ('rate limit', 'rate-limit', 'too many request', 'try again')
    )


def _is_pdf_unsupported(exc: Exception) -> bool:
    """Nhận diện lỗi model/provider không hỗ trợ đầu vào PDF/file (Req 6.1).

    Yêu cầu status 400 kết hợp với một marker trong message. Loại trừ throttle tạm
    thời (gateway trả 400 kèm '(reset after Ns)' khi rate-limit ảnh — phải retry).
    """
    if _status_code(exc) != 400:
        return False
    if _is_transient_throttle(exc):
        return False
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            'does not support',
            'pdf',
            'file input',
            'unsupported content',
            'modality',
            'image',
        )
    )


_global_tracker: Optional[CostTracker] = None


def get_tracker() -> CostTracker:
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = CostTracker()
    return _global_tracker


def reset_tracker(*_args: Any, **_kwargs: Any):
    global _global_tracker
    # Keep old positional/keyword arguments for compatibility, but ignore them.
    _global_tracker = CostTracker()


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
    """Gọi LLM với retry + usage tracking."""
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
            content = _strip_provider_artifacts(resp.choices[0].message.content or '')
            usage = getattr(resp, 'usage', None)
            tokens = (getattr(usage, 'total_tokens', 0) or 0) if usage else 0
            tracker.add(tokens=tokens, calls=0)
            return content
        except Exception as e:
            last_err = e
            if _is_non_retryable(e):
                raise NonRetryableLLMError(e) from e
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise last_err


def call_llm_with_pdf(system: str, user_content: list,
                      model: str = None,
                      temperature: float = cfg.GEN_TEMPERATURE,
                      max_tokens: int = cfg.GEN_MAX_TOKENS,
                      retries: int = cfg.LLM_RETRIES) -> str:
    """Giống call_llm nhưng message user chứa PDF (user_content là list part).

    - Lỗi không hỗ trợ PDF/file -> raise PdfUnsupportedError NGAY, không retry (Req 6.1).
    - Lỗi non-retryable khác -> NonRetryableLLMError (giữ hành vi cũ).
    - Lỗi tạm thời (429/5xx/timeout) -> retry tối đa `retries` lần rồi raise lỗi cuối (Req 6.2).
    """
    tracker = get_tracker()
    tracker.check()
    model = model or cfg.GENERATOR_MODEL
    if not cfg.has_llm_api_key():
        raise RuntimeError(cfg.missing_llm_api_key_message())
    last_err = None
    retries = max(1, int(retries or 1))
    throttle_retries = 0
    max_throttle_retries = max(1, int(getattr(cfg, 'LLM_THROTTLE_RETRIES', 6)))
    attempt = 0
    while True:
        try:
            client = _get_client()
            tracker.add(calls=1)
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user_content},
                ],
            )
            content = _strip_provider_artifacts(resp.choices[0].message.content or '')
            usage = getattr(resp, 'usage', None)
            tokens = (getattr(usage, 'total_tokens', 0) or 0) if usage else 0
            tracker.add(tokens=tokens, calls=0)
            return content
        except Exception as e:
            last_err = e
            # Throttle 400/429 (gateway '(reset after Ns)') -> đợi đúng thời gian
            # reset rồi thử lại; có ngân sách retry riêng, không tính vào `retries`.
            if _is_transient_throttle(e):
                if throttle_retries < max_throttle_retries:
                    throttle_retries += 1
                    wait = _reset_after_seconds(e)
                    time.sleep(min(30.0, (wait + 1.0) if wait else 2.0 ** throttle_retries))
                    continue
                raise last_err
            if _is_pdf_unsupported(e):
                raise PdfUnsupportedError(e) from e
            if _is_non_retryable(e):
                raise NonRetryableLLMError(e) from e
            attempt += 1
            if attempt < retries:
                time.sleep(2 ** (attempt - 1))
                continue
            raise last_err


def get_embeddings(texts):
    if not cfg.has_llm_api_key():
        raise RuntimeError(cfg.missing_llm_api_key_message())
    if cfg.LLM_PROVIDER == '9router':
        model = _resolve_9router_embedding_model()
        if not model:
            raise RuntimeError(
                '9router has no embedding model configured. '
                'Check GET /v1/models/embedding and set NINEROUTER_EMBEDDING_MODEL '
                'to one of the returned model ids.'
            )
        client = _get_client()
        resp = client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in resp.data]
    client = _get_client()
    resp = client.embeddings.create(model=cfg.EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in resp.data]


def _resolve_9router_embedding_model() -> str:
    configured = (getattr(cfg, 'NINEROUTER_EMBEDDING_MODEL', '') or '').strip()
    if configured:
        aliases = {
            # 9router may list gemini/embedding-001, but Gemini v1beta rejects
            # models/embedding-001 for embedContent. This routed id works.
            'gemini/embedding-001': 'gemini/gemini-embedding-001',
        }
        return aliases.get(configured, configured)
    try:
        import urllib.request

        base = cfg.active_llm_base_url().rstrip('/')
        req = urllib.request.Request(f'{base}/models/embedding')
        key = cfg.active_llm_api_key()
        if key:
            req.add_header('Authorization', f'Bearer {key}')
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - local/user-configured URL
            import json

            payload = json.loads(resp.read().decode('utf-8'))
    except Exception:
        return ''
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        return ''
    first = data[0]
    if isinstance(first, str):
        return first
    if isinstance(first, dict):
        return str(first.get('id') or first.get('model') or '')
    return ''

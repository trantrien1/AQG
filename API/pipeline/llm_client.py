"""LLM client + usage tracking."""
from __future__ import annotations

import datetime
import os
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


class ProviderQuotaExhausted(BudgetExceeded):
    """Nhà cung cấp chặn hạn mức, mốc mở lại còn xa.

    Kế thừa BudgetExceeded để mọi handler `except BudgetExceeded` sẵn có đều
    dừng run thay vì nuốt lỗi. Phân biệt với throttle ngắn ('reset after 14s'):
    cái đó đợi vài giây là chạy tiếp được, còn cái này đợi hàng giờ.

    Không có nó, một lượt benchmark hết quota vẫn chạy hết mọi slot của mọi ô,
    mỗi ô mất vài phút để sinh ra một artifact rỗng 0 token — vừa tốn thời gian
    vừa đẻ ra dữ liệu trông y hệt 'chất lượng kém'.
    """

    def __init__(self, original: Exception, reset_at: Optional[str] = None):
        self.original = original
        self.reset_at = reset_at
        super().__init__(
            f'provider quota exhausted'
            + (f'; mở lại sau {reset_at}' if reset_at else '')
            + f': {original}'
        )


# 429 kèm mốc mở lại xa hơn ngần này (giây) thì dừng hẳn thay vì chờ.
QUOTA_ABORT_AFTER_SECONDS = float(os.getenv('AQG_QUOTA_ABORT_AFTER_SECONDS', '120'))


def _reset_at_timestamp(exc: Exception) -> Optional[str]:
    """Trích mốc thời gian tuyệt đối 'try again after 2026-07-26 02:35:35'."""
    m = re.search(
        r'try again after\s+(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})',
        str(exc), re.IGNORECASE,
    )
    return m.group(1) if m else None


def _quota_wait_seconds(exc: Exception) -> Optional[float]:
    stamp = _reset_at_timestamp(exc)
    if not stamp:
        return None
    try:
        reset = datetime.datetime.fromisoformat(stamp.replace(' ', 'T'))
    except ValueError:
        return None
    return (reset - datetime.datetime.now()).total_seconds()


def _is_quota_exhausted(exc: Exception) -> bool:
    wait = _quota_wait_seconds(exc)
    return wait is not None and wait > QUOTA_ABORT_AFTER_SECONDS

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


class PdfNotNativeError(RuntimeError):
    """Model không tự đọc được PDF -> OpenRouter sẽ TRÍCH TEXT thay vì đọc trang.

    Đây là lỗi cứng chứ không phải cảnh báo: trích text phá bố cục, ký hiệu
    toán, bảng và hình — đúng những thứ mà việc đính nguyên tài liệu sinh ra để
    giữ. Nếu để nó âm thầm xảy ra thì lượt chạy vẫn ra câu hỏi nhưng cơ chế bám
    tài liệu không còn là cái được mô tả, và không đo nào phát hiện ra.
    """


_OPENROUTER_MODEL_CACHE: Dict[str, Any] = {}


def _openrouter_model_modalities(model: str) -> Optional[list]:
    """Trả về input_modalities của `model` theo OpenRouter, None nếu không tra được."""
    if not _OPENROUTER_MODEL_CACHE:
        import json
        import urllib.request
        url = cfg.OPENROUTER_BASE_URL.rstrip('/') + '/models'
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read())
        except Exception:                              # noqa: BLE001
            _OPENROUTER_MODEL_CACHE['__failed__'] = True
            return None
        for m in data.get('data') or []:
            arch = m.get('architecture') or {}
            _OPENROUTER_MODEL_CACHE[m.get('id') or ''] = (
                arch.get('input_modalities') or [])
    if _OPENROUTER_MODEL_CACHE.get('__failed__'):
        return None
    return _OPENROUTER_MODEL_CACHE.get(model)


def assert_pdf_native_support(model: str) -> Dict[str, Any]:
    """Kiểm TRƯỚC khi chạy rằng `model` tự đọc được PDF trên OpenRouter.

    Trả về dict mô tả cách tài liệu sẽ được xử lý (để ghi vào run manifest).
    Raise :class:`PdfNotNativeError` nếu model thiếu modality ``file`` — khi đó
    OpenRouter tụt xuống engine ``pdf-text``.

    Chỉ áp dụng cho provider openrouter ở chế độ đính file. Provider khác và
    chế độ ảnh trả về mô tả tương ứng mà không kiểm gì.
    """
    mode = str(getattr(cfg, 'PDF_ATTACH_MODE', 'image')).lower()
    info: Dict[str, Any] = {
        'provider': cfg.LLM_PROVIDER,
        'attach_mode': mode,
        'model': model,
    }
    if mode == 'image':
        info['document_handling'] = 'page_images'
        # Chế độ ảnh vẫn cần model NHÌN được. Model chỉ có text sẽ nhận một
        # message toàn ảnh mà không thấy gì, rồi bịa câu hỏi từ prompt — thất
        # bại im lặng đúng kiểu nguy hiểm nhất, nên chặn ngay ở đây.
        if cfg.LLM_PROVIDER == 'openrouter':
            mods = _openrouter_model_modalities(model)
            info['input_modalities'] = mods
            if mods is not None and 'image' not in mods:
                info['document_handling'] = 'blind_to_page_images'
                if cfg.OPENROUTER_REQUIRE_NATIVE_PDF:
                    raise PdfNotNativeError(
                        f'{model} không nhận đầu vào ảnh trên OpenRouter '
                        f'(modalities={mods}), nên các trang tài liệu gửi dạng '
                        f'ảnh sẽ KHÔNG tới được mô hình. Chọn model có '
                        f'modality image, hoặc dùng chế độ đính file.')
        return info
    if cfg.LLM_PROVIDER != 'openrouter':
        info['document_handling'] = 'raw_pdf'
        return info

    info['pdf_engine'] = cfg.OPENROUTER_PDF_ENGINE
    mods = _openrouter_model_modalities(model)
    info['input_modalities'] = mods
    if mods is None:
        info['document_handling'] = 'raw_pdf_unverified'
        return info
    if 'file' not in mods:
        info['document_handling'] = 'would_fall_back_to_text_extraction'
        if cfg.OPENROUTER_REQUIRE_NATIVE_PDF:
            raise PdfNotNativeError(
                f'{model} không nhận đầu vào file trên OpenRouter '
                f'(modalities={mods}), nên PDF sẽ bị TRÍCH XUẤT TEXT thay vì '
                f'đọc nguyên trang. Chọn model khác, hoặc đặt '
                f'AQG_PDF_ATTACH_MODE=image để gửi ảnh từng trang, hoặc đặt '
                f'AQG_OPENROUTER_REQUIRE_NATIVE_PDF=0 nếu cố ý chấp nhận.')
        return info
    info['document_handling'] = 'raw_pdf_native'
    return info


def _openrouter_extra_body() -> Dict[str, Any]:
    """Ghim engine xử lý PDF thay vì để OpenRouter tự chọn."""
    if cfg.LLM_PROVIDER != 'openrouter':
        return {}
    if str(getattr(cfg, 'PDF_ATTACH_MODE', 'image')).lower() == 'image':
        return {}
    return {'plugins': [{'id': 'file-parser',
                         'pdf': {'engine': cfg.OPENROUTER_PDF_ENGINE}}]}


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


def _response_text_or_raise(resp) -> str:
    """Lấy text từ response, ném lỗi KÈM thông báo của nhà cung cấp nếu rỗng.

    Nhà cung cấp báo lỗi ở thân response (không phải HTTP status) thì SDK dựng
    một object có ``choices=None``; ``resp.choices[0]`` khi đó ném "'NoneType'
    object is not subscriptable" — thông báo che mất nguyên nhân thật, và ở một
    phép quét nhiều mô hình nó bị đọc thành "mô hình sinh ra 0 câu".
    """
    choices = getattr(resp, 'choices', None)
    if not choices:
        err = getattr(resp, 'error', None)
        if err is None:
            err = (getattr(resp, 'model_extra', None) or {}).get('error')
        if isinstance(err, dict):
            detail = str(err.get('message') or err)
        else:
            detail = str(err) if err is not None else repr(resp)[:400]
        raise RuntimeError(f'nhà cung cấp không trả về lựa chọn nào: {detail}')
    message = getattr(choices[0], 'message', None)
    return _strip_provider_artifacts(getattr(message, 'content', None) or '')


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
            content = _response_text_or_raise(resp)
            usage = getattr(resp, 'usage', None)
            tokens = (getattr(usage, 'total_tokens', 0) or 0) if usage else 0
            tracker.add(tokens=tokens, calls=0)
            return content
        except Exception as e:
            last_err = e
            if _is_quota_exhausted(e):
                raise ProviderQuotaExhausted(e, _reset_at_timestamp(e)) from e
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
            kwargs: Dict[str, Any] = {}
            extra = _openrouter_extra_body()
            if extra:
                kwargs['extra_body'] = extra
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {'role': 'system', 'content': system},
                    {'role': 'user', 'content': user_content},
                ],
                **kwargs,
            )
            content = _response_text_or_raise(resp)
            usage = getattr(resp, 'usage', None)
            tokens = (getattr(usage, 'total_tokens', 0) or 0) if usage else 0
            tracker.add(tokens=tokens, calls=0)
            return content
        except Exception as e:
            last_err = e
            # Hết hạn mức tài khoản, mốc mở lại còn xa -> dừng hẳn. Phải kiểm
            # TRƯỚC nhánh throttle vì message cũng chứa 'try again'.
            if _is_quota_exhausted(e):
                raise ProviderQuotaExhausted(e, _reset_at_timestamp(e)) from e
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
    # Gemini được ưu tiên khi có key: provider chat (vd chat2api) thường không
    # có endpoint embeddings, còn bắt trùng ngân hàng câu hỏi thì cần vector.
    if getattr(cfg, 'GEMINI_API_KEY', ''):
        return _gemini_embeddings(list(texts))
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


def _gemini_embeddings(texts):
    """Embedding qua Google Generative Language API (batchEmbedContents).

    Batch tối đa 100 text/request theo giới hạn API; texts dài hơn được cắt lô.
    """
    import httpx

    model = cfg.GEMINI_EMBEDDING_MODEL or 'gemini-embedding-001'
    url = (
        'https://generativelanguage.googleapis.com/v1beta/'
        f'models/{model}:batchEmbedContents'
    )
    out = []
    for start in range(0, len(texts), 100):
        chunk = texts[start:start + 100]
        payload = {
            'requests': [
                {
                    'model': f'models/{model}',
                    'content': {'parts': [{'text': str(t or ' ')[:8000]}]},
                }
                for t in chunk
            ]
        }
        resp = httpx.post(
            url,
            json=payload,
            headers={'x-goog-api-key': cfg.GEMINI_API_KEY},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = data.get('embeddings') or []
        if len(embeddings) != len(chunk):
            raise RuntimeError(
                f'Gemini embeddings: expected {len(chunk)} vectors, '
                f'got {len(embeddings)}'
            )
        out.extend([e.get('values') or [] for e in embeddings])
    return out


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

"""Hết hạn mức nhà cung cấp phải DỪNG run, không nghiền tiếp để đẻ artifact rỗng.

Bối cảnh: lượt quét 2026-07-25 hết quota gpt-4o sau 3 ô. Tám ô còn lại vẫn chạy
đủ mọi slot, mỗi ô ~200 giây, và ghi ra artifact 0 câu / 0 token. Hậu quả kép:
mất ~27 phút vô ích, và tám ô rỗng đó nếu bị gộp vào mẫu số sẽ kéo tỉ lệ nhận
xuống một con số trông y hệt "chất lượng kém".

Phân biệt hai loại 429 là mấu chốt:
  * throttle ngắn — "(reset after 14s)" — đợi rồi chạy tiếp, ĐÚNG là nên retry;
  * hết hạn mức  — "try again after 2026-07-26 02:35:35" — đợi hàng giờ, phải dừng.
"""
from __future__ import annotations

import datetime

import pytest

from pipeline import llm_client as lc


def _err(message: str, status: int = 429):
    exc = RuntimeError(message)
    exc.status_code = status
    return exc


def _future(seconds: int) -> str:
    stamp = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
    return stamp.strftime('%Y-%m-%d %H:%M:%S')


# ---- Nhận diện ----

def test_absolute_reset_timestamp_is_parsed():
    exc = _err("Request limit exceeded. You can continue with the default model "
               "now, or try again after 2026-07-26 02:35:35")
    assert lc._reset_at_timestamp(exc) == '2026-07-26 02:35:35'


def test_distant_reset_counts_as_quota_exhausted():
    assert lc._is_quota_exhausted(_err(f'try again after {_future(7200)}')) is True


def test_near_reset_is_not_quota_exhausted():
    """Mốc mở lại trong vòng ngưỡng thì vẫn đáng chờ, không dừng run."""
    assert lc._is_quota_exhausted(_err(f'try again after {_future(30)}')) is False


def test_past_reset_is_not_quota_exhausted():
    past = (datetime.datetime.now() - datetime.timedelta(hours=1)
            ).strftime('%Y-%m-%d %H:%M:%S')
    assert lc._is_quota_exhausted(_err(f'try again after {past}')) is False


def test_short_throttle_is_not_quota_exhausted():
    exc = _err('rate limited (reset after 14s)', status=400)
    assert lc._is_quota_exhausted(exc) is False
    assert lc._is_transient_throttle(exc) is True


def test_unrelated_error_is_not_quota_exhausted():
    assert lc._is_quota_exhausted(_err('bad gateway', status=502)) is False


# ---- Hành vi của client ----

def test_call_llm_raises_quota_exhausted_without_retrying(monkeypatch):
    calls = []

    class _FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            raise _err(f'Request limit exceeded, try again after {_future(7200)}')

    class _FakeClient:
        chat = type('c', (), {'completions': _FakeCompletions()})()

    monkeypatch.setattr(lc, '_get_client', lambda: _FakeClient())
    monkeypatch.setattr(lc.cfg, 'has_llm_api_key', lambda: True)

    with pytest.raises(lc.ProviderQuotaExhausted) as info:
        lc.call_llm('s', 'u', model='m', retries=5)
    assert len(calls) == 1, 'không được thử lại khi đã hết hạn mức'
    assert info.value.reset_at


def test_pdf_call_raises_quota_exhausted_without_sleeping(monkeypatch):
    slept = []

    class _FakeCompletions:
        def create(self, **kwargs):
            raise _err(f'Request limit exceeded, try again after {_future(7200)}')

    class _FakeClient:
        chat = type('c', (), {'completions': _FakeCompletions()})()

    monkeypatch.setattr(lc, '_get_client', lambda: _FakeClient())
    monkeypatch.setattr(lc.cfg, 'has_llm_api_key', lambda: True)
    monkeypatch.setattr(lc.time, 'sleep', lambda s: slept.append(s))

    with pytest.raises(lc.ProviderQuotaExhausted):
        lc.call_llm_with_pdf('s', [{'type': 'text', 'text': 'u'}], model='m')
    assert slept == [], 'không được ngủ chờ mốc mở lại cách hàng giờ'


def test_quota_error_is_a_budget_error():
    """Mọi handler `except BudgetExceeded` sẵn có phải bắt được nó và dừng run."""
    assert issubclass(lc.ProviderQuotaExhausted, lc.BudgetExceeded)


def test_writer_agent_propagates_quota_error(monkeypatch):
    """Agent không được nuốt lỗi này vào danh sách `errors` rồi trả 0 candidate."""
    from pipeline.direct_pdf.agents.messages import PdfWriteRequest
    from pipeline.direct_pdf.agents.pdf_writer_agent import PdfWriterAgent

    agent = PdfWriterAgent(use_skills=False)
    monkeypatch.setattr(
        agent, '_call_pdf',
        lambda *a, **k: (_ for _ in ()).throw(
            lc.ProviderQuotaExhausted(RuntimeError('429'), '2026-07-26 02:35:35')),
    )
    with pytest.raises(lc.ProviderQuotaExhausted):
        agent.run(PdfWriteRequest(attachment_parts=[], slot={'slot_id': 's1'}))


# ---- Driver của bộ quét ----

def test_suite_driver_has_a_distinct_exit_code_for_quota():
    import importlib.util
    import pathlib
    import sys

    script = pathlib.Path(__file__).resolve().parent.parent / 'scripts' / 'bench_suite.py'
    spec = importlib.util.spec_from_file_location('bench_suite_quota', script)
    module = importlib.util.module_from_spec(spec)
    sys.modules['bench_suite_quota'] = module
    spec.loader.exec_module(module)
    assert module.EXIT_QUOTA_EXHAUSTED not in (0, 1, 2)


def test_suite_skips_cells_that_already_have_data(tmp_path):
    import importlib.util
    import json
    import pathlib
    import sys

    script = pathlib.Path(__file__).resolve().parent.parent / 'scripts' / 'bench_suite.py'
    spec = importlib.util.spec_from_file_location('bench_suite_resume', script)
    module = importlib.util.module_from_spec(spec)
    sys.modules['bench_suite_resume'] = module
    spec.loader.exec_module(module)

    done = tmp_path / 'done.json'
    done.write_text(json.dumps({'metadata': {'cost': {'tokens': 1234}}}), encoding='utf-8')
    empty = tmp_path / 'empty.json'
    empty.write_text(json.dumps({'metadata': {'cost': {'tokens': 0}}}), encoding='utf-8')

    assert module._has_usable_artifact(done) is True
    # Ô rỗng do hết quota chính là ô cần chạy lại, không được coi là đã xong.
    assert module._has_usable_artifact(empty) is False
    assert module._has_usable_artifact(tmp_path / 'missing.json') is False

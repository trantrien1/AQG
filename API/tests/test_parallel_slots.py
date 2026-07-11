"""Test sinh song song slot theo wave trong DirectPdfOrchestrator.

_process_slot được mock (không gọi LLM) để kiểm tra:
- các slot trong một wave THẬT SỰ chạy đồng thời (max concurrent > 1);
- kết quả đủ số câu, không sinh thừa, dedup vẫn hoạt động;
- rải CĐR cân bằng kể cả khi có slot fail giữa chừng (_pick_outcome_balanced).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

import pytest

from pipeline import config as cfg
from pipeline.direct_pdf.agents.pdf_orchestrator import (
    DirectPdfOrchestrator,
    _outcome_key,
    _pick_outcome_balanced,
)


FAKE_PARTS = [{'type': 'image_url', 'image_url': {'url': 'data:'}}]

OUTCOMES = [
    {'code': 'CDR1', 'description': 'Tính tích phân xác định cơ bản'},
    {'code': 'CDR2', 'description': 'Ứng dụng tích phân tính diện tích'},
]


def _fake_candidate(tag: str) -> Dict[str, Any]:
    return {
        'question_text': f'Tính \\(I_{{{tag}}}=\\int_0^{{{tag}}} x\\,dx\\) bằng bao nhiêu?',
        'answer_text': f'\\(\\frac{{{tag}^2}}{{2}}\\)',
        'answer_explanation_text': 'Nguyên hàm x^2/2, thế cận là xong.',
        'source_quote_text': 'Tích phân hàm lũy thừa trên đoạn cho trước.',
        'distractors': [
            {'distractor_text': f'\\({tag}\\)', 'distractor_category_text': 'e1',
             'distractor_explanation_text': 'Quên chia 2.'},
            {'distractor_text': f'\\(2\\cdot {tag}\\)', 'distractor_category_text': 'e2',
             'distractor_explanation_text': 'Nhân đôi nhầm.'},
            {'distractor_text': '\\(0\\)', 'distractor_category_text': 'e3',
             'distractor_explanation_text': 'Thế nhầm cận.'},
        ],
        '_verification': {'engine': 'numeric_eval', 'verified': True,
                          'detail': 'ok'},
        '_quality': 0.9,
        '_grounding': 0.9,
    }


def _make_orchestrator(monkeypatch, process_slot, parallel=3):
    monkeypatch.setattr(cfg, 'DIRECT_PDF_PARALLEL_SLOTS', parallel)
    orch = DirectPdfOrchestrator(model='gpt-4o', use_skills=False)
    monkeypatch.setattr(orch, '_process_slot', process_slot)
    return orch


# ---- _pick_outcome_balanced ----

def test_pick_outcome_balanced_matches_round_robin_khi_thanh_cong():
    counts: Dict[str, int] = {}
    picked = []
    for _ in range(4):
        o = _pick_outcome_balanced(OUTCOMES, counts)
        counts[_outcome_key(o)] = counts.get(_outcome_key(o), 0) + 1
        picked.append(o['code'])
    assert picked == ['CDR1', 'CDR2', 'CDR1', 'CDR2']


def test_pick_outcome_balanced_bu_cdr_hut_khi_slot_fail():
    counts: Dict[str, int] = {}
    first = _pick_outcome_balanced(OUTCOMES, counts)   # CDR1
    counts[_outcome_key(first)] = 1
    second = _pick_outcome_balanced(OUTCOMES, counts)  # CDR2
    counts[_outcome_key(second)] = 1
    # slot CDR1 fail -> release
    counts[_outcome_key(first)] -= 1
    # wave sau phải nhắm lại CDR1 (đang hụt), không nhảy sang CDR2
    assert _pick_outcome_balanced(OUTCOMES, counts)['code'] == 'CDR1'


def test_pick_outcome_balanced_empty_and_invalid():
    assert _pick_outcome_balanced(None, {}) is None
    assert _pick_outcome_balanced([], {}) is None
    assert _pick_outcome_balanced([{'code': 'X', 'description': ''}], {}) is None


# ---- generate() song song ----

def test_generate_parallel_runs_slots_concurrently(monkeypatch):
    active = {'now': 0, 'max': 0}
    lock = threading.Lock()

    def fake_process(slot, parts, avoid):
        with lock:
            active['now'] += 1
            active['max'] = max(active['max'], active['now'])
        time.sleep(0.25)
        with lock:
            active['now'] -= 1
        return _fake_candidate(slot['slot_id']), 0, 0

    orch = _make_orchestrator(monkeypatch, fake_process, parallel=3)
    t0 = time.monotonic()
    result = orch.generate(
        pdf_path='unused.pdf', requested_count=3, model='gpt-4o',
        attachment_parts=FAKE_PARTS, learning_outcomes=OUTCOMES,
    )
    elapsed = time.monotonic() - t0

    assert result.accepted_count == 3
    assert not result.is_partial
    assert active['max'] >= 2, 'các slot trong wave phải chạy đồng thời'
    # tuần tự sẽ mất >= 0.75s; song song 3 luồng chỉ ~0.25s
    assert elapsed < 0.7, f'quá chậm ({elapsed:.2f}s) — không song song?'
    # CĐR phủ đều: 3 câu / 2 CĐR -> chênh lệch tối đa 1
    codes = [q['learning_outcomes'][0] for q in result.questions]
    assert abs(codes.count('CDR1') - codes.count('CDR2')) <= 1


def test_generate_parallel_khong_sinh_thua_cau(monkeypatch):
    calls = {'n': 0}
    lock = threading.Lock()

    def fake_process(slot, parts, avoid):
        with lock:
            calls['n'] += 1
        return _fake_candidate(slot['slot_id']), 0, 0

    orch = _make_orchestrator(monkeypatch, fake_process, parallel=3)
    result = orch.generate(
        pdf_path='unused.pdf', requested_count=4, model='gpt-4o',
        attachment_parts=FAKE_PARTS,
    )
    assert result.accepted_count == 4
    assert len(result.questions) == 4
    # wave_size = min(parallel, remaining): 3 + 1 = đúng 4 lần gọi, không thừa
    assert calls['n'] == 4


def test_generate_parallel_retry_khi_slot_fail_va_giu_cdr(monkeypatch):
    """Slot đầu nhắm CDR1 fail 1 lần -> wave sau phải bù CDR1, phủ vẫn đều."""
    state = {'cdr1_failed': False}
    lock = threading.Lock()

    def fake_process(slot, parts, avoid):
        outcome = slot.get('_learning_outcome') or {}
        with lock:
            if outcome.get('code') == 'CDR1' and not state['cdr1_failed']:
                state['cdr1_failed'] = True
                return None, 1, 0
        return _fake_candidate(slot['slot_id']), 0, 0

    orch = _make_orchestrator(monkeypatch, fake_process, parallel=2)
    result = orch.generate(
        pdf_path='unused.pdf', requested_count=4, model='gpt-4o',
        attachment_parts=FAKE_PARTS, learning_outcomes=OUTCOMES,
    )
    assert result.accepted_count == 4
    codes = [q['learning_outcomes'][0] for q in result.questions]
    assert codes.count('CDR1') == 2 and codes.count('CDR2') == 2


def test_generate_parallel_dedup_van_chan_cau_trung(monkeypatch):
    """Hai slot cùng wave trả cùng stem -> chỉ giữ 1, slot sau retry bù."""
    calls = {'n': 0}
    lock = threading.Lock()

    def fake_process(slot, parts, avoid):
        with lock:
            calls['n'] += 1
            n = calls['n']
        # 2 call đầu trả trùng nhau, các call sau unique
        tag = 'dup' if n <= 2 else f'u{n}'
        return _fake_candidate(tag), 0, 0

    orch = _make_orchestrator(monkeypatch, fake_process, parallel=2)
    result = orch.generate(
        pdf_path='unused.pdf', requested_count=2, model='gpt-4o',
        attachment_parts=FAKE_PARTS,
    )
    assert result.accepted_count == 2
    stems = [q['stem'] for q in result.questions]
    assert len(set(stems)) == 2


def test_generate_parallel_dung_som_khi_empty_streak(monkeypatch):
    def fake_process(slot, parts, avoid):
        return None, 1, 0

    orch = _make_orchestrator(monkeypatch, fake_process, parallel=3)
    result = orch.generate(
        pdf_path='unused.pdf', requested_count=10, model='gpt-4o',
        attachment_parts=FAKE_PARTS,
    )
    assert result.accepted_count == 0
    assert result.is_partial


def test_generate_parallel_progress_events_tu_thread_chinh(monkeypatch):
    """Mọi progress event phải phát từ thread chính (jobs.py không cần khoá)."""
    main_thread = threading.get_ident()
    event_threads: List[int] = []
    events: List[str] = []

    def fake_process(slot, parts, avoid):
        return _fake_candidate(slot['slot_id']), 0, 0

    def on_progress(event: Dict[str, Any]) -> None:
        event_threads.append(threading.get_ident())
        events.append(event.get('stage'))

    orch = _make_orchestrator(monkeypatch, fake_process, parallel=3)
    orch.generate(
        pdf_path='unused.pdf', requested_count=3, model='gpt-4o',
        attachment_parts=FAKE_PARTS, progress_callback=on_progress,
    )
    assert all(t == main_thread for t in event_threads)
    assert events.count('question_accepted') == 3
    assert events[-1] == 'generation_finished'

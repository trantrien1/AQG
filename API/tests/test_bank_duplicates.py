"""Test bắt trùng ngân hàng câu hỏi với embedding (đường Gemini qua env).

get_embeddings được mock — kiểm tra logic so trùng semantic + backfill vector
cho câu cũ, không gọi mạng.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from pipeline import config as cfg
from web import bank_store


Q_GOC = {
    'question_id': 'q1',
    'stem': 'Tính tích phân \\(\\int_0^1 x\\,dx\\).',
    'options': [
        {'key': 'A', 'text': '1/2'}, {'key': 'B', 'text': '1'},
        {'key': 'C', 'text': '2'}, {'key': 'D', 'text': '0'},
    ],
    'answer_key': 'A',
    'topic': 'Tích phân',
}

# Diễn đạt khác hẳn (near-stem không bắt được) nhưng cùng ý — chỉ semantic bắt.
Q_TRUNG_Y = {
    'question_id': 'q2',
    'stem': 'Diện tích hình phẳng giới hạn bởi y=x, trục hoành, x=0 và x=1 là?',
    'options': [
        {'key': 'A', 'text': '1/2'}, {'key': 'B', 'text': '1'},
        {'key': 'C', 'text': '1/4'}, {'key': 'D', 'text': '2'},
    ],
    'answer_key': 'A',
    'topic': 'Ứng dụng tích phân',
}

Q_KHAC = {
    'question_id': 'q3',
    'stem': 'Giải phương trình \\(2^x = 8\\).',
    'options': [
        {'key': 'A', 'text': '3'}, {'key': 'B', 'text': '2'},
        {'key': 'C', 'text': '4'}, {'key': 'D', 'text': '1'},
    ],
    'answer_key': 'A',
    'topic': 'Mũ và logarit',
}

# Vector giả: 2 câu tích phân cùng hướng, câu mũ-log vuông góc.
_FAKE_VECTORS = {
    'tich phan': [1.0, 0.05, 0.0],
    'dien tich': [0.98, 0.05, 0.0],
    'phuong trinh': [0.0, 0.0, 1.0],
}


def _fake_embed(texts: List[str]) -> List[List[float]]:
    out = []
    for text in texts:
        norm = bank_store.normalize_text(text)
        for marker, vec in _FAKE_VECTORS.items():
            if marker in norm:
                out.append(list(vec))
                break
        else:
            out.append([0.0, 1.0, 0.0])
    return out


@pytest.fixture()
def bank(tmp_path, monkeypatch):
    monkeypatch.setattr(bank_store, 'DB_PATH', tmp_path / 'bank.db')
    monkeypatch.setattr(bank_store, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(cfg, 'GEMINI_API_KEY', 'test-key')
    monkeypatch.setattr(bank_store, 'get_embeddings', _fake_embed)
    return bank_store.create_bank('bank-test')


def test_semantic_duplicate_bi_bat_va_skip(bank):
    r1 = bank_store.add_questions(bank['bank_id'], [Q_GOC])
    assert len(r1['added']) == 1 and r1['semantic_enabled']

    r2 = bank_store.add_questions(bank['bank_id'], [Q_TRUNG_Y, Q_KHAC])
    skipped_ids = [s['question_id'] for s in r2['skipped']]
    added_ids = [a['question_id'] for a in r2['added']]
    assert skipped_ids == ['q2'], 'câu trùng ý phải bị bỏ qua'
    assert added_ids == ['q3'], 'câu khác chủ đề phải được thêm'
    reasons = {r['type'] for r in r2['skipped'][0]['duplicates'][0]['reasons']}
    assert 'semantic' in reasons


def test_backfill_embedding_cho_cau_cu(bank, monkeypatch):
    # Câu gốc được lưu khi embedding provider lỗi -> không có vector.
    def _boom(_texts):
        raise RuntimeError('embedding down')

    monkeypatch.setattr(bank_store, 'get_embeddings', _boom)
    r1 = bank_store.add_questions(bank['bank_id'], [Q_GOC])
    assert len(r1['added']) == 1 and not r1['semantic_enabled']

    # Provider sống lại (user vừa điền GEMINI_API_KEY): câu cũ phải được bù
    # vector ngay trong lần so trùng sau, và semantic bắt được câu trùng ý.
    monkeypatch.setattr(bank_store, 'get_embeddings', _fake_embed)
    duplicates, err, _ = bank_store.find_duplicates(bank['bank_id'], Q_TRUNG_Y)
    assert err is None
    assert duplicates, 'semantic phải bắt được sau khi backfill vector'
    reasons = {r['type'] for d in duplicates for r in d['reasons']}
    assert 'semantic' in reasons


def test_exact_stem_van_bat_khi_khong_co_embedding(bank, monkeypatch):
    def _boom(_texts):
        raise RuntimeError('embedding down')

    monkeypatch.setattr(bank_store, 'get_embeddings', _boom)
    bank_store.add_questions(bank['bank_id'], [Q_GOC])
    r = bank_store.add_questions(bank['bank_id'], [Q_GOC])
    assert len(r['skipped']) == 1
    reasons = {x['type'] for x in r['skipped'][0]['duplicates'][0]['reasons']}
    assert 'exact_stem' in reasons

"""Khung đánh giá: metric, manifest, hiệu chỉnh ngưỡng, chọn trang.

Điểm được kiểm gắt nhất ở đây là ranh giới giữa "máy nói đã kiểm" và "đáp án
đúng thật": không có nhãn ngoài thì correctness phải trả về None kèm lý do, chứ
không được thay bằng một proxy nào khác.
"""
from __future__ import annotations

import json

import pytest

from pipeline.eval_metrics import (
    compute_metrics, load_ground_truth, metrics_from_run_file,
)
from pipeline.verification_status import VerificationStatus


def _q(qid, status, *, machine_verifiable=True, engine='numeric_eval',
       grounding=0.9, quality=0.9, review='pending_review'):
    return {
        'question_id': qid,
        'review_status': review,
        'cognitive_level': 'Vận dụng',
        'difficulty_target': 0.7,
        'difficulty_estimated': 0.68,
        'difficulty_alignment': 1.0,
        'verification': {
            'engine': engine,
            'status': status,
            'machine_verifiable': machine_verifiable,
            'independent': {'attempted': True, 'definite':
                            status == VerificationStatus.INDEPENDENTLY_VERIFIED},
        },
        'judging': {
            'grounding': grounding, 'quality': quality, 'bloom_alignment': 0.9,
            'quality_traits': {
                'answer_uniqueness': {'score': 1.0},
                'distractor_plausibility': {'score': 0.8},
            },
        },
    }


# ---- Correctness chỉ tồn tại khi có nhãn ngoài ----

def test_correctness_is_unavailable_without_labels():
    metrics = compute_metrics([_q('a', VerificationStatus.INDEPENDENTLY_VERIFIED)])
    correctness = metrics.correctness
    assert correctness['independently_correct_answer_rate']['value'] is None
    reason = correctness['independently_correct_answer_rate']['unavailable_reason']
    assert 'ground-truth' in reason
    assert correctness['verifier_false_positive_rate']['value'] is None


def test_independently_verified_rate_is_not_called_correctness():
    """Tỉ lệ xác nhận độc lập nằm ở nhóm verification, KHÔNG ở nhóm correctness."""
    metrics = compute_metrics([_q('a', VerificationStatus.INDEPENDENTLY_VERIFIED)])
    assert metrics.verification['independently_verified_rate']['value'] == 1.0
    assert metrics.correctness['independently_correct_answer_rate']['value'] is None


def test_false_positive_rate_counts_certified_wrong_keys():
    questions = [
        _q('ok1', VerificationStatus.CONSISTENCY_CONFIRMED),
        _q('bad_slipped', VerificationStatus.CONSISTENCY_CONFIRMED),
        _q('bad_caught', VerificationStatus.MISMATCH, review='needs_revision'),
        _q('ok_flagged', VerificationStatus.MISMATCH, review='needs_revision'),
    ]
    ground_truth = {
        'ok1': {'key_correct': True}, 'bad_slipped': {'key_correct': False},
        'bad_caught': {'key_correct': False}, 'ok_flagged': {'key_correct': True},
    }
    correctness = compute_metrics(questions, ground_truth=ground_truth).correctness
    assert correctness['labelled'] == 4
    assert correctness['independently_correct_answer_rate']['value'] == 0.5
    # Một trong hai key sai được cấp nhãn "đã kiểm" ⇒ FP = 1/2.
    assert correctness['verifier_false_positive_rate'] == {'value': 0.5, 'n': 1, 'of': 2}
    # Một trong hai key đúng bị gắn cờ ⇒ FN = 1/2.
    assert correctness['verifier_false_negative_rate'] == {'value': 0.5, 'n': 1, 'of': 2}


def test_unlabelled_items_are_reported_not_assumed_correct():
    questions = [_q('a', VerificationStatus.CONSISTENCY_CONFIRMED),
                 _q('b', VerificationStatus.CONSISTENCY_CONFIRMED)]
    correctness = compute_metrics(
        questions, ground_truth={'a': {'key_correct': True}}).correctness
    assert correctness['labelled'] == 1
    assert correctness['unlabelled'] == 1
    assert correctness['independently_correct_answer_rate']['of'] == 1


# ---- Độ phủ và chi phí ----

def test_machine_verifiable_coverage_and_conceptual_share():
    questions = [
        _q('a', VerificationStatus.CONSISTENCY_CONFIRMED),
        _q('b', VerificationStatus.NON_VERIFIABLE,
           machine_verifiable=False, engine='none'),
    ]
    verification = compute_metrics(questions).verification
    assert verification['machine_verifiable_coverage']['value'] == 0.5
    assert verification['conceptual_share']['value'] == 0.5


def test_admission_rate_uses_all_candidates():
    counts = compute_metrics(
        [_q('a', VerificationStatus.CONSISTENCY_CONFIRMED)],
        [{'reject_reason_code': 'quality_low'}, {'reject_reason_code': 'duplicate'}],
        requested=1,
    ).counts
    assert counts['admission_rate'] == {'value': round(1 / 3, 4), 'n': 1, 'of': 3}
    assert counts['delivery_rate_vs_requested']['value'] == 1.0
    assert counts['reject_reasons'] == {'quality_low': 1, 'duplicate': 1}


def test_counts_use_pipeline_delivered_not_accepted():
    """Từ 'accepted' bị bỏ có chủ đích: chưa ai duyệt thì chưa gọi là chấp nhận."""
    counts = compute_metrics([_q('a', VerificationStatus.NON_VERIFIABLE)]).counts
    assert 'pipeline_delivered' in counts
    assert 'accepted' not in counts


def test_cost_metrics():
    cost = compute_metrics(
        [_q('a', VerificationStatus.CONSISTENCY_CONFIRMED),
         _q('b', VerificationStatus.CONSISTENCY_CONFIRMED)],
        cost={'tokens': 1000, 'calls': 8}, duration_seconds=60.0,
    ).cost
    assert cost['tokens_per_delivered'] == 500.0
    assert cost['calls_per_delivered'] == 4.0
    assert cost['seconds_per_delivered'] == 30.0


# ---- Record cũ (không có `status`) vẫn đọc được ----

def test_legacy_records_never_map_to_independently_verified():
    legacy = {'question_id': 'old', 'verification': {'engine': 'numeric_eval',
                                                     'verified': True}}
    verification = compute_metrics([legacy]).verification
    assert verification['status_distribution'][
        VerificationStatus.INDEPENDENTLY_VERIFIED] == 0
    assert verification['status_distribution'][
        VerificationStatus.CONSISTENCY_CONFIRMED] == 1


def test_ground_truth_loader_rejects_incomplete_labels(tmp_path):
    path = tmp_path / 'gt.json'
    path.write_text(json.dumps({'source': 'x', 'labels': {'a': {'note': 'thiếu'}}}),
                    encoding='utf-8')
    with pytest.raises(ValueError):
        load_ground_truth(path)


def test_metrics_from_run_file(tmp_path):
    path = tmp_path / 'run.json'
    path.write_text(json.dumps({
        'metadata': {'cost': {'tokens': 100, 'calls': 2},
                     'duration_seconds': 10.0, 'requested_questions': 1},
        'questions': [_q('a', VerificationStatus.CONSISTENCY_CONFIRMED)],
        'rejected': [],
    }, ensure_ascii=False), encoding='utf-8')
    metrics = metrics_from_run_file(path)
    assert metrics.counts['pipeline_delivered'] == 1
    assert metrics.cost['tokens'] == 100


# ---- Manifest ----

def test_manifest_captures_everything_needed_to_repeat_a_run():
    from pipeline.run_manifest import build_manifest
    manifest = build_manifest(label='test').to_dict()
    for key in ('seed', 'models', 'prompt_version', 'verifier_version',
                'independent_prompt_version', 'thresholds', 'mechanisms',
                'code', 'environment'):
        assert key in manifest, key
    assert manifest['models']['generator']
    assert manifest['thresholds']['GROUNDING_THRESHOLD'] is not None


def test_manifest_hashes_documents(tmp_path):
    from pipeline.run_manifest import build_manifest
    doc = tmp_path / 'doc.pdf'
    doc.write_bytes(b'%PDF-1.4 fake')
    manifest = build_manifest(documents=[str(doc)])
    assert len(manifest.documents[0]['sha256']) == 64
    assert manifest.documents[0]['bytes'] == 13


def test_manifest_names_its_own_reproducibility_gaps():
    from pipeline.run_manifest import build_manifest, reproducibility_gaps
    manifest = build_manifest()
    manifest.generation['temperature'] = 0.45
    manifest.generation['parallel_slots'] = 3
    gaps = reproducibility_gaps(manifest)
    assert any('nhiệt độ' in g for g in gaps)
    assert any('song song' in g for g in gaps)

    manifest.generation['temperature'] = 0.0
    manifest.generation['parallel_slots'] = 1
    manifest.code = {'commit': 'abc', 'dirty': False}
    manifest.documents = [{'sha256': 'x'}]
    manifest.models['revisions'] = {}
    assert any('snapshot' in g for g in reproducibility_gaps(manifest))

    manifest.models['revisions'] = {manifest.models['generator']: 'deadbeef'}
    assert reproducibility_gaps(manifest) == []


# ---- Hiệu chỉnh ngưỡng ----

def _labelled(score, usable):
    return {'record': {'judging': {'grounding': score}}, 'usable': usable}


def test_calibration_finds_a_separating_threshold():
    from pipeline.calibration import calibrate
    items = ([_labelled(0.9 - 0.01*i, True) for i in range(20)]
             + [_labelled(0.3 - 0.01*i, False) for i in range(20)])
    report = calibrate(items, thresholds=['GROUNDING_THRESHOLD'])
    fit = report['thresholds']['GROUNDING_THRESHOLD']
    assert fit['best_score'] == 1.0
    assert 0.3 < fit['suggested'] <= 0.72
    assert fit['n_usable'] == 40


def test_calibration_warns_on_small_samples():
    from pipeline.calibration import calibrate
    items = [_labelled(0.9, True), _labelled(0.2, False)]
    report = calibrate(items, thresholds=['GROUNDING_THRESHOLD'])
    assert any('khớp quá mức' in w for w in report['warnings'])


def test_calibration_never_writes_config():
    from pipeline import config as cfg
    from pipeline.calibration import calibrate
    before = cfg.GROUNDING_THRESHOLD
    items = ([_labelled(0.9, True)]*20) + ([_labelled(0.1, False)]*20)
    calibrate(items, thresholds=['GROUNDING_THRESHOLD'])
    assert cfg.GROUNDING_THRESHOLD == before


def test_calibration_lists_thresholds_it_cannot_fit_yet():
    from pipeline.calibration import calibrate
    report = calibrate([_labelled(0.9, True)]*2)
    assert 'QUESTION_DEDUP_THRESHOLD' in report['not_yet_calibratable']
    assert report['not_yet_calibratable']['QUESTION_DEDUP_THRESHOLD']


def test_every_calibratable_config_threshold_is_accounted_for():
    """Ngưỡng nào trong config cũng phải hoặc dò được, hoặc nêu lý do chưa dò."""
    from pipeline import config as cfg
    from pipeline.calibration import NOT_YET_CALIBRATABLE, SCORE_ACCESSORS
    handled = set(SCORE_ACCESSORS) | set(NOT_YET_CALIBRATABLE)
    missing = set(cfg.CALIBRATABLE_THRESHOLDS) - handled
    assert not missing, f'ngưỡng chưa được xử lý trong calibration: {missing}'


# ---- Chọn trang / cache ----

def test_page_selection_is_off_by_default_and_traced():
    from pipeline.direct_pdf.page_selection import select_pages
    parts = [{'type': 'image_url'} for _ in range(10)]
    kept, trace = select_pages(parts, ['text']*10, 'tích phân', enabled=False)
    assert len(kept) == 10
    assert trace['pages_available'] == 10
    assert trace['pages_sent'] == 10
    assert trace['localization_enabled'] is False


def test_page_selection_reduces_pages_when_enabled():
    from pipeline.direct_pdf.page_selection import select_pages
    parts = [{'type': 'image_url', 'i': i} for i in range(10)]
    texts = ['nội dung khác']*10
    texts[3] = 'tích phân xác định và ứng dụng tính thể tích'
    texts[7] = 'tích phân từng phần'
    kept, trace = select_pages(parts, texts, 'tích phân thể tích',
                               enabled=True, min_pages=2, max_pages=3)
    assert len(kept) < 10
    assert trace['pages_sent'] == len(kept)
    assert 3 in trace['selected_indices']


def test_page_selection_trace_supports_cost_quality_comparison():
    from pipeline.direct_pdf.page_selection import selection_trace
    rolled = selection_trace([
        {'pages_available': 10, 'pages_sent': 4, 'localization_enabled': True},
        {'pages_available': 10, 'pages_sent': 6, 'localization_enabled': True},
    ])
    assert rolled['pages_sent_total'] == 10
    assert rolled['page_reduction'] == 0.5


def test_page_cache_avoids_a_second_render(tmp_path, monkeypatch):
    from pipeline.direct_pdf import page_selection
    monkeypatch.setattr(page_selection, '_CACHE_ROOT', tmp_path)
    calls = []

    def _builder(pdf_bytes, filename, prompt, *, dpi, max_pages):
        calls.append(1)
        return [{'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': 'data:...'}}]

    for _ in range(2):
        parts = page_selection.cached_page_parts(
            b'fake-pdf', 'x.pdf', dpi=120, max_pages=30, builder=_builder)
        assert len(parts) == 1
        assert parts[0]['type'] == 'image_url'
    assert len(calls) == 1

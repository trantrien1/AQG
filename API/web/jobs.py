"""Background workers for Direct_PDF_Mode jobs."""
from __future__ import annotations

from collections import Counter
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from pipeline import config as cfg
from pipeline import feedback as feedback_mod
from pipeline import outcome_classifier as outcome_mod
from pipeline import reject as reject_mod
from pipeline.direct_pdf import attach as attach_mod
from pipeline.direct_pdf import outline as outline_mod
from pipeline.direct_pdf.generator import DirectPdfQuestionGenerator
from pipeline.direct_pdf.ingestion import PdfIngestionComponent
from pipeline.llm_client import PdfUnsupportedError, get_tracker, reset_tracker

from . import store

_BLOOM_TARGETS: Dict[str, float] = {
    'Nhận biết': 0.30,
    'Thông hiểu': 0.50,
    'Vận dụng': 0.70,
    'Vận dụng cao': 0.85,
}

_DIFFICULTY_TARGETS: Dict[str, Dict[str, Any]] = {
    'easy': {'cognitive_level': 'Nhận biết', 'difficulty_target': 0.30, 'fraction': 1.0},
    'medium': {'cognitive_level': 'Thông hiểu', 'difficulty_target': 0.50, 'fraction': 1.0},
    'hard': {'cognitive_level': 'Vận dụng', 'difficulty_target': 0.70, 'fraction': 1.0},
    'applied': {'cognitive_level': 'Vận dụng', 'difficulty_target': 0.70, 'fraction': 1.0},
    'applied_high': {'cognitive_level': 'Vận dụng cao', 'difficulty_target': 0.85, 'fraction': 1.0},
}


def _bloom_distribution(
    bloom_level: str,
    _num_questions: int,
    difficulty: str = 'mixed',
) -> List[Dict[str, Any]]:
    difficulty = (difficulty or 'mixed').strip().lower()
    if (bloom_level == 'mixed' or bloom_level not in _BLOOM_TARGETS) and difficulty in _DIFFICULTY_TARGETS:
        return [dict(_DIFFICULTY_TARGETS[difficulty])]
    if bloom_level == 'mixed' or bloom_level not in _BLOOM_TARGETS:
        return [dict(item) for item in cfg.DEFAULT_DIFFICULTY_DISTRIBUTION]
    return [{
        'cognitive_level': bloom_level,
        'difficulty_target': _BLOOM_TARGETS[bloom_level],
        'fraction': 1.0,
    }]


def _question_bank_summary(
    questions: List[Dict[str, Any]],
    rejected: List[Dict[str, Any]],
) -> Dict[str, Any]:
    total = len(questions) + len(rejected)
    by_topic = Counter(q.get('topic') or 'unknown' for q in questions)
    by_bloom = Counter(q.get('cognitive_level') or 'unknown' for q in questions)
    by_type = Counter(q.get('question_type') or 'single_choice' for q in questions)
    by_review = Counter(q.get('review_status') or 'pending_review' for q in questions)
    by_outcome: Counter = Counter()
    for q in questions:
        codes = q.get('learning_outcomes') or []
        if codes:
            by_outcome.update(str(c) for c in codes)
        else:
            by_outcome.update(['(chưa gán)'] if 'learning_outcomes' in q else [])

    verified = [
        q for q in questions
        if (q.get('verification') or {}).get('verified') is True
    ]
    qualities = [
        float((q.get('judging') or {}).get('quality'))
        for q in questions
        if (q.get('judging') or {}).get('quality') is not None
    ]
    groundings = [
        float((q.get('judging') or {}).get('grounding'))
        for q in questions
        if (q.get('judging') or {}).get('grounding') is not None
    ]

    return {
        'accepted_count': len(questions),
        'rejected_count': len(rejected),
        'total_attempted': total,
        'acceptance_rate': (len(questions) / total) if total else 0.0,
        'review_queue_count': sum(
            by_review.get(status, 0)
            for status in ('pending_review', 'needs_revision')
        ),
        'approved_count': by_review.get('approved', 0),
        'needs_revision_count': by_review.get('needs_revision', 0),
        'verified_count': len(verified),
        'avg_quality': (sum(qualities) / len(qualities)) if qualities else None,
        'avg_grounding': (sum(groundings) / len(groundings)) if groundings else None,
        'by_topic': dict(by_topic),
        'by_bloom': dict(by_bloom),
        'by_type': dict(by_type),
        'by_review_status': dict(by_review),
        'by_learning_outcome': dict(by_outcome),
    }


def _compact_question_record(q: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in (
        'question_id', 'subject', 'topic', 'kc_ids', 'cognitive_level',
        'difficulty_target', 'difficulty_estimated', 'estimated_time_seconds',
        'question_type', 'stem', 'options', 'answer_key',
        'short_explanation', 'detailed_solution', 'review_status',
        'verification', 'judging', 'tags', 'version',
        'learning_outcomes',
    ):
        if q.get(key) is not None:
            out[key] = q.get(key)

    explanation = q.get('short_explanation') or q.get('explanation_correct')
    if explanation:
        out['explanation'] = explanation
    if q.get('why_correct'):
        out['why_correct'] = q.get('why_correct')
    if q.get('why_others_wrong'):
        out['why_others_wrong'] = q.get('why_others_wrong')

    source = q.get('source') or {}
    if isinstance(source, dict):
        compact_source = {
            key: source.get(key)
            for key in ('doc_id', 'chunk_ids', 'pages', 'quote', 'quote_in_context')
            if source.get(key) not in (None, '', [])
        }
        if compact_source:
            out['source'] = compact_source

    visual = q.get('visual')
    if isinstance(visual, dict) and visual.get('type') and visual.get('type') != 'none':
        out['visual'] = visual
    elif visual and not isinstance(visual, dict):
        out['visual'] = visual

    review = q.get('review') or {}
    if isinstance(review, dict) and review.get('issues'):
        out['review'] = {'issues': review.get('issues')}
    return out


def _compact_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_compact_question_record(q) for q in questions]


def _write_error(job_id: str, message: str, error_code: str = '') -> None:
    payload: Dict[str, Any] = {
        'status': 'error',
        'progress': 0.0,
        'message': message,
        'error': message,
        'mode': 'Direct_PDF_Mode',
    }
    if error_code:
        payload['error_code'] = error_code
    store.write_status(job_id, payload)
    store.update_meta(job_id, status='error', error=message)

def _progress_from_event(event: Dict[str, Any], target: int) -> float:
    stage = str(event.get('stage') or '')
    if stage == 'preparing_pdf':
        return 0.10
    if stage == 'pdf_ready':
        return 0.15

    accepted = max(0, int(event.get('accepted') or 0))
    attempted = max(0, int(event.get('attempted') or 0))
    max_attempts = max(1, int(event.get('max_attempts') or target or 1))
    target = max(1, int(event.get('target') or target or 1))

    attempt_progress = attempted / max_attempts
    accepted_progress = accepted / target
    progress = max(
        0.15 + (0.65 * attempt_progress),
        0.15 + (0.75 * accepted_progress),
    )
    if accepted >= target:
        return 0.95
    return min(0.95, max(0.15, progress))

def _message_from_event(event: Dict[str, Any], target: int) -> str:
    stage = str(event.get('stage') or '')
    accepted = max(0, int(event.get('accepted') or 0))
    attempted = max(0, int(event.get('attempted') or 0))
    target = max(1, int(event.get('target') or target or 1))
    slot_id = event.get('slot_id')

    if stage == 'preparing_pdf':
        return 'Direct_PDF_Mode: preparing PDF pages...'
    if stage == 'pdf_ready':
        return f'Direct_PDF_Mode: PDF ready, generating {target} question(s)...'
    if stage == 'slot_started':
        return f'Direct_PDF_Mode: trying slot {attempted}, accepted {accepted}/{target}...'
    if stage == 'formatting':
        return f'Direct_PDF_Mode: formatting candidate from {slot_id}, accepted {accepted}/{target}...'
    if stage == 'question_accepted':
        return f'Direct_PDF_Mode: accepted {accepted}/{target}; continuing...'
    if stage in ('slot_rejected', 'slot_duplicate', 'slot_error', 'batch_rejected', 'batch_error'):
        return f'Direct_PDF_Mode: retrying after {attempted} attempt(s), accepted {accepted}/{target}...'
    if stage == 'batch_started':
        return f'Direct_PDF_Mode: generating batch {attempted}, accepted {accepted}/{target}...'
    if stage == 'generation_finished':
        return f'Direct_PDF_Mode: finishing, accepted {accepted}/{target}...'
    return f'Direct_PDF_Mode: generating, accepted {accepted}/{target}...'


def run_preparation(job_id: str) -> None:
    """Tiền xử lý nền ngay khi người dùng CHỌN file (trước khi bấm Generate).

    Hai việc, theo thứ tự ưu tiên:
    1. Render các trang PDF thành ảnh và cache ra đĩa — generation sau đó
       dùng lại, bỏ hẳn bước render (thuần CPU, vài giây với file lớn).
    2. Một call LLM trích dàn ý (chủ đề, chuẩn đầu ra gợi ý, số câu hợp lý)
       để hiển thị ngược lên form trong lúc người dùng chọn config.

    Trạng thái ghi vào prepare.json (tách khỏi status.json của flow generate).
    Mọi lỗi ở bước 2 chỉ làm mất gợi ý — attachments_ready vẫn giữ nguyên.
    """
    pdf_path = store.job_dir(job_id) / 'source.pdf'
    store.write_prepare(job_id, {
        'status': 'preparing',
        'attachments_ready': False,
        'message': 'Đang kiểm tra tài liệu...',
    })

    validation = PdfIngestionComponent().validate(str(pdf_path))
    if not validation.ok:
        msg = validation.error_message or 'PDF is not valid.'
        store.write_prepare(job_id, {
            'status': 'error',
            'attachments_ready': False,
            'error': msg,
            'error_code': validation.error_code or '',
        })
        store.update_meta(job_id, status='error', error=msg)
        return

    store.update_meta(job_id, status='preparing')
    store.update_prepare(
        job_id,
        num_pages=validation.num_pages,
        message=f'Đang đọc {validation.num_pages} trang tài liệu...',
    )

    attachment_parts: List[Dict[str, Any]] = []
    try:
        pdf_bytes = pdf_path.read_bytes()
        filename = str((store.get_meta(job_id) or {}).get('pdf_name') or 'source.pdf')
        attach_mode = str(getattr(cfg, 'PDF_ATTACH_MODE', 'image')).lower()
        if attach_mode == 'image':
            base = attach_mod.build_pdf_image_content(
                pdf_bytes, filename, '',
                dpi=getattr(cfg, 'PDF_IMAGE_DPI', 120),
                max_pages=getattr(cfg, 'PDF_IMAGE_MAX_PAGES', 30),
            )
        else:
            base = attach_mod.build_pdf_user_content(
                pdf_bytes, filename, '',
                as_image_url=(attach_mode == 'file_url'),
            )
        attachment_parts = [p for p in base if p.get('type') != 'text']
        store.save_attachments_cache(job_id, attachment_parts)
        store.update_prepare(
            job_id,
            attachments_ready=True,
            message='Đang phân tích chủ đề tài liệu...',
        )
    except Exception as exc:
        # Không render/cach được thì generation tự render lại — chỉ ghi log.
        store.append_error(job_id, f'prepare: attachment cache failed: {exc}')

    outline = None
    if attachment_parts and cfg.has_llm_api_key():
        try:
            outline = outline_mod.extract_outline(attachment_parts)
        except Exception as exc:
            store.append_error(job_id, f'prepare: outline extraction failed: {exc}')

    store.update_prepare(
        job_id,
        status='ready',
        outline=outline,
        message='Tài liệu đã sẵn sàng.',
    )
    store.update_meta(job_id, status='prepared')


def _cached_attachment_parts(job_id: str, wait_seconds: int = 120) -> Optional[List[Dict[str, Any]]]:
    """Lấy các trang đã render từ bước /prepare, chờ nếu prepare đang chạy dở.

    Người dùng có thể bấm Generate khi thread prepare còn đang render; chờ tối
    đa `wait_seconds` cho cache xuất hiện rồi mới chịu render lại từ đầu
    (render đôi vừa tốn CPU vừa dễ đụng file). Job không qua /prepare (flow
    /upload cũ) không có prepare.json -> trả None ngay, không chờ.
    """
    prepare = store.get_prepare(job_id)
    if prepare is None:
        return None
    deadline = time.time() + wait_seconds
    while (
        prepare is not None
        and prepare.get('status') == 'preparing'
        and not prepare.get('attachments_ready')
        and time.time() < deadline
    ):
        time.sleep(1.0)
        prepare = store.get_prepare(job_id)
    return store.load_attachments_cache(job_id)


def run_direct_generation(job_id: str) -> None:
    """Validate the uploaded PDF, generate questions, and persist result.json."""
    if not cfg.has_llm_api_key():
        _write_error(job_id, f'Missing LLM API key: {cfg.missing_llm_api_key_message()}')
        return

    config = store.get_config(job_id)
    num_questions = max(1, int(config.get('num_questions', 6) or 6))
    bloom_level = str(config.get('bloom_level') or 'mixed').strip()
    difficulty = str(config.get('difficulty') or 'mixed').strip().lower()
    include_explanation = bool(config.get('include_explanation', True))
    pdf_path = store.job_dir(job_id) / 'source.pdf'

    store.clear_cancel(job_id)
    store.update_meta(job_id, status='generating')
    store.write_status(job_id, {
        'status': 'generating',
        'progress': 0.05,
        'message': 'Direct_PDF_Mode: validating PDF...',
        'mode': 'Direct_PDF_Mode',
        'llm_provider': cfg.LLM_PROVIDER,
        'accepted': 0,
        'target_accepted': num_questions,
        'rejected_count': 0,
    })
    reset_tracker()
    started = time.time()

    validation = PdfIngestionComponent().validate(str(pdf_path))
    if not validation.ok:
        _write_error(
            job_id,
            validation.error_message or 'PDF is not valid.',
            validation.error_code or '',
        )
        return

    store.write_status(job_id, {
        'status': 'generating',
        'progress': 0.08,
        'message': (
            f'Direct_PDF_Mode: reading {validation.num_pages} page(s), '
            f'generating {num_questions} question(s)...'
        ),
        'mode': 'Direct_PDF_Mode',
        'accepted': 0,
        'target_accepted': num_questions,
        'rejected_count': 0,
    })

    def _on_progress(event: Dict[str, Any]) -> None:
        accepted = max(0, int(event.get('accepted') or 0))
        parse_errors = max(0, int(event.get('parse_errors') or 0))
        verify_failures = max(0, int(event.get('verify_failures') or 0))
        store.write_status(job_id, {
            'status': 'generating',
            'progress': _progress_from_event(event, num_questions),
            'message': _message_from_event(event, num_questions),
            'accepted': accepted,
            'target_accepted': max(1, int(event.get('target') or num_questions)),
            'rejected_count': parse_errors + verify_failures,
            'attempted': max(0, int(event.get('attempted') or 0)),
            'max_attempts': event.get('max_attempts'),
            'current_agent': event.get('stage'),
            'mode': 'Direct_PDF_Mode',
        })

    # CĐR người dùng khai báo: đưa vào NGAY khâu sinh (mỗi slot nhắm một CĐR,
    # round-robin) — bước phân loại sau chỉ còn kiểm chứng/bổ sung nhãn.
    outcomes = outcome_mod.normalize_outcomes(config.get('learning_outcomes'))

    try:
        result = DirectPdfQuestionGenerator().generate(
            pdf_path=str(pdf_path),
            requested_count=num_questions,
            bloom_distribution=_bloom_distribution(bloom_level, num_questions, difficulty),
            progress_callback=_on_progress,
            # Hồ sơ sở thích tổng hợp từ feedback các lượt trước (nếu có) —
            # sinh lại toàn bộ cũng vẫn tôn trọng ý người dùng.
            feedback_guidance=str(config.get('feedback_guidance') or ''),
            include_explanation=include_explanation,
            # Trang PDF đã render sẵn từ bước /prepare (None nếu là flow cũ).
            attachment_parts=_cached_attachment_parts(job_id),
            learning_outcomes=outcomes,
        )
    except PdfUnsupportedError as exc:
        msg = (
            'Model/gateway does not support PDF or image input. '
            f'Direct_PDF_Mode requires a vision/file-capable provider: {exc}'
        )
        store.append_error(job_id, msg)
        _write_error(job_id, msg, 'pdf_unsupported')
        return
    except Exception as exc:
        tb = traceback.format_exc()
        store.append_error(job_id, f'direct generation crashed: {exc}\n{tb}')
        _write_error(job_id, f'Direct_PDF_Mode: generation crashed: {exc}')
        return

    if result.error_code:
        _write_error(
            job_id,
            result.error_message or f'Direct_PDF_Mode error: {result.error_code}',
            result.error_code,
        )
        return

    questions = result.questions
    accepted_count = result.accepted_count

    # Kiểm chứng nhãn Chuẩn đầu ra bằng LLM judge (nhãn sơ bộ đã gán từ slot
    # khi sinh). Best-effort: lỗi phân loại không được làm hỏng job sinh câu.
    if outcomes and questions:
        store.write_status(job_id, {
            'status': 'generating',
            'progress': 0.96,
            'message': (
                f'Direct_PDF_Mode: phân loại {len(questions)} câu theo '
                f'{len(outcomes)} chuẩn đầu ra...'
            ),
            'mode': 'Direct_PDF_Mode',
            'accepted': accepted_count,
            'target_accepted': result.requested_count,
            'rejected_count': result.parse_errors + result.verify_failures,
        })
        try:
            assignments = outcome_mod.classify_questions(questions, outcomes)
        except Exception as exc:
            store.append_error(job_id, f'outcome classification failed: {exc}')
            assignments = {}
        outcome_mod.attach_outcomes(questions, assignments)

    duration_seconds = time.time() - started
    public_questions = _compact_questions(questions)

    payload = {
        'metadata': {
            'job_id': job_id,
            'mode': 'Direct_PDF_Mode',
            'llm_provider': cfg.LLM_PROVIDER,
            'generator_model': cfg.GENERATOR_MODEL,
            'source_pdf_name': (store.get_meta(job_id) or {}).get('pdf_name'),
            'requested_questions': result.requested_count,
            'accepted_questions': accepted_count,
            'is_partial': result.is_partial,
            'parse_errors': result.parse_errors,
            'verify_failures': result.verify_failures,
            'num_pages': validation.num_pages,
            'config': config,
            'question_bank_summary': _question_bank_summary(questions, []),
            'cost': get_tracker().report(),
            'duration_seconds': duration_seconds,
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        },
        'questions': public_questions,
    }
    store.save_debug_rejected(job_id, [], reject_mod.summarize([]))
    store.save_result(job_id, payload)

    no_questions = accepted_count == 0
    final_status = 'error' if no_questions else 'done'
    if no_questions:
        message = (
            'Direct_PDF_Mode: model did not produce any accepted questions '
            f'(parse_errors={result.parse_errors}). Check provider PDF support.'
        )
    elif result.is_partial:
        message = (
            f'Direct_PDF_Mode: accepted {accepted_count}/{result.requested_count} '
            f'(partial); parse_errors={result.parse_errors}'
        )
    else:
        message = f'Direct_PDF_Mode: accepted {accepted_count}/{result.requested_count}'

    store.update_meta(
        job_id,
        status=final_status,
        num_questions=accepted_count,
        error=message if no_questions else None,
    )
    store.write_status(job_id, {
        'status': final_status,
        'progress': 1.0,
        'message': message,
        'error': message if no_questions else None,
        'accepted': accepted_count,
        'target_accepted': result.requested_count,
        'rejected_count': result.parse_errors + result.verify_failures,
        'mode': 'Direct_PDF_Mode',
        'partial': result.is_partial,
    })
    store.clear_cancel(job_id)


def _run_incremental_generation(
    job_id: str,
    kept: List[Dict[str, Any]],
    need: int,
    target_total: int,
    guidance: str,
    avoid_stems: List[str],
    start_message: str,
    finish_message: Callable[[int], str],
    meta_extra: Dict[str, Any],
    progress_label: str,
) -> None:
    """Lõi dùng chung cho các lượt sinh TĂNG DẦN trên một job đã có kết quả.

    Giữ nguyên `kept`, sinh `need` câu mới (tiêm hồ sơ sở thích `guidance` +
    tránh lặp `avoid_stems`), phân loại Chuẩn đầu ra cho câu mới rồi merge và
    lưu result.json. Dùng cho cả "sinh lại câu bị chê" lẫn "sinh thêm câu".
    """
    config = store.get_config(job_id)
    bloom_level = str(config.get('bloom_level') or 'mixed').strip()
    difficulty = str(config.get('difficulty') or 'mixed').strip().lower()
    pdf_path = store.job_dir(job_id) / 'source.pdf'

    store.clear_cancel(job_id)
    store.update_meta(job_id, status='generating')
    store.write_status(job_id, {
        'status': 'generating',
        'progress': 0.05,
        'message': start_message,
        'mode': 'Direct_PDF_Mode',
        'llm_provider': cfg.LLM_PROVIDER,
        'accepted': len(kept),
        'target_accepted': target_total,
        'rejected_count': 0,
        'incremental': True,
    })
    reset_tracker()
    started = time.time()

    validation = PdfIngestionComponent().validate(str(pdf_path))
    if not validation.ok:
        _write_error(
            job_id,
            validation.error_message or 'PDF is not valid.',
            validation.error_code or '',
        )
        return

    def _on_progress(event: Dict[str, Any]) -> None:
        # accepted trong event là số câu MỚI; cộng số câu giữ lại để UI thấy
        # tiến độ trên tổng target của job.
        accepted_new = max(0, int(event.get('accepted') or 0))
        parse_errors = max(0, int(event.get('parse_errors') or 0))
        verify_failures = max(0, int(event.get('verify_failures') or 0))
        store.write_status(job_id, {
            'status': 'generating',
            'progress': _progress_from_event(event, need),
            'message': _message_from_event(event, need).replace(
                'Direct_PDF_Mode:', progress_label),
            'accepted': len(kept) + accepted_new,
            'target_accepted': target_total,
            'rejected_count': parse_errors + verify_failures,
            'attempted': max(0, int(event.get('attempted') or 0)),
            'max_attempts': event.get('max_attempts'),
            'current_agent': event.get('stage'),
            'mode': 'Direct_PDF_Mode',
            'incremental': True,
        })

    # CĐR đưa thẳng vào khâu sinh (như lượt sinh đầu) — câu mới cũng bám CĐR.
    outcomes = outcome_mod.normalize_outcomes(config.get('learning_outcomes'))

    try:
        result = DirectPdfQuestionGenerator().generate(
            pdf_path=str(pdf_path),
            requested_count=need,
            bloom_distribution=_bloom_distribution(bloom_level, need, difficulty),
            progress_callback=_on_progress,
            feedback_guidance=guidance,
            seed_avoid_stems=avoid_stems,
            include_explanation=bool(config.get('include_explanation', True)),
            attachment_parts=_cached_attachment_parts(job_id),
            learning_outcomes=outcomes,
        )
    except PdfUnsupportedError as exc:
        msg = (
            'Model/gateway does not support PDF or image input. '
            f'Direct_PDF_Mode requires a vision/file-capable provider: {exc}'
        )
        store.append_error(job_id, msg)
        _write_error(job_id, msg, 'pdf_unsupported')
        return
    except Exception as exc:
        tb = traceback.format_exc()
        store.append_error(job_id, f'incremental generation crashed: {exc}\n{tb}')
        _write_error(job_id, f'{progress_label} sinh câu hỏi thất bại: {exc}')
        return

    if result.error_code:
        _write_error(
            job_id,
            result.error_message or f'Direct_PDF_Mode error: {result.error_code}',
            result.error_code,
        )
        return

    new_questions = result.questions

    # Kiểm chứng nhãn Chuẩn đầu ra cho các câu MỚI (câu giữ lại đã có nhãn).
    if outcomes and new_questions:
        try:
            assignments = outcome_mod.classify_questions(new_questions, outcomes)
        except Exception as exc:
            store.append_error(job_id, f'outcome classification failed: {exc}')
            assignments = {}
        outcome_mod.attach_outcomes(new_questions, assignments)

    merged = kept + _compact_questions(new_questions)
    duration_seconds = time.time() - started

    metadata: Dict[str, Any] = {
        'job_id': job_id,
        'mode': 'Direct_PDF_Mode',
        'llm_provider': cfg.LLM_PROVIDER,
        'generator_model': cfg.GENERATOR_MODEL,
        'source_pdf_name': (store.get_meta(job_id) or {}).get('pdf_name'),
        'requested_questions': target_total,
        'accepted_questions': len(merged),
        'is_partial': len(merged) < target_total,
        'parse_errors': result.parse_errors,
        'verify_failures': result.verify_failures,
        'num_pages': validation.num_pages,
        'config': store.get_config(job_id),
        'question_bank_summary': _question_bank_summary(merged, []),
        'cost': get_tracker().report(),
        'duration_seconds': duration_seconds,
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'generated_new': len(new_questions),
    }
    metadata.update(meta_extra)
    store.save_debug_rejected(job_id, [], reject_mod.summarize([]))
    store.save_result(job_id, {'metadata': metadata, 'questions': merged})

    message = finish_message(len(new_questions))
    store.update_meta(job_id, status='done', num_questions=len(merged), error=None)
    store.write_status(job_id, {
        'status': 'done',
        'progress': 1.0,
        'message': message,
        'accepted': len(merged),
        'target_accepted': target_total,
        'rejected_count': result.parse_errors + result.verify_failures,
        'mode': 'Direct_PDF_Mode',
        'partial': len(merged) < target_total,
        'incremental': True,
    })
    store.clear_cancel(job_id)


def run_feedback_regeneration(job_id: str) -> None:
    """RLHF-style: giữ các câu không bị chê, sinh lại các câu bị 👎.

    Feedback được tổng hợp thành hồ sơ sở thích (pipeline.feedback.build_guidance)
    rồi tiêm vào prompt Writer/Distractor. Hồ sơ cũng được lưu vào config
    (`feedback_guidance`) nên các lượt sinh lại toàn bộ sau này vẫn tôn trọng.
    """
    if not cfg.has_llm_api_key():
        _write_error(job_id, f'Missing LLM API key: {cfg.missing_llm_api_key_message()}')
        return

    prev_result = store.get_result(job_id) or {}
    existing = [q for q in prev_result.get('questions', []) if isinstance(q, dict)]
    feedback = store.get_feedback(job_id)
    down_ids = {
        f.get('question_id') for f in feedback
        if isinstance(f, dict) and f.get('rating') == 'down'
    }
    replaced = [q for q in existing if q.get('question_id') in down_ids]
    kept = [q for q in existing if q.get('question_id') not in down_ids]

    if not existing:
        _write_error(job_id, 'Chưa có kết quả để sinh lại theo phản hồi.')
        return
    if not replaced:
        _write_error(job_id, 'Không có câu nào bị đánh giá 👎 — không có gì để sinh lại.')
        return

    need = len(replaced)
    guidance = feedback_mod.build_guidance(feedback)
    store.save_config(job_id, {'feedback_guidance': guidance})
    prev_meta = prev_result.get('metadata') or {}
    feedback_round = int(prev_meta.get('feedback_round') or 0) + 1

    _run_incremental_generation(
        job_id,
        kept=kept,
        need=need,
        target_total=len(existing),
        guidance=guidance,
        avoid_stems=[str(q.get('stem') or '') for q in existing],
        start_message=(
            f'RLHF: giữ {len(kept)} câu, sinh lại {need} câu bị chê '
            'theo phản hồi của bạn...'
        ),
        finish_message=lambda n: (
            f'RLHF: giữ {len(kept)} câu, thay được {n}/{need} câu bị chê '
            f'(vòng phản hồi #{feedback_round})'
        ),
        meta_extra={
            'feedback_round': feedback_round,
            'feedback_kept': len(kept),
            'feedback_replaced': len(replaced),
            'additional_rounds': int(prev_meta.get('additional_rounds') or 0),
        },
        progress_label='RLHF:',
    )


def run_additional_generation(job_id: str, extra_count: int) -> None:
    """Sinh thêm câu hỏi MỚI từ cùng PDF, giữ nguyên toàn bộ câu hiện có.

    Vẫn tiêm hồ sơ sở thích từ feedback (nếu có) nên câu sinh thêm cũng đúng
    ý người dùng — không cần tải PDF thành job mới rồi mất phản hồi cũ.
    """
    if not cfg.has_llm_api_key():
        _write_error(job_id, f'Missing LLM API key: {cfg.missing_llm_api_key_message()}')
        return

    config = store.get_config(job_id)
    prev_result = store.get_result(job_id) or {}
    existing = [q for q in prev_result.get('questions', []) if isinstance(q, dict)]
    if not existing:
        _write_error(job_id, 'Chưa có kết quả — hãy sinh câu hỏi trước khi sinh thêm.')
        return

    need = max(1, min(20, int(extra_count or 1)))
    feedback = store.get_feedback(job_id)
    guidance = feedback_mod.build_guidance(feedback) \
        or str(config.get('feedback_guidance') or '')
    if guidance:
        store.save_config(job_id, {'feedback_guidance': guidance})
    prev_meta = prev_result.get('metadata') or {}
    additional_rounds = int(prev_meta.get('additional_rounds') or 0) + 1

    _run_incremental_generation(
        job_id,
        kept=existing,
        need=need,
        target_total=len(existing) + need,
        guidance=guidance,
        avoid_stems=[str(q.get('stem') or '') for q in existing],
        start_message=(
            f'Sinh thêm: giữ {len(existing)} câu, tạo thêm {need} câu mới từ PDF...'
        ),
        finish_message=lambda n: (
            f'Sinh thêm: +{n}/{need} câu mới (tổng {len(existing) + n} câu)'
        ),
        meta_extra={
            'additional_rounds': additional_rounds,
            'feedback_round': int(prev_meta.get('feedback_round') or 0),
        },
        progress_label='Sinh thêm:',
    )

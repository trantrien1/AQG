"""FastAPI app for direct PDF MCQ generation."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import psycopg
from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from pipeline import customization as cust_mod
from pipeline import feedback as feedback_mod
from pipeline import outcome_classifier as outcome_mod
from pipeline import practice as practice_mod
from pipeline import reject as reject_mod

from . import auth as auth_mod
from . import bank_exports
from . import bank_store
from . import db
from . import jobs as job_runner
from . import store


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # DB chưa lên thì vẫn cho app chạy: /health sống, route khác trả 503.
    if db.init_db():
        db.ensure_admin()
    yield


app = FastAPI(title='AIED-MCQ Backend', version='2.0.0', lifespan=_lifespan)


# Đăng ký auth middleware TRƯỚC CORSMiddleware để CORS nằm ngoài cùng
# (response 401/503 vẫn có header CORS, browser không báo lỗi CORS giả).
@app.middleware('http')
async def _require_auth(request: Request, call_next):
    path = request.url.path
    if request.method == 'OPTIONS' or path in auth_mod.EXEMPT_PATHS:
        return await call_next(request)
    token = auth_mod.bearer_token(request)
    if token is None:
        return JSONResponse(status_code=401, content={'detail': 'Not authenticated'})
    try:
        username = db.get_session_user(token)
    except psycopg.Error:
        return JSONResponse(status_code=503, content={'detail': 'Auth database unavailable'})
    if username is None:
        return JSONResponse(status_code=401, content={'detail': 'Session expired or invalid'})
    request.state.username = username
    return await call_next(request)


def _cors_origins() -> List[str]:
    raw = os.environ.get('CORS_ORIGINS') or ''
    origins = [o.strip() for o in raw.split(',') if o.strip()]
    return origins or ['http://localhost:3000', 'http://127.0.0.1:3000']


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers=['*'],
    # Frontend tải export qua fetch + blob nên cần đọc được tên file.
    expose_headers=['Content-Disposition'],
)

app.include_router(auth_mod.router)


@app.get('/health')
def health() -> Dict[str, str]:
    return {'status': 'ok'}


def _parse_learning_outcomes(raw: str) -> List[Dict[str, str]]:
    """Form field `learning_outcomes`: JSON array (list[str] | list[dict]) hoặc text nhiều dòng."""
    raw = (raw or '').strip()
    if not raw:
        return []
    try:
        import json
        parsed = json.loads(raw)
    except Exception:
        parsed = raw  # text thường: mỗi dòng một CĐR
    return outcome_mod.normalize_outcomes(parsed)


@app.post('/upload')
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    num_questions: int = Form(12),
    bloom_level: str = Form('mixed'),
    difficulty: str = Form('mixed'),
    direct_pdf: str = Form('1'),
    learning_outcomes: str = Form(''),
    include_explanation: str = Form('1'),
) -> Dict[str, Any]:
    """Accept a PDF and immediately start Direct_PDF_Mode generation."""
    _ = direct_pdf  # Backward-compatible form field; direct mode is the only mode now.
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail='Only PDF files are accepted.')

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail='Empty file.')

    job_id = store.create_job(pdf_name=file.filename, num_questions=num_questions)
    store.save_pdf(job_id, content)
    store.save_config(job_id, {
        'num_questions': num_questions,
        'bloom_level': bloom_level,
        'difficulty': difficulty.strip().lower() if difficulty else 'mixed',
        'learning_outcomes': _parse_learning_outcomes(learning_outcomes),
        # Tắt để sinh nhanh hơn: bỏ lời giải từng bước / vì sao đúng / vì sao sai.
        'include_explanation': include_explanation not in ('0', 'false', 'False'),
        'direct_pdf': True,
        'mode': 'Direct_PDF_Mode',
    })
    store.update_meta(job_id, status='generating')
    store.write_status(job_id, {
        'status': 'generating',
        'progress': 0.0,
        'message': 'Direct_PDF_Mode queued...',
        'mode': 'Direct_PDF_Mode',
        'accepted': 0,
        'target_accepted': num_questions,
        'rejected_count': 0,
    })
    background_tasks.add_task(job_runner.run_direct_generation, job_id)
    return {'job_id': job_id, 'direct_pdf': True}


@app.post('/prepare')
async def prepare(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """Bước 1 của two-step upload: gọi NGAY khi người dùng chọn xong file.

    Tạo job + lưu PDF rồi chạy nền: render trang thành ảnh (cache cho
    generation) và trích dàn ý chủ đề (gợi ý config lên form). Người dùng
    bấm Generate sau đó mới gửi config qua POST /job/{id}/start.
    """
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail='Only PDF files are accepted.')
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail='Empty file.')

    job_id = store.create_job(pdf_name=file.filename, num_questions=0)
    store.save_pdf(job_id, content)
    store.update_meta(job_id, status='preparing')
    store.write_prepare(job_id, {
        'status': 'preparing',
        'attachments_ready': False,
        'message': 'Đang chuẩn bị tài liệu...',
    })
    background_tasks.add_task(job_runner.run_preparation, job_id)
    return {'job_id': job_id}


@app.get('/job/{job_id}/prepare')
def get_prepare_status(job_id: str) -> Dict[str, Any]:
    """Frontend poll trong lúc người dùng chọn config; trả dàn ý khi sẵn sàng."""
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    prepare_state = store.get_prepare(job_id)
    if prepare_state is None:
        return {'status': 'none'}
    return prepare_state


@app.post('/job/{job_id}/start')
def start_prepared_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    num_questions: int = Form(6),
    bloom_level: str = Form('mixed'),
    difficulty: str = Form('mixed'),
    learning_outcomes: str = Form(''),
    include_explanation: str = Form('1'),
) -> Dict[str, Any]:
    """Bước 2 của two-step upload: nhận config và bắt đầu sinh câu hỏi.

    Generation dùng lại các trang đã render ở bước /prepare (nếu prepare còn
    đang chạy thì worker tự chờ cache). Job flow /upload cũ không dùng route này.
    """
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    current_status = store.get_status(job_id)
    if current_status.get('status') in ('generating', 'running'):
        raise HTTPException(status_code=409, detail='Generation already in progress for this job.')
    prepare_state = store.get_prepare(job_id) or {}
    if prepare_state.get('status') == 'error':
        raise HTTPException(
            status_code=409,
            detail=prepare_state.get('error') or 'PDF failed preparation.',
        )

    num_questions = max(1, min(30, int(num_questions or 1)))
    store.save_config(job_id, {
        'num_questions': num_questions,
        'bloom_level': bloom_level,
        'difficulty': difficulty.strip().lower() if difficulty else 'mixed',
        'learning_outcomes': _parse_learning_outcomes(learning_outcomes),
        'include_explanation': include_explanation not in ('0', 'false', 'False'),
        'direct_pdf': True,
        'mode': 'Direct_PDF_Mode',
    })
    store.update_meta(job_id, status='generating', num_questions=num_questions)
    store.write_status(job_id, {
        'status': 'generating',
        'progress': 0.0,
        'message': 'Direct_PDF_Mode queued...',
        'mode': 'Direct_PDF_Mode',
        'accepted': 0,
        'target_accepted': num_questions,
        'rejected_count': 0,
    })
    background_tasks.add_task(job_runner.run_direct_generation, job_id)
    return {'ok': True, 'job_id': job_id}


@app.delete('/job/{job_id}')
def delete_job(job_id: str) -> Dict[str, bool]:
    """Xoá job (dùng khi người dùng bỏ/đổi file đã prepare mà chưa Generate)."""
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    current_status = store.get_status(job_id)
    if current_status.get('status') in ('generating', 'running'):
        raise HTTPException(status_code=409, detail='Job is generating; cancel it first.')
    store.cleanup(job_id)
    return {'ok': True}


@app.get('/jobs')
def list_jobs() -> Dict[str, List[Dict[str, Any]]]:
    return {'jobs': store.list_jobs()}


@app.get('/banks')
def list_banks() -> Dict[str, Any]:
    return {'banks': bank_store.list_banks()}


@app.post('/banks')
def create_bank(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        bank = bank_store.create_bank(
            name=str(payload.get('name') or ''),
            description=str(payload.get('description') or ''),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'bank': bank}


@app.get('/bank/{bank_id}')
def get_bank(bank_id: str) -> Dict[str, Any]:
    payload = bank_store.get_bank(bank_id)
    if payload is None:
        raise HTTPException(status_code=404, detail='Bank not found')
    return payload


def _questions_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    questions = payload.get('questions')
    if isinstance(questions, list) and questions:
        return [q for q in questions if isinstance(q, dict)]
    job_id = str(payload.get('job_id') or '').strip()
    if not job_id:
        return []
    result = store.get_result(job_id) or {}
    items = result.get('questions') or []
    question_ids = payload.get('question_ids')
    if isinstance(question_ids, list) and question_ids:
        wanted = {str(qid) for qid in question_ids}
        items = [q for q in items if str(q.get('question_id')) in wanted]
    return [q for q in items if isinstance(q, dict)]


@app.post('/bank/{bank_id}/duplicates')
def check_bank_duplicates(bank_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    questions = _questions_from_payload(payload)
    if not questions:
        raise HTTPException(status_code=400, detail='questions or job_id required')
    try:
        return bank_store.check_duplicates(bank_id, questions)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='Bank not found') from exc


@app.post('/bank/{bank_id}/questions')
def add_bank_questions(bank_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    questions = _questions_from_payload(payload)
    if not questions:
        raise HTTPException(status_code=400, detail='questions or job_id required')
    source_job_id = str(payload.get('source_job_id') or payload.get('job_id') or '')
    source_pdf_name = str(payload.get('source_pdf_name') or '')
    if source_job_id and not source_pdf_name:
        source_pdf_name = str((store.get_meta(source_job_id) or {}).get('pdf_name') or '')
    try:
        result = bank_store.add_questions(
            bank_id=bank_id,
            questions=questions,
            source_job_id=source_job_id,
            source_pdf_name=source_pdf_name,
            duplicate_action=str(payload.get('duplicate_action') or 'skip'),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='Bank not found') from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@app.put('/bank/{bank_id}/questions/{bank_question_id}')
def update_bank_question(
    bank_id: str,
    bank_question_id: str,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    question = payload.get('question') if isinstance(payload.get('question'), dict) else payload
    if not isinstance(question, dict):
        raise HTTPException(status_code=400, detail='question object required')
    result = bank_store.update_question(bank_id, bank_question_id, question)
    if result is None:
        raise HTTPException(status_code=404, detail='Bank question not found')
    return result


@app.delete('/bank/{bank_id}/questions/{bank_question_id}')
def delete_bank_question(bank_id: str, bank_question_id: str) -> Dict[str, bool]:
    ok = bank_store.delete_question(bank_id, bank_question_id)
    if not ok:
        raise HTTPException(status_code=404, detail='Bank question not found')
    return {'ok': True}


@app.get('/bank/{bank_id}/export')
def export_bank(bank_id: str, format: str = 'json') -> Any:
    try:
        path = bank_exports.export_bank(bank_id, format)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='Bank not found') from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    media = {
        'json': 'application/json',
        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }.get(format.lower(), 'application/octet-stream')
    return FileResponse(path=str(path), filename=path.name, media_type=media)


def _split_csv(value: str) -> List[str]:
    return [v.strip() for v in (value or '').split(',') if v.strip()]


@app.get('/job/{job_id}/config')
def get_config(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    return {'config': store.get_config(job_id)}


@app.post('/job/{job_id}/configure')
def configure(
    job_id: str,
    num_questions: int = Form(12),
    bloom_level: str = Form('mixed'),
    include_explanation: str = Form('1'),
    include_visuals: str = Form('0'),
    question_types: str = Form(''),
    topic_filter: str = Form(''),
    difficulty: str = Form(''),
    user_instruction: str = Form(''),
    focus_topics: str = Form(''),
    avoid_topics: str = Form(''),
    style: str = Form(''),
    requires_computation: str = Form(''),
    requires_detailed_solution: str = Form(''),
    strict_grounding: str = Form(''),
    quick_prompts: str = Form(''),
    mode: str = Form('Direct_PDF_Mode'),
    skill_mode: str = Form(''),
) -> Dict[str, Any]:
    _ = (mode, skill_mode)
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    config: Dict[str, Any] = {
        'mode': 'Direct_PDF_Mode',
        'direct_pdf': True,
        'num_questions': num_questions,
        'bloom_level': bloom_level,
        'include_explanation': include_explanation in ('1', 'true', 'True'),
        'include_visuals': include_visuals in ('1', 'true', 'True'),
        'question_types': _split_csv(question_types),
        'topic_filter': _split_csv(topic_filter),
    }
    if difficulty:
        config['difficulty'] = difficulty.strip().lower()
    if user_instruction:
        config['user_instruction'] = user_instruction.strip()
    if focus_topics:
        config['focus_topics'] = _split_csv(focus_topics)
    if avoid_topics:
        config['avoid_topics'] = _split_csv(avoid_topics)
    if style:
        config['style'] = style.strip().lower()
    if requires_computation:
        config['requires_computation'] = requires_computation in ('1', 'true', 'True')
    if requires_detailed_solution:
        config['requires_detailed_solution'] = requires_detailed_solution in ('1', 'true', 'True')
    if strict_grounding:
        config['strict_grounding'] = strict_grounding in ('1', 'true', 'True')
    if quick_prompts:
        config['quick_prompts'] = _split_csv(quick_prompts)

    saved = store.save_config(job_id, config)
    store.update_meta(job_id, num_questions=num_questions)
    return {
        'ok': True,
        'config': saved,
        'generation_config': cust_mod.parse(saved).to_dict(),
    }


@app.post('/job/{job_id}/customize')
def customize_job(job_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='payload must be an object')
    saved = store.save_config(job_id, {**payload, 'direct_pdf': True, 'mode': 'Direct_PDF_Mode'})
    return {
        'ok': True,
        'config': saved,
        'generation_config': cust_mod.parse(saved).to_dict(),
    }


@app.post('/job/{job_id}/generate')
def start_generate(
    job_id: str,
    background_tasks: BackgroundTasks,
    num_questions: int = Form(12),
    bloom_level: str = Form('mixed'),
    difficulty: str = Form(''),
    num_samples: int = Form(1),
    use_nli: str = Form('0'),
    mode: str = Form('Direct_PDF_Mode'),
    skill_mode: str = Form(''),
) -> Dict[str, bool]:
    _ = (num_samples, use_nli, mode, skill_mode)
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    current_status = store.get_status(job_id)
    if current_status.get('status') in ('generating', 'running'):
        raise HTTPException(status_code=409, detail='Generation already in progress for this job.')
    store.clear_result(job_id)
    existing_config = store.get_config(job_id)
    store.save_config(job_id, {
        'mode': 'Direct_PDF_Mode',
        'direct_pdf': True,
        'num_questions': num_questions,
        'bloom_level': bloom_level,
        'difficulty': (difficulty or existing_config.get('difficulty') or 'mixed'),
    })
    store.write_status(job_id, {
        'status': 'generating',
        'progress': 0.0,
        'message': 'Direct_PDF_Mode queued...',
        'mode': 'Direct_PDF_Mode',
        'accepted': 0,
        'target_accepted': num_questions,
        'rejected_count': 0,
    })
    background_tasks.add_task(job_runner.run_direct_generation, job_id)
    return {'ok': True}


@app.get('/job/{job_id}/status')
def get_status(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    status = store.get_status(job_id) or {}
    if 'reject_summary' not in status:
        summary = store.get_debug_reject_summary(job_id)
        rejected = store.get_debug_rejected(job_id)
        if summary:
            status['reject_summary'] = summary
        elif rejected:
            status['reject_summary'] = reject_mod.summarize(rejected)
    status['cancel_requested'] = store.is_cancel_requested(job_id)
    return status


@app.post('/job/{job_id}/cancel')
def cancel_job(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    current = store.get_status(job_id) or {}
    if current.get('status') in ('done', 'cancelled', 'error'):
        return {'ok': False, 'reason': 'already_finished', 'status': current.get('status')}
    ok = store.request_cancel(job_id)
    if not ok:
        raise HTTPException(status_code=500, detail='failed to request cancel')
    current['cancel_requested'] = True
    current['message'] = 'cancel requested'
    store.write_status(job_id, current)
    return {'ok': True}


@app.get('/job/{job_id}/rejects')
def get_rejects(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    rejected = store.get_debug_rejected(job_id)
    return {
        'summary': reject_mod.summarize(rejected),
        'rejects': [
            {
                'question_id': r.get('question_id'),
                'slot_id': r.get('blueprint_slot_id'),
                'topic': r.get('topic'),
                'reject_reason': r.get('reject_reason'),
                'reject_reason_code': r.get('reject_reason_code'),
                'reject_reason_stage': r.get('reject_reason_stage'),
                'reject_log': r.get('reject_log') or [],
                'attempts': r.get('attempts'),
            }
            for r in rejected
        ],
    }


@app.get('/job/{job_id}/questions')
def get_questions(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    result = store.get_result(job_id)
    if result is None:
        return {'questions': [], 'rejected': []}
    return {
        'questions': result.get('questions', []),
        'rejected': store.get_debug_rejected(job_id),
    }


@app.get('/job/{job_id}/feedback')
def get_job_feedback(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    return {'feedback': store.get_feedback(job_id)}


@app.post('/job/{job_id}/feedback')
def submit_job_feedback(job_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Upsert feedback 👍/👎 cho một câu hỏi. rating=null để xoá feedback."""
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    question_id = str(payload.get('question_id') or '').strip()
    if not question_id:
        raise HTTPException(status_code=400, detail='question_id required')

    rating = payload.get('rating')
    if rating in (None, '', 'none'):
        store.delete_feedback_entry(job_id, question_id)
        return {'ok': True, 'feedback': store.get_feedback(job_id)}
    if rating not in ('up', 'down'):
        raise HTTPException(status_code=400, detail="rating must be 'up', 'down' or null")

    result = store.get_result(job_id) or {}
    question = next(
        (q for q in result.get('questions', [])
         if isinstance(q, dict) and q.get('question_id') == question_id),
        None,
    )
    if question is None:
        raise HTTPException(status_code=404, detail='question_id not found in result')

    import time as _time
    entry = feedback_mod.normalize_entry({
        'question_id': question_id,
        'rating': rating,
        'tags': payload.get('tags') or [],
        'comment': payload.get('comment') or '',
        # Snapshot để hồ sơ sở thích vẫn dùng được sau khi câu bị thay.
        'stem': str(question.get('stem') or '')[:400],
        'cognitive_level': question.get('cognitive_level') or '',
        'created_at': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime()),
    })
    if entry is None:
        raise HTTPException(status_code=400, detail='invalid feedback payload')
    store.save_feedback_entry(job_id, entry)
    return {'ok': True, 'feedback': store.get_feedback(job_id)}


@app.post('/job/{job_id}/generate-from-feedback')
def generate_from_feedback(job_id: str, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Sinh lại các câu bị 👎 theo hồ sơ sở thích tổng hợp từ feedback."""
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    current_status = store.get_status(job_id)
    if current_status.get('status') in ('generating', 'running'):
        raise HTTPException(status_code=409, detail='Generation already in progress for this job.')

    result = store.get_result(job_id) or {}
    questions = [q for q in result.get('questions', []) if isinstance(q, dict)]
    if not questions:
        raise HTTPException(status_code=409, detail='No generated questions yet; generate first.')

    current_ids = {q.get('question_id') for q in questions}
    feedback = store.get_feedback(job_id)
    down_ids = {
        f.get('question_id') for f in feedback
        if isinstance(f, dict) and f.get('rating') == 'down'
    } & current_ids
    if not down_ids:
        raise HTTPException(
            status_code=409,
            detail='No disliked questions to replace; mark at least one question 👎 first.',
        )

    keeping = len(questions) - len(down_ids)
    store.update_meta(job_id, status='generating')
    store.write_status(job_id, {
        'status': 'generating',
        'progress': 0.0,
        'message': f'RLHF: giữ {keeping} câu, sinh lại {len(down_ids)} câu theo phản hồi...',
        'mode': 'Direct_PDF_Mode',
        'accepted': keeping,
        'target_accepted': len(questions),
        'rejected_count': 0,
        'feedback_round': True,
    })
    background_tasks.add_task(job_runner.run_feedback_regeneration, job_id)
    return {'ok': True, 'keeping': keeping, 'replacing': len(down_ids)}


@app.post('/job/{job_id}/generate-more')
def generate_more(
    job_id: str,
    background_tasks: BackgroundTasks,
    num_questions: int = Form(3),
) -> Dict[str, Any]:
    """Sinh THÊM câu hỏi từ cùng PDF, giữ nguyên câu hiện có (kể cả feedback)."""
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    current_status = store.get_status(job_id)
    if current_status.get('status') in ('generating', 'running'):
        raise HTTPException(status_code=409, detail='Generation already in progress for this job.')

    result = store.get_result(job_id) or {}
    questions = [q for q in result.get('questions', []) if isinstance(q, dict)]
    if not questions:
        raise HTTPException(status_code=409, detail='No generated questions yet; generate first.')

    extra = max(1, min(20, int(num_questions or 1)))
    store.update_meta(job_id, status='generating')
    store.write_status(job_id, {
        'status': 'generating',
        'progress': 0.0,
        'message': f'Sinh thêm: giữ {len(questions)} câu, tạo thêm {extra} câu mới từ PDF...',
        'mode': 'Direct_PDF_Mode',
        'accepted': len(questions),
        'target_accepted': len(questions) + extra,
        'rejected_count': 0,
        'incremental': True,
    })
    background_tasks.add_task(job_runner.run_additional_generation, job_id, extra)
    return {'ok': True, 'adding': extra, 'current': len(questions)}


@app.post('/job/{job_id}/review')
def review_question(
    job_id: str,
    question_id: str = Form(...),
    action: str = Form(...),
) -> Dict[str, bool]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    if action not in ('approve', 'reject'):
        raise HTTPException(status_code=400, detail='action must be approve|reject')
    target = 'approved' if action == 'approve' else 'rejected'
    ok = store.update_question_review(job_id, question_id, target)
    if not ok:
        raise HTTPException(status_code=404, detail='question_id not found')
    return {'ok': True}


@app.get('/job/{job_id}/export')
def export(job_id: str) -> Any:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='No result to export yet')
    path = store.export_path(job_id)
    if path is None:
        raise HTTPException(status_code=404, detail='No result to export yet')
    return FileResponse(path=str(path), filename=f'{job_id}.json', media_type='application/json')


def _accepted_questions(job_id: str) -> List[Dict[str, Any]]:
    result = store.get_result(job_id) or {}
    return [q for q in result.get('questions', []) if q.get('answer_key')]


@app.post('/job/{job_id}/practice/start')
def practice_start(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    questions = _accepted_questions(job_id)
    if not questions:
        raise HTTPException(status_code=409, detail='No accepted questions to practice; generate first.')
    try:
        session = practice_mod.start_session(store.job_dir(job_id), questions)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    qid = session.get('current_question_id')
    current = next((q for q in questions if q.get('question_id') == qid), None)
    return {'session': session, 'question': practice_mod.public_question(current) if current else None}


@app.get('/job/{job_id}/practice/{session_id}')
def practice_get(job_id: str, session_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    session = practice_mod.get_session(store.job_dir(job_id), session_id)
    if session is None:
        raise HTTPException(status_code=404, detail='Session not found')
    questions = _accepted_questions(job_id)
    qid = session.get('current_question_id')
    current = next((q for q in questions if q.get('question_id') == qid), None)
    return {'session': session, 'question': practice_mod.public_question(current) if current else None}


@app.get('/job/{job_id}/practice')
def practice_list(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    return {'sessions': practice_mod.list_sessions(store.job_dir(job_id))}


@app.post('/job/{job_id}/practice/{session_id}/answer')
def practice_answer(job_id: str, session_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    qid = payload.get('question_id')
    answer_key = payload.get('answer_key')
    if not qid or not answer_key:
        raise HTTPException(status_code=400, detail='question_id and answer_key required')
    try:
        return practice_mod.submit_answer(
            store.job_dir(job_id), session_id, str(qid), str(answer_key), _accepted_questions(job_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/job/{job_id}/practice/{session_id}/feedback')
def practice_feedback(job_id: str, session_id: str, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    qid = payload.get('question_id')
    feedback = payload.get('feedback')
    if not qid or feedback not in ('like', 'dislike'):
        raise HTTPException(status_code=400, detail="payload requires question_id + feedback in {'like','dislike'}")
    try:
        return practice_mod.submit_feedback(store.job_dir(job_id), session_id, str(qid), feedback)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post('/job/{job_id}/practice/{session_id}/next')
def practice_next(job_id: str, session_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    questions = _accepted_questions(job_id)
    try:
        nxt = practice_mod.next_question(store.job_dir(job_id), session_id, questions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'question': practice_mod.public_question(nxt) if nxt else None, 'finished': nxt is None}


@app.get('/job/{job_id}/benchmark')
def benchmark_endpoint(job_id: str) -> Dict[str, Any]:
    if not store.job_exists(job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    from pipeline import benchmark as bench_mod
    metrics = bench_mod.benchmark_job(job_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail='No result.json yet')
    return {'metrics': metrics}


@app.exception_handler(Exception)
def unhandled_exception(_request, exc: Exception):  # noqa: ANN001
    return JSONResponse(
        status_code=500,
        content={'detail': f'{type(exc).__name__}: {exc}'},
    )

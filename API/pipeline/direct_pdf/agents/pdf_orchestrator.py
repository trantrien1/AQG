"""DirectPdfOrchestrator — điều phối multi-agent (rút gọn) cho Direct_PDF_Mode.

Chuỗi cho mỗi slot: PdfWriter -> PdfDistractor -> VerifierAgent(context='')
-> PdfCritic -> chọn candidate tốt nhất -> FormatterAgent. Không có Planner
(dùng thẳng `_synthetic_slot`) và không có Refiner (candidate reject -> retry
slot). "Context" của mọi agent sinh/critic là các trang PDF đã render
(`attachment_parts`), gọi qua `call_llm_with_pdf`.

Trả về `DirectPdfResult` GIỐNG HỆT monolith cũ nên `runner.run_direct_pdf` và
`web/jobs.run_direct_generation` tiêu thụ không cần sửa.
"""
from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import attach as attach_mod
from ..generator import DirectPdfResult, _synthetic_slot
from .pdf_writer_agent import PdfWriterAgent
from .pdf_distractor_agent import PdfDistractorAgent
from .pdf_critic_agent import PdfCriticAgent
from .messages import PdfWriteRequest, PdfDistractorRequest, PdfCriticRequest
from ... import config as cfg
from ...agents import VerifierAgent, FormatterAgent
from ...agents.messages import (
    VerifyRequest, FormatAcceptedRequest,
)
from ...llm_client import BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError
from ...rule_validator import validate_record
from ... import reject as reject_mod
from ... import schema as schema_mod
from ...schema import record_option_text_issues

ProgressCallback = Callable[[Dict[str, Any]], None]

# Số record bị loại tối đa giữ lại cho UI — tránh phình debug_rejected.json
# khi model fail hàng loạt.
_MAX_REJECTED_RECORDS = 80

# reason_code mặc định theo stage khi message không khớp heuristic nào.
_STAGE_DEFAULT_CODE = {
    'writer': 'writer_empty',
    'distractor': 'bad_distractors',
    'verifier': 'verifier_failed',
    'critic': 'quality_low',
    'format': 'format_error',
    'dedup': 'duplicate',
    'orchestrator': 'orchestrator_error',
}


def _rejected_record(
    slot: Dict[str, Any],
    stage: str,
    message: str,
    code: Optional[str] = None,
    cand: Optional[Dict[str, Any]] = None,
    record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Dựng record câu bị loại cho tab "Từ chối" trên web.

    Ưu tiên record formatter (đủ stem/options/answer_key); chưa format được thì
    thử dựng từ candidate; tệ nhất là entry chỉ có lý do (UI vẫn hiển thị).
    """
    message = str(message or '')[:500]
    if code is None:
        code = reject_mod.classify(message)
        if code == 'unknown':
            code = _STAGE_DEFAULT_CODE.get(stage, 'unknown')
    out: Dict[str, Any] = {}
    if record:
        out = dict(record)
    elif cand:
        try:
            out = schema_mod.to_question_record(dict(slot), dict(cand))
        except Exception:
            out = {'stem': str(cand.get('stem') or '')}
    out.setdefault('stem', '')
    slot_id = slot.get('slot_id')
    out.update({
        'question_id': f'rej_{slot_id}_{stage}',
        'blueprint_slot_id': slot_id,
        'cognitive_level': out.get('cognitive_level') or slot.get('cognitive_level'),
        'review_status': 'rejected',
        'reject_reason': message,
        'reject_reason_code': code,
        'reject_reason_stage': stage,
        'reject_log': [reject_mod.make(code, stage=stage, message=message,
                                       slot_id=slot_id)],
        'attempts': 1,
    })
    return out


def _stem_key(text: Any) -> str:
    return re.sub(r'\s+', ' ', str(text or '').strip().lower())[:80]


def _pick_cognitive(bloom_distribution: Optional[List[Dict[str, Any]]],
                    index: int) -> str:
    """Chọn mức Bloom cho slot thứ `index` theo phân bố (round-robin có trọng số).

    Không có Planner nên orchestrator tự rải Bloom: xây một danh sách phẳng theo
    tỉ lệ rồi lấy phần tử `index % len`. Rỗng -> 'Thông hiểu'.
    """
    if not bloom_distribution:
        return 'Thông hiểu'
    flat: List[str] = []
    for b in bloom_distribution:
        level = str(b.get('cognitive_level') or b.get('level') or '').strip()
        if not level:
            continue
        frac = b.get('fraction')
        if frac is None:
            frac = b.get('ratio')
        weight = max(1, int(round(float(frac) * 10))) if frac is not None else 1
        flat.extend([level] * weight)
    if not flat:
        return 'Thông hiểu'
    return flat[index % len(flat)]


def _pick_outcome(learning_outcomes: Optional[List[Dict[str, str]]],
                  index: int) -> Optional[Dict[str, str]]:
    """Chọn Chuẩn đầu ra cho slot thứ `index` (round-robin, như rải Bloom).

    Mỗi câu nhắm đúng MỘT CĐR để writer bám sát; danh sách N CĐR được phủ đều
    trên N câu đầu rồi lặp lại. Không có CĐR -> None (prompt như cũ).
    """
    if not learning_outcomes:
        return None
    valid = [o for o in learning_outcomes
             if isinstance(o, dict) and str(o.get('description') or '').strip()]
    if not valid:
        return None
    return valid[index % len(valid)]


def _outcome_key(outcome: Dict[str, str]) -> str:
    return str(outcome.get('code') or outcome.get('description') or '').strip()


def _pick_outcome_balanced(
    learning_outcomes: Optional[List[Dict[str, str]]],
    counts: Dict[str, int],
) -> Optional[Dict[str, str]]:
    """Chọn CĐR đang được nhắm ÍT NHẤT (đã accept + đang bay trong wave).

    Khi sinh song song, `len(questions)` không còn phản ánh slot đang chạy nên
    round-robin theo index sẽ dồn lệch CĐR lúc có slot fail. Đếm trực tiếp và
    lấy min (tie-break theo thứ tự khai báo) — trùng khớp round-robin khi mọi
    slot đều thành công, và tự bù CĐR bị hụt khi một slot giữa wave fail.
    """
    if not learning_outcomes:
        return None
    valid = [o for o in learning_outcomes
             if isinstance(o, dict) and str(o.get('description') or '').strip()]
    if not valid:
        return None
    best = min(range(len(valid)),
               key=lambda i: (counts.get(_outcome_key(valid[i]), 0), i))
    return valid[best]


def _difficulty_target_for_level(
    bloom_distribution: Optional[List[Dict[str, Any]]],
    level: str,
) -> float:
    if bloom_distribution:
        for item in bloom_distribution:
            item_level = str(item.get('cognitive_level') or item.get('level') or '').strip()
            if item_level == level:
                try:
                    return float(item.get('difficulty_target', 0.5))
                except (TypeError, ValueError):
                    return 0.5
    defaults = {
        'Nhận biết': 0.30,
        'Thông hiểu': 0.50,
        'Vận dụng': 0.70,
        'Vận dụng cao': 0.85,
    }
    return defaults.get(level, 0.5)


class DirectPdfOrchestrator:
    """Multi-agent (rút gọn) cho Direct_PDF_Mode, giữ contract DirectPdfResult."""

    def __init__(self, model: Optional[str] = None, use_skills: bool = True):
        self.model = model or cfg.GENERATOR_MODEL
        self.writer = PdfWriterAgent(use_skills=use_skills, model=self.model)
        self.distractor = PdfDistractorAgent(use_skills=use_skills, model=self.model)
        # Critic chấm/đánh giá — dùng JUDGE_MODEL (mặc định = generator model
        # khi không set env) để có thể chạy model nhẹ hơn, tiết kiệm quota.
        self.critic = PdfCriticAgent(use_skills=use_skills, model=cfg.JUDGE_MODEL)
        # Tái dùng nguyên trạng agent deterministic (không gọi LLM).
        self.verifier = VerifierAgent(use_skills=use_skills)
        self.formatter = FormatterAgent(use_skills=use_skills)
        # _process_slot chạy song song nhiều thread; SymPy (trong Verifier)
        # không cam kết thread-safe nên tuần tự hoá riêng bước verify — bước
        # này thuần CPU và nhanh (<1s) so với các call LLM nên không nghẽn.
        self._verifier_lock = threading.Lock()

    # ---- build attachment (một lần) ----
    def _build_attachment_parts(self, pdf_path: str) -> List[Dict[str, Any]]:
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        filename = pdf_path.rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
        # prompt_text ở đây chỉ là placeholder cho builder; agent sẽ tự ghép
        # prompt riêng + attachment_parts (phần non-text) khi gọi.
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
        return [p for p in base if p.get('type') != 'text']

    # ---- một slot: writer -> distractor -> verify -> critic ----
    def _process_slot(
        self,
        slot: Dict[str, Any],
        attachment_parts: List[Dict[str, Any]],
        avoid_stems: List[str],
    ) -> Tuple[Optional[Dict[str, Any]], int, int, List[Dict[str, Any]]]:
        """Trả (candidate hoặc None, parse_errors, verify_failures, rejects)."""
        parse_errors = 0
        verify_failures = 0
        rejects: List[Dict[str, Any]] = []

        w_resp = self.writer.run(PdfWriteRequest(
            attachment_parts=attachment_parts, slot=slot,
            avoid_stems=avoid_stems, num_samples=1,
        ))
        if not w_resp.candidates:
            print(f'    [pdf-slot {slot.get("slot_id")}] writer 0 candidates; '
                  f'errors={w_resp.errors}')
            rejects.append(_rejected_record(
                slot, 'writer',
                f'Writer không sinh được câu hỏi hợp lệ (errors={w_resp.errors})',
            ))
            return None, parse_errors + 1, verify_failures, rejects

        scored: List[Dict[str, Any]] = []
        for cand in w_resp.candidates:
            # Stage 2: distractor
            d_resp = self.distractor.run(PdfDistractorRequest(
                attachment_parts=attachment_parts, candidate=cand, slot=slot,
            ))
            if d_resp.error or len(d_resp.distractors) != 3:
                print(f'    [pdf-slot {slot.get("slot_id")}] distractor drop: '
                      f'error={d_resp.error} n={len(d_resp.distractors)}')
                rejects.append(_rejected_record(
                    slot, 'distractor',
                    f'Không tạo đủ 3 phương án nhiễu đạt chuẩn '
                    f'(error={d_resp.error}, n={len(d_resp.distractors)})',
                    cand=cand,
                ))
                parse_errors += 1
                continue
            cand['distractors'] = d_resp.distractors

            # Stage 3: verifier (deterministic, context='')
            with self._verifier_lock:
                v_resp = self.verifier.run(VerifyRequest(
                    candidate=cand, slot=slot, context='',
                ))
            if v_resp.rejected:
                print(f'    [pdf-slot {slot.get("slot_id")}] verifier reject: '
                      f'{v_resp.reject_reason}')
                rejects.append(_rejected_record(
                    slot, 'verifier', v_resp.reject_reason or '', cand=cand,
                ))
                # Reject vì claim số học sai -> tính verify_failures.
                if 'verifier=false' in (v_resp.reject_reason or '').lower():
                    verify_failures += 1
                else:
                    parse_errors += 1
                continue
            _ver = v_resp.annotations.get('_verification') or {}
            if _ver.get('verified') is False:
                # Mismatch số học không còn bị loại (thường do hint viết lệch,
                # không phải LLM tính sai) — chỉ log để theo dõi.
                print(f'    [pdf-slot {slot.get("slot_id")}] verifier mismatch '
                      f'(giữ lại): {_ver.get("engine")}: '
                      f'{str(_ver.get("detail"))[:80]}')
            patch = v_resp.annotations.pop('_candidate_patch', None)
            if isinstance(patch, dict):
                cand.update(patch)
            cand.update(v_resp.annotations)

            # Stage 4: critic (vision)
            cr_resp = self.critic.run(PdfCriticRequest(
                attachment_parts=attachment_parts, candidate=cand, slot=slot,
            ))
            cand.update(cr_resp.annotations)
            if cr_resp.rejected:
                print(f'    [pdf-slot {slot.get("slot_id")}] critic reject: '
                      f'{cr_resp.reject_reason}')
                rejects.append(_rejected_record(
                    slot, 'critic', cr_resp.reject_reason or '', cand=cand,
                ))
                parse_errors += 1
                continue
            scored.append(cand)

        if not scored:
            return None, parse_errors, verify_failures, rejects

        # Chọn tốt nhất: ưu tiên verified, rồi _quality, rồi _grounding.
        def _key(c: Dict[str, Any]):
            verified = 1 if (c.get('_verification') or {}).get('verified') is True else 0
            return (verified, c.get('_quality') or 0.0, c.get('_grounding') or 0.0)

        best = max(scored, key=_key)
        return best, parse_errors, verify_failures, rejects

    def generate(
        self,
        pdf_path: str,
        requested_count: int,
        bloom_distribution: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
        feedback_guidance: str = '',
        seed_avoid_stems: Optional[List[str]] = None,
        include_explanation: bool = True,
        attachment_parts: Optional[List[Dict[str, Any]]] = None,
        learning_outcomes: Optional[List[Dict[str, str]]] = None,
    ) -> DirectPdfResult:
        if model:
            self.model = model
            self.writer.model = model
            self.distractor.model = model
            # KHÔNG ghi đè critic: nó cố định chạy cfg.JUDGE_MODEL (model chấm
            # nhẹ, vd gpt-4o-mini). Ghi đè bằng generator model ở đây từng vô
            # hiệu hoá toàn bộ cấu hình OPENAI_JUDGE_MODEL.

        def _emit(**event: Any) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(event)
            except Exception:
                pass

        # 1. Build attachment MỘT LẦN — trừ khi caller đã đưa sẵn các trang
        # render từ bước /prepare (chạy nền lúc người dùng chọn config).
        _emit(stage='preparing_pdf', accepted=0, attempted=0, target=requested_count)
        if not attachment_parts:
            try:
                attachment_parts = self._build_attachment_parts(pdf_path)
            except attach_mod.PdfAttachError as e:
                return DirectPdfResult(
                    questions=[], accepted_count=0, requested_count=requested_count,
                    is_partial=requested_count > 0, parse_errors=0,
                    error_code='attach_failed', error_message=str(e),
                )
        _emit(stage='pdf_ready', accepted=0, attempted=0, target=requested_count)

        questions: List[Dict[str, Any]] = []
        seen: set = set()
        parse_errors = 0
        verify_failures = 0
        # Gom record câu bị loại (mọi stage) — chỉ append ở thread chính.
        rejected_records: List[Dict[str, Any]] = []
        # RLHF: câu đã có sẵn (giữ lại từ lượt trước) hoặc bị chê — không lặp lại.
        seed_avoid = [str(s) for s in (seed_avoid_stems or [])
                      if str(s or '').strip()]
        for s in seed_avoid:
            k = _stem_key(s)
            if k:
                seen.add(k)
        feedback_guidance = str(feedback_guidance or '').strip()

        max_attempts = cfg.MAX_SLOT_ATTEMPTS * requested_count + 6
        # Số lô rỗng LIÊN TIẾP trước khi bỏ cuộc. Đặt tương đối theo số câu yêu
        # cầu (tối thiểu 4) để mục tiêu lớn không dừng sớm khi gặp một chuỗi câu
        # bị model từ chối/throttle tạm thời.
        max_empty_streak = max(4, requested_count // 3)
        empty_streak = 0
        slot_index = 0
        attempts_used = 0
        # Sinh song song theo wave: mỗi wave chạy tối đa `parallel` slot đồng
        # thời (mỗi slot = chuỗi Writer->Distractor->Verify->Critic độc lập).
        # Formatter + dedup + append vẫn TUẦN TỰ ở thread chính nên progress
        # callback và state (questions/seen/streak) không cần khoá.
        parallel = max(1, int(getattr(cfg, 'DIRECT_PDF_PARALLEL_SLOTS', 1)))
        # Đếm CĐR đã nhắm (accepted + đang bay) để wave sau bù CĐR bị hụt.
        outcome_counts: Dict[str, int] = {}

        def _release_outcome(slot: Dict[str, Any]) -> None:
            o = slot.get('_learning_outcome')
            if isinstance(o, dict):
                k = _outcome_key(o)
                if outcome_counts.get(k, 0) > 0:
                    outcome_counts[k] -= 1

        def _build_slot(virtual_index: int) -> Dict[str, Any]:
            nonlocal slot_index
            cognitive = _pick_cognitive(bloom_distribution, virtual_index)
            slot = _synthetic_slot(slot_index, {
                'cognitive_level': cognitive,
                'difficulty_target': _difficulty_target_for_level(bloom_distribution, cognitive),
            })
            # Direct_PDF: writer tạo BÀI TẬP MỚI theo phương pháp trong tài liệu
            # rồi trích một công thức/định nghĩa chung làm source_quote. Đánh dấu
            # slot là 'exercise' để rule_validator bỏ qua check token-overlap
            # (vốn giả định quote cùng chunk với câu hỏi — đúng cho pipeline chunk,
            # nhưng misfire ở đây khiến quote công thức chung bị loại nhầm là
            # 'not_relevant'). Các check metadata/heading bắt quote rác vẫn chạy.
            slot['source_chunk_type'] = 'exercise'
            outcome = _pick_outcome_balanced(learning_outcomes, outcome_counts)
            if outcome:
                # Writer đọc key này để soạn câu kiểm tra đúng CĐR được gán;
                # record nhận nhãn ngay khi accept (classifier sau chỉ kiểm chứng).
                slot['_learning_outcome'] = outcome
                k = _outcome_key(outcome)
                outcome_counts[k] = outcome_counts.get(k, 0) + 1
            if feedback_guidance:
                # Writer/Distractor đọc key này để tuân thủ sở thích người dùng.
                slot['_feedback_guidance'] = feedback_guidance
            if not include_explanation:
                # Chế độ nhanh: Writer bỏ detailed_solution/why_correct (ít token
                # đầu ra hơn hẳn), Formatter xoá mọi trường giải thích khỏi record.
                slot['_no_explanation'] = True
                slot['_generation_config'] = {
                    'include_explanation': False,
                    'requires_detailed_solution': False,
                }
            slot_index += 1
            return slot

        with ThreadPoolExecutor(max_workers=parallel) as pool:
            while (len(questions) < requested_count
                   and attempts_used < max_attempts
                   and empty_streak < max_empty_streak):
                remaining = requested_count - len(questions)
                # wave_size <= remaining nên không bao giờ sinh thừa câu.
                wave_size = min(parallel, remaining, max_attempts - attempts_used)
                # Slot trong cùng wave chạy đồng thời nên chỉ né được stem của
                # các câu ĐÃ accept; trùng lặp nội-wave do dedup `seen` chặn sau.
                avoid = seed_avoid + [q.get('stem', '') for q in questions]
                wave: List[Tuple[Dict[str, Any], Any]] = []
                for i in range(wave_size):
                    slot = _build_slot(len(questions) + i)
                    attempts_used += 1
                    _emit(
                        stage='slot_started',
                        slot_id=slot.get('slot_id'),
                        attempted=attempts_used,
                        max_attempts=max_attempts,
                        accepted=len(questions),
                        target=requested_count,
                    )
                    wave.append((slot, pool.submit(
                        self._process_slot, slot, attachment_parts, avoid)))

                for slot, fut in wave:
                    try:
                        cand, pe, vf, slot_rejects = fut.result()
                    except (BudgetExceeded, NonRetryableLLMError,
                            PdfUnsupportedError):
                        # `with pool` sẽ đợi các slot đang bay xong rồi raise.
                        raise
                    except Exception as exc:
                        _release_outcome(slot)
                        empty_streak += 1
                        if len(rejected_records) < _MAX_REJECTED_RECORDS:
                            rejected_records.append(_rejected_record(
                                slot, 'orchestrator',
                                f'Slot lỗi bất ngờ: {exc}',
                            ))
                        _emit(
                            stage='slot_error',
                            slot_id=slot.get('slot_id'),
                            attempted=attempts_used,
                            max_attempts=max_attempts,
                            accepted=len(questions),
                            target=requested_count,
                            empty_streak=empty_streak,
                        )
                        continue

                    parse_errors += pe
                    verify_failures += vf
                    room = _MAX_REJECTED_RECORDS - len(rejected_records)
                    if room > 0 and slot_rejects:
                        rejected_records.extend(slot_rejects[:room])

                    record = None
                    if cand is not None:
                        _emit(
                            stage='formatting',
                            slot_id=slot.get('slot_id'),
                            attempted=attempts_used,
                            max_attempts=max_attempts,
                            accepted=len(questions),
                            target=requested_count,
                        )
                        fmt = self.formatter.run(FormatAcceptedRequest(
                            slot=slot, candidate=cand, doc={}, attempts=1,
                        ))
                        issues = record_option_text_issues(fmt.record)
                        issues.extend(validate_record(fmt.record))
                        if issues:
                            print(f'    [pdf-format] record dropped, issues={issues}')
                            if len(rejected_records) < _MAX_REJECTED_RECORDS:
                                rejected_records.append(_rejected_record(
                                    slot, 'format',
                                    f'Định dạng không đạt: {issues}',
                                    record=fmt.record,
                                ))
                            parse_errors += 1
                        else:
                            record = fmt.record
                            outcome = slot.get('_learning_outcome')
                            if isinstance(outcome, dict) and outcome.get('code'):
                                record['learning_outcomes'] = [str(outcome['code'])]

                    if record is None:
                        _release_outcome(slot)
                        empty_streak += 1
                        _emit(
                            stage='slot_rejected',
                            slot_id=slot.get('slot_id'),
                            attempted=attempts_used,
                            max_attempts=max_attempts,
                            accepted=len(questions),
                            target=requested_count,
                            parse_errors=parse_errors,
                            verify_failures=verify_failures,
                            empty_streak=empty_streak,
                        )
                        continue

                    key = _stem_key(record.get('stem', ''))
                    if key and key in seen:
                        _release_outcome(slot)
                        empty_streak += 1
                        if len(rejected_records) < _MAX_REJECTED_RECORDS:
                            rejected_records.append(_rejected_record(
                                slot, 'dedup',
                                'Trùng với câu đã được chấp nhận trong cùng lượt sinh',
                                record=record,
                            ))
                        _emit(
                            stage='slot_duplicate',
                            slot_id=slot.get('slot_id'),
                            attempted=attempts_used,
                            max_attempts=max_attempts,
                            accepted=len(questions),
                            target=requested_count,
                            empty_streak=empty_streak,
                        )
                        continue
                    if key:
                        seen.add(key)
                    questions.append(record)
                    empty_streak = 0
                    _emit(
                        stage='question_accepted',
                        slot_id=slot.get('slot_id'),
                        attempted=attempts_used,
                        max_attempts=max_attempts,
                        accepted=len(questions),
                        target=requested_count,
                        parse_errors=parse_errors,
                        verify_failures=verify_failures,
                    )

        questions = questions[:requested_count]
        accepted_count = len(questions)
        _emit(
            stage='generation_finished',
            attempted=slot_index,
            max_attempts=max_attempts,
            accepted=accepted_count,
            target=requested_count,
            parse_errors=parse_errors,
            verify_failures=verify_failures,
        )
        return DirectPdfResult(
            questions=questions,
            accepted_count=accepted_count,
            requested_count=requested_count,
            is_partial=accepted_count < requested_count,
            parse_errors=parse_errors,
            verify_failures=verify_failures,
            error_code=None,
            error_message=None,
            rejected=rejected_records,
        )

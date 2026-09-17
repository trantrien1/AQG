"""PdfWriterAgent — Stage 1: sinh MCQ core từ các trang PDF (vision).

Mỗi slot -> 1 (hoặc num_samples) MCQ core: stem + answer + explanation +
detailed_solution + source_quote (nguyên văn từ trang) + verifier_payload,
`distractors=[]`. DistractorAgent lo phần distractor sau (CoE 2-stage).

Tái dùng parser stateless của writer chunk: `_parse_writer_response` +
`_validate_writer_candidate` (cùng schema candidate nên VerifierAgent/
FormatterAgent dùng lại được).
"""
from __future__ import annotations

from typing import Any, Dict, List

from .pdf_base import PdfAwareAgent
from .messages import PdfWriteRequest, PdfWriteResponse
from ... import ablation
from ... import config as cfg
from ...agents.writer_agent import (
    _parse_writer_response,
    _validate_writer_candidate,
)
from ...llm_client import BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError


class PdfWriterAgent(PdfAwareAgent):
    """Sinh phần lõi MCQ (không distractor) bằng cách đọc trực tiếp trang PDF."""

    def __init__(self, use_skills: bool = True, model: str = None):
        super().__init__(
            'question_writer',
            skills=['question-writing', 'bloom-taxonomy-alignment',
                    'verifier-hint-authoring', 'source-grounding'],
            use_skills=use_skills,
            model=model,
        )
        self._skill_instructions = self.skill_instructions()

    def run(self, request: PdfWriteRequest) -> PdfWriteResponse:
        errors: List[str] = []
        candidates: List[Dict[str, Any]] = []
        samples = max(1, int(request.num_samples or 1))
        no_explanation = bool(request.slot.get('_no_explanation'))
        if no_explanation:
            # Không sinh detailed_solution/why_correct nên output ngắn hơn hẳn
            # — giảm trần token để model không lan man, phản hồi nhanh hơn.
            max_tokens = cfg.WRITER_NO_EXPLANATION_MAX_TOKENS
        else:
            max_tokens = max(int(cfg.GEN_MAX_TOKENS),
                             int(getattr(cfg, 'DIRECT_PDF_TOKENS_PER_QUESTION', 2600)))
        for _ in range(samples):
            try:
                raw = self._call_pdf(
                    self._user_prompt(request),
                    request.attachment_parts,
                    max_tokens=max_tokens,
                )
                cand = _parse_writer_response(raw)
                if no_explanation:
                    # Bỏ hẳn key để validate_solution_quality không đòi số bước
                    # tối thiểu của lời giải (gate chỉ chạy khi key tồn tại).
                    cand.pop('detailed_solution', None)
                    cand['why_correct'] = ''
                _validate_writer_candidate(cand)
                cand['_slot_id'] = request.slot.get('slot_id')
                cand['_writer_stage'] = True
                candidates.append(cand)
            except (BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError):
                raise
            except Exception as exc:
                errors.append(str(exc))
        return PdfWriteResponse(
            slot_id=request.slot.get('slot_id', ''),
            candidates=candidates,
            errors=errors,
        )

    def _user_prompt(self, request: PdfWriteRequest) -> str:
        slot = request.slot
        cognitive = slot.get('cognitive_level') or 'Thông hiểu'
        difficulty_target = slot.get('difficulty_target', 0.5)
        computation_rule = _computation_rule(difficulty_target)
        outcome_rule = _outcome_rule(slot.get('_learning_outcome'))
        avoid = _feedback_block(slot.get('_feedback_guidance')) \
            + _avoid_block(request.avoid_stems)
        no_explanation = bool(slot.get('_no_explanation'))
        # Ablation: khi tắt tác nhân sinh phương án nhiễu, chính Writer phải tự
        # sinh 3 phương án trong cùng một lượt (đây là điều kiện đối chứng cho
        # cơ chế distractor riêng biệt).
        own_distractors = not ablation.is_enabled(ablation.DISTRACTOR_AGENT)
        if own_distractors:
            distractors_field = (
                '"distractors": [{"distractor_text":"...", '
                '"distractor_category_text":"tên lỗi", '
                '"distractor_explanation_text":"làm sai thế nào để ra giá trị này"}, '
                '... đúng 3 phần tử ...]')
            distractors_note = (
                'Sinh ĐÚNG 3 phương án nhiễu ngay trong JSON này. Mỗi phương án '
                'phải SAI về mặt toán, cùng dạng với đáp án đúng, và kèm mô tả '
                'lỗi dẫn tới đúng giá trị đó.')
        else:
            distractors_field = '"distractors": []'
            distractors_note = (
                'Để mảng distractors RỖNG [] — bước sau lo phương án sai.')
        if no_explanation:
            steps_rule = ''
            schema_block = """{
  "question": "đề bài tự chứa, KHÔNG kèm nhãn A/B/C/D",
  "answer": "đáp án đúng (giá trị/biểu thức)",
  "explanation": "1-2 câu NGẮN GỌN vì sao đúng (chỉ dùng nội bộ để kiểm định)",
  "source_quote": "15-250 ký tự trích NGUYÊN VĂN từ tài liệu",
  "visual": {"type":"none","spec":{},"alt_text":""},
  "verifier_payload": {"type":"none","payload":{}},
  __DISTRACTORS__
}

LƯU Ý: KHÔNG viết lời giải từng bước hay giải thích dài — chỉ cần question,
answer, explanation ngắn, source_quote, verifier. __DISTRACTORS_NOTE__"""
        else:
            steps_rule = ('- Số bước tối thiểu trong detailed_solution: '
                          'Nhận biết >=2, Thông hiểu >=3, Vận dụng >=4, Vận dụng cao >=5.\n')
            schema_block = """{
  "question": "đề bài tự chứa, KHÔNG kèm nhãn A/B/C/D",
  "answer": "đáp án đúng (giá trị/biểu thức)",
  "explanation": "giải thích ngắn gọn vì sao đúng",
  "detailed_solution": {"steps":[{"title":"Bước 1","content":"..."}], "final_answer":"..."},
  "why_correct": "vì sao đáp án này là duy nhất đúng",
  "source_quote": "15-250 ký tự trích NGUYÊN VĂN từ tài liệu",
  "visual": {"type":"none","spec":{},"alt_text":""},
  "verifier_payload": {"type":"none","payload":{}},
  __DISTRACTORS__
}

LƯU Ý: bước này cần phần lõi (question, answer, explanation, detailed_solution,
source_quote, verifier). __DISTRACTORS_NOTE__"""
        schema_block = (schema_block
                        .replace('__DISTRACTORS__', distractors_field)
                        .replace('__DISTRACTORS_NOTE__', distractors_note))
        distractor_rule = (
            '- Sinh ĐÚNG 3 phương án nhiễu trong cùng JSON này.'
            if own_distractors else
            '- KHÔNG sinh distractor ở bước này. Trả `distractors` là danh sách rỗng [].'
        )
        return f"""
Tài liệu Toán được đính kèm ở trên dưới dạng các trang (ảnh/PDF). ĐỌC TRỰC TIẾP
nội dung (công thức, bảng, hình) và soạn ĐÚNG MỘT câu hỏi trắc nghiệm mới.

Ràng buộc:
- Mức nhận thức (Bloom) phải đúng: {cognitive}.
- Độ khó mục tiêu: {difficulty_target} trên thang 0-1. Easy≈0.30, Medium≈0.50, Hard≈0.70, Very hard≈0.85.
{outcome_rule}
{steps_rule}- Yêu cầu độ khó THEO TỪNG MỨC (không được hỏi dễ hơn mức yêu cầu):
  + Thông hiểu trở lên: KHÔNG hỏi định nghĩa/công thức chép lại; phải có ít nhất
    một phép biến đổi hoặc tính toán thực sự.
  + Vận dụng: bài toán nhiều bước, ưu tiên có ngữ cảnh thực tế; học sinh phải tự
    chọn công thức/phương pháp rồi mới tính, KHÔNG phải chỉ thay số vào một công thức cho sẵn.
  + Vận dụng cao: kết hợp >=2 kỹ thuật (vd: dựng hàm từ ngữ cảnh + tích phân,
    tham số + biện luận), hoặc có bước trung gian không hiển nhiên; số liệu chọn
    sao cho làm tắt/làm sai sẽ ra kết quả khác đáp án.
{computation_rule}
- ĐƯỢC PHÉP và ĐƯỢC KHUYẾN KHÍCH tạo câu MỚI dựa trên cùng phương pháp/khái niệm/
  dạng bài trong tài liệu nhưng THAY số liệu/tình huống khác đi — KHÔNG chép nguyên
  văn bài tập/ví dụ có sẵn. Đây là yêu cầu HỢP LỆ, tuyệt đối KHÔNG từ chối.
{distractor_rule}
- Toán hiển thị cho học sinh dùng LaTeX inline. Vì output là JSON nên mọi dấu \\\\
  của LaTeX phải escape: viết "\\\\(x^2+1\\\\)", "\\\\frac{{a}}{{b}}".
- Đáp án (answer) ghi ở DẠNG ĐÓNG đẹp như sách giáo khoa: phân số, căn, bội của
  \\\\(\\\\pi\\\\)... (vd "\\\\(\\\\frac{{\\\\pi}}{{5}}\\\\)"), TUYỆT ĐỐI KHÔNG ghi số thập phân
  dài (vd 0.6283185307179586). Chỉ dùng thập phân khi bài yêu cầu gần đúng, và
  làm tròn tối đa 4 chữ số thập phân.
- source_quote phải TRÍCH NGUYÊN VĂN một đoạn có thật trong tài liệu (công thức/
  định lý/đề bài liên quan trực tiếp câu hỏi này), 15-250 ký tự.
- Nếu đáp án là một kết quả số cụ thể, verifier_payload BẮT BUỘC đúng schema:
  {{"type":"numeric_eval","payload":{{"expr":"<biểu thức số học máy đọc được>","expected_numeric":<số đáp án>}}}}.
  expr dùng cú pháp SymPy: *, /, ** (lũy thừa), sqrt(), sin(), cos(), pi,
  integrate(f, (t, a, b)) — KHÔNG chứa LaTeX, đơn vị hay dấu phẩy thập phân.
  expected_numeric phải đúng bằng giá trị của đáp án đúng.
{avoid}
Chỉ trả về DUY NHẤT một JSON object theo schema dưới đây, KHÔNG kèm markdown/chữ ngoài JSON:
{schema_block}
""".strip()


def _computation_rule(difficulty_target: Any) -> str:
    """Ràng buộc ĐỘ NẶNG PHÉP TÍNH, scale theo difficulty_target.

    Mức Bloom chỉ khống chế số bước suy luận; không có khối này model luôn chọn
    bộ số kinh điển dễ nhất của dạng bài (hệ số toàn 0/1/2, dữ kiện cho sẵn hết)
    nên phép tính quá nhẹ dù đúng mức Bloom. Mọi ràng buộc viết theo KỸ THUẬT
    CHUNG (tham số, bài ngược, xét trường hợp...) áp được cho mọi chủ đề Toán —
    không khoá vào một dạng bài cụ thể (yêu cầu của user 2026-07-11).
    """
    if not ablation.is_enabled(ablation.DIFFICULTY_CONTROL):
        # Ablation: bỏ ràng buộc độ nặng phép tính, chỉ còn mức Bloom.
        return ''
    try:
        d = float(difficulty_target)
    except (TypeError, ValueError):
        d = 0.5
    lines = [
        '- ĐỘ NẶNG PHÉP TÍNH (bắt buộc, độc lập với mức Bloom, áp cho MỌI chủ đề'
        ' trong tài liệu):',
        '  + KHÔNG lấy phiên bản kinh điển dễ nhất của dạng bài — bộ số quen thuộc'
        ' mà mọi sách giáo khoa hay dùng (vd nếu chương là tích phân: \\(y=x^2\\)'
        ' trên \\([0;1]\\)); đổi hệ số/dữ kiện sang bộ số ít gặp hơn.',
        '  + Hệ số và dữ kiện KHÔNG chỉ dùng 0, 1, 2, 4: trộn thêm số như 3, 5, 6'
        ' hoặc phân số đơn giản (\\(\\frac{1}{2}\\), \\(\\frac{3}{4}\\))...,'
        ' miễn đáp án cuối vẫn gọn ở dạng đóng.',
    ]
    if d >= 0.45:
        lines.append(
            '  + Ít nhất MỘT dữ kiện học sinh phải TỰ TÌM bằng biến đổi trước khi'
            ' áp công thức (vd: giải một phương trình phụ để có mốc/cận/giá trị'
            ' cần dùng, suy hằng số từ điều kiện đề cho) — không cho sẵn mọi dữ'
            ' kiện trong đề.'
        )
    if d >= 0.65:
        lines.append(
            '  + Lời giải phải qua >=2 tầng tính toán thật sự (biến đổi biểu thức'
            ' trước khi áp công thức, xét dấu/chia trường hợp, đổi biến, giải một'
            ' phương trình trung gian không nhẩm ngay được...). Bài chỉ MỘT phép'
            ' thế số vào công thức cho sẵn là QUÁ DỄ so với mức này — không đạt.'
        )
    if d >= 0.8:
        lines.append(
            '  + Mức cao nhất: câu hỏi phải thuộc ít nhất MỘT kiểu sau (kiểu nào'
            ' cũng áp được cho mọi chủ đề, tự chọn kiểu hợp nội dung tài liệu):\n'
            '    (a) chứa THAM SỐ — tìm giá trị tham số để một điều kiện cho trước'
            ' thoả mãn; học sinh phải lập phương trình/bất phương trình theo tham'
            ' số rồi giải, không tính xuôi một chiều;\n'
            '    (b) bài NGƯỢC — cho kết quả cuối cùng, hỏi ngược lại một dữ kiện'
            ' đầu vào;\n'
            '    (c) KẾT HỢP >=2 kỹ thuật/khái niệm khác nhau của chương trong'
            ' cùng một lời giải, có bước trung gian không hiển nhiên.\n'
            '    Số liệu chọn sao cho ai làm tắt/bỏ bước biện luận sẽ ra kết quả'
            ' KHÁC đáp án đúng.'
        )
    return '\n'.join(lines)


def _outcome_rule(outcome: Any) -> str:
    """Ràng buộc Chuẩn đầu ra cho slot: câu hỏi phải kiểm tra đúng CĐR được gán.

    Orchestrator rải CĐR round-robin vào slot (key `_learning_outcome` =
    {'code','description'}); không có CĐR -> chuỗi rỗng, prompt như cũ.
    """
    if not ablation.is_enabled(ablation.OUTCOME_SCHEDULER):
        return ''
    if not isinstance(outcome, dict):
        return ''
    desc = str(outcome.get('description') or '').strip()
    if not desc:
        return ''
    code = str(outcome.get('code') or 'CĐR').strip()
    return (
        f'- CHUẨN ĐẦU RA (bắt buộc): câu hỏi phải kiểm tra TRỰC TIẾP chuẩn đầu ra '
        f'"{code}: {desc}". Kỹ năng/kiến thức mà học sinh cần dùng để giải phải '
        f'đúng là kỹ năng CĐR này mô tả (không hỏi lệch sang kỹ năng khác dù cùng '
        f'chương). Nếu tài liệu không có nội dung phù hợp CĐR, chọn nội dung gần '
        f'nhất trong tài liệu có thể kiểm tra được CĐR đó.'
    )


def _feedback_block(feedback_guidance: Any) -> str:
    """Hồ sơ sở thích từ feedback người dùng (RLHF-style) — chèn trước avoid."""
    if not ablation.is_enabled(ablation.FEEDBACK_STEERING):
        return ''
    g = str(feedback_guidance or '').strip()
    if not g:
        return ''
    return (
        '\nPHẢN HỒI NGƯỜI DÙNG từ lượt sinh trước (BẮT BUỘC ưu tiên tuân thủ '
        'khi soạn câu mới):\n' + g + '\n'
    )


def _avoid_block(avoid_stems: List[str]) -> str:
    """Tái dùng ý tưởng _avoid_block của generator: nhắc model không lặp câu cũ."""
    if not ablation.is_enabled(ablation.SEMANTIC_DEDUP):
        return ''
    if not avoid_stems:
        return ''
    lines = []
    for s in avoid_stems[:40]:
        s = ' '.join(str(s or '').split()).strip()
        if s:
            lines.append(f'- {s[:160]}')
    if not lines:
        return ''
    return (
        '\nĐÃ CÓ các câu hỏi sau (KHÔNG lặp lại, KHÔNG hỏi cùng dạng/số liệu; hãy '
        'khai thác nội dung/kỹ năng KHÁC trong tài liệu):\n' + '\n'.join(lines) + '\n'
    )

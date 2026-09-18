"""Writer fine-tune cắm vào pipeline Direct_PDF_Mode (không cần GPU/model)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'notebooks'))

from mcqft import ft_writer, pipeline_ft, prompts  # noqa: E402
from pipeline import rule_validator  # noqa: E402
from pipeline.direct_pdf.agents.messages import (  # noqa: E402
    PdfCriticResponse, PdfDistractorResponse, PdfWriteRequest,
)
from pipeline.direct_pdf.generator import _synthetic_slot  # noqa: E402

DOC_TEXT = """DẠNG 2: TÍCH PHÂN HÀM MŨ
Công thức cơ bản: $\\int e^{ax}\\,dx = \\frac{1}{a}e^{ax} + C$ với $a \\neq 0$.
Câu 12. Tính $\\int_0^1 e^{2x}\\,dx$.
A. $\\frac{e^2-1}{2}$ B. $e^2-1$ C. $\\frac{e^2}{2}$ D. $2e^2$
Lời giải
Ta có $\\int_0^1 e^{2x}dx = \\frac{1}{2}e^{2x}\\Big|_0^1 = \\frac{e^2-1}{2}$.
"""

DRAFT = prompts.gen_target({
    'question': ('Cho hàm số $f(x)=e^{3x}$ liên tục trên $\\mathbb{R}$. '
                 'Tính tích phân $I=\\int_0^1 f(x)\\,dx$ theo $e$.'),
    'choices': ['A. $\\frac{e^3-1}{3}$', 'B. $e^3-1$', 'C. $\\frac{e^3}{3}$', 'D. $3e^3$'],
    'answer': 'A',
    'solution': ('Đặt $u=3x$ nên $du=3dx$.\n'
                 'Khi đó $I=\\frac{1}{3}\\int_0^3 e^{u}du$.\n'
                 'Suy ra $I=\\frac{1}{3}e^{u}\\Big|_0^3$.\n'
                 'Vậy $I=\\frac{e^3-1}{3}$.'),
})


def _slot(level='Thông hiểu'):
    slot = _synthetic_slot(0, {'cognitive_level': level, 'difficulty_target': 0.5})
    slot['source_chunk_type'] = 'exercise'
    return slot


# ---------------------------------------------------------------------------
# chuyển câu mô hình soạn -> candidate của pipeline
# ---------------------------------------------------------------------------

def test_split_steps_only_splits_further_when_needed():
    solution = 'Ta có $a. b$ và $x=1$. Sau đó $y=2$.'
    assert len(ft_writer.split_steps(solution, 1)) == 1
    steps = ft_writer.split_steps(solution, 3)
    assert len(steps) >= 2
    # cắt ở ngoài công thức: "$a. b$" không bị tách giữa dấu $
    assert all(s['content'].count('$') % 2 == 0 for s in steps)


def test_trim_explanation_cuts_at_a_line_break():
    text = 'dòng một\n' + 'x' * 2000
    out = ft_writer.trim_explanation(text, limit=100)
    assert out == 'dòng một' and len(out) <= 100


def test_source_quote_prefers_a_formula_line_over_an_exercise_stem():
    candidate = {'question_text': ('Cho hàm số $f(x)=e^{3x}$. Tính tích phân '
                                   '$I=\\int_0^1 f(x)\\,dx$ theo $e$.'),
                 'answer_text': '$\\frac{e^3-1}{3}$',
                 'answer_explanation_text': 'Dùng công thức nguyên hàm hàm mũ.'}
    quote = ft_writer.pick_source_quote(candidate, DOC_TEXT, _slot())
    assert 'Công thức cơ bản' in quote
    assert rule_validator.source_quote_issues(
        dict(candidate, source_quote_text=quote), _slot()) == []


def test_candidate_passes_the_pipeline_rule_validator():
    record, errors = ft_writer.parse_generated(DRAFT)
    assert errors == []
    slot = _slot()
    cand = ft_writer.to_candidate(record, slot, DOC_TEXT)
    assert cand['answer_text'] == '$\\frac{e^3-1}{3}$'
    assert len(cand['detailed_solution']['steps']) >= 3
    assert cand['source_quote_text']
    # Writer của pipeline cũng chỉ sinh phần lõi; distractor do tác nhân sau thêm.
    cand['distractors'] = [
        {'distractor_text': f'$x_{i}$', 'distractor_category_text': f'loi_{i}',
         'distractor_explanation_text': f'Nhân sai hệ số nên ra $x_{i}$ = {i}+1.'}
        for i in range(3)]
    assert rule_validator.validate_candidate(cand, slot) == []


def test_own_distractors_mode_keeps_the_model_options():
    record, _ = ft_writer.parse_generated(DRAFT)
    cand = ft_writer.to_candidate(record, _slot(), DOC_TEXT, own_distractors=True)
    texts = [d['distractor_text'] for d in cand['distractors']]
    assert texts == ['$e^3-1$', '$\\frac{e^3}{3}$', '$3e^3$']
    assert all(d['distractor_explanation_text'] for d in cand['distractors'])


# ---------------------------------------------------------------------------
# FineTunedWriter
# ---------------------------------------------------------------------------

def _request(slot):
    return PdfWriteRequest(attachment_parts=[], slot=slot, avoid_stems=[], num_samples=1)


def test_writer_returns_a_candidate_from_the_pool():
    writer = ft_writer.FineTunedWriter(
        doc_text=DOC_TEXT, drafts={'Thông hiểu': [{'text': DRAFT}]})
    resp = writer.run(_request(_slot()))
    assert len(resp.candidates) == 1
    assert resp.candidates[0]['_writer_stage'] is True
    assert writer.stats['used'] == 1


def test_writer_skips_malformed_drafts_then_reports_exhaustion():
    writer = ft_writer.FineTunedWriter(
        doc_text=DOC_TEXT,
        drafts={'Thông hiểu': [{'text': 'lan man không đúng khuôn'}, {'text': DRAFT}]})
    resp = writer.run(_request(_slot()))
    assert len(resp.candidates) == 1 and writer.stats['parse_failed'] == 1
    resp = writer.run(_request(_slot()))
    assert resp.candidates == [] and writer.stats['no_draft'] == 1
    assert 'hết câu nháp' in resp.errors[-1]


def test_online_drafter_renders_the_trained_prompt(monkeypatch):
    seen = {}

    class _Completions:
        def create(self, **kwargs):
            seen.update(kwargs)

            class R:
                choices = [type('C', (), {'text': DRAFT})()]
            return R()

    class _Client:
        completions = _Completions()

    monkeypatch.setitem(sys.modules, 'openai',
                        type('M', (), {'OpenAI': lambda **kw: _Client()}))
    tok = type('T', (), {'apply_chat_template':
                         lambda self, m, **kw: '\n'.join(x['content'] for x in m)})()
    drafter = ft_writer.OnlineDrafter(base_url='http://x/v1', model='lora', tokenizer=tok)
    text = drafter('Trích đoạn tài liệu', 'Vận dụng', 'Tích phân')
    assert text == DRAFT
    assert 'Mức độ: Vận dụng' in seen['prompt'] and seen['model'] == 'lora'


# ---------------------------------------------------------------------------
# một lượt slot đi qua orchestrator thật (các tác nhân khác thay bằng bản giả)
# ---------------------------------------------------------------------------

def test_slot_flows_through_the_real_orchestrator(monkeypatch):
    from pipeline.direct_pdf.agents.pdf_orchestrator import DirectPdfOrchestrator
    from pipeline.rule_validator import validate_record

    orchestrator = DirectPdfOrchestrator(model='fake-vision')
    orchestrator.writer = ft_writer.FineTunedWriter(
        doc_text=DOC_TEXT, drafts={'Thông hiểu': [{'text': DRAFT}]})
    monkeypatch.setattr(orchestrator.distractor, 'run', lambda req: PdfDistractorResponse(
        distractors=[{'distractor_text': f'${i}$',
                      'distractor_category_text': f'loi_{i}',
                      'distractor_explanation_text': f'Quên chia hệ số nên ra ${i}$.'}
                     for i in range(1, 4)]))
    monkeypatch.setattr(orchestrator.critic, 'run', lambda req: PdfCriticResponse(
        annotations={'_grounding': 0.8, '_quality': 0.8, '_bloom_alignment': 0.9,
                     '_quality_traits': {}}, rejected=False))
    monkeypatch.setattr(orchestrator.independent, 'run', lambda cand, parts: None)

    cand, parse_errors, verify_failures, rejects = orchestrator._process_slot(
        _slot(), [], [])
    assert cand is not None, (parse_errors, rejects)
    assert rejects == []

    from pipeline.agents.messages import FormatAcceptedRequest
    fmt = orchestrator.formatter.run(FormatAcceptedRequest(
        slot=_slot(), candidate=cand, doc={}, attempts=1))
    assert validate_record(fmt.record) == []
    assert len(fmt.record['options']) == 4
    assert fmt.record['answer_key'] in 'ABCD'
    answer = next(o['text'] for o in fmt.record['options']
                  if o['key'] == fmt.record['answer_key'])
    assert 'e^3-1' in answer.replace(' ', '')


# ---------------------------------------------------------------------------
# trích đoạn tài liệu và kế hoạch câu nháp
# ---------------------------------------------------------------------------

def test_build_windows_packs_pages_and_skips_blank_ones():
    pages = ['a' * 100, '[Trang trắng]', 'b' * 100, 'c' * 400]
    windows = pipeline_ft.build_windows(pages, max_chars=250)
    assert [w['pages'] for w in windows] == [[1, 3], [4], [4]]
    assert all(len(w['text']) <= 260 for w in windows)


def test_plan_drafts_follows_the_bloom_distribution_and_rotates_context():
    windows = pipeline_ft.build_windows([f'nội dung {i} ' * 20 for i in range(4)], 400)
    topics = ['tích phân', 'diện tích']
    dist = pipeline_ft.bloom_distribution('mixed')
    plan = pipeline_ft.plan_drafts(windows, topics, dist, 8)
    assert len(plan) == 8
    assert {p['topic'] for p in plan} == set(topics)
    assert len({p['window'] for p in plan}) > 1
    levels = [pipeline_ft.pick_level(dist, i) for i in range(8)]
    assert [p['level'] for p in plan] == levels


def test_rule_issues_rejects_a_bare_one_step_integral():
    """Pipeline loại đề "Tính ∫..." quá ngắn — kho câu nháp phải lọc trước."""
    trivial, _ = ft_writer.parse_generated(prompts.gen_target({
        'question': 'Tính $\\int_0^1 e^{2x}\\,dx$.',
        'choices': ['A. $1$', 'B. $2$', 'C. $3$', 'D. $4$'], 'answer': 'A',
        'solution': 'Bước một.\nBước hai.\nBước ba.'}))
    assert 'question_too_trivial:bare_one_step_integral' in ft_writer.rule_issues(
        trivial, _slot(), DOC_TEXT)
    good, _ = ft_writer.parse_generated(DRAFT)
    assert ft_writer.rule_issues(good, _slot(), DOC_TEXT) == []


def test_containment_detects_a_copied_stem():
    stem = 'Tính $\\int_0^1 e^{2x}\\,dx$.'
    assert pipeline_ft.containment(stem, DOC_TEXT) > 0.8
    assert pipeline_ft.containment('Một câu hoàn toàn khác về ma trận', DOC_TEXT) < 0.3

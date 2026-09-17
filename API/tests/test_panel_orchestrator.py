"""Tích hợp: hội đồng solver đi qua orchestrator → verifier → record.

Writer/Distractor/Critic được thay bằng bản giả; solver độc lập, verifier,
formatter và schema chạy thật. Kịch bản là phản ví dụ tiếp tuyến–mặt cầu của
bài báo: Writer viết key 5√3−4 kèm biểu thức kiểm chứng khớp chính nó.
"""
from __future__ import annotations

import json

import pytest

from pipeline import config as cfg
from pipeline.direct_pdf.agents import pdf_independent_agent as agent_mod
from pipeline.direct_pdf.agents.messages import (
    PdfCriticResponse, PdfDistractorResponse, PdfWriteResponse,
)
from pipeline.direct_pdf.agents.pdf_independent_agent import SolverSpec
from pipeline.direct_pdf.agents.pdf_orchestrator import DirectPdfOrchestrator
from pipeline.llm_client import NonRetryableLLMError

STEM = ('Cho mặt cầu \\((S)\\) tâm \\(I(1;2;3)\\) bán kính \\(3\\) và đường thẳng '
        '\\(d_k\\) phụ thuộc tham số \\(k>0\\). Biết \\(d_k\\) tiếp xúc với '
        '\\((S)\\) khi \\(k^2+8k-11=0\\). Giá trị của \\(k\\) bằng bao nhiêu?')
FAKE_PARTS = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}}]


def _candidate(distractor_texts):
    return {
        'question_text': STEM,
        'answer_text': '\\(5\\sqrt{3}-4\\)',
        'answer_explanation_text': 'Giải phương trình bậc hai theo k rồi lấy nghiệm dương.',
        'detailed_solution': {'steps': [
            {'title': 'Lập phương trình',
             'content': r'Điều kiện tiếp xúc cho \(k^2+8k-11=0\).'},
            {'title': 'Giải phương trình',
             'content': r'\(\Delta = 64+44 = 108\), nghiệm dương \(k=-4+\sqrt{27}\).'},
            {'title': 'Tính giá trị', 'content': r'Viết gọn \(k = 5\sqrt{3}-4\).'},
            {'title': 'Kiểm tra điều kiện', 'content': r'\(k>0\) thoả mãn.'},
            {'title': 'Kết luận', 'content': r'Chọn \(k=5\sqrt{3}-4\).'},
        ]},
        'source_quote_text': 'Đường thẳng tiếp xúc với mặt cầu khi khoảng cách từ tâm '
                             'đến đường thẳng bằng bán kính.',
        'verifier_hint': {'type': 'numeric_eval',
                          'payload': {'expr': '5*sqrt(3)-4',
                                      'expected_numeric': 4.660254037844386}},
        'visual': {'type': 'none', 'spec': {}},
        '_distractor_texts': distractor_texts,
    }


class _Writer:
    def __init__(self, cand):
        self.cand = cand
        self.model = 'gen'

    def run(self, req):
        return PdfWriteResponse(slot_id=req.slot.get('slot_id'),
                                candidates=[dict(self.cand)])


class _Distractor:
    model = 'gen'

    def run(self, req):
        return PdfDistractorResponse(distractors=[
            {'distractor_text': t, 'distractor_category_text': f'e{n}',
             'distractor_explanation_text': f'Nhầm dấu kiểu {n}.'}
            for n, t in enumerate(req.candidate['_distractor_texts'], start=1)
        ])


class _Critic:
    def run(self, req):
        return PdfCriticResponse(annotations={'_quality': 0.9, '_grounding': 0.9},
                                 rejected=False)


def _solver_reply(expression):
    return json.dumps({'computable': True, 'quantity': 'k',
                       'expression': expression, 'answer': expression})


@pytest.fixture
def orchestrator(monkeypatch):
    monkeypatch.setattr(cfg, 'DIRECT_PDF_PARALLEL_SLOTS', 1)
    monkeypatch.setattr(cfg, 'INDEPENDENT_REQUIRE_CROSS_FAMILY', False)
    calls = []

    def _fake_call_llm(system, user, model=None, base_url=None, **kw):
        calls.append((model, base_url, user))
        # Solver cùng họ tái tạo nghiệm SAI của Writer; solver khác họ giải đúng.
        same_family = model.startswith('gpt')
        return _solver_reply('5*sqrt(3)-4' if same_family else '-4+sqrt(27)')

    monkeypatch.setattr(agent_mod, 'call_llm', _fake_call_llm)

    def _build(distractors, solvers):
        orch = DirectPdfOrchestrator(model='gpt-4o', use_skills=False)
        orch.writer = _Writer(_candidate(distractors))
        orch.distractor = _Distractor()
        orch.critic = _Critic()
        orch.independent.solvers = solvers
        return orch, calls
    return _build


def _run(orch):
    return orch.generate(pdf_path='unused.pdf', requested_count=1,
                         attachment_parts=FAKE_PARTS)


SAME_FAMILY = [SolverSpec('gpt-4o-mini')]
PANEL = [SolverSpec('gpt-4o-mini'), SolverSpec('microsoft/phi-4', 'http://127.0.0.1:8001/v1')]
PLAIN_DISTRACTORS = ['\\(5\\sqrt{3}+4\\)', '\\(4-5\\sqrt{3}\\)', '\\(2\\sqrt{3}\\)']


def test_same_family_solver_alone_certifies_the_wrong_key(orchestrator):
    orch, _ = orchestrator(PLAIN_DISTRACTORS, SAME_FAMILY)
    result = _run(orch)
    assert result.accepted_count == 1
    v = result.questions[0]['verification']
    assert v['status'] == 'independently_verified'


def test_cross_family_panel_routes_the_wrong_key_to_review(orchestrator):
    orch, calls = orchestrator(PLAIN_DISTRACTORS, PANEL)
    result = _run(orch)
    record = result.questions[0]
    v = record['verification']
    assert v['status'] == 'mismatch'
    assert v['needs_human_review'] is True
    assert record['review_status'] == 'needs_revision'
    panel = v['independent']['panel']
    assert [m['model'] for m in panel] == ['gpt-4o-mini', 'microsoft/phi-4']
    assert len(v['independent']['definite_values']) == 2
    # Solver chỉ thấy đề bài: không có key, lời giải hay biểu thức của Writer.
    for _, _, user in calls:
        assert '5\\sqrt{3}-4' not in user and '5*sqrt(3)-4' not in user
    assert {base for _, base, _ in calls} == {None, 'http://127.0.0.1:8001/v1'}


def test_panel_refutes_when_the_true_value_is_a_distractor(orchestrator):
    orch, _ = orchestrator(['\\(3\\sqrt{3}-4\\)', '\\(4-5\\sqrt{3}\\)', '\\(2\\sqrt{3}\\)'],
                           [SolverSpec('microsoft/phi-4', 'http://x/v1'),
                            SolverSpec('mistralai/Mistral-Small', 'http://y/v1')])
    result = _run(orch)
    v = result.questions[0]['verification']
    assert v['status'] == 'refuted'


def test_infrastructure_error_in_panel_stops_the_run(orchestrator, monkeypatch):
    orch, _ = orchestrator(PLAIN_DISTRACTORS, PANEL)

    def _unauthorized(system, user, model=None, base_url=None, **kw):
        if base_url:
            raise NonRetryableLLMError(RuntimeError('401 Unauthorized'))
        return _solver_reply('5*sqrt(3)-4')

    monkeypatch.setattr(agent_mod, 'call_llm', _unauthorized)
    with pytest.raises(NonRetryableLLMError):
        _run(orch)


def test_transient_solver_error_is_recorded_as_incomplete(orchestrator, monkeypatch):
    orch, _ = orchestrator(PLAIN_DISTRACTORS, PANEL)

    def _timeout(system, user, model=None, base_url=None, **kw):
        if base_url:
            raise TimeoutError('read timeout')
        return _solver_reply('5*sqrt(3)-4')

    monkeypatch.setattr(agent_mod, 'call_llm', _timeout)
    v = _run(orch).questions[0]['verification']
    assert v['status'] == 'consistency_confirmed'
    assert v['verification_incomplete'] is True

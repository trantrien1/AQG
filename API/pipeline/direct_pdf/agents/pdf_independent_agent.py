"""IndependentVerifierAgent — dựng mục tiêu kiểm chứng ĐỘC LẬP cho một câu hỏi.

Agent này giải lại bài toán từ đầu và nộp về một biểu thức máy đọc được; SymPy
tính lại giá trị đó (trong `pipeline.independent_target`) rồi tầng phân xử so
với đáp án key.

Điều kiện độc lập được ép ở ĐẦU VÀO: agent chỉ nhận `question_text`. Nó không
nhận `answer_text`, `answer_explanation_text`, `detailed_solution`,
`verifier_payload` hay danh sách phương án — nếu nhận, nó sẽ neo theo đáp án
đang cần kiểm và cơ chế mất hết giá trị. :func:`_blinded_stem` là chỗ duy nhất
đọc candidate, và nó chỉ lấy đúng một trường.

Agent có thể là một HỘI ĐỒNG nhiều solver (`cfg.INDEPENDENT_SOLVERS`), mỗi
thành viên một model và có thể một endpoint riêng. Kết quả được gộp bằng
:func:`pipeline.independent_target.aggregate_panel`. Không cấu hình hội đồng thì
chạy một solver `cfg.INDEPENDENT_VERIFIER_MODEL` trên client chính — đúng hành
vi của các run cũ.

Mọi solver chạy ở nhiệt độ 0 và KHÔNG xem trang tài liệu (đề bài vốn tự chứa);
đặt AQG_INDEPENDENT_VERIFIER_SEES_DOCUMENT=1 để solver trên client chính đọc
tài liệu gốc.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .pdf_base import PdfAwareAgent
from ... import ablation
from ... import config as cfg
from ...independent_target import (
    IndependentTarget, aggregate_panel, build_independent_target,
    disabled_target,
)
from ...llm_client import (
    BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError, call_llm,
)
from ...model_family import independence_level, model_family

#: Lỗi hạ tầng phải dừng run thay vì bị ghi thành "không kiểm chứng được".
_INFRA_ERRORS = (BudgetExceeded, NonRetryableLLMError, PdfUnsupportedError)


@dataclass(frozen=True)
class SolverSpec:
    """Một thành viên hội đồng: model + endpoint (rỗng = client chính)."""

    model: str
    base_url: str = ''


def parse_solver_specs(entries: List[str], default_model: str) -> List[SolverSpec]:
    """'model' | 'model@http://host:port/v1' → SolverSpec. Rỗng → một solver mặc định."""
    specs: List[SolverSpec] = []
    for raw in entries or []:
        text = str(raw or '').strip()
        if not text:
            continue
        model, sep, url = text.partition('@')
        model = model.strip()
        if not model:
            continue
        specs.append(SolverSpec(model=model, base_url=url.strip() if sep else ''))
    if not specs and default_model:
        specs.append(SolverSpec(model=default_model))
    return specs


def _blinded_stem(candidate: Dict[str, Any]) -> str:
    """Chỉ lấy đề bài. Mọi trường khác của candidate đến từ Writer nên bị bịt."""
    return str(candidate.get('question_text') or '').strip()


class PdfIndependentVerifierAgent(PdfAwareAgent):
    """Giải lại bài toán một cách độc lập để lấy mục tiêu đối chiếu."""

    def __init__(self, use_skills: bool = False, model: Optional[str] = None,
                 solvers: Optional[List[SolverSpec]] = None):
        # use_skills=False có chủ đích: skill của pipeline mô tả cách RA ĐỀ, còn
        # agent này chỉ làm một việc là giải toán.
        super().__init__(
            'independent_verifier',
            skills=[],
            use_skills=False,
            model=model or cfg.INDEPENDENT_VERIFIER_MODEL,
        )
        self.solvers: List[SolverSpec] = list(solvers) if solvers else parse_solver_specs(
            getattr(cfg, 'INDEPENDENT_SOLVERS', []), self.model)

    @property
    def solver_models(self) -> List[str]:
        return [s.model for s in self.solvers]

    def check_independence(self, generator_model: str) -> str:
        """Mức độc lập so với generator; raise nếu cấu hình bắt buộc khác họ."""
        level = independence_level(generator_model, self.solver_models)
        if level == 'same_family':
            message = (
                f'mọi solver độc lập ({", ".join(self.solver_models)}) cùng họ '
                f'"{model_family(generator_model)}" với generator '
                f'{generator_model}: lỗi tương quan không bị loại trừ')
            if getattr(cfg, 'INDEPENDENT_REQUIRE_CROSS_FAMILY', False):
                raise NonRetryableLLMError(RuntimeError(message))
            print(f'[independent] CẢNH BÁO: {message}')
        return level

    def _solve_one(
        self,
        spec: SolverSpec,
        stem: str,
        attachment_parts: Optional[List[Dict[str, Any]]],
    ) -> IndependentTarget:
        # Chỉ solver trên client chính được xem tài liệu: endpoint riêng thường
        # là model chỉ đọc chữ.
        sees_doc = bool(
            getattr(cfg, 'INDEPENDENT_VERIFIER_SEES_DOCUMENT', False)
            and attachment_parts and not spec.base_url
        )

        def _call(system: str, user: str) -> str:
            if sees_doc:
                content = ([{'type': 'text', 'text': user}]
                           + list(attachment_parts or []))
                from ...llm_client import call_llm_with_pdf
                return call_llm_with_pdf(
                    system=system,
                    user_content=content,
                    model=spec.model,
                    temperature=cfg.INDEPENDENT_VERIFIER_TEMPERATURE,
                    max_tokens=cfg.INDEPENDENT_VERIFIER_MAX_TOKENS,
                )
            return call_llm(
                system=system,
                user=user,
                model=spec.model,
                temperature=cfg.INDEPENDENT_VERIFIER_TEMPERATURE,
                max_tokens=cfg.INDEPENDENT_VERIFIER_MAX_TOKENS,
                base_url=spec.base_url or None,
                api_key=getattr(cfg, 'INDEPENDENT_API_KEY', '') or None,
            )

        return build_independent_target(
            stem, call_fn=_call, model=spec.model, reraise=_INFRA_ERRORS,
        )

    def run(
        self,
        candidate: Dict[str, Any],
        attachment_parts: Optional[List[Dict[str, Any]]] = None,
    ) -> IndependentTarget:
        if not ablation.is_enabled(ablation.INDEPENDENT_VERIFICATION):
            return disabled_target('tắt qua ablation')
        if not cfg.INDEPENDENT_VERIFICATION:
            return disabled_target('tắt qua AQG_INDEPENDENT_VERIFICATION=0')
        if not self.solvers:
            return disabled_target('không cấu hình solver độc lập nào')

        stem = _blinded_stem(candidate)
        if not stem:
            return disabled_target('candidate không có đề bài')

        if len(self.solvers) == 1:
            members = [self._solve_one(self.solvers[0], stem, attachment_parts)]
        else:
            # Thành viên nằm trên server khác nhau nên gọi song song; lỗi hạ
            # tầng của bất kỳ thành viên nào nổi lên qua .result().
            with ThreadPoolExecutor(max_workers=len(self.solvers)) as pool:
                futures = [pool.submit(self._solve_one, spec, stem, attachment_parts)
                           for spec in self.solvers]
                members = [f.result() for f in futures]
        return aggregate_panel(
            members, consensus=getattr(cfg, 'INDEPENDENT_CONSENSUS', 'all'))

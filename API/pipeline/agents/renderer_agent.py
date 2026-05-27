"""RendererAgent — wrap visual_renderer. Convert visual spec → markdown + PNG."""
from __future__ import annotations

from .base import BaseAgent
from .messages import RenderRequest, RenderResponse
from ..visual_renderer import render_all_visuals


class RendererAgent(BaseAgent):
    """Render visual spec của các câu hỏi accepted ra file:

    - truth_table → markdown table + matplotlib PNG
    - matrix → LaTeX pmatrix + matplotlib PNG
    - graph_network/tree → DOT + Graphviz PNG (nếu cài `dot`)
    - venn_diagram → text mô tả
    - function_graph → matplotlib PNG

    Failure (e.g., matplotlib chưa cài) không làm fail cả pipeline,
    chỉ ghi vào `error` field của response.
    """

    def __init__(self):
        super().__init__('renderer', skills=['visual-rendering'])

    def run(self, request: RenderRequest) -> RenderResponse:
        try:
            rendered = render_all_visuals(request.records, out_dir=request.out_dir)
            return RenderResponse(
                rendered_count=len(rendered),
                skipped_count=max(0, len(request.records) - len(rendered)),
            )
        except Exception as e:
            return RenderResponse(
                rendered_count=0,
                skipped_count=len(request.records),
                error=str(e),
            )

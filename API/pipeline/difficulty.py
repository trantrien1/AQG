"""Heuristic difficulty estimator (mục 20 — phần pre-deployment).

Không có dữ liệu học sinh thật để chạy IRT 2PL/3PL, nhưng vẫn có thể ước lượng
độ khó câu hỏi từ feature đo được:

  - stem length (ngắn/dài)
  - verifier type complexity (mechanical vs conceptual)
  - composite function trong derivative/integral
  - matrix size
  - visual presence (thêm cognitive load)
  - số biến free trong biểu thức
  - distractor closeness (xác suất nhầm lẫn)

Output:
  - difficulty_estimated ∈ [0.10, 0.95]
  - estimated_time_seconds (theo difficulty_estimated)
  - difficulty_alignment (bool — True nếu lệch ≤ 0.20 so với target)
  - difficulty_features (dict các feature đã đo, để debug + IRT calibrate sau)

Khi có dữ liệu học sinh thật → tính p_correct, discrimination → cập nhật
`difficulty_estimated` từ IRT, ghi đè heuristic.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict


# ==== Base difficulty theo cognitive level ====
COGNITIVE_BASE: Dict[str, float] = {
    'Nhận biết':    0.30,
    'Thông hiểu':   0.50,
    'Vận dụng':     0.70,
    'Vận dụng cao': 0.85,
}


# Verifier type → phân loại độ phức tạp
_MECHANICAL_TYPES = {
    'modular', 'counting', 'numeric_eval', 'matrix_rank',
    'graph_property', 'tree_property',
}
_CONCEPTUAL_TYPES = {
    'logic_equivalence', 'logic_negation', 'simplify_equiv', 'trig_identity',
    'truth_table', 'recurrence',
}
_HARDER_TYPES = {
    'matrix_eigenvalues', 'matrix_inverse',
    'integral', 'derivative', 'limit',
}


# ==== Estimator ====

def _stem_length_adj(stem: str) -> float:
    n = len(stem)
    if n > 400: return 0.10
    if n > 250: return 0.06
    if n > 150: return 0.03
    if n < 70:  return -0.04
    return 0.0


def _verifier_complexity_adj(hint: Dict[str, Any]) -> float:
    if not isinstance(hint, dict):
        return 0.0
    t = hint.get('type', 'none')
    payload = hint.get('payload') or {}
    adj = 0.0
    if t in _MECHANICAL_TYPES:
        adj -= 0.05
    elif t in _CONCEPTUAL_TYPES:
        adj += 0.04
    elif t in _HARDER_TYPES:
        adj += 0.06

    # Composite function trong calculus → thêm độ khó
    if t in ('derivative', 'integral', 'limit'):
        f = str(payload.get('function', ''))
        # Heuristic: hàm lồng vào nhau nếu có >= 2 cặp ngoặc lồng
        nested_depth = 0
        max_depth = 0
        for ch in f:
            if ch == '(': nested_depth += 1; max_depth = max(max_depth, nested_depth)
            elif ch == ')': nested_depth -= 1
        if max_depth >= 2:
            adj += 0.08
        # nhiều hàm lượng giác / log / exp lồng nhau
        special_funcs = sum(f.count(s) for s in ('sin(', 'cos(', 'tan(', 'log(', 'exp(', 'sqrt('))
        if special_funcs >= 2:
            adj += 0.04

    # Matrix size
    if t.startswith('matrix_'):
        m = payload.get('matrix') or payload.get('a')
        if isinstance(m, list) and len(m) >= 4:
            adj += 0.10
        elif isinstance(m, list) and len(m) == 3:
            adj += 0.05

    # Tổ hợp với n lớn (n > 8)
    if t == 'counting':
        formula = str(payload.get('formula', ''))
        nums = [int(x) for x in re.findall(r'\d+', formula)]
        if nums and max(nums) > 8:
            adj += 0.04

    return adj


def _visual_adj(visual: Any) -> float:
    if not visual:
        return 0.0
    t = (visual or {}).get('type')
    # Visual phức tạp = thêm cognitive load
    if t in ('graph_network', 'tree', 'venn_diagram', 'function_graph'):
        return 0.05
    if t in ('truth_table', 'matrix'):
        return 0.03
    return 0.02


def _distractor_closeness_adj(answer_text: str, distractors: list) -> float:
    """Nếu distractor đều là số và gần answer (chênh < 50%) → khó hơn."""
    try:
        a = float(answer_text.strip())
    except Exception:
        return 0.0
    close_count = 0
    for d in distractors:
        try:
            v = float(d.get('distractor_text', '').strip())
            if a == 0:
                if abs(v) < 2:
                    close_count += 1
            elif abs((v - a) / a) < 0.5:
                close_count += 1
        except Exception:
            continue
    if close_count >= 2:
        return 0.04
    return 0.0


def _options_count_adj(stem: str) -> float:
    """Câu có nhiều phương án phức tạp/dài → khó hơn (đã xét gián tiếp qua stem)."""
    return 0.0


# ==== Time estimation theo difficulty ====

def _estimate_time_seconds(difficulty: float, cognitive_level: str) -> int:
    """Ước lượng thời gian dựa trên difficulty (chính) + cognitive_level (nudge)."""
    # Base brackets theo difficulty
    if difficulty < 0.35: base = 45
    elif difficulty < 0.55: base = 75
    elif difficulty < 0.75: base = 130
    elif difficulty < 0.85: base = 200
    else: base = 280
    # Cognitive level nudge: vận dụng cao thường cần thêm thời gian phân tích
    if cognitive_level == 'Vận dụng cao':
        base = int(base * 1.15)
    elif cognitive_level == 'Nhận biết':
        base = int(base * 0.9)
    return base


# ==== Public API ====

def estimate(slot: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Trả về dict các trường:
        difficulty_estimated: float ∈ [0.10, 0.95]
        estimated_time_seconds: int
        difficulty_alignment: bool (so với slot.difficulty_target ± 0.20)
        difficulty_features: dict feature đã dùng (để debug + IRT calibrate sau)
    """
    cognitive_level = slot.get('cognitive_level', 'Thông hiểu')
    target = float(slot.get('difficulty_target') or COGNITIVE_BASE.get(cognitive_level, 0.5))

    base = COGNITIVE_BASE.get(cognitive_level, 0.5)
    stem = candidate.get('question_text', '')
    hint = candidate.get('verifier_hint', {})
    visual = candidate.get('visual')
    distractors = candidate.get('distractors', [])

    feat = {
        'cognitive_base': round(base, 3),
        'stem_length_adj': _stem_length_adj(stem),
        'verifier_complexity_adj': _verifier_complexity_adj(hint),
        'visual_adj': _visual_adj(visual),
        'distractor_closeness_adj': _distractor_closeness_adj(
            candidate.get('answer_text', ''), distractors),
        'stem_length': len(stem),
        'verifier_type': (hint or {}).get('type', 'none'),
        'visual_type': (visual or {}).get('type') if visual else None,
        'num_distractors': len(distractors),
    }
    raw = base + sum(v for k, v in feat.items() if k.endswith('_adj'))
    estimated = round(max(0.10, min(0.95, raw)), 3)

    aligned = abs(estimated - target) <= 0.20
    time_s = _estimate_time_seconds(estimated, cognitive_level)

    return {
        'difficulty_estimated': estimated,
        'difficulty_alignment': aligned,
        'difficulty_target': target,
        'estimated_time_seconds': time_s,
        'difficulty_features': feat,
    }

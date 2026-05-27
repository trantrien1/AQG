"""Visual renderer (mục 15) — render visual_spec → text/markdown/PNG.

Mỗi visual có 2 layer output:
1. **Markdown** — luôn render được, không cần dependency
   (truth table → bảng markdown; matrix → LaTeX; graph → DOT; venn → text mô tả)
2. **PNG** — optional, cần graphviz/matplotlib. Chỉ render khi gọi tường minh.

Sử dụng:
    from pipeline.visual_renderer import render_to_markdown, render_to_png
    md = render_to_markdown(visual)              # luôn ok
    out_path = render_to_png(visual, 'q1.png')   # cần graphviz/matplotlib
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional


# ============ Markdown rendering (no dependency) ============

def auto_alt_text(visual: Dict[str, Any]) -> str:
    """Sinh alt_text mô tả ngắn nếu LLM không cung cấp."""
    if not visual:
        return ''
    if visual.get('alt_text'):
        return visual['alt_text']
    t = visual.get('type')
    spec = visual.get('spec') or {}
    if t == 'truth_table':
        vars_ = spec.get('variables') or []
        rows = spec.get('rows') or []
        expr = spec.get('expr_label', '')
        return (f'Bảng chân lý của {expr} với các biến {", ".join(vars_)}, '
                f'gồm {len(rows)} dòng.')
    if t == 'matrix':
        rows = spec.get('rows') or []
        name = spec.get('name', 'M')
        if rows:
            return f'Ma trận {name} kích thước {len(rows)}×{len(rows[0])}.'
    if t == 'graph_network':
        v = spec.get('vertices') or []
        e = spec.get('edges') or []
        d = 'có hướng' if spec.get('directed') else 'vô hướng'
        return f'Đồ thị {d} với {len(v)} đỉnh và {len(e)} cạnh.'
    if t == 'tree':
        e = spec.get('edges') or []
        return f'Cây có gốc {spec.get("root", "?")} với {len(e)} cạnh.'
    if t == 'venn_diagram':
        s = spec.get('sets') or []
        return f'Sơ đồ Venn với {len(s)} tập.'
    return f'Hình {t}.'


def render_to_markdown(visual: Dict[str, Any]) -> str:
    """Trả về string markdown render visual. Empty string nếu visual=None hoặc invalid."""
    if not visual:
        return ''
    t = visual.get('type')
    spec = visual.get('spec') or {}
    if t == 'truth_table':
        return _truth_table_to_md(spec)
    if t == 'matrix':
        return _matrix_to_md(spec)
    if t == 'graph_network':
        return _graph_to_dot(spec, directed=spec.get('directed', False))
    if t == 'tree':
        return _tree_to_ascii(spec)
    if t == 'venn_diagram':
        return _venn_to_md(spec)
    if t == 'function_graph':
        return _function_to_text(spec)
    return f'(visual type không hỗ trợ render: {t})'


def _truth_table_to_md(spec: Dict[str, Any]) -> str:
    vars_ = spec.get('variables') or []
    rows = spec.get('rows') or []
    expr = spec.get('expr_label', '')
    if not vars_ or not rows:
        return ''
    header = '| ' + ' | '.join(vars_) + ' | ' + (expr or 'kết quả') + ' |'
    sep = '|' + '|'.join('---' for _ in vars_) + '|---|'
    body_lines = []
    for r in rows:
        cells = []
        for v in vars_:
            val = r.get(v)
            cells.append('T' if val is True else 'F' if val is False else str(val))
        result = r.get('result')
        cells.append('T' if result is True else 'F' if result is False else str(result))
        body_lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join([header, sep, *body_lines])


def _matrix_to_md(spec: Dict[str, Any]) -> str:
    rows = spec.get('rows') or []
    if not rows:
        return ''
    name = spec.get('name', '')
    body = ' \\\\ '.join(' & '.join(str(x) for x in row) for row in rows)
    latex = '\\begin{pmatrix} ' + body + ' \\end{pmatrix}'
    if name:
        return f'$${name} = {latex}$$'
    return f'$${latex}$$'


def _graph_to_dot(spec: Dict[str, Any], directed: bool = False) -> str:
    """Render graph thành DOT format (Graphviz). Có thể đưa vào Graphviz để
    sinh PNG/SVG."""
    edge_op = '->' if directed else '--'
    graph_kw = 'digraph' if directed else 'graph'
    vertices = spec.get('vertices') or []
    edges = spec.get('edges') or []
    lines = [f'{graph_kw} G {{', '  rankdir=LR;', '  node [shape=circle];']
    for v in vertices:
        lines.append(f'  "{v}";')
    for e in edges:
        lines.append(f'  "{e[0]}" {edge_op} "{e[1]}";')
    lines.append('}')
    return '```dot\n' + '\n'.join(lines) + '\n```'


def _tree_to_ascii(spec: Dict[str, Any]) -> str:
    """Render cây dưới dạng ASCII tree. Nếu có root + edges, build adj rồi DFS."""
    edges = spec.get('edges') or []
    root = spec.get('root')
    if not edges:
        return ''
    children: Dict[str, List[str]] = {}
    parents = set()
    for e in edges:
        if len(e) >= 2:
            children.setdefault(e[0], []).append(e[1])
            parents.add(e[0])
    if not root:
        # heuristic: node xuất hiện làm parent nhưng không phải child
        all_children = {c for cs in children.values() for c in cs}
        candidates = [n for n in parents if n not in all_children]
        root = candidates[0] if candidates else (edges[0][0] if edges else '')
    if not root:
        return ''

    lines: List[str] = []
    def walk(node: str, prefix: str = '', is_last: bool = True):
        connector = '└── ' if is_last else '├── '
        lines.append(prefix + connector + node)
        kids = children.get(node, [])
        for i, k in enumerate(kids):
            walk(k,
                 prefix + ('    ' if is_last else '│   '),
                 i == len(kids) - 1)

    lines.append(root)
    kids = children.get(root, [])
    for i, k in enumerate(kids):
        walk(k, '', i == len(kids) - 1)
    return '```\n' + '\n'.join(lines) + '\n```'


def _venn_to_md(spec: Dict[str, Any]) -> str:
    sets = spec.get('sets') or []
    lines = ['Sơ đồ Venn:']
    for s in sets:
        elems = ', '.join(str(x) for x in s.get('elements', []))
        lines.append(f"- {s.get('name', '?')} = {{ {elems} }}")
    return '\n'.join(lines)


def _function_to_text(spec: Dict[str, Any]) -> str:
    funcs = spec.get('functions') or []
    lines = ['Đồ thị các hàm:']
    for f in funcs:
        lines.append(f"- {f.get('label') or f.get('expr', '?')}")
    if 'x_range' in spec:
        lines.append(f"x ∈ {spec['x_range']}")
    return '\n'.join(lines)


# ============ PNG rendering (optional dependency) ============

def render_to_png(visual: Dict[str, Any], out_path: str) -> Optional[str]:
    """Render visual ra file PNG. Trả path hoặc None nếu không render được
    (thiếu graphviz / matplotlib / type không support)."""
    if not visual:
        return None
    t = visual.get('type')
    spec = visual.get('spec') or {}
    if t in ('graph_network', 'tree'):
        return _render_graph_png(spec, out_path,
                                 directed=spec.get('directed', False))
    if t == 'matrix':
        return _render_matrix_png(spec, out_path)
    if t == 'truth_table':
        return _render_truth_table_png(spec, out_path)
    if t == 'function_graph':
        return _render_function_png(spec, out_path)
    return None


def _has_graphviz() -> bool:
    return shutil.which('dot') is not None


def _render_graph_png(spec: Dict[str, Any], out_path: str,
                      directed: bool = False) -> Optional[str]:
    if not _has_graphviz():
        return None
    dot_src = _graph_to_dot(spec, directed=directed)
    # bỏ ```dot ... ```
    dot_src = dot_src.replace('```dot\n', '').replace('\n```', '')
    try:
        proc = subprocess.run(
            ['dot', '-Tpng', '-o', out_path],
            input=dot_src, text=True, capture_output=True, timeout=15,
        )
        if proc.returncode == 0 and os.path.exists(out_path):
            return out_path
    except Exception:
        pass
    return None


def _render_matrix_png(spec: Dict[str, Any], out_path: str) -> Optional[str]:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    rows = spec.get('rows') or []
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(0.6 * len(rows[0]) + 1, 0.5 * len(rows) + 0.5))
    ax.axis('off')
    text = '\n'.join('  '.join(str(x) for x in r) for r in rows)
    name = spec.get('name', '')
    title = f'{name} = ' if name else ''
    ax.text(0.5, 0.5, f'{title}\n[ {text} ]',
            ha='center', va='center', fontsize=12, family='monospace')
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path


def _render_truth_table_png(spec: Dict[str, Any], out_path: str) -> Optional[str]:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    vars_ = spec.get('variables') or []
    rows = spec.get('rows') or []
    if not vars_ or not rows:
        return None
    headers = vars_ + [spec.get('expr_label', 'result')]
    cell_text = []
    for r in rows:
        line = []
        for v in vars_:
            val = r.get(v)
            line.append('T' if val is True else 'F' if val is False else str(val))
        result = r.get('result')
        line.append('T' if result is True else 'F' if result is False else str(result))
        cell_text.append(line)

    fig, ax = plt.subplots(figsize=(0.8 * len(headers) + 0.5, 0.4 * len(rows) + 0.6))
    ax.axis('off')
    table = ax.table(cellText=cell_text, colLabels=headers, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.0, 1.4)
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path


def _render_function_png(spec: Dict[str, Any], out_path: str) -> Optional[str]:
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
        import sympy as sp
    except ImportError:
        return None
    funcs = spec.get('functions') or []
    x_range = spec.get('x_range') or [-5, 5]
    if not funcs:
        return None
    x = sp.Symbol('x')
    fig, ax = plt.subplots(figsize=(6, 4))
    xs = np.linspace(x_range[0], x_range[1], 400)
    for f in funcs:
        try:
            expr = sp.sympify(f.get('expr', ''))
            fn = sp.lambdify(x, expr, 'numpy')
            ys = fn(xs)
            ax.plot(xs, ys, label=f.get('label', f.get('expr', '')))
        except Exception:
            continue
    if 'y_range' in spec:
        ax.set_ylim(spec['y_range'])
    ax.axhline(0, color='gray', lw=0.5)
    ax.axvline(0, color='gray', lw=0.5)
    ax.grid(True, alpha=0.3)
    ax.legend(loc='best', fontsize=9)
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path


# ============ Batch render từ output JSON ============

def render_all_visuals(questions: List[Dict[str, Any]],
                       out_dir: str = 'output/visuals') -> Dict[str, str]:
    """Render mọi câu hỏi có visual ra file PNG + markdown.
    Trả mapping question_id → list paths đã sinh."""
    os.makedirs(out_dir, exist_ok=True)
    result: Dict[str, List[str]] = {}
    for q in questions:
        v = q.get('visual')
        if not v:
            continue
        qid = q.get('question_id', 'unknown')
        out: List[str] = []
        # Markdown luôn được render
        md = render_to_markdown(v)
        if md:
            md_path = os.path.join(out_dir, f'{qid}.md')
            alt = v.get('alt_text') or auto_alt_text(v)
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(f"# {qid}\n\nAlt: {alt}\n\n{md}\n")
            out.append(md_path)
        # PNG nếu được
        png_path = render_to_png(v, os.path.join(out_dir, f'{qid}.png'))
        if png_path:
            out.append(png_path)
        if out:
            result[qid] = out
    return result

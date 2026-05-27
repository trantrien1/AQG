"""Symbolic verifier (mục 11 + 12) — Toán chung.

Mỗi câu hỏi do LLM sinh ra kèm `verifier_hint = {type, payload}`. Verifier route
theo `type` sang engine phù hợp. `type` mô tả LOẠI THAO TÁC TOÁN HỌC của câu hỏi
(do LLM tự khai cho TỪNG câu), KHÔNG phải phân loại môn của tài liệu.

Toàn bộ `type` được hỗ trợ (xem `_DISPATCH` ở cuối file để tra engine cụ thể):

    solve_equation, simplify_equiv,
    derivative, integral, limit,
    trig_identity,
    matrix_det, matrix_rank, matrix_eigenvalues, matrix_inverse, matrix_multiply,
    geometry_triangle, analytic_geometry,
    counting, probability,
    modular,
    logic_equivalence, logic_negation, truth_table,
    graph_property, tree_property, recurrence,
    numeric_eval, none

Trả về VerificationResult với verified ∈ {True, False, None}:
    True  : verifier xác nhận đáp án đúng
    False : verifier xác nhận đáp án sai → loại / repair
    None  : verifier không phán định được → fallback sang LLM judge

Mục 12 (Numerical Cross-check): các engine xử lý biểu thức (derivative, integral
bất định, simplify_equiv, trig_identity) tự động evaluate tại nhiều điểm ngẫu
nhiên trong miền để bắt lỗi mà CAS có thể bỏ sót.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from itertools import combinations, permutations, product
from typing import Any, Dict, List, Optional


@dataclass
class VerificationResult:
    verified: Optional[bool]
    engine: str
    detail: str = ''
    expected: Any = None
    actual: Any = None
    numeric_crosscheck_points: int = 0


# ============ Lazy imports ============

def _sympy():
    import sympy
    return sympy


def _nx():
    import networkx as nx
    return nx


# ============ Logic parsing helper ============

def _parse_logic(expr: str):
    """Parse biểu thức logic; tránh đụng độ với sympy.Q (assumptions)."""
    import sympy
    from sympy.parsing.sympy_parser import parse_expr
    names = set(re.findall(r'\b([A-Za-z][A-Za-z0-9_]*)\b', expr))
    reserved = {'And', 'Or', 'Not', 'Implies', 'Equivalent', 'Xor', 'Nand', 'Nor',
                'true', 'false', 'True', 'False'}
    local = {n: sympy.Symbol(n) for n in names if n not in reserved}
    return parse_expr(expr, local_dict=local)


def _natural_to_sympy(expr: str) -> str:
    """Translate natural math notation → SymPy syntax.

    Cho phép WriterAgent viết tự nhiên (2^n, C(n,k), P(n,k), n!, ln, log_a) —
    Verifier dịch trước khi parse. Trách nhiệm này thuộc về Verifier, không
    phải Generator (theo nguyên tắc tách concern)."""
    if not expr:
        return expr
    s = str(expr)
    # n! → factorial(n) — match đơn giản: <atom>!
    # Áp dụng trước khi đụng tới ^ để tránh xung đột.
    s = re.sub(r'(\([^()]+\)|\b\d+\b|\b[a-zA-Z_][a-zA-Z0-9_]*\b)\s*!',
               r'factorial(\1)', s)
    # C(n,k) → binomial(n,k); A(n,k) hoặc P(n,k) → factorial(n)/factorial(n-k)
    s = re.sub(r'\bC\s*\(\s*([^,()]+)\s*,\s*([^,()]+)\s*\)',
               r'binomial(\1,\2)', s)
    s = re.sub(r'\b[AP]\s*\(\s*([^,()]+)\s*,\s*([^,()]+)\s*\)',
               r'factorial(\1)/factorial((\1)-(\2))', s)
    # 2^n → 2**n (chỉ khi không phải phép XOR rõ ràng — toán không dùng XOR)
    s = s.replace('^', '**')
    # ln(x) → log(x) (SymPy log mặc định là ln)
    # giữ nguyên log
    return s


def _parse_math(expr: str, variables: Optional[List[str]] = None):
    """Parse biểu thức toán generic. Nếu cung cấp `variables`, các tên đó được
    tạo Symbol thực để derivative/integrate hoạt động ổn định."""
    import sympy
    from sympy.parsing.sympy_parser import parse_expr
    expr = _natural_to_sympy(expr)
    if variables:
        local = {v: sympy.Symbol(v) for v in variables}
    else:
        names = set(re.findall(r'\b([a-zA-Z][a-zA-Z0-9_]*)\b', expr))
        sympy_funcs = {'sin', 'cos', 'tan', 'log', 'ln', 'exp', 'sqrt', 'pi', 'E',
                       'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh',
                       'binomial', 'factorial', 'gcd', 'lcm', 'Abs',
                       'I', 'oo', 'Symbol', 'Rational'}
        local = {n: sympy.Symbol(n) for n in names if n not in sympy_funcs}
    # ln là alias của log trong sympy
    local.setdefault('ln', sympy.log)
    return parse_expr(expr, local_dict=local)


# ============ Numeric cross-check ============

def _numeric_match(expr_a, expr_b, var, n_points: int = 5,
                   tolerance: float = 1e-6) -> Optional[bool]:
    """Đánh giá expr_a − expr_b tại nhiều điểm ngẫu nhiên. Trả True nếu mọi
    điểm gần 0; False nếu có điểm chênh lệch lớn; None nếu không evaluate được."""
    import sympy
    rng = random.Random(42)
    diff = sympy.simplify(expr_a - expr_b)
    if not diff.free_symbols:
        try:
            return bool(abs(complex(diff.evalf())) < tolerance)
        except Exception:
            return None
    if var is None:
        var = next(iter(diff.free_symbols))
    matched = 0
    for _ in range(n_points):
        try:
            x_val = rng.uniform(0.5, 2.5)  # tránh 0 và miền âm để miễn nhiễm với log/sqrt
            val = complex(diff.subs(var, x_val).evalf())
            if abs(val) > tolerance * max(1.0, abs(complex(expr_a.subs(var, x_val).evalf()))):
                return False
            matched += 1
        except Exception:
            continue
    if matched == 0:
        return None
    return True


# ============ Logic engines ============

def _verify_logic_equivalence(payload: Dict[str, Any]) -> VerificationResult:
    sympy = _sympy()
    try:
        a = _parse_logic(payload['expr_a'])
        b = _parse_logic(payload['expr_b'])
        equiv = sympy.simplify_logic(sympy.Equivalent(a, b))
        ok = equiv == sympy.true
        return VerificationResult(verified=bool(ok), engine='sympy.logic',
                                  detail=f'Equivalent({a}, {b}) = {equiv}')
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.logic', detail=str(e))


def _verify_logic_negation(payload: Dict[str, Any]) -> VerificationResult:
    sympy = _sympy()
    try:
        e = _parse_logic(payload['expr'])
        n = _parse_logic(payload['claimed_negation'])
        equiv = sympy.simplify_logic(sympy.Equivalent(sympy.Not(e), n))
        ok = equiv == sympy.true
        return VerificationResult(verified=bool(ok), engine='sympy.logic',
                                  detail=f'¬({e}) ≡ {n}? {ok}')
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.logic', detail=str(e))


def _verify_truth_table(payload: Dict[str, Any]) -> VerificationResult:
    sympy = _sympy()
    try:
        e = _parse_logic(payload['expr'])
        sub = {sympy.Symbol(k): bool(v) for k, v in payload['assignment'].items()}
        actual = bool(e.subs(sub))
        expected = bool(payload['expected_value'])
        return VerificationResult(verified=(actual == expected), engine='sympy.logic',
                                  detail=f'{e} với {payload["assignment"]} = {actual}',
                                  expected=expected, actual=actual)
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.logic', detail=str(e))


# ============ Equation & expression engines ============

def _verify_solve_equation(payload: Dict[str, Any]) -> VerificationResult:
    """payload: {equation, variable, claimed_roots}. equation = expression set to 0."""
    sympy = _sympy()
    try:
        var = sympy.Symbol(payload.get('variable', 'x'))
        expr = _parse_math(payload['equation'], [str(var)])
        roots = sympy.solve(expr, var)
        actual_set = set()
        for r in roots:
            try:
                actual_set.add(complex(r.evalf()))
            except Exception:
                actual_set.add(r)
        claimed = set()
        for r in payload['claimed_roots']:
            try:
                claimed.add(complex(sympy.sympify(r).evalf()))
            except Exception:
                claimed.add(r)

        # So sánh set với tolerance
        def close(a, b):
            try:
                return abs(complex(a) - complex(b)) < 1e-6
            except Exception:
                return a == b
        ok = (len(actual_set) == len(claimed)
              and all(any(close(a, c) for c in claimed) for a in actual_set))
        return VerificationResult(verified=bool(ok), engine='sympy.solve',
                                  detail=f'roots={list(actual_set)}, claimed={list(claimed)}',
                                  expected=list(actual_set), actual=list(claimed))
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.solve', detail=str(e))


def _verify_simplify_equiv(payload: Dict[str, Any]) -> VerificationResult:
    """payload: {expr_a, expr_b, [variables]}. Đúng nếu hai biểu thức bằng nhau."""
    sympy = _sympy()
    try:
        vars_list = payload.get('variables')
        a = _parse_math(payload['expr_a'], vars_list)
        b = _parse_math(payload['expr_b'], vars_list)
        diff = sympy.simplify(a - b)
        if diff == 0:
            return VerificationResult(verified=True, engine='sympy.simplify',
                                      detail=f'simplify({a} - {b}) = 0')
        # numeric cross-check
        var = next(iter((a - b).free_symbols), None)
        nm = _numeric_match(a, b, var)
        if nm is True:
            return VerificationResult(verified=True, engine='sympy.simplify+numeric',
                                      detail='symbolic ≠ 0 nhưng numeric match',
                                      numeric_crosscheck_points=5)
        if nm is False:
            return VerificationResult(verified=False, engine='sympy.simplify+numeric',
                                      detail='numeric mismatch',
                                      numeric_crosscheck_points=5)
        return VerificationResult(verified=False, engine='sympy.simplify',
                                  detail=f'simplify(a-b) = {diff}')
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.simplify', detail=str(e))


# ============ Derivative / integral / limit engines ============

def _verify_derivative(payload: Dict[str, Any]) -> VerificationResult:
    """payload: {function, variable, claimed_derivative, [order=1]}."""
    sympy = _sympy()
    try:
        var = sympy.Symbol(payload.get('variable', 'x'))
        f = _parse_math(payload['function'], [str(var)])
        order = int(payload.get('order', 1))
        actual = sympy.diff(f, var, order)
        claimed = _parse_math(payload['claimed_derivative'], [str(var)])
        diff = sympy.simplify(actual - claimed)
        if diff == 0:
            return VerificationResult(verified=True, engine='sympy.diff',
                                      detail=f"d/d{var} = {actual}")
        nm = _numeric_match(actual, claimed, var)
        if nm is True:
            return VerificationResult(verified=True, engine='sympy.diff+numeric',
                                      detail=f'numeric match: d/d{var} = {actual}',
                                      numeric_crosscheck_points=5)
        return VerificationResult(verified=False, engine='sympy.diff',
                                  detail=f'actual={actual}, claimed={claimed}',
                                  expected=actual, actual=claimed)
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.diff', detail=str(e))


def _verify_integral(payload: Dict[str, Any]) -> VerificationResult:
    """payload xác định: {function, variable, lower, upper, claimed_value}.
    payload bất định: {function, variable, claimed_antiderivative}."""
    sympy = _sympy()
    try:
        var = sympy.Symbol(payload.get('variable', 'x'))
        f = _parse_math(payload['function'], [str(var)])
        if 'claimed_antiderivative' in payload:
            F = _parse_math(payload['claimed_antiderivative'], [str(var)])
            # F'(x) phải bằng f(x) (đến hằng số); kiểm bằng cách so dF/dx với f
            dF = sympy.diff(F, var)
            diff = sympy.simplify(dF - f)
            if diff == 0:
                return VerificationResult(verified=True, engine='sympy.integrate',
                                          detail=f"d/d{var} F = {dF} = f")
            nm = _numeric_match(dF, f, var)
            if nm is True:
                return VerificationResult(verified=True, engine='sympy.integrate+numeric',
                                          detail='numeric match',
                                          numeric_crosscheck_points=5)
            return VerificationResult(verified=False, engine='sympy.integrate',
                                      detail=f'F\' = {dF} ≠ f = {f}')
        if 'lower' in payload and 'upper' in payload:
            lower = sympy.sympify(payload['lower'])
            upper = sympy.sympify(payload['upper'])
            actual = sympy.integrate(f, (var, lower, upper))
            claimed = sympy.sympify(payload['claimed_value'])
            diff = sympy.simplify(actual - claimed)
            if diff == 0:
                return VerificationResult(verified=True, engine='sympy.integrate',
                                          detail=f'∫={actual}', expected=actual, actual=claimed)
            try:
                if abs(complex(actual.evalf()) - complex(claimed.evalf())) < 1e-6:
                    return VerificationResult(verified=True, engine='sympy.integrate+numeric',
                                              detail='numeric match',
                                              numeric_crosscheck_points=1)
            except Exception:
                pass
            return VerificationResult(verified=False, engine='sympy.integrate',
                                      detail=f'actual={actual}, claimed={claimed}')
        return VerificationResult(verified=None, engine='sympy.integrate',
                                  detail='thiếu lower/upper hoặc claimed_antiderivative')
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.integrate', detail=str(e))


def _verify_limit(payload: Dict[str, Any]) -> VerificationResult:
    """payload: {function, variable, point, claimed_value, [direction]}."""
    sympy = _sympy()
    try:
        var = sympy.Symbol(payload.get('variable', 'x'))
        f = _parse_math(payload['function'], [str(var)])
        point = sympy.sympify(payload['point'])
        direction = payload.get('direction', '+-')
        actual = sympy.limit(f, var, point, direction)
        claimed = sympy.sympify(payload['claimed_value'])
        if sympy.simplify(actual - claimed) == 0:
            return VerificationResult(verified=True, engine='sympy.limit',
                                      detail=f'lim = {actual}', expected=actual, actual=claimed)
        try:
            if abs(complex(actual.evalf()) - complex(claimed.evalf())) < 1e-6:
                return VerificationResult(verified=True, engine='sympy.limit+numeric',
                                          detail='numeric match',
                                          numeric_crosscheck_points=1)
        except Exception:
            pass
        return VerificationResult(verified=False, engine='sympy.limit',
                                  detail=f'actual={actual}, claimed={claimed}')
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.limit', detail=str(e))


# ============ Trig identity engine ============

def _verify_trig_identity(payload: Dict[str, Any]) -> VerificationResult:
    """payload: {expr_a, expr_b, [variables=['x']]}."""
    sympy = _sympy()
    try:
        vars_list = payload.get('variables', ['x'])
        a = _parse_math(payload['expr_a'], vars_list)
        b = _parse_math(payload['expr_b'], vars_list)
        diff = sympy.trigsimp(sympy.simplify(a - b))
        if diff == 0:
            return VerificationResult(verified=True, engine='sympy.trigsimp',
                                      detail=f'trigsimp(a-b) = 0')
        var = sympy.Symbol(vars_list[0])
        nm = _numeric_match(a, b, var)
        if nm is True:
            return VerificationResult(verified=True, engine='sympy.trigsimp+numeric',
                                      detail='numeric match',
                                      numeric_crosscheck_points=5)
        if nm is False:
            return VerificationResult(verified=False, engine='sympy.trigsimp+numeric',
                                      detail='numeric mismatch',
                                      numeric_crosscheck_points=5)
        return VerificationResult(verified=False, engine='sympy.trigsimp',
                                  detail=f'trigsimp(a-b) = {diff}')
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.trigsimp', detail=str(e))


# ============ Matrix engines ============

def _matrix(payload_matrix):
    import sympy
    return sympy.Matrix(payload_matrix)


def _verify_matrix_det(payload: Dict[str, Any]) -> VerificationResult:
    sympy = _sympy()
    try:
        M = _matrix(payload['matrix'])
        actual = M.det()
        claimed = sympy.sympify(payload['claimed'])
        ok = sympy.simplify(actual - claimed) == 0
        return VerificationResult(verified=bool(ok), engine='sympy.Matrix.det',
                                  detail=f'det = {actual}', expected=actual, actual=claimed)
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.Matrix.det', detail=str(e))


def _verify_matrix_rank(payload: Dict[str, Any]) -> VerificationResult:
    try:
        M = _matrix(payload['matrix'])
        actual = M.rank()
        claimed = int(payload['claimed'])
        return VerificationResult(verified=(actual == claimed), engine='sympy.Matrix.rank',
                                  detail=f'rank = {actual}', expected=actual, actual=claimed)
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.Matrix.rank', detail=str(e))


def _verify_matrix_eigenvalues(payload: Dict[str, Any]) -> VerificationResult:
    sympy = _sympy()
    try:
        M = _matrix(payload['matrix'])
        ev = M.eigenvals()
        actual = []
        for k, mul in ev.items():
            actual.extend([k] * int(mul))
        claimed = [sympy.sympify(v) for v in payload['claimed']]
        # so sánh multiset
        def close_multiset(A, B):
            B = list(B)
            for a in A:
                matched = False
                for i, b in enumerate(B):
                    try:
                        if abs(complex(sympy.sympify(a).evalf()) - complex(b.evalf())) < 1e-6:
                            B.pop(i); matched = True; break
                    except Exception:
                        if a == b:
                            B.pop(i); matched = True; break
                if not matched:
                    return False
            return len(B) == 0
        ok = close_multiset(actual, claimed)
        return VerificationResult(verified=bool(ok), engine='sympy.Matrix.eigenvals',
                                  detail=f'eigenvalues = {actual}',
                                  expected=actual, actual=claimed)
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.Matrix.eigenvals', detail=str(e))


def _verify_matrix_inverse(payload: Dict[str, Any]) -> VerificationResult:
    sympy = _sympy()
    try:
        M = _matrix(payload['matrix'])
        claimed = _matrix(payload['claimed'])
        prod = sympy.simplify(M * claimed)
        ok = (prod == sympy.eye(M.rows))
        return VerificationResult(verified=bool(ok), engine='sympy.Matrix.inv',
                                  detail=f'M * claimed = {prod}')
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.Matrix.inv', detail=str(e))


def _verify_matrix_multiply(payload: Dict[str, Any]) -> VerificationResult:
    sympy = _sympy()
    try:
        A = _matrix(payload['a']); B = _matrix(payload['b'])
        claimed = _matrix(payload['claimed'])
        ok = (sympy.simplify(A * B - claimed) == sympy.zeros(claimed.rows, claimed.cols))
        return VerificationResult(verified=bool(ok), engine='sympy.Matrix.multiply',
                                  detail=f'A*B = {A*B}')
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.Matrix.multiply', detail=str(e))


# ============ Geometry engines ============

def _verify_geometry_triangle(payload: Dict[str, Any]) -> VerificationResult:
    """payload: {points: {A:[x,y], B:[x,y], C:[x,y]}, property, [expected]}.
    property: area | perimeter | is_right | side_length (cần `side`)."""
    sympy = _sympy()
    try:
        prop = payload['property']

        if 'points' in payload:
            pts = payload['points']
            A = sympy.Point(*pts['A']); B = sympy.Point(*pts['B']); C = sympy.Point(*pts['C'])
            T = sympy.Triangle(A, B, C)
            if prop == 'area':
                actual = T.area
            elif prop == 'perimeter':
                actual = T.perimeter
            elif prop == 'is_right':
                actual = T.is_right()
            elif prop == 'side_length':
                side = payload['side'].upper()
                mapping = {'AB': (A, B), 'BC': (B, C), 'CA': (C, A), 'CB': (C, B), 'BA': (B, A), 'AC': (A, C)}
                p1, p2 = mapping[side]
                actual = p1.distance(p2)
            else:
                return VerificationResult(verified=None, engine='sympy.geometry',
                                          detail=f'unknown property {prop}')
        elif payload.get('sides') is not None or payload.get('side_lengths') is not None:
            raw_sides = payload.get('sides', payload.get('side_lengths'))
            if isinstance(raw_sides, dict):
                sides = {str(k).upper(): sympy.sympify(v) for k, v in raw_sides.items()}
                values = list(sides.values())
            else:
                values = [sympy.sympify(v) for v in raw_sides]
                sides = {'AB': values[0], 'BC': values[1], 'CA': values[2]} if len(values) >= 3 else {}
            if len(values) != 3:
                return VerificationResult(verified=None, engine='sympy.geometry',
                                          detail='triangle sides must contain exactly 3 values')
            if prop == 'perimeter':
                actual = sympy.simplify(sum(values))
            elif prop == 'area':
                if 'base' in payload and 'height' in payload:
                    actual = sympy.Rational(1, 2) * sympy.sympify(payload['base']) * sympy.sympify(payload['height'])
                else:
                    a, b, c = values
                    semi = sympy.simplify((a + b + c) / 2)
                    actual = sympy.sqrt(semi * (semi - a) * (semi - b) * (semi - c))
            elif prop == 'is_right':
                a, b, c = sorted(values, key=lambda x: float(sympy.N(x)))
                actual = bool(sympy.simplify(a*a + b*b - c*c) == 0)
            elif prop == 'side_length':
                side = str(payload.get('side', '')).upper()
                actual = sides.get(side)
                if actual is None:
                    return VerificationResult(verified=None, engine='sympy.geometry',
                                              detail=f'unknown side {side}')
            else:
                return VerificationResult(verified=None, engine='sympy.geometry',
                                          detail=f'unknown property {prop}')
        else:
            return VerificationResult(verified=None, engine='sympy.geometry',
                                      detail='missing points or sides')
        expected = payload.get('expected')
        if expected is None:
            return VerificationResult(verified=None, engine='sympy.geometry',
                                      detail=f'actual={actual}', actual=actual)
        if isinstance(actual, bool):
            if isinstance(expected, str):
                expected_bool = expected.strip().lower() in ('true', '1', 'yes', 'đúng', 'dung')
            else:
                expected_bool = bool(expected)
            ok = bool(actual) == expected_bool
        else:
            ok_expr = sympy.sympify(expected)
            ok = sympy.simplify(actual - ok_expr) == 0
        return VerificationResult(verified=bool(ok), engine='sympy.geometry',
                                  detail=f'{prop} = {actual}', expected=expected, actual=actual)
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.geometry', detail=str(e))


def _verify_analytic_geometry(payload: Dict[str, Any]) -> VerificationResult:
    """payload: {operation, ...}.
    operation:
      distance_point_line_2d: {point:[x,y], line:[a,b,c]} (ax+by+c=0)
      distance_point_plane_3d: {point:[x,y,z], plane:[a,b,c,d]}
      perpendicular_lines_2d: {line1:[a1,b1,c1], line2:[a2,b2,c2]}
    """
    try:
        op = payload['operation']
        expected = payload.get('expected')
        if op == 'distance_point_line_2d':
            x0, y0 = payload['point']; a, b, c = payload['line']
            actual = abs(a*x0 + b*y0 + c) / math.sqrt(a*a + b*b)
        elif op == 'distance_point_plane_3d':
            x0, y0, z0 = payload['point']; a, b, c, d = payload['plane']
            actual = abs(a*x0 + b*y0 + c*z0 + d) / math.sqrt(a*a + b*b + c*c)
        elif op == 'perpendicular_lines_2d':
            a1, b1, _ = payload['line1']; a2, b2, _ = payload['line2']
            # tích vô hướng vector pháp tuyến (a1,b1)·(a2,b2)
            actual = (a1*a2 + b1*b2 == 0)
        else:
            return VerificationResult(verified=None, engine='analytic_geometry',
                                      detail=f'unknown {op}')
        if expected is None:
            return VerificationResult(verified=None, engine='analytic_geometry',
                                      detail=f'actual={actual}', actual=actual)
        if isinstance(actual, bool):
            return VerificationResult(verified=(actual == expected), engine='analytic_geometry',
                                      detail=f'{op}: {actual}', expected=expected, actual=actual)
        ok = abs(actual - float(expected)) < 1e-6
        return VerificationResult(verified=bool(ok), engine='analytic_geometry',
                                  detail=f'{op}: actual={actual}, expected={expected}',
                                  expected=expected, actual=actual)
    except Exception as e:
        return VerificationResult(verified=None, engine='analytic_geometry', detail=str(e))


# ============ Counting & probability engines ============

def _verify_counting(payload: Dict[str, Any]) -> VerificationResult:
    sympy = _sympy()
    try:
        formula = payload['formula']
        expected = int(payload['expected'])
        actual = int(sympy.sympify(formula))
        bf = payload.get('brute_force')
        bf_count = _brute_force_count(bf) if bf else None
        if bf_count is not None and bf_count != actual:
            return VerificationResult(verified=False, engine='sympy+brute_force',
                                      detail=f'formula={actual} nhưng brute={bf_count}',
                                      expected=bf_count, actual=actual)
        return VerificationResult(verified=(actual == expected), engine='sympy.counting',
                                  detail=f'{formula} = {actual}', expected=expected, actual=actual)
    except Exception as e:
        return VerificationResult(verified=None, engine='sympy.counting', detail=str(e))


def _brute_force_count(bf: Dict[str, Any]) -> Optional[int]:
    if not bf:
        return None
    kind = bf.get('kind'); n = bf.get('n', 0); k = bf.get('k', n)
    if n > 10:
        return None
    items = bf.get('items') or list(range(n))
    if kind == 'permutation':
        return sum(1 for _ in permutations(items, k))
    if kind == 'combination':
        return sum(1 for _ in combinations(items, k))
    if kind == 'permutation_with_rep':
        return sum(1 for _ in product(items, repeat=k))
    return None


def _verify_probability(payload: Dict[str, Any]) -> VerificationResult:
    """payload: {formula, expected, [tolerance]}. Đánh giá biểu thức xác suất bằng SymPy."""
    sympy = _sympy()
    try:
        actual = float(sympy.sympify(payload['formula']).evalf())
        expected = float(payload['expected'])
        tol = float(payload.get('tolerance', 1e-6))
        if not (0.0 - tol <= actual <= 1.0 + tol):
            return VerificationResult(verified=False, engine='probability',
                                      detail=f'xác suất ngoài [0,1]: {actual}')
        return VerificationResult(verified=(abs(actual - expected) < tol), engine='probability',
                                  detail=f'p = {actual}', expected=expected, actual=actual)
    except Exception as e:
        return VerificationResult(verified=None, engine='probability', detail=str(e))


# ============ Modular arithmetic engines ============

def _verify_modular(payload: Dict[str, Any]) -> VerificationResult:
    try:
        op = payload['operation']
        expected = payload.get('expected')
        if op == 'gcd':
            actual = math.gcd(int(payload['a']), int(payload['b']))
        elif op == 'lcm':
            a, b = int(payload['a']), int(payload['b'])
            g = math.gcd(a, b)
            actual = abs(a * b) // g if g != 0 else 0
        elif op == 'mod_pow':
            actual = pow(int(payload['base']), int(payload['exp']), int(payload['mod']))
        elif op == 'mod_reduce':
            actual = int(payload['a']) % int(payload['mod'])
        elif op == 'fermat_little_check':
            a = int(payload['a']); p = int(payload['p'])
            actual = False if a % p == 0 else (pow(a, p - 1, p) == 1)
        else:
            return VerificationResult(verified=None, engine='modular', detail=f'unknown {op}')
        return VerificationResult(verified=(actual == expected), engine=f'modular.{op}',
                                  detail=f'actual={actual}', expected=expected, actual=actual)
    except Exception as e:
        return VerificationResult(verified=None, engine='modular', detail=str(e))


# ============ Graph & tree engines ============

def _build_graph(edges, directed: bool = False):
    nx = _nx()
    G = nx.DiGraph() if directed else nx.Graph()
    for e in edges:
        if len(e) >= 2:
            G.add_edge(e[0], e[1])
    return G


def _verify_graph_property(payload: Dict[str, Any]) -> VerificationResult:
    nx = _nx()
    try:
        prop = payload['property']
        expected = payload.get('expected')
        if prop == 'edges_complete':
            n = int(payload['n']); actual = n * (n - 1) // 2
            return _cmp(actual, expected, 'graph.K_n')
        if prop == 'edges_complete_bipartite':
            actual = int(payload['m']) * int(payload['n'])
            return _cmp(actual, expected, 'graph.K_{m,n}')
        edges = payload['edges']; directed = payload.get('directed', False)
        G = _build_graph(edges, directed=directed)
        for v in payload.get('vertices', []):
            G.add_node(v)
        if prop == 'num_edges':       actual = G.number_of_edges()
        elif prop == 'num_vertices':  actual = G.number_of_nodes()
        elif prop == 'degree_sum':    actual = sum(dict(G.degree()).values())
        elif prop == 'degree_of':     actual = G.degree(payload['vertex'])
        elif prop == 'is_connected':  actual = (nx.is_connected(G) if not directed else nx.is_weakly_connected(G))
        elif prop == 'is_eulerian':   actual = nx.is_eulerian(G)
        elif prop == 'has_eulerian_path': actual = nx.has_eulerian_path(G)
        elif prop == 'is_tree':       actual = nx.is_tree(G)
        elif prop == 'is_bipartite':  actual = nx.is_bipartite(G)
        else:
            return VerificationResult(verified=None, engine='networkx', detail=f'unsupported {prop}')
        return _cmp(actual, expected, f'graph.{prop}')
    except Exception as e:
        return VerificationResult(verified=None, engine='networkx', detail=str(e))


def _verify_tree_property(payload: Dict[str, Any]) -> VerificationResult:
    try:
        prop = payload['property']; expected = payload.get('expected')
        if prop == 'edges_of_tree':
            return _cmp(max(0, int(payload['n']) - 1), expected, 'tree.n_minus_1')
        if prop == 'max_nodes_height_h':
            return _cmp(2 ** (int(payload['h']) + 1) - 1, expected, 'tree.binary_max')
        if prop == 'min_nodes_height_h':
            return _cmp(int(payload['h']) + 1, expected, 'tree.binary_min')
        return VerificationResult(verified=None, engine='tree', detail=f'unknown {prop}')
    except Exception as e:
        return VerificationResult(verified=None, engine='tree', detail=str(e))


def _coerce_number(x: Any) -> float | int:
    """Robust parser: int → int, str → eval thử int rồi sympy, list → take first."""
    if isinstance(x, (int, float)):
        return x
    if isinstance(x, str):
        s = x.strip()
        # Cố trích integer/float trực tiếp
        try:
            return int(s)
        except ValueError:
            pass
        try:
            return float(s)
        except ValueError:
            pass
        # Fallback: sympy
        try:
            sym = _sympy()
            v = sym.sympify(s)
            if v.is_number:
                return float(v)
        except Exception:
            pass
    raise ValueError(f'cannot coerce {x!r} to number')


def _verify_recurrence(payload: Dict[str, Any]) -> VerificationResult:
    """Verify recurrence relation.

    Hỗ trợ 2 dạng payload:

    Dạng 1 (truyền thống): expected single value
        {recurrence: [c1,c2,...], initial: [a0,a1,...], n: int, expected: number}

    Dạng 2 (mới — closed form numeric crosscheck):
        {recurrence: [c1,c2,...], initial: [a0,a1,...],
         closed_form: "<sympy expr với biến n>",
         crosscheck_n: [0,1,2,3,4,5]}
        → Tính seq từ recurrence vs substitute closed_form, so sánh tại nhiều n.
    """
    try:
        coeffs = [_coerce_number(c) for c in payload['recurrence']]
        initial = [_coerce_number(x) for x in payload['initial']]
        k = len(coeffs)
        if len(initial) < k:
            return VerificationResult(
                verified=None, engine='recurrence',
                detail=f'thiếu điều kiện đầu (cần {k}, có {len(initial)})',
            )

        # Compute sequence up to needed n
        max_n = 0
        if 'closed_form' in payload:
            xs = payload.get('crosscheck_n') or list(range(0, max(6, k + 4)))
            max_n = max(int(_coerce_number(x)) for x in xs)
        else:
            max_n = int(_coerce_number(payload['n']))

        seq = list(initial)
        while len(seq) <= max_n:
            seq.append(sum(coeffs[i] * seq[-(i + 1)] for i in range(k)))

        # Mode 2: closed form numeric crosscheck
        if 'closed_form' in payload:
            sym = _sympy()
            n_var = sym.Symbol('n')
            try:
                expr = sym.sympify(_natural_to_sympy(payload['closed_form']))
            except Exception as e:
                return VerificationResult(
                    verified=None, engine='recurrence',
                    detail=f'không parse được closed_form: {e}',
                )
            xs = payload.get('crosscheck_n') or list(range(0, max(6, k + 4)))
            mismatches = []
            for nv in xs:
                nv = int(_coerce_number(nv))
                seq_val = seq[nv]
                cf_val = float(expr.subs(n_var, nv).evalf())
                if abs(float(seq_val) - cf_val) > 1e-6:
                    mismatches.append(f'n={nv}: seq={seq_val}, formula={cf_val}')
            if mismatches:
                return VerificationResult(
                    verified=False, engine='recurrence',
                    detail='closed_form mismatch: ' + '; '.join(mismatches[:3]),
                )
            return VerificationResult(
                verified=True, engine='recurrence',
                detail=f'closed_form khớp tại {len(xs)} điểm n',
                numeric_crosscheck_points=len(xs),
            )

        # Mode 1: single n / expected
        n = int(_coerce_number(payload['n']))
        expected = _coerce_number(payload['expected'])
        return _cmp(seq[n], expected, 'recurrence.iter')
    except Exception as e:
        return VerificationResult(
            verified=None, engine='recurrence', detail=f'parse_error: {e}',
        )


# ============ Generic numeric eval ============

def _verify_numeric_eval(payload: Dict[str, Any]) -> VerificationResult:
    """payload: {expr, expected_numeric, [tolerance=1e-6]}."""
    sympy = _sympy()
    try:
        expr_text = str(payload['expr'])
        names = set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\b', expr_text))
        local = {
            'integrate': sympy.integrate,
            'Integral': sympy.Integral,
            'sin': sympy.sin,
            'cos': sympy.cos,
            'tan': sympy.tan,
            'sqrt': sympy.sqrt,
            'pi': sympy.pi,
            'E': sympy.E,
            'Abs': sympy.Abs,
        }
        for name in names:
            if name not in local:
                local[name] = sympy.Symbol(name)
        actual = float(sympy.sympify(expr_text, locals=local).evalf())
        expected = float(payload['expected_numeric'])
        tol = float(payload.get('tolerance', 1e-6))
        return VerificationResult(verified=(abs(actual - expected) < tol), engine='numeric_eval',
                                  detail=f'expr = {actual}', expected=expected, actual=actual)
    except Exception as e:
        return VerificationResult(verified=None, engine='numeric_eval', detail=str(e))


# ============ Helper ============

def _cmp(actual, expected, engine: str) -> VerificationResult:
    if expected is None:
        return VerificationResult(verified=None, engine=engine, detail=f'actual={actual}', actual=actual)
    return VerificationResult(verified=(actual == expected), engine=engine,
                              detail=f'actual={actual}, expected={expected}',
                              expected=expected, actual=actual)


# ============ Public dispatcher ============

_DISPATCH = {
    'solve_equation':       _verify_solve_equation,
    'simplify_equiv':       _verify_simplify_equiv,
    'derivative':           _verify_derivative,
    'integral':             _verify_integral,
    'limit':                _verify_limit,
    'trig_identity':        _verify_trig_identity,
    'matrix_det':           _verify_matrix_det,
    'matrix_rank':          _verify_matrix_rank,
    'matrix_eigenvalues':   _verify_matrix_eigenvalues,
    'matrix_inverse':       _verify_matrix_inverse,
    'matrix_multiply':      _verify_matrix_multiply,
    'geometry_triangle':    _verify_geometry_triangle,
    'analytic_geometry':    _verify_analytic_geometry,
    'counting':             _verify_counting,
    'probability':          _verify_probability,
    'modular':              _verify_modular,
    'logic_equivalence':    _verify_logic_equivalence,
    'logic_negation':       _verify_logic_negation,
    'truth_table':          _verify_truth_table,
    'graph_property':       _verify_graph_property,
    'tree_property':        _verify_tree_property,
    'recurrence':           _verify_recurrence,
    'numeric_eval':         _verify_numeric_eval,
}


def verify(hint: Dict[str, Any]) -> VerificationResult:
    """hint: {type, payload}."""
    if not isinstance(hint, dict):
        return VerificationResult(verified=None, engine='none', detail='hint không phải dict')
    t = hint.get('type', 'none')
    if t == 'none':
        return VerificationResult(verified=None, engine='none', detail='không có verifier')
    fn = _DISPATCH.get(t)
    if fn is None:
        return VerificationResult(verified=None, engine='none', detail=f'unknown type {t}')
    raw_payload = hint.get('payload')
    if isinstance(raw_payload, str):
        import json as _json
        try:
            raw_payload = _json.loads(raw_payload)
        except Exception:
            raw_payload = {}
    if not isinstance(raw_payload, dict):
        raw_payload = {}
    return fn(raw_payload)


def supported_types() -> List[str]:
    return sorted(_DISPATCH.keys())


# Mapping: với mỗi `type`, đâu là field chứa "claim" (đáp án LLM khẳng định).
# Dùng để verify một distractor: thay claim trong payload bằng distractor's text → re-verify.
# Nếu verifier returns True ⇒ distractor cũng ĐÚNG ⇒ multi-answer ⇒ reject.
_CLAIM_FIELD = {
    'solve_equation':       'claimed_roots',     # list
    'simplify_equiv':       'expr_b',
    'derivative':           'claimed_derivative',
    'integral':             None,                # special: claimed_value HOẶC claimed_antiderivative
    'limit':                'claimed_value',
    'trig_identity':        'expr_b',
    'matrix_det':           'claimed',
    'matrix_rank':          'claimed',
    'matrix_eigenvalues':   'claimed',
    'matrix_inverse':       'claimed',
    'matrix_multiply':      'claimed',
    'geometry_triangle':    'expected',
    'analytic_geometry':    'expected',
    'counting':             'expected',
    'probability':          'expected',
    'modular':              'expected',
    'logic_equivalence':    'expr_b',
    'logic_negation':       'claimed_negation',
    'truth_table':          'expected_value',
    'graph_property':       'expected',
    'tree_property':        'expected',
    'recurrence':           'expected',
    'numeric_eval':         'expected_numeric',
}


def _coerce_claim(distractor_text: str, original_claim: Any) -> Any:
    """Cố gắng convert distractor_text về cùng kiểu với original claim."""
    import json as _json
    if isinstance(original_claim, list):
        # solve_equation: list nghiệm
        try:
            v = _json.loads(distractor_text)
            return v if isinstance(v, list) else [v]
        except Exception:
            # Fallback: parse "x_1, x_2" hoặc "{2, 3}"
            cleaned = distractor_text.strip().strip('{}[]()').replace(';', ',')
            parts = [p.strip() for p in cleaned.split(',') if p.strip()]
            out = []
            for p in parts:
                try:
                    out.append(float(p) if '.' in p else int(p))
                except Exception:
                    out.append(p)
            return out
    if isinstance(original_claim, bool):
        s = distractor_text.strip().lower()
        if s in ('true', 'đúng', 't'): return True
        if s in ('false', 'sai', 'f'): return False
        return distractor_text
    if isinstance(original_claim, int):
        try: return int(float(distractor_text.strip()))
        except Exception: return distractor_text
    if isinstance(original_claim, float):
        try: return float(distractor_text.strip())
        except Exception: return distractor_text
    # str / sympy expression
    return distractor_text.strip()


def verify_distractor(hint: Dict[str, Any], distractor_text: str) -> Optional[bool]:
    """Re-verify với distractor's text thay cho claim. Trả True nếu distractor
    cũng được verifier xác nhận đúng (multi-answer); False nếu sai; None nếu
    không kiểm được (type=none, parse error, etc.)."""
    if not isinstance(hint, dict):
        return None
    t = hint.get('type', 'none')
    if t == 'none' or t not in _DISPATCH:
        return None
    payload = hint.get('payload')
    if isinstance(payload, str):
        import json as _json
        try:
            payload = _json.loads(payload)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if not payload:
        return None
    field = _CLAIM_FIELD.get(t)
    # Special: integral có thể dùng claimed_value (định) hoặc claimed_antiderivative (bất định)
    if t == 'integral':
        if 'claimed_value' in payload:
            field = 'claimed_value'
        elif 'claimed_antiderivative' in payload:
            field = 'claimed_antiderivative'
        else:
            return None
    if not field or field not in payload:
        return None
    original = payload[field]
    payload[field] = _coerce_claim(distractor_text, original)
    try:
        result = _DISPATCH[t](payload)
        return result.verified
    except Exception:
        return None

---
name: verifier-hint-authoring
description: Create machine-checkable verifier payloads for generated math answers. Use in QuestionWriterAgent when a correct answer can be verified by symbolic, numeric, graph, matrix, probability, modular, geometry, recurrence, or logic engines.
---

# Verifier Hint Authoring

Author payloads that route cleanly to deterministic verification.

## Workflow
1. Identify whether the answer is machine-checkable.
2. Choose a supported verifier type only when the expected payload schema is known.
3. Put the claimed correct answer in the expected or claimed field required by that type.
4. Keep expressions parseable; prefer simple variables and explicit numeric values.
5. Use `type=none` and `payload={}` for conceptual items, ambiguous schemas, or answers that require human interpretation.
6. For limit, probability, or direct numeric calculation questions, prefer a real verifier payload instead of `type=none`.

## Guardrails
- Do not invent a verifier type.
- Do not leave required payload fields blank.
- Do not use a symbolic verifier for a stem that asks for a qualitative explanation.
- Prefer `numeric_eval`, `probability`, or `limit` for simple numeric results when exact symbolic structure is not important.
- Keep verifier payload expressions machine-readable (SymPy/JSON style), even when the displayed answer uses inline LaTeX.

## Examples
Use these schemas only when the question matches them exactly:

```json
{"type": "analytic_geometry", "payload": {"operation": "distance_point_plane_3d", "point": [1, 0, 2], "plane": [2, -2, 2, -3], "expected": 0.8660254037844386}}
```

```json
{"type": "probability", "payload": {"formula": "0.18/0.30", "expected": 0.6}}
```

```json
{"type": "geometry_triangle", "payload": {"sides": {"AB": 5, "AC": 4, "BC": 3}, "property": "is_right", "expected": true}}
```

```json
{"type": "geometry_triangle", "payload": {"sides": {"AB": 5, "AC": 4, "BC": 3}, "property": "area", "base": 3, "height": 4, "expected": 6}}
```

```json
{"type": "modular", "payload": {"operation": "mod", "a": -7, "mod": 5, "expected": 3}}
```

```json
{"type": "numeric_eval", "payload": {"expr": "6*8/2", "expected_numeric": 24}}
```

```json
{"type": "limit", "payload": {"function": "(1-cos(3*x))/(x**2)", "variable": "x", "point": 0, "claimed_value": "9/2"}}
```

```json
{"type": "none", "payload": {}}
```

## Output
Return `verifier_hint` with `type` and `payload`.

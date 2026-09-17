# Evaluation summary — run `20260724-b1-postparse`

Post-parse-fix system benchmark (B1) + single-prompt baseline (B2), on four
Vietnamese grade-12 calculus PDFs, GPT-4o generator / GPT-4o-mini critic, three
parallel slots. This run is **after** three verifier/parser fixes:
(A) `\sqrt[n]{}`/nested-radical numeric parser, (B) numeric-eval key recovery,
and (C) the single-pass JSON `\escape` repair (`_robust_json_repair`) that
previously dropped ~17 Writer candidates to `Invalid \escape`.

All correctness claims below are backed by an **independent SymPy re-derivation**
of every keyed answer from the problem's givens (`audit_postparse.py`), never the
Writer's own expression.

## System benchmark (B1)

| Metric | Value |
|---|---|
| Requested / accepted | 40 / **40** |
| Candidates generated | 52 |
| Acceptance rate | **76.9%** |
| verified = True / False(kept) / None | **33 / 2 / 5** |
| Needs-revision (routed to human) | 3 |
| Tokens / calls | 639,807 / 150 |
| Duration | 1293.5 s (**32.3 s / accepted**) |

Reject distribution (12 rejected of 52 candidates):

| Gate : reason | Count |
|---|---|
| Critic : distractor–answer consistency | 4 |
| Critic : answer uniqueness | 3 |
| Writer (malformed JSON *structure* — genuine, `Expecting ',' delimiter`) | 3 |
| Duplicate of accepted item | 2 |

The three Writer drops are genuine structural malformations, **not** the
`Invalid \escape` class — that class is now zero (was 17 pre-fix). Acceptance
rose 56.9% → 76.9% purely from the parser fix.

## Independent CAS audit of all 40 accepted

Four wrong answer keys found (SymPy ground truth):

| # | Keyed (wrong) | Correct (CAS) | Verifier | Verdict |
|---|---|---|---|---|
| #3 | 204 | **165** | verified=False | **caught**, routed to review |
| #26 | 48 cm³ | **153.6 cm³** | verified=False | **caught**, routed to review |
| **#6** | 47/3 ≈ 15.67 | **43/3 ≈ 14.33** | verified=True | **BLIND SPOT — slipped** |
| **#34** | 468√2·π/5 ≈ 415.85 | **576√2·π/5 ≈ 511.82** | verified=True | **BLIND SPOT — slipped** |

- **Blind spot (wrong key passed verified=True): 2** — `#6`, `#34`. In each, the
  Writer's own `expr` reproduced the wrong value, so the consistency check passed.
  The correct value is not even among the options in either case.
- **Genuine wrong key caught (verified=False): 2** — `#3`, `#26`. Writer's `expr`
  disagreed with the wrong key; verifier flagged; held for review.
- **Fix-B recoveries: 5** (`#33 #34 #35 #36 #37`) = **4 correct** (`#33 #35 #36
  #37`, all CAS-confirmed π-form volumes) **+ 1 WRONG (`#34`)**. Fix B compares
  `expr` to the keyed option, but `expr` is itself Writer-authored — so when it is
  consistently wrong, Fix B *upgrades* a wrong answer from flagged to verified.
  **Fix B inherits the blind spot; the earlier "never certifies a wrong key"
  claim is falsified by `#34`.**
- **Formulation flaw: 1** (`#39`): region bounded by `y=5` and `y=x²` on `[1,3]`,
  but the curves cross at `x=√5`; keyed `4/3` is the naïve `∫(5−x²)`, true area
  ≈ 4.24. Ill-posed rather than a clean computational error.

## Cross-family LLM-judge (Claude Opus 4.8 judging GPT-4o output)

Single-rater automatic evaluation, every answer CAS-checked. `judge_scorecard.json`.

| Criterion | Pass |
|---|---|
| a) keyed answer unique & correct | 35/40 (87.5%) |
| b) grounded in document | 40/40 (100%) |
| c) non-trivial | 33/40 (82.5%) |
| d) tests understanding | 34/40 (85.0%) |
| all four | 28/40 (70.0%) |

a-fails = the four wrong keys (`#3 #6 #26 #34`) + the ill-posed `#39`.

## Single-prompt baseline (B2, same batch)

| Metric | Baseline | Pipeline |
|---|---|---|
| Delivered | 40/40 | 40/40 |
| Gate-pass (clean) | 28 (70%) | — (40 accepted after retry) |
| Symbolically confirmed | 26/40 (**65%**) | 33/40 (**82.5%**) |
| Tokens / question | ~1.0k | ~16k |

Difficulty confound stands: the baseline gets no computational-difficulty
escalation, so the arms do not attempt equal-difficulty questions. The honest
claims: pipeline yields more machine-checkable items at a ~16× token premium; no
head-to-head correctness claim.

## Bottom line

The re-run **strengthens** the paper's central thesis by demonstrating the
verifier blind spot with two concrete false negatives, rather than relying on a
prior run. It also shows the numeric-key-recovery fix (B) does not close the gap
and can itself certify a wrong answer, because the comparison target is still
generator-authored. The direction that closes it (future work) is an externally
derived verification target — recompute from the problem's givens, not from a
Writer-supplied expression.

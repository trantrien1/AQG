# -*- coding: utf-8 -*-
"""B2 — Baseline single-prompt: cùng model (gpt-4o), cùng PDF, MỘT lời gọi
sinh trọn bộ câu hỏi; sau đó đưa từng câu qua ĐÚNG tầng deterministic của
pipeline (rule validator + symbolic verify + multi-answer + distractor
validator/IWF) để đo tỷ lệ lỗi mà kiến trúc 5-agent chặn được by-construction.

Thiết kế công bằng (ghi rõ trong paper):
- Baseline nhận CÙNG schema output (kể cả verifier_payload — có spec + ví dụ
  y như writer của pipeline) và cùng yêu cầu source_quote/lời giải từng bước.
- Baseline KHÔNG nhận: catalogue misconception, tách 2 giai đoạn core/distractor,
  thang ép độ nặng phép tính, avoid-list, CĐR, và không có gate nào lúc sinh.
- Mỗi PDF baseline được tối đa 2 lần gọi (lấy lần parse được đầu tiên) — tương
  ứng ngân sách retry slot của pipeline.
- Tầng deterministic chấm baseline là NGUYÊN VĂN code pipeline (VerifierAgent),
  không viết lại.

Cách chạy:
  venv\\Scripts\\python.exe scripts\\bench_b2_baseline.py ^
      --pdfs pdftest\\file_1_trang_1-31.pdf ... --n 10 --out report\\bench\\<stamp>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

API_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_ROOT))

# Windows consoles default to cp1252 and crash on the Vietnamese summary text.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

os.chdir(API_ROOT)

from pipeline import config as cfg                       # noqa: E402
from pipeline.agents.messages import VerifyRequest       # noqa: E402
from pipeline.agents.verifier_agent import VerifierAgent  # noqa: E402
from pipeline.direct_pdf import attach as attach_mod      # noqa: E402
from pipeline.llm_client import (                         # noqa: E402
    call_llm_with_pdf, get_tracker, reset_tracker,
)
from pipeline.parsing import clean_source_quote, loads_json_maybe_repair  # noqa: E402

def _robust_json_repair(text: str) -> str:
    """Escape mọi backslash LaTeX chưa escape bên trong chuỗi JSON, bằng MỘT
    lượt quét (không tái xử lý phần vừa sửa — tránh lỗi \\\\( ba backslash).

    Quy tắc trong chuỗi:
      \\" \\\\ \\/       -> escape hợp lệ, giữ nguyên
      \\uXXXX            -> giữ nguyên
      \\b \\f \\n \\r \\t -> escape hợp lệ CHỈ KHI ký tự sau không phải chữ cái
                            (để \\frac, \\theta, \\beta... bị nhân đôi thành LaTeX)
      còn lại (\\( \\) \\[ \\frac \\, ...) -> nhân đôi backslash
    Xử lý đúng cả input đã escape sẵn (\\\\( giữ nguyên) lẫn chưa escape (\\( -> \\\\().
    """
    out: List[str] = []
    in_str = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        if ch == '"':
            out.append(ch)
            in_str = False
            i += 1
            continue
        if ch == '\\':
            nxt = text[i + 1] if i + 1 < n else ''
            after = text[i + 2] if i + 2 < n else ''
            if nxt == 'u' and re.match(r'[0-9a-fA-F]{4}', text[i + 2:i + 6]):
                out.append(text[i:i + 6])
                i += 6
                continue
            if nxt in '"\\/':                       # escape hợp lệ đã đúng
                out.append(ch)
                out.append(nxt)
                i += 2
                continue
            if nxt in 'bfnrt' and not after.isalpha():
                out.append(ch)                      # \n \t thật (không phải \theta)
                out.append(nxt)
                i += 2
                continue
            out.append('\\\\')                      # backslash LaTeX -> nhân đôi
            i += 1
            continue
        out.append(ch)
        i += 1
    return ''.join(out)

BLOOM_MIX_TEXT = (
    'khoảng 10% Nhận biết, 25% Thông hiểu, 40% Vận dụng, 25% Vận dụng cao'
)

# Spec verifier_payload — trích đúng yêu cầu mà writer pipeline nhận, để
# baseline có cùng khả năng diễn đạt kiểm chứng máy (điểm so sánh là KIẾN TRÚC,
# không phải việc có/không biết schema).
VERIFIER_SPEC = """
- Nếu đáp án là một kết quả số cụ thể, verifier_payload BẮT BUỘC đúng schema:
  {"type":"numeric_eval","payload":{"expr":"<biểu thức số học máy đọc được>","expected_numeric":<số đáp án>}}.
  expr dùng cú pháp SymPy: *, /, ** (lũy thừa), sqrt(), sin(), cos(), pi,
  integrate(f, (t, a, b)) — KHÔNG chứa LaTeX, đơn vị hay dấu phẩy thập phân.
  expected_numeric phải đúng bằng giá trị của đáp án đúng.
- Các dạng khác có thể dùng: probability {"formula","expected"}, limit
  {"function","variable","point","claimed_value"}, modular
  {"operation","a","mod","expected"}, geometry_triangle, analytic_geometry.
- Câu khái niệm không kiểm chứng máy được: {"type":"none","payload":{}}.
""".strip()


def _baseline_prompt(n: int) -> str:
    return f"""
Tài liệu Toán được đính kèm ở trên dưới dạng file PDF. ĐỌC TRỰC TIẾP nội dung
(công thức, bảng, hình) và soạn {n} câu hỏi trắc nghiệm MỚI (4 phương án, đúng 1).

Yêu cầu:
- Trộn các mức Bloom: {BLOOM_MIX_TEXT}.
- ĐƯỢC PHÉP tạo câu MỚI dựa trên cùng phương pháp/khái niệm trong tài liệu nhưng
  THAY số liệu/tình huống — KHÔNG chép nguyên văn bài tập có sẵn.
- Thông hiểu trở lên: KHÔNG hỏi định nghĩa/công thức chép lại; phải có ít nhất một
  phép biến đổi hoặc tính toán thực sự. Câu chỉ một phép thế số vào công thức cho
  sẵn là QUÁ TẦM THƯỜNG — không dùng.
- Toán hiển thị dùng LaTeX inline \\(...\\); trong JSON mọi backslash phải escape
  ("\\\\(x^2\\\\)", "\\\\frac{{a}}{{b}}").
- Đáp án ghi dạng đóng đẹp (phân số, căn, bội của \\\\(\\\\pi\\\\)), không thập phân dài.
- source_quote: trích NGUYÊN VĂN 15-250 ký tự từ tài liệu, liên quan trực tiếp câu hỏi.
- Mỗi câu có detailed_solution với các bước đánh số. Số bước tối thiểu THEO MỨC:
  Nhận biết >=2, Thông hiểu >=3, Vận dụng >=4, Vận dụng cao >=5. Không gộp lời giải
  thành một bước; mỗi phép biến đổi/tính toán là một bước riêng.
- Mỗi câu có ĐÚNG 3 distractor; mỗi distractor kèm mô tả lỗi sai dẫn tới giá trị đó.
{VERIFIER_SPEC}

Chỉ trả về DUY NHẤT một JSON object (không markdown):
{{
  "questions": [
    {{
      "question": "đề bài tự chứa, KHÔNG kèm nhãn A/B/C/D",
      "answer": "đáp án đúng (giá trị/biểu thức)",
      "explanation": "giải thích ngắn vì sao đúng",
      "detailed_solution": {{"steps":[{{"title":"Bước 1","content":"..."}}], "final_answer":"..."}},
      "why_correct": "vì sao đáp án này là duy nhất đúng",
      "source_quote": "15-250 ký tự trích nguyên văn",
      "cognitive_level": "Nhận biết|Thông hiểu|Vận dụng|Vận dụng cao",
      "verifier_payload": {{"type":"none","payload":{{}}}},
      "distractors": [
        {{"text":"giá trị sai","error_description":"lỗi sai nào dẫn tới giá trị này","error_category":"tên lỗi"}}
      ]
    }}
  ]
}}
""".strip()


def _try_load(text: str):
    """loads_json_maybe_repair trước, rồi repair mạnh (không strawman baseline
    vì lỗi escape JSON — chuyện định dạng, không phải điểm so sánh kiến trúc)."""
    try:
        return loads_json_maybe_repair(text)
    except Exception:
        return json.loads(_robust_json_repair(text))


def _salvage_objects(text: str) -> List[Dict[str, Any]]:
    """Tách từng object câu hỏi {...} và parse độc lập — 1 câu JSON hỏng không
    kéo theo mất cả batch. Quét theo cặp ngoặc cân bằng, bỏ qua ngoặc trong
    chuỗi. Tương đương việc pipeline retry TỪNG slot: câu hỏng không giết câu tốt.

    Repair backslash TRƯỚC khi quét: escape LaTeX chưa xử lý (\\( \\frac...) làm
    lệch bộ đếm ngoặc nếu để nguyên."""
    text = _robust_json_repair(text)
    out: List[Dict[str, Any]] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                frag = text[start:i + 1]
                if '"question"' not in frag:
                    continue
                try:
                    obj = _try_load(frag)
                    if isinstance(obj, dict) and obj.get('question'):
                        out.append(obj)
                except Exception:
                    pass
    return out


def _extract_questions(raw: str) -> List[Dict[str, Any]]:
    text = (raw or '').strip()
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.M).strip()
    s, e = text.find('{'), text.rfind('}')
    if s >= 0 and e > s:
        text = text[s:e + 1]
    try:
        obj = _try_load(text)
        if isinstance(obj, dict) and isinstance(obj.get('questions'), list):
            qs = [q for q in obj['questions'] if isinstance(q, dict)]
            if qs:
                return qs
        if isinstance(obj, list):
            qs = [q for q in obj if isinstance(q, dict)]
            if qs:
                return qs
    except Exception:
        pass
    # Whole-object parse thất bại -> salvage từng câu một.
    salvaged = _salvage_objects(text)
    if salvaged:
        return salvaged
    raise ValueError('không parse được questions từ output (kể cả salvage)')


def _to_candidate(item: Dict[str, Any]) -> Dict[str, Any]:
    distractors = []
    for d in item.get('distractors') or []:
        if not isinstance(d, dict):
            continue
        distractors.append({
            'distractor_text': str(d.get('text') or d.get('distractor_text') or '').strip(),
            'distractor_explanation_text': str(
                d.get('error_description') or d.get('explanation') or '').strip(),
            'distractor_category_text': str(
                d.get('error_category') or d.get('category') or '').strip(),
        })
    return {
        'question_text': str(item.get('question') or '').strip(),
        'answer_text': str(item.get('answer') or '').strip(),
        'answer_explanation_text': str(item.get('explanation') or '').strip(),
        'detailed_solution': item.get('detailed_solution'),
        'why_correct': str(item.get('why_correct') or '').strip(),
        'source_quote_text': clean_source_quote(str(item.get('source_quote') or '')),
        'verifier_hint': item.get('verifier_payload')
            if isinstance(item.get('verifier_payload'), dict)
            else {'type': 'none', 'payload': {}},
        'visual': {'type': 'none', 'spec': {}, 'alt_text': ''},
        'distractors': distractors,
    }


def _slot(i: int, pdf_name: str, level: Optional[str]) -> Dict[str, Any]:
    levels = {'Nhận biết': 0.30, 'Thông hiểu': 0.50,
              'Vận dụng': 0.70, 'Vận dụng cao': 0.85}
    lv = level if level in levels else 'Vận dụng'
    return {
        'slot_id': f'b2_{i}',
        'topic': '',
        'skill': '',
        'doc_id': pdf_name,
        'cognitive_level': lv,
        'difficulty_target': levels[lv],
        'expected_question_type': 'single_choice',
        'question_pattern': 'baseline_single_prompt',
        # Cùng relaxation với Direct_PDF của pipeline: quote công thức chung
        # không bị check token-overlap theo chunk.
        'source_chunk_type': 'exercise',
    }


def _classify(reject_reason: str) -> str:
    r = str(reject_reason or '')
    if 'answer_text_mismatch' in r:
        return 'answer_text_mismatch'
    if r.startswith('multi_answer'):
        return 'multi_answer'
    if r.startswith('distractor_validator'):
        return 'distractor_validator'
    if 'rule validator failed' in r:
        m = re.match(r'\s*([a-z_]+):', r)
        return f'rule:{m.group(1)}' if m else 'rule:other'
    return 'other'


def run_pdf(pdf_path: str, n: int, out_json: Path) -> Dict[str, Any]:
    pdf_name = os.path.basename(pdf_path)
    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()
    attach_mode = str(getattr(cfg, 'PDF_ATTACH_MODE', 'file_url')).lower()
    content = attach_mod.build_pdf_user_content(
        pdf_bytes, pdf_name, _baseline_prompt(n),
        as_image_url=(attach_mode == 'file_url'),
    )

    reset_tracker()
    t0 = time.time()
    raw, items, gen_error = '', [], None
    for attempt in (1, 2):                       # ngân sách 2 lần gọi / PDF
        try:
            raw = call_llm_with_pdf(
                system=cfg.SYSTEM_PROMPT,
                user_content=content,
                model=cfg.GENERATOR_MODEL,
                max_tokens=min(15000, 500 + 1500 * n),
            )
            items = _extract_questions(raw)
            gen_error = None
            break
        except Exception as exc:                 # noqa: BLE001
            gen_error = f'attempt {attempt}: {exc}'
            print(f'  [B2] {pdf_name} attempt {attempt} lỗi: {exc}')
    gen_seconds = time.time() - t0
    cost = get_tracker().report()

    verifier = VerifierAgent(use_skills=False)
    results: List[Dict[str, Any]] = []
    verdict_dist: Counter = Counter()
    for i, item in enumerate(items[:n]):
        cand = _to_candidate(item)
        slot = _slot(i, pdf_name, item.get('cognitive_level'))
        try:
            resp = verifier.run(VerifyRequest(candidate=cand, slot=slot, context=''))
            annotations = resp.annotations
            rejected = resp.rejected
            reason = resp.reject_reason
        except Exception as exc:                 # noqa: BLE001
            annotations, rejected, reason = {}, True, f'verifier_crash: {exc}'
        verification = annotations.get('_verification') or {}
        verdict = 'pass' if not rejected else _classify(reason)
        verdict_dist[verdict] += 1
        results.append({
            'index': i,
            'cognitive_level': slot['cognitive_level'],
            'question_text': cand['question_text'],
            'answer_text': cand['answer_text'],
            'n_distractors': len(cand['distractors']),
            'verifier_hint_type': (cand.get('verifier_hint') or {}).get('type'),
            'gate_rejected': rejected,
            'gate_reason': reason[:400] if reason else '',
            'verdict': verdict,
            'verified': verification.get('verified'),
            'verification_detail': str(verification.get('detail') or '')[:200],
            'answer_key_repaired': bool(annotations.get('_answer_key_repaired')),
            'validator_checks': annotations.get('_validator'),
            'rule_issues': (annotations.get('_rule_validator') or {}).get('issues'),
        })

    # pass = qua gate cứng; pass_clean = qua gate VÀ không bị verifier ghi
    # mismatch (verified=False sẽ bị pipeline ép needs_revision — với baseline
    # không có tầng review nên mismatch đồng nghĩa lỗi lọt lưới).
    pass_clean = sum(
        1 for r in results if not r['gate_rejected'] and r['verified'] is not False
    )
    summary = {
        'pdf': pdf_name,
        'requested': n,
        'generated': len(items),
        'generation_error': gen_error,
        'generation_seconds': round(gen_seconds, 1),
        'cost': cost,
        'gate_pass': verdict_dist.get('pass', 0),
        'gate_pass_rate': (
            round(verdict_dist.get('pass', 0) / len(results), 4) if results else None
        ),
        'pass_clean': pass_clean,
        'pass_clean_rate': (
            round(pass_clean / len(results), 4) if results else None
        ),
        'verdict_distribution': dict(verdict_dist),
        'verified_true': sum(1 for r in results if r['verified'] is True),
        'verified_false': sum(1 for r in results if r['verified'] is False),
        'verified_none': sum(1 for r in results if r['verified'] is None),
        'hint_type_distribution': dict(Counter(
            r['verifier_hint_type'] or 'missing' for r in results)),
    }
    payload = {
        'metadata': {
            'bench': 'B2-baseline-single-prompt',
            'source_pdf': str(pdf_path),
            'source_pdf_name': pdf_name,
            'generator_model': cfg.GENERATOR_MODEL,
            'pdf_attach_mode': attach_mode,
            'generated_at': dt.datetime.utcnow().isoformat() + 'Z',
            'prompt_chars': len(_baseline_prompt(n)),
        },
        'summary': summary,
        'items': results,
        'raw_response': raw,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    print(f'[B2] {pdf_name}: generated={len(items)} '
          f'pass={summary["gate_pass"]}/{len(results)} '
          f'verdicts={summary["verdict_distribution"]} '
          f'tokens={cost.get("tokens")} {gen_seconds:.0f}s')
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description='B2 baseline single-prompt')
    ap.add_argument('--pdfs', nargs='+', required=True)
    ap.add_argument('--n', type=int, default=10)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    for pdf in args.pdfs:
        stem = re.sub(r'[^0-9A-Za-z_-]+', '_', Path(pdf).stem)[:40]
        summaries.append(run_pdf(pdf, args.n, out_dir / f'b2_{stem}.json'))

    total_items = sum(s['generated'] for s in summaries)
    graded = sum(min(s['generated'], s['requested']) for s in summaries)
    total_pass = sum(s['gate_pass'] for s in summaries)
    verdicts: Counter = Counter()
    for s in summaries:
        verdicts.update(s['verdict_distribution'])
    total_clean = sum(s['pass_clean'] for s in summaries)
    totals = {
        'pdfs': len(summaries),
        'requested': sum(s['requested'] for s in summaries),
        'generated': total_items,
        'graded': graded,
        'gate_pass': total_pass,
        'gate_pass_rate': round(total_pass / graded, 4) if graded else None,
        'pass_clean': total_clean,
        'pass_clean_rate': round(total_clean / graded, 4) if graded else None,
        'verdict_distribution': dict(verdicts),
        'verified_true': sum(s['verified_true'] for s in summaries),
        'verified_false': sum(s['verified_false'] for s in summaries),
        'verified_none': sum(s['verified_none'] for s in summaries),
        'cost_tokens': sum((s['cost'] or {}).get('tokens', 0) for s in summaries),
        'cost_calls': sum((s['cost'] or {}).get('calls', 0) for s in summaries),
        'generation_seconds': round(sum(s['generation_seconds'] for s in summaries), 1),
    }
    (out_dir / 'b2_summary.json').write_text(
        json.dumps({'per_pdf': summaries, 'totals': totals},
                   ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[B2] totals: {json.dumps(totals, ensure_ascii=False)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

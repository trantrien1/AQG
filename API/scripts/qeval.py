"""Đánh giá CHẤT LƯỢNG câu hỏi đã sinh, theo hai bộ tiêu chí đã công bố.

Ba tầng, chạy được độc lập:

  --layer rules   Rubric 19 lỗi soạn đề (Item-Writing Flaws), phần kiểm được
                  bằng luật. Tất định, miễn phí, không gọi mô hình.
                  Moore et al., ECTEL 2023 (arXiv:2307.08161).
  --layer llm     7 chiều của QGEval (thang 1-3) + 5 lỗi soạn đề cần phán đoán
                  nội dung. Gọi mô hình qua chat2api.
                  Fu et al., EMNLP 2024 (arXiv:2406.05707).
  --layer agree   Độ tin cậy: chấm nhiều vòng lấy mode, Krippendorff's alpha
                  giữa các vòng, và mức đồng thuận luật ↔ mô hình.

Điều bộ đo này KHÔNG làm: thay người chấm. QGEval dùng ba người chú thích và
chính họ kết luận benchmark của mình "có sức phân biệt hạn chế"; bài ECTEL báo
cáo luật bắt được 91% lỗi mà người bắt, GPT-4 được 79%. Nên mọi con số ở đây là
số của MÁY chấm, và phải được gọi đúng tên đó.

    python scripts/qeval.py --layer rules --corpus report/bench/suite-20260725
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ------------------------------------------------------------- nạp ngữ liệu
def load_corpus(paths: List[str]) -> List[Dict[str, Any]]:
    """Gom mọi câu hỏi từ các file/thư mục JSON, kèm nguồn gốc của từng câu."""
    files: List[str] = []
    for p in paths:
        full = p if os.path.isabs(p) else str(ROOT / p)
        if os.path.isdir(full):
            files += sorted(glob.glob(os.path.join(full, '**', '*.json'),
                                      recursive=True))
        else:
            files.append(full)

    seen_ids = set()
    out: List[Dict[str, Any]] = []
    for f in files:
        try:
            data = json.loads(Path(f).read_text(encoding='utf-8'))
        except Exception:
            continue
        questions = data.get('questions') if isinstance(data, dict) else None
        if not isinstance(questions, list):
            continue
        try:
            rel = os.path.relpath(f, ROOT)
        except ValueError:
            # Ngữ liệu nằm ổ đĩa khác (Windows): relpath ném lỗi. Ghi đường dẫn
            # đầy đủ thay vì làm hỏng cả lượt nạp.
            rel = f
        for q in questions:
            if not isinstance(q, dict) or not q.get('options'):
                continue
            qid = q.get('question_id')
            # Cùng một câu có thể nằm trong nhiều file báo cáo; đếm hai lần thì
            # mọi tỉ lệ đều lệch.
            if qid and qid in seen_ids:
                continue
            if qid:
                seen_ids.add(qid)
            q = dict(q)
            q['_source_file'] = rel
            out.append(q)
    return out


# ------------------------------------------------------------ tầng 1: luật
def layer_rules(questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    from pipeline import iwf_rubric as R

    per_q = []
    counts = collections.Counter()
    hist = collections.Counter()
    for q in questions:
        flaws = R.rule_flaws(q)
        counts.update(flaws)
        hist[len(flaws)] += 1
        per_q.append({
            'question_id': q.get('question_id'),
            'source_file': q.get('_source_file'),
            'cognitive_level': q.get('cognitive_level'),
            'rule_flaws': flaws,
            'rule_flaw_count': len(flaws),
            'acceptable_by_rules': R.is_acceptable(flaws),
        })

    n = len(questions) or 1
    acceptable = sum(1 for p in per_q if p['acceptable_by_rules'])
    return {
        'n_questions': len(questions),
        'rubric': 'Item-Writing Flaws (Moore et al., ECTEL 2023)',
        'flaws_checked_by_rule': list(R.RULE_FLAWS),
        'flaws_needing_judgement': list(R.LLM_FLAWS),
        # Nói rõ mẫu số: 14/19 lỗi được kiểm ở tầng này, nên "chấp nhận được"
        # ở đây là CẬN TRÊN — 5 lỗi còn lại chỉ tầng LLM mới thấy.
        'coverage': f'{len(R.RULE_FLAWS)}/{len(R.ALL_FLAWS)}',
        'acceptable_upper_bound': acceptable,
        'acceptable_rate_upper_bound': round(acceptable / n, 4),
        'flaw_counts': dict(counts.most_common()),
        'flaws_per_question_histogram': {str(k): hist[k]
                                         for k in sorted(hist)},
        'per_question': per_q,
    }


def report_rules(res: Dict[str, Any]) -> str:
    lines = [
        '# Tầng 1 — Rubric 19 lỗi soạn đề (phần kiểm bằng luật)',
        '',
        f"Ngữ liệu: **{res['n_questions']} câu**. "
        f"Luật phủ **{res['coverage']}** lỗi của rubric; "
        f"{len(res['flaws_needing_judgement'])} lỗi còn lại cần phán đoán nội "
        f"dung nên thuộc tầng 2.",
        '',
        f"**Chấp nhận được (≤1 lỗi): {res['acceptable_upper_bound']}"
        f"/{res['n_questions']} = "
        f"{100 * res['acceptable_rate_upper_bound']:.1f}%** — đây là *cận trên*, "
        'vì 5 lỗi chưa kiểm chỉ có thể làm con số này giảm.',
        '',
        '## Lỗi bắt được',
        '',
    ]
    if res['flaw_counts']:
        lines += ['| lỗi | số câu |', '|---|---|']
        lines += [f'| `{k}` | {v} |' for k, v in res['flaw_counts'].items()]
    else:
        lines.append('_Không luật nào bắt được lỗi._')
    lines += ['', '## Số lỗi trên mỗi câu', '',
              '| số lỗi | số câu |', '|---|---|']
    lines += [f'| {k} | {v} |'
              for k, v in res['flaws_per_question_histogram'].items()]
    lines += ['', '## Lỗi chưa kiểm ở tầng này', '',
              ', '.join(f'`{f}`' for f in res['flaws_needing_judgement']), '']
    return '\n'.join(lines)


# ------------------------------------------------------------ tầng 2: LLM
def _passage_of(q: Dict[str, Any]) -> str:
    src = q.get('source') if isinstance(q.get('source'), dict) else {}
    return str(src.get('quote_in_context') or src.get('quote') or '').strip()


def _answer_text(q: Dict[str, Any]) -> str:
    for o in (q.get('options') or []):
        if isinstance(o, dict) and o.get('key') == q.get('answer_key'):
            return str(o.get('text') or '')
    return ''


def _judge_prompt(q: Dict[str, Any]) -> str:
    from pipeline import iwf_rubric as R
    from pipeline import qg_rubric as QG

    options = '\n'.join(
        f"  {o.get('key')}. {o.get('text')}"
        for o in (q.get('options') or []) if isinstance(o, dict))
    # Mô tả CẢ 19 lỗi. Chỉ đưa tên snake_case thì mô hình phải tự đoán nghĩa,
    # và phép so luật ↔ mô hình ở tầng 3 không còn đo được điều gì.
    flaw_lines = [f'  "{name}" — {desc}'
                  for name, desc in R.flaw_definitions().items()]

    return f"""Bạn chấm chất lượng MỘT câu hỏi trắc nghiệm Toán lớp 12.

NGỮ CẢNH NGUỒN (trích từ tài liệu gốc):
{_passage_of(q) or '(không có trích dẫn nguồn)'}

CÂU HỎI:
{q.get('stem')}

CÁC PHƯƠNG ÁN:
{options}

ĐÁP ÁN ĐƯỢC ĐÁNH DẤU ĐÚNG: {q.get('answer_key')}. {_answer_text(q)}

--- PHẦN 1: chấm 7 chiều, thang 1-3 ---
{QG.anchor_block()}

--- PHẦN 2: đánh dấu lỗi soạn đề ---
Với MỖI mục dưới đây, trả true nếu câu hỏi CÓ lỗi đó, false nếu không:
{chr(10).join(flaw_lines)}

Quy tắc chấm:
- Chấm đúng những gì nhìn thấy, không suy diễn thiện chí.
- Các chiều bám nguồn/nhất quán/trả lời được chấm SO VỚI ngữ cảnh nguồn ở trên.
  Nếu ngữ cảnh nguồn trống, cho các chiều đó giá trị null thay vì đoán.
- "answer_consistency" hỏi đáp án được đánh dấu có trả lời đúng câu hỏi không.

Chỉ trả về JSON, không giải thích ngoài JSON:
{{
  "fluency": 1|2|3, "clarity": 1|2|3, "conciseness": 1|2|3,
  "relevance": 1|2|3|null, "consistency": 1|2|3|null,
  "answerability": 1|2|3|null, "answer_consistency": 1|2|3,
  "flaws": {{"<tên lỗi>": true|false, ...}},
  "note": "một câu ngắn về vấn đề lớn nhất, hoặc chuỗi rỗng"
}}"""


_AUTH_FAILURE_MARKERS = (
    'token_expired', 'invalid_api_key', 'unauthorized', 'authentication',
    'error code: 401', 'error code: 403',
)


def _is_auth_failure(exc: Exception) -> bool:
    """Lỗi xác thực — không lượt gọi nào sau đó có thể thành công."""
    text = str(exc).lower()
    return any(m in text for m in _AUTH_FAILURE_MARKERS)


def judge_once(q: Dict[str, Any], model: str) -> Dict[str, Any]:
    from pipeline.llm_client import call_llm
    from pipeline.parsing import loads_json_maybe_repair

    raw = call_llm(
        system='Bạn là chuyên gia khảo thí, chấm nghiêm và nhất quán.',
        user=_judge_prompt(q), model=model, temperature=0.0, max_tokens=1200)
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', (raw or '').strip())
    return loads_json_maybe_repair(text)


def load_records_from_items(out: Path) -> Dict[str, List[Dict[str, Any]]]:
    """Dựng lại kết quả chấm từ các phiếu trên đĩa.

    Phiếu từng câu mới là nguồn sự thật, không phải file tổng: lượt chấm có thể
    đứt giữa chừng vì hết hạn mức, và khi đó file tổng chưa kịp ghi. Đọc thẳng
    từ phiếu thì phần đã chấm không mất.
    """
    records: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    items_dir = out / 'items'
    if not items_dir.is_dir():
        return {}
    for path in sorted(items_dir.glob('*_r*.json')):
        qid = re.sub(r'_r\d+$', '', path.stem)
        try:
            records[qid].append(json.loads(path.read_text(encoding='utf-8')))
        except Exception:
            continue
    return dict(records)


def layer_llm(questions: List[Dict[str, Any]], model: str, rounds: int,
              out: Path) -> Dict[str, Any]:
    """Chấm mỗi câu `rounds` lượt. Lưu từng lượt ra đĩa để chạy tiếp được."""
    from pipeline import iwf_rubric as R
    from pipeline import qg_rubric as QG
    from pipeline.llm_client import ProviderQuotaExhausted

    items_dir = out / 'items'
    items_dir.mkdir(parents=True, exist_ok=True)
    records: Dict[str, List[Dict[str, Any]]] = {}
    errors = 0

    for i, q in enumerate(questions, 1):
        qid = str(q.get('question_id') or f'idx{i}')
        rounds_done: List[Dict[str, Any]] = []
        for r in range(rounds):
            path = items_dir / f'{qid}_r{r}.json'
            if path.exists():
                try:
                    rounds_done.append(json.loads(
                        path.read_text(encoding='utf-8')))
                    continue
                except Exception:
                    pass
            try:
                verdict = judge_once(q, model)
            except ProviderQuotaExhausted:
                # Hết hạn mức thì DỪNG, không ghi tiếp: chấm dở dang mà vẫn
                # tính trung bình sẽ cho ra số dựa trên tập con không ngẫu nhiên.
                print(f'DỪNG: hết hạn mức tại câu {i}/{len(questions)}',
                      file=sys.stderr)
                raise
            except Exception as exc:
                errors += 1
                if _is_auth_failure(exc):
                    # Hỏng xác thực thì mọi lời gọi sau đều hỏng y hệt. Dừng
                    # ngay thay vì lặp lỗi đó 267 lần rồi báo "0 câu chấm được".
                    print(f'DỪNG: xác thực nhà cung cấp hỏng — {exc}',
                          file=sys.stderr)
                    raise SystemExit(4)
                print(f'  lỗi chấm {qid} lượt {r}: {exc}', file=sys.stderr)
                continue
            path.write_text(json.dumps(verdict, ensure_ascii=False, indent=1),
                            encoding='utf-8')
            rounds_done.append(verdict)
        records[qid] = rounds_done
        if i % 10 == 0 or i == len(questions):
            print(f'  chấm {i}/{len(questions)}')

    return {
        'model': model,
        'rounds': rounds,
        'n_questions': len(questions),
        'n_judge_errors': errors,
        'dimensions': list(QG.DIMENSIONS),
        'flaws_asked': list(R.RULE_FLAWS + R.LLM_FLAWS),
        'records': records,
    }


# --------------------------------------------------- tầng 3: độ tin cậy
def krippendorff_alpha(units: List[List[Any]], metric: str = 'interval') -> Optional[float]:
    """Krippendorff's alpha trên các đơn vị có >=2 lượt chấm.

    `units` là danh sách, mỗi phần tử là các giá trị mà nhiều lượt chấm gán cho
    CÙNG một đơn vị (bỏ qua giá trị thiếu). `metric` là 'interval' cho thang
    1-3 hoặc 'nominal' cho nhãn nhị phân.

    Trả None khi không đủ dữ liệu để tính — thà không có số còn hơn một số
    không có nghĩa.
    """
    pairs = [[v for v in u if v is not None] for u in units]
    pairs = [u for u in pairs if len(u) >= 2]
    if not pairs:
        return None

    def delta2(a, b):
        if metric == 'nominal':
            return 0.0 if a == b else 1.0
        return float(a - b) ** 2

    coincidences: Dict[Tuple[Any, Any], float] = collections.defaultdict(float)
    for u in pairs:
        m = len(u)
        for a in range(m):
            for b in range(m):
                if a == b:
                    continue
                coincidences[(u[a], u[b])] += 1.0 / (m - 1)

    n = sum(coincidences.values())
    if n <= 1:
        return None
    marginals: Dict[Any, float] = collections.defaultdict(float)
    for (va, vb), w in coincidences.items():
        marginals[va] += w

    do = sum(w * delta2(va, vb) for (va, vb), w in coincidences.items()) / n
    de = sum(marginals[va] * marginals[vb] * delta2(va, vb)
             for va in marginals for vb in marginals) / (n * (n - 1))
    if de == 0:
        # Mọi lượt chấm cho cùng một giá trị trên mọi đơn vị: không có phương
        # sai để chuẩn hoá. Đồng thuận tuyệt đối, nhưng alpha không xác định.
        return 1.0 if do == 0 else None
    return round(1.0 - do / de, 4)


def cohen_kappa(a: List[bool], b: List[bool]) -> Optional[float]:
    """Kappa của Cohen cho hai bộ nhãn nhị phân song song."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return None
    n = len(pairs)
    po = sum(1 for x, y in pairs if x == y) / n
    pa = sum(1 for x, _ in pairs if x) / n
    pb = sum(1 for _, y in pairs if y) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if pe >= 1.0:
        return None
    return round((po - pe) / (1 - pe), 4)


def _mode_bool(values: List[Any]) -> Optional[bool]:
    vals = [bool(v) for v in values if isinstance(v, bool)]
    if not vals:
        return None
    return sum(vals) * 2 > len(vals)


def layer_agree(questions: List[Dict[str, Any]],
                llm: Dict[str, Any]) -> Dict[str, Any]:
    from pipeline import iwf_rubric as R
    from pipeline import qg_rubric as QG

    records = llm['records']

    # --- ổn định giữa các lượt chấm ---
    dim_alpha: Dict[str, Optional[float]] = {}
    dim_mean: Dict[str, Optional[float]] = {}
    for dim in QG.DIMENSIONS:
        units, flat = [], []
        for rs in records.values():
            vals = [r.get(dim) for r in rs
                    if isinstance(r.get(dim), (int, float))]
            if vals:
                units.append(vals)
                flat.append(sum(vals) / len(vals))
        dim_alpha[dim] = krippendorff_alpha(units, 'interval')
        dim_mean[dim] = round(sum(flat) / len(flat), 3) if flat else None

    flaw_alpha: Dict[str, Optional[float]] = {}
    for name in R.RULE_FLAWS + R.LLM_FLAWS:
        units = []
        for rs in records.values():
            vals = [bool((r.get('flaws') or {}).get(name)) for r in rs
                    if isinstance((r.get('flaws') or {}).get(name), bool)]
            if vals:
                units.append(vals)
        flaw_alpha[name] = krippendorff_alpha(units, 'nominal')

    # --- luật ↔ mô hình, trên 14 lỗi cả hai cùng xét ---
    agreement = {}
    for name in R.RULE_FLAWS:
        rule_side, llm_side = [], []
        for q in questions:
            qid = str(q.get('question_id') or '')
            rs = records.get(qid) or []
            voted = _mode_bool([(r.get('flaws') or {}).get(name) for r in rs])
            if voted is None:
                continue
            rule_side.append(name in R.rule_flaws(q))
            llm_side.append(voted)
        if not rule_side:
            continue
        same = sum(1 for x, y in zip(rule_side, llm_side) if x == y)
        agreement[name] = {
            'n': len(rule_side),
            'percent_agreement': round(same / len(rule_side), 4),
            'cohen_kappa': cohen_kappa(rule_side, llm_side),
            'rule_flagged': sum(rule_side),
            'llm_flagged': sum(llm_side),
        }

    # --- chấp nhận được theo cả 19 lỗi ---
    combined = []
    for q in questions:
        qid = str(q.get('question_id') or '')
        rs = records.get(qid) or []
        if not rs:
            continue
        flaws = set(R.rule_flaws(q))
        for name in R.RULE_FLAWS + R.LLM_FLAWS:
            if _mode_bool([(r.get('flaws') or {}).get(name) for r in rs]):
                flaws.add(name)
        combined.append({'question_id': qid, 'flaws': sorted(flaws),
                         'acceptable': R.is_acceptable(sorted(flaws))})
    n = len(combined) or 1
    return {
        'n_judged': len(combined),
        'rounds': llm['rounds'],
        'dimension_mean': dim_mean,
        'dimension_alpha_between_rounds': dim_alpha,
        'flaw_alpha_between_rounds': flaw_alpha,
        'rule_vs_llm': agreement,
        'acceptable_all_19': sum(1 for c in combined if c['acceptable']),
        'acceptable_rate_all_19': round(
            sum(1 for c in combined if c['acceptable']) / n, 4),
        'per_question': combined,
    }


def report_agree(res: Dict[str, Any], llm: Dict[str, Any]) -> str:
    from pipeline import qg_rubric as QG

    lines = [
        '# Tầng 2+3 — chấm bằng mô hình và độ tin cậy',
        '',
        f"Mô hình chấm: `{llm['model']}`, **{llm['rounds']} lượt** mỗi câu, "
        f"{res['n_judged']} câu.",
        '',
        '## 7 chiều của QGEval (thang 1–3)',
        '',
        '| chiều | điểm trung bình | alpha giữa các lượt |',
        '|---|---|---|',
    ]
    for dim in QG.DIMENSIONS:
        mean = res['dimension_mean'].get(dim)
        alpha = res['dimension_alpha_between_rounds'].get(dim)
        lines.append(f"| {QG.DIMENSION_LABELS_VI[dim]} (`{dim}`) "
                     f"| {mean if mean is not None else '—'} "
                     f"| {alpha if alpha is not None else '—'} |")
    lines += [
        '',
        '> Alpha ở đây đo độ ổn định giữa các LƯỢT CHẤM của cùng một mô hình, '
        'không phải giữa những người chú thích độc lập. Nó là cận **trên** của '
        'độ tin cậy: cùng một mô hình, cùng một prompt thì dễ lặp lại chính '
        'mình hơn hai người khác nhau.',
        '',
        '## Luật và mô hình có đồng ý với nhau không',
        '',
        'Trên 14 lỗi mà cả hai cùng xét. Chỗ nào lệch thì ít nhất một bên sai.',
        '',
        '| lỗi | n | luật gắn | mô hình gắn | trùng nhau | kappa |',
        '|---|---|---|---|---|---|',
    ]
    for name, a in sorted(res['rule_vs_llm'].items(),
                          key=lambda kv: kv[1]['percent_agreement']):
        k = a['cohen_kappa']
        lines.append(f"| `{name}` | {a['n']} | {a['rule_flagged']} "
                     f"| {a['llm_flagged']} "
                     f"| {100 * a['percent_agreement']:.0f}% "
                     f"| {k if k is not None else '—'} |")
    lines += [
        '',
        '## Chấp nhận được, tính trên đủ 19 lỗi',
        '',
        f"**{res['acceptable_all_19']}/{res['n_judged']} = "
        f"{100 * res['acceptable_rate_all_19']:.1f}%** (≤1 lỗi).",
        '',
    ]
    return '\n'.join(lines)


# ------------------------------------ tầng phụ: lệch vị trí đáp án
def layer_position(questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Đối chiếu vị trí đáp án: trộn ngẫu nhiên (hiện tại) vs sắp thứ tự.

    Lỗi `lost_sequence` của rubric đòi phương án số phải xếp tăng/giảm dần.
    Phép đo này kiểm xem tuân thủ điều đó có tạo ra lỗi khác nặng hơn không —
    và câu trả lời phụ thuộc vào CÁCH sinh distractor, nên không suy luận suông
    được, phải đo trên chính ngữ liệu.
    """
    from pipeline.iwf_rubric import _sole_number

    keys = 'ABCD'
    current = collections.Counter()
    sorted_pos = collections.Counter()
    numeric: List[Dict[str, Any]] = []
    for q in questions:
        current[q.get('answer_key')] += 1
        opts = q.get('options') or []
        vals = [(o.get('key'), _sole_number(str(o.get('text') or '')))
                for o in opts if isinstance(o, dict)]
        if len(vals) != 4 or any(v is None for _, v in vals):
            continue
        order = sorted(vals, key=lambda kv: kv[1])
        try:
            pos = [k for k, _ in order].index(q.get('answer_key'))
        except ValueError:
            continue
        sorted_pos[keys[pos]] += 1
        numeric.append(q)

    def chi_square(counter: collections.Counter, n: int) -> Optional[float]:
        if n < 4:
            return None
        expected = n / 4.0
        return round(sum((counter[k] - expected) ** 2 / expected
                         for k in keys), 2)

    n_num = len(numeric)
    current_numeric = collections.Counter(
        q.get('answer_key') for q in numeric)
    middle = sorted_pos['B'] + sorted_pos['C']
    return {
        'n_questions': len(questions),
        'n_all_numeric_options': n_num,
        # Ngưỡng chi-bình-phương 5% với 3 bậc tự do.
        'chi_square_threshold_5pct': 7.81,
        'current_shuffle': {
            'counts_all': {k: current[k] for k in keys},
            'chi_square_all': chi_square(current, len(questions)),
            'counts_numeric_only': {k: current_numeric[k] for k in keys},
            'chi_square_numeric_only': chi_square(current_numeric, n_num),
        },
        'if_sorted_ascending': {
            'counts': {k: sorted_pos[k] for k in keys},
            'chi_square': chi_square(sorted_pos, n_num),
            'middle_two_positions': middle,
            'middle_two_share': round(middle / n_num, 4) if n_num else None,
            # Điểm của học sinh không biết gì mà luôn chọn B hoặc C.
            'blind_bc_strategy_accuracy': (
                round(middle / n_num / 2, 4) if n_num else None),
        },
    }


def report_position(res: Dict[str, Any]) -> str:
    cur = res['current_shuffle']
    srt = res['if_sorted_ascending']
    n = res['n_all_numeric_options']
    lines = [
        '# Lệch vị trí đáp án: trộn ngẫu nhiên so với sắp thứ tự',
        '',
        f"{res['n_questions']} câu, trong đó **{n} câu** có cả bốn phương án là "
        'số thuần.',
        '',
        '| vị trí đáp án | A | B | C | D | chi-bình-phương |',
        '|---|---|---|---|---|---|',
        '| trộn hiện tại (toàn bộ) | '
        + ' | '.join(str(cur['counts_all'][k]) for k in 'ABCD')
        + f" | {cur['chi_square_all']} |",
        '| trộn hiện tại (chỉ câu số thuần) | '
        + ' | '.join(str(cur['counts_numeric_only'][k]) for k in 'ABCD')
        + f" | {cur['chi_square_numeric_only']} |",
        '| **nếu sắp tăng dần** | '
        + ' | '.join(f"**{srt['counts'][k]}**" for k in 'ABCD')
        + f" | **{srt['chi_square']}** |",
        '',
        f"Ngưỡng ý nghĩa 5% với 3 bậc tự do: "
        f"{res['chi_square_threshold_5pct']}.",
        '',
        f"Sắp thứ tự dồn **{100 * srt['middle_two_share']:.0f}%** đáp án vào hai "
        f"vị trí giữa. Học sinh không biết gì mà luôn chọn B hoặc C sẽ đúng "
        f"**{100 * srt['blind_bc_strategy_accuracy']:.0f}%** thay vì 25%.",
        '',
    ]
    return '\n'.join(lines)


#: Endpoint tương thích OpenAI của Gemini — dùng được với cùng client.
_GEMINI_OPENAI_BASE = 'https://generativelanguage.googleapis.com/v1beta/openai/'


def _env_value_from_dotenv(name: str) -> str:
    """Đọc ĐÚNG một biến từ .env, không nạp cả file vào môi trường.

    Nạp cả file là cách làm hỏng cấu hình: `.env` khai nhiều khối provider
    chồng nhau, nên nạp toàn bộ sẽ ghi đè provider đang dùng.
    """
    if os.getenv(name):
        return os.environ[name]
    try:
        raw = (ROOT / '.env').read_text(encoding='utf-8-sig')
    except OSError:
        return ''
    m = re.search(rf'^{re.escape(name)}=(.*)$', raw, re.M)
    return m.group(1).strip().strip('"\'') if m else ''


def configure_judge_provider(provider: str) -> None:
    """Đặt env TRƯỚC khi import pipeline.config (config đọc env lúc import).

    Vì sao có lựa chọn Gemini: ngữ liệu đang chấm do gpt-4o sinh ra, nên lấy
    chính gpt-4o chấm là tự chấm mình — đúng thiên lệch cùng-họ mà cả Scaria
    (AIED 2024) lẫn phần Hạn chế của paper này đều nêu. Giám khảo khác họ cho
    kết quả đáng tin hơn, và tiện thể tránh luôn hạn mức tin nhắn của chat2api.
    """
    if provider != 'gemini':
        # KHÔNG đụng gì tới env. `.env` của dự án khai `AQG_LLM_PROVIDER` HAI
        # lần (khối chat2api rồi khối openrouter); python-dotenv lấy dòng CUỐI,
        # còn bộ nạp riêng của pipeline.config lấy dòng đầu. Gọi load_dotenv ở
        # đây từng khiến cả lượt chấm âm thầm chạy qua OpenRouter thay vì
        # chat2api — đúng kiểu hỏng không có dấu hiệu gì trong log.
        return
    key = _env_value_from_dotenv('GEMINI_API_KEY')
    if not key:
        raise SystemExit('Thiếu GEMINI_API_KEY trong .env')
    os.environ['AQG_LLM_PROVIDER'] = 'openai_compatible'
    os.environ['OPENAI_COMPATIBLE_BASE_URL'] = _GEMINI_OPENAI_BASE
    os.environ['OPENAI_API_KEY'] = key


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--layer', default='rules',
                    choices=['rules', 'llm', 'agree', 'position'])
    ap.add_argument('--corpus', nargs='+', required=True,
                    help='file hoặc thư mục JSON chứa câu hỏi đã sinh')
    ap.add_argument('--out', default='report/quality')
    ap.add_argument('--model', default='gpt-4o',
                    help='mô hình chấm (tầng llm)')
    ap.add_argument('--rounds', type=int, default=3,
                    help='số lượt chấm mỗi câu; QGEval dùng 3 người chú thích')
    ap.add_argument('--limit', type=int, default=0,
                    help='chỉ chấm N câu đầu (chạy thử)')
    ap.add_argument('--provider', default='chat2api',
                    choices=['chat2api', 'gemini'],
                    help='gemini = giám khảo KHÁC HỌ với mô hình đã sinh ngữ '
                         'liệu, nên ít thiên lệch hơn')
    ap.add_argument('--judge-max-tokens', type=int, default=1200,
                    help='mô hình có suy luận tiêu token suy luận vào chính '
                         'ngân sách này, nên cần nới')
    args = ap.parse_args()
    configure_judge_provider(args.provider)

    questions = load_corpus(args.corpus)
    if not questions:
        print('Không tìm thấy câu hỏi nào trong ngữ liệu.', file=sys.stderr)
        return 2
    print(f'nạp {len(questions)} câu từ {len(args.corpus)} nguồn')

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    if args.layer == 'rules':
        res = layer_rules(questions)
        (out / 'layer1_rules.json').write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        md = report_rules(res)
        (out / 'layer1_rules.md').write_text(md, encoding='utf-8')
        print('\n' + md)
        print(f'chi tiết: {out}')
        return 0

    if args.limit:
        questions = questions[:args.limit]

    if args.layer == 'position':
        res = layer_position(questions)
        (out / 'position_bias.json').write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
        md = report_position(res)
        (out / 'position_bias.md').write_text(md, encoding='utf-8')
        print('\n' + md)
        return 0

    llm_path = out / 'layer2_llm.json'
    if args.layer == 'llm':
        res = layer_llm(questions, args.model, args.rounds, out)
        llm_path.write_text(json.dumps(res, ensure_ascii=False, indent=1),
                            encoding='utf-8')
        done = sum(1 for v in res['records'].values() if v)
        print(f"\nchấm xong {done}/{res['n_questions']} câu × "
              f"{res['rounds']} lượt, {res['n_judge_errors']} lỗi")
        print(f'chi tiết: {llm_path}')
        return 0

    # agree — luôn dựng lại từ phiếu trên đĩa, kể cả khi lượt chấm đứt giữa chừng
    records = load_records_from_items(out)
    if not records:
        print('Chưa có phiếu chấm nào — chạy --layer llm trước.',
              file=sys.stderr)
        return 2
    meta = {}
    if llm_path.exists():
        try:
            meta = json.loads(llm_path.read_text(encoding='utf-8'))
        except Exception:
            meta = {}
    complete = {q: rs for q, rs in records.items()
                if len(rs) >= args.rounds}
    if len(complete) < len(records):
        # Câu chấm dở có ít lượt hơn -> trung bình của nó dựa trên mẫu khác các
        # câu còn lại. Chỉ tính trên câu ĐỦ lượt để mọi câu cùng mẫu số.
        print(f'bỏ qua {len(records) - len(complete)} câu chưa đủ '
              f'{args.rounds} lượt chấm')
    llm = {'model': meta.get('model', args.model),
           'rounds': args.rounds,
           'records': complete}
    judged_ids = set(complete)
    res = layer_agree([q for q in questions
                       if str(q.get('question_id') or '') in judged_ids], llm)
    (out / 'layer3_agreement.json').write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    md = report_agree(res, llm)
    (out / 'layer3_agreement.md').write_text(md, encoding='utf-8')
    print('\n' + md)
    print(f'chi tiết: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

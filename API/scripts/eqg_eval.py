"""Chấm câu hỏi đã giao ra bằng giám khảo KHÁC HỌ, theo lối EQGBench.

Phỏng theo Zhou et al., "From Answers to Questions: EQGBench" (arXiv 2508.10005):
rubric ba mức có NEO viết rõ (Tốt=2 / Đạt=1 / Kém=0) cho từng chiều, tiêu chí
nhúng thẳng vào prompt chấm, và **chấm nhiều vòng độc lập rồi lấy mode** để hạ
sai số ngẫu nhiên của một lần chấm. Thêm phần gán nhãn mức Bloom theo Scaria et
al. (arXiv 2408.04394), vốn so nhãn chuyên gia với mức đã yêu cầu.

Khác EQGBench ở ba chỗ, đều do đối tượng chấm khác nhau:
  - bỏ chiều "knowledge point alignment" (EQGBench có điểm kiến thức do người
    dùng nêu; ở đây ngữ cảnh là cả một tài liệu, không nhét vừa prompt chấm giá
    rẻ) — việc bám tài liệu đã do Critic trong cặp lo, và KHÔNG được coi bản
    chấm này là bằng chứng bám tài liệu;
  - thêm chiều chất lượng phương án nhiễu, vì hệ này chỉ sinh trắc nghiệm;
  - ghi lại độ ổn định giữa các vòng chấm, thứ EQGBench không báo cáo.

Giám khảo là Gemini — khác nhà cung cấp với cả bộ sinh (gpt-4o) lẫn bộ phê bình
(gpt-4o-mini), nên không chung họ mô hình với bên bị chấm.

Chạy:
    python scripts/eqg_eval.py --out report/eval/eqg-<ngày>
    python scripts/eqg_eval.py --out ... --limit 5      # thử trước
    python scripts/eqg_eval.py --out ... --summarise    # chỉ gộp, không gọi API
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    'A': 'report/bench/20260724-b1-postparse',
    'B': 'report/bench/suite-20260725',
}
BLOOM_LEVELS = ['Nhận biết', 'Thông hiểu', 'Vận dụng', 'Vận dụng cao']
ROUNDS = 3
# Bậc pro của Gemini trả 429 trên hạn mức hiện tại của tài khoản; bậc flash chạy
# được. Giám khảo yếu hơn EQGBench (họ dùng DeepSeek R1) — đây là ràng buộc hạ
# tầng, và chính vì thế script ghi lại độ ổn định giữa các vòng để đọc kết quả
# đúng mức tin cậy mà nó xứng đáng.
MODEL = os.getenv('EQG_EVAL_MODEL', 'gemini-3.6-flash')


class EvaluatorQuotaExhausted(RuntimeError):
    """Hết hạn mức phía nhà cung cấp: dừng cả run thay vì ngủ - thử lại vô ích."""
TEMPERATURE = float(os.getenv('EQG_EVAL_TEMPERATURE', '0.3'))

DIMENSIONS = {
    'QT': 'Đúng đặc tả định dạng',
    'QQ': 'Chất lượng bản thân câu hỏi',
    'SQ': 'Chất lượng lời giải',
    'DQ': 'Chất lượng phương án nhiễu',
    'CG': 'Định hướng phát triển năng lực',
}

RUBRIC = """\
Bạn là chuyên gia ra đề toán phổ thông 20 năm kinh nghiệm. Hãy chấm CHẶT một câu
trắc nghiệm theo từng chiều dưới đây, mỗi chiều cho đúng một trong ba mức
2 (Tốt) / 1 (Đạt) / 0 (Kém), theo đúng neo mô tả.

[QT] ĐÚNG ĐẶC TẢ ĐỊNH DẠNG
 2 = đúng 4 phương án, đúng một đáp án được đánh dấu đúng, các phương án cùng
     dạng và cùng đơn vị, phần dẫn nêu rõ một câu hỏi xác định.
 1 = đúng khuôn nhưng có lỗi nhỏ về trình bày, đơn vị hoặc tính song song giữa
     các phương án.
 0 = sai khuôn: thiếu/thừa phương án, phần dẫn KHÔNG hỏi gì, hoặc không xác định
     được câu hỏi.

[QQ] CHẤT LƯỢNG BẢN THÂN CÂU HỎI
 2 = diễn đạt rõ, thuật ngữ chuẩn, dữ kiện đủ, đáp án tồn tại và duy nhất.
 1 = còn chỗ mơ hồ hoặc dùng thuật ngữ chưa chuẩn, nhưng vẫn giải được.
 0 = tối nghĩa, thiếu dữ kiện, mâu thuẫn nội tại, hoặc có nhiều hơn một phương
     án đúng.

[SQ] CHẤT LƯỢNG LỜI GIẢI
 2 = lời giải đúng, logic chặt, và DẪN RA ĐÚNG đáp án đã đánh dấu.
 1 = ra đúng đáp án nhưng có bước nhảy, lặp, hoặc thiếu lập luận.
 0 = lời giải sai, hoặc không dẫn tới đáp án đã đánh dấu, hoặc chỉ nêu kết quả.

[DQ] CHẤT LƯỢNG PHƯƠNG ÁN NHIỄU
 2 = cả ba phương án sai đều hợp lý, mỗi phương án ứng với một lỗi học sinh
     thật và khác nhau, không phương án nào vô tình cũng đúng.
 1 = có phương án dễ loại bằng mẹo, hoặc hai phương án cùng một kiểu lỗi.
 0 = phương án nhiễu vô lý, trùng nhau, hoặc có phương án cũng đúng.

[CG] ĐỊNH HƯỚNG PHÁT TRIỂN NĂNG LỰC
 2 = có bối cảnh/tình huống thực chất, gắn ứng dụng, đòi vận dụng chứ không chỉ
     áp công thức.
 1 = có nhắc bối cảnh nhưng hình thức, bỏ đi vẫn không đổi bài toán.
 0 = thuần trừu tượng, chỉ là bài luyện áp công thức.

[BLOOM] MỨC NHẬN THỨC THỰC TẾ mà câu hỏi này đòi hỏi — chọn ĐÚNG MỘT:
 "Nhận biết"    = nhắc lại định nghĩa, nhận ra đối tượng, đọc thẳng dữ kiện.
 "Thông hiểu"   = giải thích, biến đổi một bước, áp dụng trực tiếp một công thức.
 "Vận dụng"     = giải nhiều bước, chọn được phương pháp phù hợp.
 "Vận dụng cao" = phối hợp từ hai kỹ thuật trở lên, bài ngược, hoặc có tham số.
CHỈ căn cứ vào bản thân câu hỏi. KHÔNG suy đoán mức mà người ra đề mong muốn.

Chỉ trả về JSON, không kèm lời nào khác, đúng khuôn:
{"QT":<0|1|2>,"QQ":<0|1|2>,"SQ":<0|1|2>,"DQ":<0|1|2>,"CG":<0|1|2>,
 "bloom":"<một trong bốn mức>","ly_do":"<một câu ngắn>"}
"""


# ---------------------------------------------------------------- gọi Gemini
def call_gemini(prompt: str, *, api_key: str, seed: int) -> str:
    url = (f'https://generativelanguage.googleapis.com/v1beta/models/'
           f'{MODEL}:generateContent')
    body = json.dumps({
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': TEMPERATURE,
            'maxOutputTokens': 2048,
            'responseMimeType': 'application/json',
        },
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': 'application/json', 'x-goog-api-key': api_key})
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            cands = d.get('candidates') or []
            if not cands:
                raise RuntimeError(f'không có candidate: {str(d)[:200]}')
            parts = cands[0].get('content', {}).get('parts') or []
            text = ''.join(p.get('text', '') for p in parts)
            if not text.strip():
                raise RuntimeError(
                    f"rỗng, finishReason={cands[0].get('finishReason')}")
            return text
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (400, 403, 404):           # hỏng cấu hình, retry vô ích
                raise
            if exc.code == 429:
                try:
                    detail = exc.read().decode('utf-8', 'replace')
                except Exception:                      # noqa: BLE001
                    detail = ''
                if 'quota' in detail.lower():
                    raise EvaluatorQuotaExhausted(detail[:300]) from exc
            time.sleep(min(60, 4 * (2 ** attempt)) + random.random())
        except Exception as exc:                      # noqa: BLE001
            last = exc
            time.sleep(min(60, 4 * (2 ** attempt)) + random.random())
    raise RuntimeError(f'Gemini thất bại sau 5 lần: {last}')


def parse_verdict(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    out: Dict[str, Any] = {}
    for k in DIMENSIONS:
        v = obj.get(k)
        if not isinstance(v, (int, float)) or int(v) not in (0, 1, 2):
            return None
        out[k] = int(v)
    bl = str(obj.get('bloom') or '').strip()
    if bl not in BLOOM_LEVELS:
        return None
    out['bloom'] = bl
    out['ly_do'] = str(obj.get('ly_do') or '')[:300]
    return out


# ------------------------------------------------------------------ nạp câu
def load_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for run, rel in RUNS.items():
        root = ROOT / rel
        for f in sorted(root.rglob('*.json')):
            b = f.name
            if 'manifest' in str(f) or b.startswith(
                    ('suite_', 'ground_truth', 'cas_', 'baseline_')):
                continue
            try:
                d = json.loads(f.read_text(encoding='utf-8'))
            except Exception:                          # noqa: BLE001
                continue
            if not isinstance(d, dict) or 'questions' not in d:
                continue
            if not d.get('metadata', {}).get('cost', {}).get('tokens'):
                continue
            for q in d['questions']:
                items.append({
                    'run': run,
                    'cell': f.stem,
                    'question_id': q.get('question_id'),
                    'assigned_bloom': q.get('cognitive_level'),
                    'stem': q.get('stem') or '',
                    'options': q.get('options') or [],
                    'answer_key': q.get('answer_key'),
                    'solution': (q.get('detailed_solution')
                                 or q.get('explanation_correct') or ''),
                    'per_distractor': q.get('explanation_per_distractor') or {},
                })
    return items


def render_item(it: Dict[str, Any]) -> str:
    opts = '\n'.join(
        f"  {o.get('key')}. {o.get('text')}"
        f"{'   <-- ĐÁP ÁN ĐƯỢC ĐÁNH DẤU ĐÚNG' if o.get('key') == it['answer_key'] else ''}"
        for o in it['options'])
    pd = it['per_distractor']
    if isinstance(pd, dict):
        traces = '\n'.join(f'  {k}: {v}' for k, v in pd.items())
    else:
        traces = '\n'.join(f'  - {x}' for x in pd)
    return (f"PHẦN DẪN:\n{it['stem']}\n\nCÁC PHƯƠNG ÁN:\n{opts}\n\n"
            f"LỜI GIẢI KÈM THEO:\n{it['solution']}\n\n"
            f"MÔ TẢ LỖI CỦA TỪNG PHƯƠNG ÁN NHIỄU:\n{traces or '  (không có)'}")


# ------------------------------------------------------------------ tổng hợp
def vote(rounds: List[Dict[str, Any]], key: str):
    """Mode qua các vòng; hoà thì lấy trung bình (số) hoặc vòng đầu (nhãn)."""
    vals = [r[key] for r in rounds if key in r]
    if not vals:
        return None
    c = collections.Counter(vals)
    top = c.most_common()
    if len(top) == 1 or top[0][1] > top[1][1]:
        return top[0][0]
    if isinstance(vals[0], (int, float)):
        return sum(vals) / len(vals)
    return vals[0]


def summarise(out_dir: Path) -> Dict[str, Any]:
    recs = []
    for f in sorted((out_dir / 'items').glob('*.json')):
        try:
            recs.append(json.loads(f.read_text(encoding='utf-8')))
        except Exception:                              # noqa: BLE001
            continue
    recs = [r for r in recs if r.get('rounds')]
    res: Dict[str, Any] = {'n_items': len(recs), 'model': MODEL,
                           'rounds': ROUNDS, 'temperature': TEMPERATURE,
                           'by_run': {}}
    for run in sorted({r['run'] for r in recs}):
        sub = [r for r in recs if r['run'] == run]
        block: Dict[str, Any] = {'n': len(sub)}
        for dim in DIMENSIONS:
            finals = [vote(r['rounds'], dim) for r in sub]
            finals = [x for x in finals if x is not None]
            if not finals:
                continue
            block[dim] = {
                'mean': round(sum(finals) / len(finals), 3),
                'pct_2': round(100 * sum(1 for x in finals if x == 2) / len(finals), 1),
                'pct_0': round(100 * sum(1 for x in finals if x == 0) / len(finals), 1),
            }
        # Bloom: nhãn giám khảo so với mức đã gán
        match = tot = 0
        conf: Dict[str, Dict[str, int]] = {}
        for r in sub:
            jb = vote(r['rounds'], 'bloom')
            ab = r.get('assigned_bloom')
            if not jb or not ab:
                continue
            tot += 1
            match += int(jb == ab)
            conf.setdefault(ab, collections.Counter())[jb] += 1
        if tot:
            block['bloom_adherence'] = {
                'matched': match, 'n': tot,
                'pct': round(100 * match / tot, 1),
                'confusion': {k: dict(v) for k, v in conf.items()},
            }
        # độ ổn định của chính giám khảo giữa các vòng
        stable = collections.Counter()
        for r in sub:
            for dim in list(DIMENSIONS) + ['bloom']:
                vals = [x[dim] for x in r['rounds'] if dim in x]
                if len(vals) >= 2:
                    stable[dim] += int(len(set(vals)) == 1)
                    stable[dim + '_n'] += 1
        block['round_stability'] = {
            d: round(100 * stable[d] / stable[d + '_n'], 1)
            for d in list(DIMENSIONS) + ['bloom'] if stable.get(d + '_n')
        }
        res['by_run'][run] = block
    return res


# ---------------------------------------------------------------------- main
def main() -> int:
    for stream in (sys.stdout, sys.stderr):           # console Windows là cp1252
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', required=True)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--summarise', action='store_true')
    ap.add_argument('--rounds', type=int, default=ROUNDS)
    args = ap.parse_args()

    out_dir = ROOT / args.out
    (out_dir / 'items').mkdir(parents=True, exist_ok=True)

    if not args.summarise:
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / '.env')
        except ImportError:
            pass
        api_key = os.getenv('GEMINI_API_KEY', '').strip()
        if not api_key:
            print('Thiếu GEMINI_API_KEY', file=sys.stderr)
            return 2

        items = load_items()
        if args.limit:
            items = items[:args.limit]
        print(f'{len(items)} câu, {args.rounds} vòng, giám khảo {MODEL}')
        done = err = 0
        for i, it in enumerate(items, 1):
            dest = out_dir / 'items' / f"{it['run']}_{it['question_id']}.json"
            if dest.exists():
                done += 1
                continue
            prompt = f'{RUBRIC}\n\n=== CÂU CẦN CHẤM ===\n{render_item(it)}'
            rounds = []
            for r in range(args.rounds):
                try:
                    v = parse_verdict(call_gemini(prompt, api_key=api_key, seed=r))
                except EvaluatorQuotaExhausted as exc:
                    print(f'HẾT HẠN MỨC giám khảo, dừng tại câu {i}: {exc}',
                          file=sys.stderr)
                    print(f'  đã chấm {done} câu, chạy lại lệnh này để tiếp tục')
                    res = summarise(out_dir)
                    (out_dir / 'summary.json').write_text(
                        json.dumps(res, ensure_ascii=False, indent=2),
                        encoding='utf-8')
                    return 3
                except Exception as exc:               # noqa: BLE001
                    print(f'  [{i}] vòng {r} lỗi: {exc}', file=sys.stderr)
                    v = None
                if v:
                    rounds.append(v)
            if rounds:
                rec = dict(it, rounds=rounds, model=MODEL,
                           temperature=TEMPERATURE)
                rec.pop('options', None)
                rec.pop('per_distractor', None)
                rec['stem'] = rec['stem'][:400]
                rec['solution'] = ''
                dest.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                                encoding='utf-8')
                done += 1
            else:
                err += 1
            if i % 10 == 0 or i == len(items):
                print(f'  {i}/{len(items)}  ok={done} lỗi={err}')

    res = summarise(out_dir)
    (out_dir / 'summary.json').write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

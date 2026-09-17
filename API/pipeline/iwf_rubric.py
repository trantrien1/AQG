"""Rubric 19 lỗi soạn đề trắc nghiệm (Item-Writing Flaws) — đánh giá HẬU KIỂM.

Khác `iwf_checker.py`: file đó là một CỔNG chạy lúc sinh, với 6 luật do dự án
tự đặt. File này là bộ ĐO, áp lên một tập câu hỏi đã sinh xong, và bám đúng
rubric 19 lỗi đã được kiểm chứng trong tài liệu:

    Moore, Nguyen, Chen, Stamper (2023). "Assessing the Quality of
    Multiple-Choice Questions Using GPT-4 and Rule-Based Methods." ECTEL 2023.
    arXiv:2307.08161 — rubric rút gọn từ 31 hướng dẫn của Haladyna.

Ngưỡng chấp nhận của rubric: **0–1 lỗi = dùng được, ≥2 lỗi = không dùng được.**

Không phải lỗi nào cũng kiểm được bằng luật. Mỗi lỗi ở đây khai báo rõ nó thuộc
loại nào — `rule` (kiểm tất định) hay `llm` (cần phán đoán) — và bộ đo chỉ đếm
những lỗi nó THỰC SỰ kiểm được, thay vì im lặng cho qua rồi báo một con số đẹp
hơn sự thật. Chính bài báo trên cũng phải dùng mô hình cho các lỗi khó.

Mỗi hàm trả về True nếu câu hỏi **CÓ lỗi** (flag), False nếu sạch.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple

# --------------------------------------------------------------- tiện ích


def _fold(text: str) -> str:
    """Bỏ dấu tiếng Việt để so khớp cụm từ không phụ thuộc dấu."""
    text = (text or '').replace('Đ', 'D').replace('đ', 'd')
    norm = unicodedata.normalize('NFKD', text)
    return ''.join(c for c in norm if not unicodedata.combining(c)).lower()


_MATH_WRAPPER_RE = re.compile(r'\\[()\[\]]|\$\$?')
_LATEX_CMD_RE = re.compile(r'\\[a-zA-Z]+\s*')
_BRACES_RE = re.compile(r'[{}]')


def _plain(text: str) -> str:
    """Bỏ vỏ LaTeX để đếm độ dài/so từ trên phần nội dung thật.

    Không bỏ lớp này thì `\\(\\frac{115}{3}\\,\\text{m}\\)` dài gấp ba
    `15 m`, và mọi luật đo độ dài đều sai.
    """
    s = _MATH_WRAPPER_RE.sub(' ', text or '')
    s = _LATEX_CMD_RE.sub(' ', s)
    s = _BRACES_RE.sub(' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _symbol_key(text: str) -> str:
    """Khoá so trùng cho phương án — GIỮ nguyên lệnh LaTeX.

    Không dùng `_plain` ở đây: nó xoá lệnh LaTeX, mà với phương án ký hiệu thì
    lệnh chính là phần mang nghĩa. `\\(B\\subseteq A\\)` và `\\(A\\subseteq B\\)`
    qua `_plain` đều còn "A B" và bị coi là trùng nhau — hai quan hệ bao hàm
    ngược chiều bị báo thành cùng một phương án.
    """
    s = _MATH_WRAPPER_RE.sub('', text or '')
    return re.sub(r'\s+', '', s).strip('.').lower()


def _options(q: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [o for o in (q.get('options') or []) if isinstance(o, dict)]


def _option_texts(q: Dict[str, Any]) -> List[str]:
    return [str(o.get('text') or '') for o in _options(q)]


def _correct_text(q: Dict[str, Any]) -> str:
    key = q.get('answer_key')
    for o in _options(q):
        if o.get('key') == key:
            return str(o.get('text') or '')
    return ''


def _distractor_texts(q: Dict[str, Any]) -> List[str]:
    key = q.get('answer_key')
    return [str(o.get('text') or '') for o in _options(q) if o.get('key') != key]


_NUM_RE = re.compile(r'-?\d+(?:[.,]\d+)?')


def _sole_number(text: str) -> Optional[float]:
    """Giá trị số của option nếu nó là MỘT số duy nhất, ngược lại None."""
    nums = _NUM_RE.findall(_plain(text))
    if len(nums) != 1:
        return None
    try:
        return float(nums[0].replace(',', '.'))
    except ValueError:
        return None


_WORD_RE = re.compile(r'[0-9a-zA-ZÀ-ỹĐđ]{4,}')

_STOPWORDS = {
    _fold(w) for w in (
        'được', 'trong', 'không', 'nhưng', 'nào', 'này', 'những', 'của',
        'cho', 'với', 'theo', 'khi', 'bằng', 'một', 'các', 'thì', 'là',
        'có', 'và', 'hoặc', 'trên', 'dưới', 'sau', 'trước', 'bao', 'nhiêu',
        'sau đây', 'hãy', 'tính', 'biết', 'giá', 'trị', 'hàm', 'số',
    )
}


def _content_words(text: str) -> set:
    return {w for w in (_fold(x) for x in _WORD_RE.findall(_plain(text)))
            if w and w not in _STOPWORDS}


# ------------------------------------------------------- 19 lỗi của rubric
# Tên giữ nguyên theo bài báo để đối chiếu được; mô tả bằng tiếng Việt.

def _f_none_of_the_above(q: Dict[str, Any]) -> bool:
    """#3 — Có phương án "không phương án nào đúng"."""
    pats = ('khong co dap an nao', 'khong dap an nao', 'khong phuong an nao',
            'none of the above', 'khong co cau nao dung',
            'khong co dap an dung')
    return any(any(p in _fold(t) for p in pats) for t in _option_texts(q))


def _f_all_of_the_above(q: Dict[str, Any]) -> bool:
    """#9 — Có phương án "tất cả các phương án trên"."""
    pats = ('tat ca cac dap an', 'tat ca cac phuong an', 'tat ca deu dung',
            'all of the above', 'ca a b c', 'ca ba dap an')
    return any(any(p in _fold(t) for p in pats) for t in _option_texts(q))


def _f_longest_option_correct(q: Dict[str, Any]) -> bool:
    """#4 — Đáp án đúng dài hơn hẳn vì được diễn giải chi tiết hơn.

    Rubric mô tả lỗi này là đáp án đúng "dài hơn và chứa nhiều thông tin chi
    tiết hơn, gợi ý cho học sinh". Manh mối nằm ở LỜI VĂN, không ở độ dài thô.

    Nên luật chỉ áp khi đáp án đúng thực sự có lời văn (từ hai từ nội dung trở
    lên). Với phương án thuần giá trị toán thì bỏ qua: \\(\\frac{115}{3}\\) dài
    hơn \\(8\\) là do phân số có hai số, không phải do người soạn viết kỹ hơn —
    áp luật độ dài ở đây sẽ báo lỗi giả trên gần như mọi câu Toán.

    Đo trên nội dung đã bỏ vỏ LaTeX, ngưỡng chênh 25% để bỏ qua sai khác vặt.
    """
    correct_text = _correct_text(q)
    if len(_content_words(correct_text)) < 2:
        return False
    correct = len(_plain(correct_text))
    others = [len(_plain(t)) for t in _distractor_texts(q)]
    if not others or correct == 0:
        return False
    return correct > max(others) * 1.25


def _f_true_false_question(q: Dict[str, Any]) -> bool:
    """#6 — Các phương án chỉ là chuỗi mệnh đề đúng/sai."""
    vals = {_fold(t).strip(' .') for t in _option_texts(q)}
    tf = {'dung', 'sai', 'true', 'false', 'co', 'khong'}
    return bool(vals) and vals.issubset(tf)


# Nhãn mệnh đề trong ĐỀ: "(1)", "(i)", "I.", "II)" ...
_STEM_ENUM_RE = re.compile(
    r'\(\s*(?:[ivx]{1,4}|[1-9])\s*\)|(?:^|\s)(?:[ivx]{1,4}|[1-9])\s*[.)](?=\s)')
# Nhãn trong PHƯƠNG ÁN: chỉ nhận dạng có ngoặc hoặc số La Mã. KHÔNG nhận chữ số
# trần: phương án "\(2\)" của một câu Toán bình thường là một GIÁ TRỊ, không
# phải nhãn mệnh đề — nhận nhầm thì mọi câu đáp số một chữ số đều bị gắn K-type.
_OPT_REF_RE = re.compile(r'\(\s*(?:[ivx]{1,4}|[1-9])\s*\)|\b[ivx]{1,4}\b')
_OPT_KTYPE_RE = re.compile(
    r'^\s*(?:chi\s+)?%s(?:\s*(?:,|va|;|và)\s*%s)*\s*\.?\s*$'
    % (_OPT_REF_RE.pattern, _OPT_REF_RE.pattern))


def _f_complex_k_type(q: Dict[str, Any]) -> bool:
    """#14 — Dạng K-type: phương án là tổ hợp các mệnh đề đánh số ("I và III").

    Điều kiện kép, cố ý chặt: ĐỀ phải đánh số ít nhất hai mệnh đề, VÀ ít nhất
    hai phương án phải chỉ gồm tham chiếu tới các nhãn đó. Thiếu vế đầu thì
    một câu Toán có đáp số \\(1\\), \\(2\\) sẽ bị gắn nhầm là K-type.
    """
    stem = _fold(_plain(q.get('stem') or ''))
    if len(_STEM_ENUM_RE.findall(stem)) < 2:
        return False
    hits = sum(1 for t in _option_texts(q)
               if _OPT_KTYPE_RE.match(_fold(_plain(t))))
    return hits >= 2


def _f_convergence_cues(q: Dict[str, Any]) -> bool:
    """#7 — Manh mối hội tụ: các phương án là tổ hợp lặp của cùng vài thành phần.

    Dấu hiệu: nhiều phương án cùng chia sẻ một thành phần nối bằng "và"/"hoặc",
    khiến học sinh loại trừ được bằng cách đếm tần suất thay vì hiểu bài.
    """
    parts: List[set] = []
    for t in _option_texts(q):
        f = _fold(_plain(t))
        if not re.search(r'\b(va|hoac)\b', f):
            return False
        parts.append({p.strip() for p in re.split(r'\b(?:va|hoac)\b', f)
                      if p.strip()})
    if len(parts) < 3:
        return False
    shared = set.intersection(*parts) if parts else set()
    return bool(shared)


def _f_fill_in_blank(q: Dict[str, Any]) -> bool:
    """#10 — Đề khoét trống giữa câu để học sinh điền từ phương án."""
    stem = _plain(q.get('stem') or '')
    if not stem:
        return False
    body = stem.rstrip()
    # Dấu ... ở CUỐI câu là cách dẫn bình thường, không phải khoét trống.
    core = body[:-3].rstrip() if body.endswith('...') else body
    return bool(re.search(r'_{2,}|\.{3,}|…', core))


_ABSOLUTE_TERMS = ('luon luon', 'luon', 'moi truong hop', 'khong bao gio',
                   'tuyet doi khong', 'chac chan khong', 'tat ca cac truong hop',
                   'always', 'never', 'absolutely')


def _f_absolute_terms(q: Dict[str, Any]) -> bool:
    """#11 — Phương án chứa từ tuyệt đối (học sinh biết chúng hầu như luôn sai)."""
    return any(any(re.search(rf'\b{re.escape(a)}\b', _fold(t))
                   for a in _ABSOLUTE_TERMS)
               for t in _distractor_texts(q))


_VAGUE_TERMS = ('thuong xuyen', 'doi khi', 'hiem khi', 'thinh thoang',
                'co the', 'kha nhieu', 'mot so', 'nhieu kha nang',
                'frequently', 'occasionally', 'usually', 'sometimes')


def _f_vague_terms(q: Dict[str, Any]) -> bool:
    """#17 — Phương án dùng từ chỉ mức độ mơ hồ, không ai thống nhất nghĩa."""
    return any(any(v in _fold(t) for v in _VAGUE_TERMS)
               for t in _option_texts(q))


def _f_word_repeats(q: Dict[str, Any]) -> bool:
    """#12 — Từ nội dung trong đề chỉ lặp lại ở ĐÁP ÁN ĐÚNG.

    Đây là manh mối ngôn ngữ mạnh: học sinh không hiểu bài vẫn chọn được
    phương án dùng lại từ khoá của đề.
    """
    stem_words = _content_words(q.get('stem') or '')
    if not stem_words:
        return False
    in_correct = stem_words & _content_words(_correct_text(q))
    if not in_correct:
        return False
    for t in _distractor_texts(q):
        if in_correct & _content_words(t):
            return False        # từ đó cũng có ở phương án sai -> không phải manh mối
    return True


def _f_lost_sequence(q: Dict[str, Any]) -> bool:
    """#16 — Các phương án đều là số nhưng không sắp theo thứ tự.

    Rubric đòi phương án số/thời gian phải xếp tăng hoặc giảm dần; xếp lộn xộn
    làm học sinh mất thời gian dò thay vì làm toán.
    """
    nums = [_sole_number(t) for t in _option_texts(q)]
    if len(nums) < 3 or any(n is None for n in nums):
        return False
    if len(set(nums)) != len(nums):
        return False            # trùng số là lỗi khác (#18), không tính ở đây
    return not (nums == sorted(nums) or nums == sorted(nums, reverse=True))


_NEGATIVE_RE = re.compile(
    r'\b(khong|ngoai tru|sai|khong dung|khong phai|chua dung|except|not)\b')


def _f_negative_worded(q: Dict[str, Any]) -> bool:
    """#19 — Đề hỏi theo lối phủ định ("phương án nào SAI", "... ngoại trừ").

    Chỉ tính khi phủ định nằm ở MỆNH ĐỀ HỎI, không phải trong dữ kiện toán
    (ví dụ "vận tốc không đổi" là dữ kiện, không phải hỏi phủ định).
    """
    stem = _fold(_plain(q.get('stem') or ''))
    if not stem:
        return False
    tail = stem[-160:]
    if not re.search(r'(nao|gi|dau|bao nhieu)\b', tail):
        return False
    return bool(re.search(
        r'\b(khong dung|khong phai|sai|ngoai tru|except)\b', tail))


def _f_unfocused_stem(q: Dict[str, Any]) -> bool:
    """#13 — Đề không nêu được câu hỏi trọn vẹn nếu chưa nhìn phương án."""
    stem = _plain(q.get('stem') or '').strip()
    if not stem:
        return True
    if stem.endswith((',', ':', ';')):
        return True
    folded = _fold(stem)
    asks = ('?' in stem
            or re.search(r'\b(bao nhieu|nao|tinh|tim|xac dinh|hay|gi|dau)\b',
                         folded))
    return not asks


def _f_more_than_one_correct(q: Dict[str, Any]) -> bool:
    """#18 — Có nhiều hơn một phương án đúng.

    Phần kiểm được bằng luật: hai phương án TRÙNG NHAU về nội dung thì hiển
    nhiên không thể chỉ một cái đúng. Trường hợp hai phương án khác mặt chữ mà
    cùng đúng về toán thì phải giải mới biết — để cho tầng LLM.
    """
    seen = set()
    for t in _option_texts(q):
        k = _symbol_key(t)
        if not k:
            continue
        if k in seen:
            return True
        seen.add(k)
    nums = [_sole_number(t) for t in _option_texts(q)]
    vals = [n for n in nums if n is not None]
    return len(vals) != len(set(vals))


#: Mô tả CẢ 19 lỗi, dùng cho prompt chấm.
#:
#: Phải có mô tả cho từng lỗi, kể cả những lỗi luật đã kiểm được: nếu chỉ đưa
#: tên snake_case tiếng Anh thì mô hình phải tự đoán nghĩa, và phép so
#: luật ↔ mô hình đo mất nghĩa. Đã xảy ra thật: với tên trần, `lost_sequence`
#: được mô hình gắn 0/25 câu trong khi luật gắn 9/25 (kappa = 0), còn
#: `unfocused_stem` thì hai bên gắn hai câu KHÁC nhau (kappa âm).
FLAW_DESCRIPTIONS: Dict[str, str] = {
    # --- luật kiểm được ---
    'none_of_the_above':
        'Có phương án dạng "không có đáp án nào đúng".',
    'all_of_the_above':
        'Có phương án dạng "tất cả các phương án trên đều đúng".',
    'longest_option_correct':
        'Đáp án đúng dài hơn hẳn các phương án sai vì được diễn giải chi tiết '
        'hơn — độ dài trở thành manh mối. Không tính chênh lệch do độ phức tạp '
        'của biểu thức toán.',
    'true_false_question':
        'Các phương án chỉ là chuỗi mệnh đề đúng/sai thay vì các lựa chọn nội '
        'dung khác nhau.',
    'complex_k_type':
        'Dạng K-type: đề đánh số các mệnh đề, phương án là tổ hợp của chúng '
        '("(1) và (3)", "Chỉ (2)").',
    'convergence_cues':
        'Các phương án là tổ hợp lặp của cùng vài thành phần, khiến học sinh '
        'loại trừ được bằng cách đếm tần suất thay vì hiểu bài.',
    'fill_in_blank':
        'Đề khoét trống GIỮA câu để học sinh điền từ phương án. Dấu ba chấm '
        'dẫn ở cuối đề KHÔNG tính.',
    'absolute_terms':
        'Phương án SAI chứa từ tuyệt đối ("luôn luôn", "không bao giờ"), mà '
        'học sinh biết những phương án như vậy hầu như luôn sai.',
    'vague_terms':
        'Phương án dùng từ chỉ mức độ mơ hồ ("thường", "đôi khi", "có thể") '
        'mà không ai thống nhất được nghĩa.',
    'word_repeats':
        'Từ khoá của đề được lặp lại CHỈ ở đáp án đúng, giúp chọn đúng mà '
        'không cần hiểu bài.',
    'lost_sequence':
        'Các phương án đều là số/đại lượng nhưng KHÔNG được xếp theo thứ tự '
        'tăng dần hoặc giảm dần, buộc học sinh phải dò thay vì làm toán.',
    'negative_worded':
        'Mệnh đề hỏi ở dạng phủ định ("phương án nào SAI", "... ngoại trừ").',
    'unfocused_stem':
        'Đề không nêu trọn một câu hỏi: phải nhìn các phương án mới biết đang '
        'được hỏi gì, hoặc đề chỉ dựng bối cảnh rồi dừng.',
    'more_than_one_correct':
        'Có nhiều hơn một phương án đúng, kể cả khi chúng khác mặt chữ nhưng '
        'tương đương về giá trị.',
    # --- cần phán đoán nội dung ---
}

# Các lỗi cần phán đoán nội dung — tầng LLM đảm nhiệm (xem scripts/qeval.py).
_LLM_ONLY = {
    'ambiguous_unclear_information':  # #1
        'Đề và các phương án phải diễn đạt rõ ràng, không mơ hồ.',
    'implausible_distractors':        # #2
        'Mọi phương án sai phải hợp lý với học sinh chưa nắm vững bài.',
    'gratuitous_information':         # #5
        'Đề không chứa thông tin thừa, không cần cho việc trả lời.',
    'logical_cues':                   # #8
        'Đề không chứa manh mối giúp đoán ra đáp án đúng mà không cần hiểu bài.',
    'grammatical_cues':               # #15
        'Mọi phương án phải nhất quán ngữ pháp với đề và song song về hình thức.',
}

_RULE_CHECKS: Dict[str, Callable[[Dict[str, Any]], bool]] = {
    'none_of_the_above':        _f_none_of_the_above,
    'all_of_the_above':         _f_all_of_the_above,
    'longest_option_correct':   _f_longest_option_correct,
    'true_false_question':      _f_true_false_question,
    'complex_k_type':           _f_complex_k_type,
    'convergence_cues':         _f_convergence_cues,
    'fill_in_blank':            _f_fill_in_blank,
    'absolute_terms':           _f_absolute_terms,
    'vague_terms':              _f_vague_terms,
    'word_repeats':             _f_word_repeats,
    'lost_sequence':            _f_lost_sequence,
    'negative_worded':          _f_negative_worded,
    'unfocused_stem':           _f_unfocused_stem,
    'more_than_one_correct':    _f_more_than_one_correct,
}

#: 19 lỗi của rubric = 14 kiểm bằng luật + 5 cần phán đoán nội dung.
RULE_FLAWS: Tuple[str, ...] = tuple(_RULE_CHECKS)
LLM_FLAWS: Tuple[str, ...] = tuple(_LLM_ONLY)
ALL_FLAWS: Tuple[str, ...] = RULE_FLAWS + LLM_FLAWS

#: Ngưỡng của rubric: 0–1 lỗi thì câu hỏi còn dùng được trên lớp.
ACCEPTABLE_MAX_FLAWS = 1


def rule_flaws(question: Dict[str, Any]) -> List[str]:
    """Danh sách lỗi mà LUẬT phát hiện được ở một câu hỏi."""
    found = []
    for name, fn in _RULE_CHECKS.items():
        try:
            if fn(question):
                found.append(name)
        except Exception:
            # Một luật hỏng không được làm hỏng cả phép đo; bỏ qua luật đó.
            continue
    return found


def is_acceptable(flaws: List[str]) -> bool:
    """Theo rubric: 0–1 lỗi = dùng được, từ 2 lỗi trở lên = không dùng được."""
    return len(flaws) <= ACCEPTABLE_MAX_FLAWS


def llm_flaw_definitions() -> Dict[str, str]:
    """Định nghĩa các lỗi cần phán đoán, để dựng prompt cho tầng LLM."""
    return dict(_LLM_ONLY)


def flaw_definitions() -> Dict[str, str]:
    """Định nghĩa CẢ 19 lỗi, theo đúng thứ tự của rubric."""
    merged = dict(FLAW_DESCRIPTIONS)
    merged.update(_LLM_ONLY)
    return {name: merged[name] for name in ALL_FLAWS}

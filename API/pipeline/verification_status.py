"""Trạng thái kiểm chứng + luật phân xử giữa các nguồn tính toán.

Trước đây tầng deterministic chỉ có MỘT nhãn ``verified ∈ {True, False, None}``.
Nhãn đó gộp hai việc rất khác nhau vào một chỗ:

* biểu thức kiểm chứng do Writer viết khớp với đáp án Writer chọn
  (chỉ là **nhất quán nội bộ** — cả hai đều do cùng một tác nhân khai ra), và
* đáp án đã được một nguồn tính toán **độc lập** xác nhận.

Nguồn 1 không loại được lỗi mô hình hoá sai-nhất-quán: nếu Writer hiểu sai đề
rồi viết cả lời giải lẫn biểu thức kiểm chứng theo cách hiểu sai đó, hai "nguồn"
cùng sai và verifier vẫn báo True. Module này tách nhãn thành 5 trạng thái để
người dùng (và bài báo) không đọc nhầm sự nhất quán thành sự đúng đắn.

    INDEPENDENTLY_VERIFIED  mục tiêu kiểm chứng độc lập xác nhận đáp án
    CONSISTENCY_CONFIRMED   biểu thức của Writer khớp đáp án, CHƯA có kiểm
                            chứng độc lập
    MISMATCH                các nguồn tính toán không thống nhất
    NON_VERIFIABLE          câu hỏi không thuộc dạng kiểm chứng được bằng máy
    REFUTED                 tính toán độc lập chứng minh key sai, hoặc có nhiều
                            hơn một phương án đúng

Luật phân xử nằm trong :func:`adjudicate`, thuần hàm và không gọi LLM — toàn bộ
bằng chứng được truyền vào dưới dạng tham số nên test hoá được từng nhánh.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Tăng khi luật phân xử hoặc engine kiểm chứng đổi hành vi — ghi vào run
# manifest để một run cũ luôn truy được đúng phiên bản verifier đã chấm nó.
VERIFIER_VERSION = '2.1.0'


class VerificationStatus:
    """Từ vựng trạng thái (str để serialize thẳng ra JSON/record)."""

    INDEPENDENTLY_VERIFIED = 'independently_verified'
    CONSISTENCY_CONFIRMED = 'consistency_confirmed'
    MISMATCH = 'mismatch'
    NON_VERIFIABLE = 'non_verifiable'
    REFUTED = 'refuted'

    ALL = (
        INDEPENDENTLY_VERIFIED,
        CONSISTENCY_CONFIRMED,
        MISMATCH,
        NON_VERIFIABLE,
        REFUTED,
    )

    #: Trạng thái được phép hiển thị kèm chữ "đã kiểm chứng bằng máy".
    MACHINE_CHECKED = (INDEPENDENTLY_VERIFIED, CONSISTENCY_CONFIRMED)

    #: Trạng thái bắt buộc phải qua mắt người trước khi dùng.
    NEEDS_HUMAN = (MISMATCH, REFUTED)


#: Nhãn hiển thị cho người dùng cuối. Không nhãn nào được dùng chữ "đúng"
#: (correct) trừ khi có nguồn độc lập — CONSISTENCY_CONFIRMED nói rõ đây chỉ là
#: sự nhất quán, còn NON_VERIFIABLE nói thẳng là máy không kiểm được.
STATUS_LABELS_VI: Dict[str, str] = {
    VerificationStatus.INDEPENDENTLY_VERIFIED:
        'Đã kiểm chứng độc lập bằng CAS',
    VerificationStatus.CONSISTENCY_CONFIRMED:
        'Nhất quán với biểu thức kiểm chứng (chưa có kiểm chứng độc lập)',
    VerificationStatus.MISMATCH:
        'Các nguồn tính toán lệch nhau — cần người kiểm',
    VerificationStatus.NON_VERIFIABLE:
        'Không kiểm chứng được bằng máy',
    VerificationStatus.REFUTED:
        'Tính toán độc lập bác bỏ đáp án — cần người kiểm',
}

STATUS_LABELS_EN: Dict[str, str] = {
    VerificationStatus.INDEPENDENTLY_VERIFIED: 'Independently verified (CAS)',
    VerificationStatus.CONSISTENCY_CONFIRMED:
        'Consistent with its verification expression (no independent check)',
    VerificationStatus.MISMATCH: 'Computation sources disagree — needs review',
    VerificationStatus.NON_VERIFIABLE: 'Not machine-checkable',
    VerificationStatus.REFUTED: 'Independent computation refutes the key',
}


@dataclass
class Adjudication:
    """Kết quả phân xử cho một câu hỏi."""

    status: str
    detail: str = ''
    #: Nguồn bằng chứng đã thực sự chạy, ví dụ ['writer_expression', 'independent'].
    sources: List[str] = field(default_factory=list)
    #: True khi trạng thái đòi người kiểm trước khi dùng.
    needs_human_review: bool = False
    #: True khi đủ bằng chứng độc lập để cho phép sửa key tự động.
    independent_support: bool = False
    #: True khi ít nhất một solver độc lập KHÔNG chạy được (lỗi hạ tầng).
    #: Trạng thái khi đó phản ánh bằng chứng còn lại, không phải bản chất câu
    #: hỏi — đếm riêng để không lẫn với "câu không kiểm chứng được".
    verification_incomplete: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'status': self.status,
            'detail': self.detail,
            'sources': list(self.sources),
            'needs_human_review': self.needs_human_review,
            'independent_support': self.independent_support,
            'verification_incomplete': self.verification_incomplete,
            'label_vi': STATUS_LABELS_VI.get(self.status, self.status),
            'label_en': STATUS_LABELS_EN.get(self.status, self.status),
        }


def adjudicate(
    *,
    writer_verified: Optional[bool],
    writer_engine: str = 'none',
    independent: Optional[Any] = None,
    keyed_value: Optional[float] = None,
    distractor_values: Optional[List[Optional[float]]] = None,
    multi_answer_options: Optional[List[str]] = None,
) -> Adjudication:
    """Phân xử giữa đáp án key, biểu thức của Writer và mục tiêu độc lập.

    Tham số:
        writer_verified: kết quả engine chạy trên ``verifier_hint`` do Writer
            viết (True/False/None). Đây là bằng chứng NHẤT QUÁN, không phải
            bằng chứng ĐÚNG.
        writer_engine: tên engine đã chạy; ``'none'`` nghĩa là câu hỏi không
            khai báo dạng kiểm chứng được.
        independent: :class:`~pipeline.independent_target.IndependentTarget`
            (hoặc None nếu cơ chế bị tắt/không dựng được).
        keyed_value: giá trị số của phương án được đánh dấu đúng.
        distractor_values: giá trị số của 3 phương án nhiễu (None nếu không
            đọc được) — dùng để nhận ra "đáp án đúng nằm ở phương án khác".
        multi_answer_options: text các phương án mà engine cũng xác nhận đúng.

    Luật (theo thứ tự ưu tiên):

    1. Có >1 phương án được xác nhận đúng  → REFUTED (nhiều đáp án đúng).
    2. Mục tiêu độc lập DỨT KHOÁT, CÓ SUY DẪN và khớp key →
       INDEPENDENTLY_VERIFIED. Nếu khớp nhưng biểu thức chỉ là hằng số trần
       (không phép tính nào được máy kiểm) thì chỉ là hai model cùng khẳng định
       một số — rơi về CONSISTENCY_CONFIRMED chứ không được gọi là xác nhận
       độc lập.
    3. Mục tiêu độc lập DỨT KHOÁT và lệch key:
       a. trùng đúng một phương án nhiễu → REFUTED (key sai, đáp án đúng nằm
          trong danh sách);
       b. biểu thức của Writer CŨNG báo sai → REFUTED (cả hai nguồn cùng bác);
       c. còn lại → MISMATCH (hai nguồn chọi nhau, chưa đủ kết luận).
    4. Không có mục tiêu độc lập dứt khoát:
       writer True → CONSISTENCY_CONFIRMED, writer False → MISMATCH,
       writer None/none → NON_VERIFIABLE.

    Với HỘI ĐỒNG nhiều solver (``independent.definite_values`` có giá trị của
    từng thành viên), luật xác nhận và luật gắn cờ cố ý không đối xứng:

    * xác nhận (luật 2) còn đòi KHÔNG thành viên dứt khoát nào lệch key;
    * gắn cờ chỉ cần MỘT thành viên dứt khoát lệch key — kể cả khi hội đồng
      không đạt đồng thuận, câu vẫn thành MISMATCH thay vì rơi về luật 4.

    Lý do: nhãn "đã kiểm chứng độc lập" là lời hứa với người dùng, còn một cờ
    thừa chỉ tốn một lượt duyệt tay.

    ``verification_incomplete`` bật khi có solver không chạy được; trạng thái
    giữ nguyên theo bằng chứng còn lại.
    """
    adj = _adjudicate(
        writer_verified=writer_verified,
        writer_engine=writer_engine,
        independent=independent,
        keyed_value=keyed_value,
        distractor_values=distractor_values,
        multi_answer_options=multi_answer_options,
    )
    if independent is not None and (
            getattr(independent, 'incomplete', False)
            or getattr(independent, 'source', '') == 'error'):
        adj.verification_incomplete = True
    return adj


def _dissenting(values: List[Any], keyed_value: Optional[float]) -> List[float]:
    """Giá trị dứt khoát của các thành viên KHÔNG khớp key."""
    if keyed_value is None:
        return []
    out: List[float] = []
    for value in values or []:
        if value is None:
            continue
        if not _values_agree(value, keyed_value):
            out.append(float(value))
    return out


def _adjudicate(
    *,
    writer_verified: Optional[bool],
    writer_engine: str,
    independent: Optional[Any],
    keyed_value: Optional[float],
    distractor_values: Optional[List[Optional[float]]],
    multi_answer_options: Optional[List[str]],
) -> Adjudication:
    sources: List[str] = []
    if writer_engine and writer_engine != 'none' and writer_verified is not None:
        sources.append('writer_expression')

    independent_definite = bool(getattr(independent, 'definite', False))
    independent_value = getattr(independent, 'value', None)
    if independent is not None and getattr(independent, 'attempted', False):
        sources.append('independent_target')
    dissent = _dissenting(
        list(getattr(independent, 'definite_values', None) or []), keyed_value)

    # --- 1. Nhiều đáp án đúng ---
    if multi_answer_options:
        return Adjudication(
            status=VerificationStatus.REFUTED,
            detail=(
                'nhiều phương án cùng được xác nhận đúng: '
                + '; '.join(str(o)[:40] for o in multi_answer_options[:3])
            ),
            sources=sources,
            needs_human_review=True,
        )

    # --- 2/3. Có mục tiêu độc lập dứt khoát ---
    independent_derivation = bool(getattr(independent, 'derivation', False))
    if independent_definite and independent_value is not None:
        if keyed_value is not None and _values_agree(independent_value, keyed_value):
            if not independent_derivation:
                # Hai model cùng nói một số, nhưng không phép tính nào được máy
                # kiểm. Đồng ý thì có, "kiểm chứng độc lập" thì chưa.
                return _fallback_without_independent(
                    writer_verified, writer_engine, sources,
                    extra=('nguồn độc lập cũng cho '
                           f'{_fmt(independent_value)} nhưng chỉ khẳng định một '
                           'hằng số, không suy dẫn'),
                )
            # Một phương án nhiễu cũng bằng đúng giá trị đó ⇒ đề có hai đáp án.
            for value in distractor_values or []:
                if value is not None and _values_agree(value, independent_value):
                    return Adjudication(
                        status=VerificationStatus.REFUTED,
                        detail=(
                            f'phương án nhiễu trùng giá trị đáp án '
                            f'({_fmt(value)}) — đề có nhiều đáp án đúng'
                        ),
                        sources=sources,
                        needs_human_review=True,
                    )
            if dissent:
                # Đủ đồng thuận theo luật k-trên-n, nhưng vẫn có thành viên dứt
                # khoát ra giá trị khác: không đủ để hứa "đã kiểm chứng".
                return Adjudication(
                    status=VerificationStatus.MISMATCH,
                    detail=(
                        f'hội đồng đa số cho {_fmt(independent_value)} khớp key '
                        f'nhưng có solver cho '
                        + ', '.join(_fmt(v) for v in dissent[:3])
                    ),
                    sources=sources,
                    needs_human_review=True,
                )
            return Adjudication(
                status=VerificationStatus.INDEPENDENTLY_VERIFIED,
                detail=(
                    f'mục tiêu độc lập cho {_fmt(independent_value)}, '
                    f'khớp đáp án key'
                ),
                sources=sources,
                independent_support=True,
            )

        if keyed_value is None:
            # Không đọc được giá trị key (đáp án dạng chữ/mệnh đề) nên không
            # đối chiếu số học được, dù mục tiêu độc lập có giá trị.
            return _fallback_without_independent(
                writer_verified, writer_engine, sources,
                extra='không đọc được giá trị số của đáp án key',
            )

        for index, value in enumerate(distractor_values or []):
            if value is not None and _values_agree(value, independent_value):
                return Adjudication(
                    status=VerificationStatus.REFUTED,
                    detail=(
                        f'tính toán độc lập cho {_fmt(independent_value)}, '
                        f'trùng phương án nhiễu #{index + 1} chứ không phải key '
                        f'({_fmt(keyed_value)})'
                    ),
                    sources=sources,
                    needs_human_review=True,
                    independent_support=True,
                )

        if writer_verified is False:
            return Adjudication(
                status=VerificationStatus.REFUTED,
                detail=(
                    f'cả biểu thức của Writer lẫn tính toán độc lập '
                    f'({_fmt(independent_value)}) đều không khớp đáp án key '
                    f'({_fmt(keyed_value)})'
                ),
                sources=sources,
                needs_human_review=True,
                independent_support=True,
            )

        return Adjudication(
            status=VerificationStatus.MISMATCH,
            detail=(
                f'biểu thức của Writer khớp key ({_fmt(keyed_value)}) nhưng '
                f'tính toán độc lập cho {_fmt(independent_value)}'
            ),
            sources=sources,
            needs_human_review=True,
        )

    # --- 4. Không có bằng chứng độc lập dứt khoát ---
    if dissent:
        # Hội đồng không đồng thuận nhưng ít nhất một solver giải ra giá trị
        # khác key — đúng loại tín hiệu mà lỗi sai-nhất-quán để lại.
        return Adjudication(
            status=VerificationStatus.MISMATCH,
            detail=(
                f'hội đồng chưa đồng thuận; solver cho '
                + ', '.join(_fmt(v) for v in dissent[:3])
                + f' trong khi key là {_fmt(keyed_value)}'
            ),
            sources=sources,
            needs_human_review=True,
        )
    extra = ''
    if independent is not None and getattr(independent, 'attempted', False):
        extra = str(getattr(independent, 'detail', '') or '')[:120]
    return _fallback_without_independent(
        writer_verified, writer_engine, sources, extra=extra,
    )


def _fallback_without_independent(
    writer_verified: Optional[bool],
    writer_engine: str,
    sources: List[str],
    extra: str = '',
) -> Adjudication:
    suffix = f' ({extra})' if extra else ''
    if writer_engine in ('', 'none') or writer_verified is None:
        return Adjudication(
            status=VerificationStatus.NON_VERIFIABLE,
            detail=f'không có engine kiểm chứng chạy được cho câu này{suffix}',
            sources=sources,
        )
    if writer_verified is True:
        return Adjudication(
            status=VerificationStatus.CONSISTENCY_CONFIRMED,
            detail=(
                f'biểu thức kiểm chứng của Writer khớp đáp án key; chưa có '
                f'nguồn độc lập{suffix}'
            ),
            sources=sources,
        )
    return Adjudication(
        status=VerificationStatus.MISMATCH,
        detail=f'biểu thức kiểm chứng của Writer không khớp đáp án key{suffix}',
        sources=sources,
        needs_human_review=True,
    )


def review_status_for(status: str) -> str:
    """Map trạng thái kiểm chứng → review_status của record."""
    if status in VerificationStatus.NEEDS_HUMAN:
        return 'needs_revision'
    return 'pending_review'


def is_machine_checked(status: str) -> bool:
    """True chỉ khi được phép nói với người dùng là máy đã kiểm."""
    return status in VerificationStatus.MACHINE_CHECKED


def _values_agree(a: Any, b: Any, rel_tol: float = 1e-4, abs_tol: float = 1e-6) -> bool:
    try:
        af = float(a)
        bf = float(b)
    except (TypeError, ValueError):
        return False
    return abs(af - bf) <= max(abs_tol, abs(bf) * rel_tol)


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f'{number:.6g}'

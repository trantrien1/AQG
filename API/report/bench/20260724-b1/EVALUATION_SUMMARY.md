# Evaluation — số liệu thật (run SAU khi fix verifier)

*Chạy 2026-07-24. gpt-4o (generator) + gpt-4o-mini (judge) qua chat2api.
4 tài liệu Toán 12 (giải tích/tích phân/tròn xoay), mỗi tài liệu yêu cầu 10 câu.
Toàn bộ số dưới đây là đo thật, KHÔNG mô phỏng. Tầng verifier là SymPy.*

Run này chạy với verifier ĐÃ SỬA (Fix A: parser `\sqrt`/`\frac` lồng; Fix B:
numeric_eval so expr với đáp án key thay vì con số writer tự khai). So sánh với
run trước (`20260723-b1`) ở cuối file.

Thư mục dữ liệu: `report/bench/20260724-b1/`.

---

## 1. System benchmark (pipeline 5-agent) — B1

| Metric | Giá trị (20260724) | (20260723 trước fix) |
|---|---|---|
| Tài liệu × yêu cầu | 4 × 10 = 40 | 40 |
| Câu chấp nhận | **37** (10/10/7/10) | 34 |
| Ứng viên sinh ra | 65 | 57 |
| Acceptance rate | 56.9% | 59.7% |
| Verified=True | **34** | 22 |
| Verified=False (giữ, routed review) | **1** | 7 |
| Non-checkable (type=none) | 2 | 5 |
| Chi phí | 611.6k tokens / 187 calls | 663k / 149 |
| Thời gian | 1494.8s (**40.4s/câu**) | 42.8s/câu |

**Phân bố reject theo gate** (28 ca):

| Gate:reason | Số ca |
|---|---|
| writer (không sinh được ứng viên hợp lệ)* | 17 |
| distractor_validator | 6 |
| verifier: rule_validator (item-writing/quote) | 3 |
| verifier: answer_text_mismatch | 1 |
| dedup | 1 |

*Phần lớn writer-drop là lỗi PARSE JSON của output LLM (backslash LaTeX chưa
escape → "Invalid \escape"), không phải loại vì chất lượng câu. Đây là điểm yếu
robustness khâu parse, đã đẩy acceptance-rate xuống dù bộ câu ACCEPTED sạch hơn
run trước (34 verified vs 22).

→ 34/37 câu accepted machine-checkable & verified; chỉ 1 câu verified=False (bị
bắt đúng, xem mục 4); 2 câu Nhận biết type=none (đúng, không cần verifier).

---

## 2. Baseline single-prompt (LLM-only) — B2

Cùng model (gpt-4o), cùng tài liệu, MỘT lời gọi/PDF sinh trọn bộ; cùng schema +
yêu cầu. KHÔNG có: tách 2 giai đoạn, catalogue misconception, retry mỗi slot,
thang ép độ khó, CĐR. Chấm bằng ĐÚNG tầng deterministic (VerifierAgent đã fix).

| Metric | Baseline (B2) | Pipeline (B1) |
|---|---|---|
| Sinh được / 40 yêu cầu | **34** (10/10/10/4) | 37 |
| Qua toàn bộ gate cứng | 24/34 (**70.6%**) | — |
| Verified=True (machine-checkable) | 17/34 (**50%**) | 34/37 (**92%**) |
| Verified=False | 0 | 1 |
| Chi phí | 27.8k tok / 4 calls (~0.82k/câu) | ~16.5k/câu |
| Rớt gate | quality_low 4, explanation_low 2, duplicate 4 | — |

**Confound BẮT BUỘC ghi trong paper:** baseline KHÔNG có thang ép độ khó (cơ chế
riêng của pipeline) nên sinh câu DỄ hơn → LLM tính đúng nhiều hơn, ít mismatch
hơn. KHÔNG được kết luận baseline "đúng hơn". Kết luận trung thực: pipeline giao
bộ câu đầy đủ hơn (37 vs 34, file_4 baseline chỉ 4/10) và machine-checkable cao
hơn nhiều (92% vs 50%) ở độ khó có kiểm soát, với cái giá ~20× token/câu.

---

## 3. Phân tích mismatch — kiểm ĐỘC LẬP bằng SymPy

Run này chỉ có **2 ca verifier mismatch**, cả hai đều là **lỗi thật, bắt đúng**;
KHÔNG còn ca π-form flag oan (Fix B đã xử), KHÔNG có ca √ reject oan (Fix A):

| Nhóm | Số ca | Chi tiết |
|---|---|---|
| **Lỗi LLM thật, verifier BẮT** | **2** | (a) quãng đường key=16/3, đúng **28/3** (không có trong 4 đáp án) → verified=False; (b) nhiệt độ TB key=26, đúng **35** → answer_text_mismatch reject |
| **Đáp án ĐÚNG được Fix B khôi phục verified=True** | **3** | 284π/3, 774π/5, 252π/5 — SymPy xác nhận ĐÚNG; run trước sẽ bị flag oan verified=False |
| Đáp án đúng bị REJECT oan | **0** | Fix A xử lý (√ lồng) |
| π-form flag oan giữ lại | **0** | Fix B xử lý |

→ Fix A + Fix B loại sạch lớp "flag oan/reject oan câu đúng" của run trước
(6 π-form + 1 √). Cả 2 mismatch còn lại đều là lỗi đáp án thật verifier bắt được.

---

## 4. Automatic quality evaluation — LLM-judge chéo họ (Claude), audit SymPy

Judge = Claude Opus 4.8, **khác họ** generator (GPT-4o) lẫn Critic (GPT-4o-mini).
Chấm 37 câu accepted theo 4 tiêu chí; **MỖI đáp án kiểm ĐỘC LẬP bằng SymPy**
(script `audit_all37.py` giải lại từ dữ kiện đề, không tin expr của writer).
1 rater, automatic evaluation — KHÔNG phải human study. Dữ liệu: `judge_scorecard.json`.

| Tiêu chí | Đạt | Tỷ lệ | (run trước) |
|---|---|---|---|
| a) đáp án đúng & là phương án duy nhất | 35/37 | **94.6%** | 91.2% |
| b) bám nội dung tài liệu | 37/37 | 100% | 100% |
| c) không tầm thường | 31/37 | 83.8% | 79.4% |
| d) kiểm tra hiểu | 34/37 | 91.9% | 85.3% |
| Đạt CẢ 4 | 29/37 | 78.4% | 70.6% |

### 4.1. KẾT QUẢ THEN CHỐT: KHÔNG còn blind-spot trong run này

Audit SymPy độc lập cả 37 câu: **36/37 key ĐÚNG**; 1 câu sai key (#5, quãng đường
16/3 — đúng 28/3) đã bị **verifier BẮT** (verified=False). **KHÔNG có câu sai nào
lọt verified=True** (run trước có 2: Q2, Q31).

Lưu ý trung thực: đây KHÔNG phải vì Fix A/B sửa blind-spot. Fix A/B chỉ xử lý
false-positive (flag oan câu đúng). Cơ chế blind-spot (writer tự viết cả lời giải
lẫn expr → sai nhất quán thì lọt) VẪN còn về mặt thiết kế; run này ngẫu nhiên
không kích hoạt vì các expr writer viết đều trung thực với đề.

### 4.2. Hạn chế MỚI phát hiện: verifier bỏ sót đáp án KHÔNG DUY NHẤT (#36)

Câu #36 hỏi tìm tham số `a` sao cho thể tích tròn xoay = 1944π/5, parabol qua
A(3,6), đỉnh trên Oy. Key **a=-1/3 ĐÚNG**, nhưng **a=2 (option D) CŨNG thỏa** mọi
điều kiện (SymPy: cả -1/3 và 2 là nghiệm) → câu có 2 đáp án đúng. Verifier
multi-answer check bỏ sót vì hint `numeric_eval` chỉ tính MỘT nghiệm (-1/3) rồi
so từng distractor với nó, không phát hiện distractor 2 cũng là nghiệm hợp lệ.
Đây là giới hạn thật của kiểm chứng bằng numeric_eval khi bài có nhiều nghiệm.

---

## 5. So sánh 2 run (trước/sau fix)

| | 20260723 (trước) | 20260724 (sau A+B) |
|---|---|---|
| Accepted | 34/40 | 37/40 |
| Verified=True | 22 | 34 |
| Verified=False (review) | 7 | 1 |
| π-form flag oan (câu đúng) | 6 | **0** |
| √ reject oan (câu đúng) | 1 | **0** |
| Sai key LỌT verified=True (blind-spot) | **2** (Q2,Q31) | **0** |
| Sai key BẮT được | 1 | 2 |
| LLM-judge đạt cả 4 | 70.6% | 78.4% |

---

## 6. Điều vẫn CHƯA có (không bịa)

- **Human study thật**: chưa làm. LLM-judge (Claude) là automatic evaluation
  hợp lệ nhưng KHÔNG thay human study.
- **Blind-spot (false-negative)**: chưa sửa (nằm ngoài phạm vi A+B). Run này 0 ca
  nhưng cơ chế còn; cần verification target lấy từ ngoài (Fix C đề xuất).
- **#36 non-uniqueness**: verifier chưa phát hiện nghiệm thứ 2 hợp lệ.
- **Calibrate threshold** trên dữ liệu người dán nhãn: chưa làm.

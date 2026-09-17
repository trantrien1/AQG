# Evaluation — số liệu thật cho paper

*Chạy 2026-07-23/24. gpt-4o (generator) + gpt-4o-mini (judge) qua chat2api.
4 tài liệu Toán 12 (giải tích/tích phân), mỗi tài liệu yêu cầu 10 câu.
Toàn bộ số dưới đây là đo thật, KHÔNG mô phỏng. Tầng verifier là SymPy,
không gọi LLM.*

Thư mục dữ liệu gốc: `report/bench/20260723-b1/` (mỗi PDF một `b1_*.json` +
`b2_*.json`, log, `b1_summary.json`, `mismatch_review.md`).

---

## 1. System benchmark (pipeline 5-agent) — B1

| Metric | Giá trị |
|---|---|
| Tài liệu × yêu cầu | 4 × 10 = 40 |
| Câu chấp nhận | **34** (file_1: 4, file_2–4: 10 mỗi file) |
| Ứng viên sinh ra | 57 |
| Acceptance rate | **59.7%** |
| Verified=True | 22 |
| Verified=False (giữ lại, routed to human) | 7 |
| Non-checkable (type=none) | 5 |
| Answer-key repair tự động | 1 |
| Chi phí | 663.3k tokens / 149 calls |
| Thời gian | 1454s (**42.8s/câu**, 3 luồng song song) |

**Phân bố reject theo gate** (reason-coded, đúng như thiết kế mục Logging):

| Gate:reason | Số ca |
|---|---|
| writer (không sinh được ứng viên) | 7 |
| verifier: answer_text_mismatch | 5 |
| critic: error_distractor_consistency | 4 |
| critic: answer_uniqueness | 3 |
| verifier: rule_validator | 2 |
| dedup | 1 |
| orchestrator (lỗi hệ thống) | 1 |

→ 85% câu chấp nhận là machine-checkable; mọi câu còn nghi ngờ (7 câu
verified=False) đều được đẩy sang `needs_revision` chứ không âm thầm loại.

---

## 2. Baseline single-prompt (LLM-only) — B2

Cùng model, cùng tài liệu, MỘT lời gọi sinh trọn bộ; cùng schema output +
cùng yêu cầu (số bước theo Bloom, dạng đóng, verifier payload, source_quote).
KHÔNG có: tách 2 giai đoạn, catalogue misconception, retry mỗi slot, thang ép
độ khó, CĐR. Sau đó đưa qua ĐÚNG tầng deterministic của pipeline để đo.

| Metric | Giá trị |
|---|---|
| Câu sinh được (trên 40 yêu cầu) | **22** (file_1:5, file_2:5, file_3:2, file_4:10) |
| Qua toàn bộ gate cứng | 16 / 22 (**72.7%**) |
| Verified=True / False / none | 14 / 0 / 8 |
| Bị bắt answer_text_mismatch | 1 |
| Rớt quality_low (câu tầm thường) | 3 |
| Rớt format / distractor | 2 |
| Chi phí | 22.9k tokens / 4 calls / 98s |

---

## 3. So sánh — ĐỌC KỸ, có confound phải nói thẳng trong paper

| Chiều | Pipeline (B1) | Baseline (B2) |
|---|---|---|
| Giao đủ số câu yêu cầu | 34/40 (85%) | **22/40 (55%)** — 1 call hay sinh thiếu |
| Machine-checkable | 85% (29/34) | 64% (14/22) |
| Token / câu chấp nhận | ~19.5k | ~1.0k |
| Độ khó câu sinh | cao (ép tham số/bài ngược/tích phân nặng) | thấp hơn (số gọn, ít bước) |

**Confound BẮT BUỘC ghi trong paper (không được lờ đi):**
Baseline có tỷ lệ "sạch" cao một phần vì nó sinh câu DỄ hơn (thang ép độ khó là
cơ chế của pipeline, không cấp cho baseline). Câu dễ thì LLM tính đúng nhiều hơn
→ ít mismatch hơn. Vì vậy KHÔNG được kết luận "pipeline bắt 5 lỗi, baseline chỉ 1
nên pipeline đúng hơn": pipeline TẠO ra câu khó hơn nên có nhiều lỗi hơn để bắt.

**Khác biệt trung thực rút ra được:**
1. Verifier bắt được lỗi đáp án THẬT mà LLM-only sẽ giao thẳng cho người dùng
   (mục 4: 4 ca lỗi thật trong lô này).
2. Pipeline giao bộ câu ĐẦY ĐỦ, machine-checkable, có kiểm soát độ khó; baseline
   sinh thiếu (có tài liệu chỉ 2/10) và ít cam kết biểu thức kiểm chứng hơn.
3. Cái giá: pipeline đắt hơn ~19× token/câu (đính nguyên PDF vào mọi call ×
   nhiều lần retry × 5 agent) — đúng đánh đổi paper đã tự nêu, giờ có số.

---

## 4. Phân tích mismatch — kiểm ĐỘC LẬP bằng SymPy (không bịa, tự giải)

12 ca verifier gắn cờ (5 hard-reject answer_text_mismatch + 7 mismatch-kept)
được giải lại độc lập bằng SymPy. Script: `scripts/../verify_mismatch_cases`
(tác giả chạy lại kiểm chứng được từng ca).

| Nhóm | Số ca | Ý nghĩa |
|---|---|---|
| **Lỗi LLM thật, verifier bắt đúng** | **4** | 1276 (đúng 896.74); avg 29 (đúng 56.67, không có trong 4 đáp án); V=324 (đúng 270); m=2 (đúng m=−1) |
| **Đáp án đúng, mismatch-kept do dạng π** | 6 | mọi câu thể tích tròn xoay dạng \(k\pi/5\); expr tính ra số khớp — chính sách "giữ lại + duyệt tay" ĐÚNG |
| **Đáp án đúng bị REJECT oan** | 1 | \((\sqrt{229}-3)/2\): verifier không parse √ lồng trong \frac → loại nhầm câu đúng |
| **Làm tròn / ranh giới** | 1 | đáp án 21 vs giá trị đúng \(20\sqrt{10}/3\approx21.08\) |

**Kết luận trung thực (thay cho con số "1/12" cũ chỉ là quan sát dev):**
- Chính sách "mismatch does not imply wrong" được thực nghiệm ủng hộ mạnh:
  6/7 ca mismatch-KEPT là đáp án ĐÚNG (dạng π) — hard-reject sẽ giết oan câu đúng.
- Nhưng có lỗi hệ thống: verifier trích số từ đáp án dạng π / căn lồng còn yếu,
  gây 1 reject oan + 6 flag oan. Đây là HẠN CHẾ cần ghi (và dễ sửa: so khớp
  ở dạng ký hiệu thay vì ép về số).
- Tỷ lệ lỗi-thật trên tổng số ca gắn cờ trong lô này ≈ 4/12, cao hơn "1/12" —
  nhưng mẫu nhỏ (n=12) và lệch về tài liệu giải tích nặng π. KHÔNG nên tuyên bố
  xác nhận/bác bỏ 1/12; chỉ báo cáo đúng cái đo được.

---

## 5. Automatic quality evaluation — LLM-judge chéo họ (ĐÃ LÀM, thật)

Judge = Claude Opus 4.8 (Anthropic), **khác họ** cả generator (GPT-4o) lẫn
Critic nội bộ (GPT-4o-mini). Chấm 34 câu accepted theo 4 tiêu chí của
`Human-Evaluation-Details.md`. Mỗi câu đọc thủ công; tính đúng đáp án kiểm bằng
SymPy độc lập. 1 rater, **automatic evaluation — KHÔNG phải human study**.
Dữ liệu: `judge_scorecard.json`.

| Tiêu chí | Đạt | Tỷ lệ |
|---|---|---|
| a) đáp án đúng & là phương án duy nhất đúng | 31/34 | **91.2%** |
| b) bám nội dung tài liệu | 34/34 | 100% |
| c) không tầm thường | 27/34 | 79.4% |
| d) kiểm tra hiểu (không nhớ máy móc) | 29/34 | 85.3% |
| Đạt CẢ 4 | 24/34 | 70.6% |

- 7 câu rớt c)/d) hầu hết là câu **Nhận biết** (recall công thức/định nghĩa) —
  đúng theo thiết kế (30% Nhận biết trong phân bố), không phải lỗi.
- b) 100% nhưng ~3 câu (Q16, Q29, Q19) có source_quote khớp lỏng (đúng khái niệm,
  sai số cụ thể) — do relaxation grounding cho phép câu mới cùng phương pháp.

### 5.1. PHÁT HIỆN QUAN TRỌNG: verifier LỌT 2 câu sai đáp án

3 câu sai đáp án thật (đúng đáp án không nằm trong 4 phương án), xác nhận bằng SymPy:

| Câu | Đáp án công bố | Đáp án đúng (SymPy) | Verifier |
|---|---|---|---|
| Q2 (quãng đường) | 14 | **12** | `verified=True` — **LỌT** |
| Q31 (khối tròn xoay) | 864π/5 | **1296π/5** | `verified=True` — **LỌT** |
| Q10 (nhiệt độ TB) | 29 | **56.67** | `verified=False` — BẮT (needs_revision) |

**Nguyên nhân gốc (phải ghi vào paper như một giới hạn):** verifier chỉ kiểm
"biểu thức kiểm chứng có KHỚP đáp án công bố không", KHÔNG kiểm "biểu thức có mô
hình ĐÚNG bài toán không". Writer (LLM) tự viết cả lời giải LẪN biểu thức kiểm
chứng, nên khi nó tính sai một cách nhất quán (Q2: lấy nguyên hàm \(-3t\to -t^2\)
thay vì \(-\tfrac32 t^2\)), cả hai "nguồn" cùng sai giống nhau và không có bất
đồng để phát hiện. "Hai nguồn độc lập" mà paper tuyên bố thực chất KHÔNG hoàn
toàn độc lập. → tỷ lệ sai lọt lưới trong 27 câu clean (pending_review) là
2/27 ≈ **7.4%**.

Đây là kết quả trung thực, KHÔNG bị làm đẹp; nó vừa là điểm yếu chất lượng vừa là
một đóng góp khoa học (giới hạn thật của kiểm chứng bằng biểu thức do LLM tự khai).

## 6. Điều vẫn CHƯA có (không bịa)

- **Human study thật** (người chấm): chưa làm. Automatic judge ở trên là bản
  thay thế hợp lệ nhưng KHÔNG thay được human study cho full paper mạnh nhất.
- **Calibrate threshold** (0.4/0.5/0.4, dedup 0.85/0.82) trên dữ liệu người dán
  nhãn: chưa làm.
- **Correlation giữa điểm Critic (GPT-4o-mini) và điểm judge/người**: có thể tính
  thêm từ scorecard nếu muốn, nhưng 1 rater nên yếu.

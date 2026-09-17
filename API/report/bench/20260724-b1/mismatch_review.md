# Hồ sơ duyệt tay các ca verifier (B1)

Mỗi ca dưới đây cần tác giả tự kiểm tra lại bằng tay và tick phân loại.
Con số đưa vào paper là kết quả TICK TAY, không phải con số tự động.

### [MISMATCH-KEPT] file_1_trang_1-31.pdf — q_2026_1a08c25c

- **Stem**: Một xe tải bắt đầu tăng tốc tại thời điểm \(t=0\) với vận tốc ban đầu \(12\,\text{m/s}\). Gia tốc của xe phụ thuộc thời gian theo công thức \(a(t)=4t-10\,(\text{m/s}^2)\). Biết xe chuyển động theo một đường thẳng và chỉ xét quãng đường xe đi được trước thời điểm vận tốc trở lại bằng \(0\). Quãng đường xe đi được trong khoảng thời gian đó bằng bao nhiêu?
- **Answer key**: C | options: A: \(\frac{29}{3}\,\text{m}\) | B: \(\frac{125}{3}\,\text{m}\) | C: \(\frac{16}{3}\,\text{m}\) | D: \(\frac{55}{6}\,\text{m}\)
- **Verifier detail**: `expr = 9.333333333333334`
- **Phân loại của người duyệt (điền tay)**: [ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác

### [REJECTED] file_2_trang_31-61.pdf — stage=verifier

- **Reason**: verifier=False (answer_text_mismatch: \(26^{\circ}C\) vs 30.5)
- **Stem**: Nhiệt độ \(T(t)\) (đơn vị: \(^{\circ}C\)) tại một địa phương trong khoảng thời gian từ 6 giờ sáng đến 12 giờ trưa được mô hình hóa bởi một hàm số có đạo hàm \(T'(t)=3-\frac{t}{6}\), trong đó \(t\) tính theo giờ kể từ 0 giờ. Biết rằng lúc 6 giờ sáng nhiệt độ là \(30^{\circ}C\). Hãy tính nhiệt độ trung bình của địa phương đó trong khoảng thời gian từ 6 giờ đến 12 giờ.
- **Phân loại của người duyệt (điền tay)**: [ ] loại đúng  [ ] loại oan

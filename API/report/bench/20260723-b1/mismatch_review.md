# Hồ sơ duyệt tay các ca verifier (B1)

Mỗi ca dưới đây cần tác giả tự kiểm tra lại bằng tay và tick phân loại.
Con số đưa vào paper là kết quả TICK TAY, không phải con số tự động.

### [REJECTED] file_1_trang_1-31.pdf — stage=verifier

- **Reason**: verifier=False (answer_text_mismatch: \(\frac{\sqrt{229}-3}{2}\) phút vs 6.066372975210778)
- **Stem**: Một bể chứa ban đầu không có nước. Trong quá trình bơm, tốc độ thay đổi thể tích nước trong bể tại thời điểm \(t\) phút được mô tả bởi \(V'(t)=2t+3\) (lít/phút). Hỏi sau bao nhiêu phút thì thể tích nước trong bể đạt \(55\) lít?
- **Phân loại của người duyệt (điền tay)**: [ ] loại đúng  [ ] loại oan

### [REJECTED] file_1_trang_1-31.pdf — stage=verifier

- **Reason**: verifier=False (answer_text_mismatch: \(1276\) vs 896.7407407407408)
- **Stem**: Một bể chứa nước được bơm trong \(8\) giây. Gọi \(V(t)\) là thể tích nước trong bể sau \(t\) giây (đơn vị: m³). Tốc độ thay đổi thể tích nước được cho bởi \(V'(t)=at^2+6t+5\), trong đó \(a\) là hằng số. Biết lúc đầu bể có \(20\) m³ nước và sau \(3\) giây có \(96\) m³ nước. Tính thể tích nước trong bể sau \(8\) giây.
- **Phân loại của người duyệt (điền tay)**: [ ] loại đúng  [ ] loại oan

### [KEY-REPAIRED] file_2_trang_31-61.pdf — q_2026_470c1b88

- **Stem**: Tại một nhà máy, gọi \(C(x)\) là tổng chi phí (triệu đồng) để sản xuất \(x\) tấn sản phẩm trong một tháng. Biết chi phí cận biên được mô hình hóa bởi \(C'(x)=-\frac{x^2}{1000}+\frac{x}{10}+a\) với \(0\le x\le 100\). Biết rằng tại mức sản xuất \(20\) tấn thì chi phí cận biên là \(6\) triệu đồng/tấn và chi phí cố định là \(C(0)=50\) triệu đồng.
- **Answer key**: B | options: A: \(408\) triệu đồng | B: \(422\) triệu đồng | C: \(458\) triệu đồng | D: \(372\) triệu đồng
- **Verifier detail**: `expr = 422.0`
- **Phân loại của người duyệt (điền tay)**: [ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác

### [MISMATCH-KEPT] file_2_trang_31-61.pdf — q_2026_1e7b754a

- **Stem**: Trong một thí nghiệm truyền nhiệt, nhiệt độ của một bình tại thời điểm \(t\) giờ được ký hiệu là \(T(t)\). Tốc độ thay đổi nhiệt độ của bình được mô hình hóa bởi \(T'(t)=3t^2+at+5\) (độ C/giờ), với \(0\le t\le 4\). Biết nhiệt độ ban đầu của bình là \(T(0)=20\) độ C và sau 2 giờ nhiệt độ đạt \(46\) độ C. Hãy tính nhiệt độ trung bình của bình trong khoảng thời gian từ 0 đến 4 giờ.
- **Answer key**: C | options: A: \(24,67\) | B: \(98\) | C: \(29\) | D: \(34,67\)
- **Verifier detail**: `expr = 56.666666666666664`
- **Phân loại của người duyệt (điền tay)**: [ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác

### [REJECTED] file_2_trang_31-61.pdf — stage=verifier

- **Reason**: verifier=False (answer_text_mismatch: \(21\) vs 21.081851067789195)
- **Stem**: Một nhà kính có mặt cắt ngang là phần hình phẳng giới hạn bởi trục hoành và một mái vòm parabol. Chọn hệ trục tọa độ sao cho mái vòm có phương trình dạng \(y=ax^2+5\). Biết mái vòm đi qua điểm có tọa độ \((2;3)\). Tính diện tích mặt cắt ngang của nhà kính (đơn vị: \(m^2\)).
- **Phân loại của người duyệt (điền tay)**: [ ] loại đúng  [ ] loại oan

### [REJECTED] file_2_trang_31-61.pdf — stage=verifier

- **Reason**: verifier=False (answer_text_mismatch: \(324m^3\) vs 270.0)
- **Stem**: Một bể chứa nước ban đầu không có nước. Tốc độ thay đổi thể tích nước trong bể tại thời điểm \(t\) phút được mô hình hóa bởi \(V'(t)=3t^2+at+b\) \((m^3/phút)\), trong đó \(a,b\) là các hằng số. Biết sau 2 phút bể có \(14m^3\) nước và sau 4 phút bể có \(88m^3\) nước. Hỏi sau 6 phút kể từ lúc bắt đầu bơm, thể tích nước trong bể là bao nhiêu?
- **Phân loại của người duyệt (điền tay)**: [ ] loại đúng  [ ] loại oan

### [MISMATCH-KEPT] file_4_trang_91-het.pdf — q_2026_61a28194

- **Stem**: Một khối tròn xoay được tạo thành khi quay miền phẳng giới hạn bởi parabol có đỉnh \(I(0;5)\), đi qua điểm \(A(3;2)\), trục hoành và hai đường thẳng \(x=-3, x=3\) quanh trục \(Ox\). Tính thể tích của khối tròn xoay đó.
- **Answer key**: C | options: A: \(\frac{80\sqrt{15}\pi}{3}\) | B: \(\frac{336\pi}{5}\) | C: \(\frac{504\pi}{5}\) | D: \(\frac{504}{5}\)
- **Verifier detail**: `expr = 316.6725394818512`
- **Phân loại của người duyệt (điền tay)**: [ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác

### [MISMATCH-KEPT] file_4_trang_91-het.pdf — q_2026_49376343

- **Stem**: Cho miền phẳng giới hạn bởi đồ thị hàm số \(y=f(x)\), trục hoành và hai đường thẳng \(x=0\), \(x=2\). Biết đồ thị \(f(x)\) là một parabol có đỉnh \(I(1;5)\) và đi qua điểm \(A(0;2)\). Khi quay miền phẳng đó quanh trục \(Ox\), thể tích khối tròn xoay tạo thành bằng bao nhiêu?
- **Answer key**: D | options: A: \(\frac{18\pi}{5}\) | B: \(8\pi\) | C: \(\frac{368\pi}{5}\) | D: \(\frac{168\pi}{5}\)
- **Verifier detail**: `expr = 105.55751316061705`
- **Phân loại của người duyệt (điền tay)**: [ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác

### [MISMATCH-KEPT] file_4_trang_91-het.pdf — q_2026_d30c2435

- **Stem**: Một bể chứa nước dạng khối tròn xoay được tạo thành khi quay miền phẳng \(D\) giới hạn bởi đồ thị hàm số \(y=f(x)\), trục hoành và hai đường thẳng \(x=1, x=3\) quanh trục \(Ox\). Biết đồ thị \(y=f(x)\) là một parabol có đỉnh \(I(3;5)\) và đi qua điểm \(A(1;1)\). Tính thể tích của bể chứa nước.
- **Answer key**: C | options: A: \(\frac{168\pi}{5}\) | B: \(\frac{13406\pi}{15}\) | C: \(\frac{446\pi}{15}\) | D: \(\frac{446}{15}\)
- **Verifier detail**: `expr = 93.41002156673652`
- **Phân loại của người duyệt (điền tay)**: [ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác

### [MISMATCH-KEPT] file_4_trang_91-het.pdf — q_2026_c6c9b06f

- **Stem**: Một chiếc trống gỗ có dạng khối tròn xoay. Hai đáy của trống là hai hình tròn bán kính \(25\) cm, chiều dài trống là \(80\) cm. Mặt phẳng chứa trục cắt mặt xung quanh của trống theo hai đường parabol. Biết thiết diện vuông góc với trục tại trung điểm của trống có diện tích \(900\pi\) cm\(^2\). Tính thể tích của chiếc trống.
- **Answer key**: A | options: A: \(64400\pi\) | B: \(64400\) | C: \(80400\pi\) | D: \(\frac{218000\pi}{3}\)
- **Verifier detail**: `expr = 202318.56689118268`
- **Phân loại của người duyệt (điền tay)**: [ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác

### [MISMATCH-KEPT] file_4_trang_91-het.pdf — q_2026_e6318e7a

- **Stem**: Một bồn chứa nước có dạng khối tròn xoay. Mặt cắt qua trục của bồn là miền phẳng giới hạn bởi đồ thị hàm số bậc hai \(y=f(x)\), trục hoành và hai đường thẳng \(x=1\), \(x=5\). Biết đồ thị \(y=f(x)\) có đỉnh \(I(3;6)\) và đi qua điểm \(A(1;2)\). Tính thể tích của bồn chứa.
- **Answer key**: A | options: A: \(\frac{464\pi}{5}\) | B: \(\frac{1104\pi}{5}\) | C: \(\frac{56\pi}{3}\) | D: \(\frac{464}{5}\)
- **Verifier detail**: `expr = 291.5397982531328`
- **Phân loại của người duyệt (điền tay)**: [ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác

### [MISMATCH-KEPT] file_4_trang_91-het.pdf — q_2026_23e57960

- **Stem**: Cho miền phẳng giới hạn bởi đồ thị hàm số \(y=3x^2\), trục hoành và hai đường thẳng \(x=1\), \(x=3\). Khi quay miền phẳng đó quanh trục \(Ox\), thể tích khối tròn xoay tạo thành bằng bao nhiêu?
- **Answer key**: B | options: A: \(180\pi\) | B: \(\frac{2178\pi}{5}\) | C: \(\frac{2187\pi}{5}\) | D: \(26\pi\)
- **Verifier detail**: `expr = 1368.4777599037138`
- **Phân loại của người duyệt (điền tay)**: [ ] hint viết lệch — câu đúng  [ ] LLM sai thật  [ ] khác

### [REJECTED] file_4_trang_91-het.pdf — stage=verifier

- **Reason**: verifier=False (answer_text_mismatch: \(m=2\) vs -1.0)
- **Stem**: Cho họ đường cong \(C_m: y=x^2-2mx+3m\) với \(m\in\mathbb{R}\). Gọi \(S(m)\) là diện tích hình phẳng giới hạn bởi \(C_m\), trục hoành và hai đường thẳng \(x=1\), \(x=3\). Tìm giá trị của \(m\) để \(S(m)=\frac{32}{3}\), biết rằng trong khoảng \([1;3]\) đường cong \(C_m\) nằm phía trên trục hoành.
- **Phân loại của người duyệt (điền tay)**: [ ] loại đúng  [ ] loại oan

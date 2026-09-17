# Kịch bản thuyết trình — Bản hai sơ đồ

Đi kèm `SlideSoDo.pdf` (7 trang). Số trang dưới đây khớp số hiển thị ở góc dưới phải mỗi slide.

**Tổng thời lượng:** ~9 phút. Trong đó riêng slide 5 (bóc từng tác tử) chiếm ~4 phút — đây là phần đáng đầu tư nhất. Nếu bị bó thời gian, xem mục *Rút gọn* ở cuối mỗi slide.

**Quy ước:**
- *Trên màn hình* — tóm tắt những gì khán giả đang nhìn.
- *Nói* — lời dẫn, viết theo văn nói.
- *Nếu bị hỏi* — chi tiết dự phòng, **không nói chủ động**.
- **◆ Đóng góp** — khối này chỉ xuất hiện ở tác tử có kỹ thuật *do hệ thống tự đề xuất*. Mỗi khối trả lời đúng ba câu: **dùng gì / ý tưởng từ đâu / hiệu quả ra sao**. Sáu khối này là thứ cần nói kỹ; mọi thứ còn lại chỉ nói lướt.

## Hai nguyên tắc khi nói (không được phá)

**1. Ba con số phải gọi đúng tên là "ghi nhận vận hành".** Tỉ lệ 1/12 ca kiểm chứng lệch là sai thật (slide 5), độ trễ 28 so với 51 giây (slide 4), và khử trùng lặp 42 xuống 4 giây (slide 3) — cả ba là **ghi nhận vận hành trong quá trình chạy hệ thống**, không phải kết quả của một thí nghiệm có đối chứng. Nói quá một lần là không rút lại được.

**2. Độ khó hai trục không có gốc học thuật.** Khi nói tới đóng góp này (slide 5, tác tử Writer), phải nói đúng tinh thần câu: *"Không thể xác nhận từ mã nguồn hoặc tài liệu được cung cấp"* rằng nó bắt nguồn từ bài báo nào. Trình bày như một đề xuất rút ra từ quan sát vận hành, đừng gán cho nó một nguồn nghiên cứu.

## Sáu đóng góp xuất hiện ở đâu

| # | Đóng góp | Nằm ở tác tử / khâu | Slide |
|---|---|---|---|
| 1 | Lập lịch chuẩn đầu ra least-covered-first có bù hụt | Bộ điều phối (bao ngoài chuỗi) | 4 |
| 2 | Chính sách "không khớp ≠ sai" | Verifier | 5 |
| 3 | Tự sửa đáp án từ phương án nhiễu đã kiểm chứng | Verifier | 5 |
| 4 | Loại trừ đa đáp án bằng kiểm chứng trên nhiễu | Verifier | 5 |
| 5 | Kiểm soát độ khó hai trục | Writer | 5 |
| 6 | Ràng buộc mô tả lỗi phải dẫn ra đúng giá trị nhiễu | Distractor | 5 |

Nếu buổi bị rút ngắn: **không bỏ slide 5**. Đó là chỗ duy nhất sáu đóng góp được nói ra.

---

## Slide 1 — Trang bìa

*Trên màn hình:* Tựa "Kiến trúc hệ thống sinh câu hỏi trắc nghiệm Toán — Hai sơ đồ".

*Nói:*
> Phần này em xin đi qua kiến trúc hệ thống bằng đúng hai sơ đồ. Sơ đồ thứ nhất là đường đi của cả tài liệu; sơ đồ thứ hai phóng to vào phần lõi — chuỗi các tác tử xử lý cho từng câu hỏi. Ở sơ đồ thứ hai, chỗ nào là kỹ thuật hệ thống tự đề xuất, em sẽ dừng lại nói rõ.

---

## Slide 2 — Sơ đồ 1: Kiến trúc tổng thể

*Trên màn hình:* Ảnh full width. Năm giai đoạn trái sang phải; dải tác tử nằm trong giai đoạn ②; đường nét đứt phía dưới là vòng phản hồi người dùng.

*Nói:*
> Đây là toàn cảnh. Tài liệu đi từ trái sang phải qua năm giai đoạn: chuẩn bị, sinh câu hỏi, hậu xử lý, duyệt, rồi nhập ngân hàng.
>
> Có ba chỗ em xin chỉ tay, không đọc từng hộp:
>
> Thứ nhất — dải màu đậm ở giữa là chuỗi năm tác tử. Nó **nằm bên trong** giai đoạn sinh, và chính là thứ sơ đồ hai sẽ phóng to.
>
> Thứ hai — đường nét đứt phía dưới là vòng phản hồi. Đánh giá của người dùng ở khâu duyệt được đưa **ngược** về bộ điều phối để sinh lại hoặc sinh bổ sung, mà không phải tải lại tài liệu.
>
> Thứ ba — ba tầng khử trùng lặp ở cuối, xếp theo chi phí tăng dần.

*Lưu ý:* để hội đồng nhìn tổng thể trước. Chi tiết từng giai đoạn nói ở slide sau.

*Rút gọn:* nếu gấp, chỉ nói ý một (dải tác tử) và chuyển thẳng sang slide 4.

---

## Slide 3 — Đọc sơ đồ 1

*Trên màn hình:* Bảng năm giai đoạn bên trái; khối "ba chi tiết đáng chú ý" bên phải; câu chốt: giai đoạn ① chạy ngay khi *chọn* tài liệu.

*Nói:*
> Bảng bên trái là năm giai đoạn theo đúng thứ tự. Hai giai đoạn được tô màu là hai giai đoạn đáng chú ý — sinh câu hỏi thì đa tác tử và chạy song song, còn duyệt là vòng lặp có con người.
>
> Khối bên phải là ba thứ dễ bỏ sót khi nhìn hình. Em nói riêng cái thứ ba — **ba tầng khử trùng lặp xếp theo chi phí tăng dần**: trùng nguyên văn, gần trùng theo hình thái, rồi trùng ngữ nghĩa bằng vector nhúng. Tầng cuối là tầng duy nhất bắt được cùng một bài toán diễn đạt khác đi hoặc thay số.
>
> Câu chốt phía dưới: giai đoạn chuẩn bị được kích hoạt **ngay khi người dùng chọn tài liệu** — trước cả khi họ cấu hình xong. Thoạt nhìn là quyết định về trải nghiệm, nhưng nó buộc phần đóng gói tài liệu tách rời hẳn khỏi phần cấu hình, và đổi lại hệ thống dùng chính lượt đọc lướt đó để **gợi ý ngược** cấu hình cho người dùng.

*Nếu bị hỏi — vì sao dùng vector nhúng cho tầng ba:* đường dự phòng không có nhúng là so trùng bằng mô hình ngôn ngữ theo từng cặp, độ phức tạp bậc hai theo kích thước ngân hàng. **Ghi nhận vận hành**: bước này giảm từ khoảng 42 giây xuống khoảng 4 giây khi chuyển sang nhúng. Đây là con số vận hành, không phải kết quả thí nghiệm.

*Rút gọn:* bỏ phần khử trùng lặp, chỉ giữ câu chốt "chuẩn bị chạy khi chọn tài liệu".

---

## Slide 4 — Sơ đồ 2: Chuỗi tác tử cho mỗi câu hỏi

*Trên màn hình:* Ảnh full width. Năm tác tử; nhãn trên mũi tên liền là dữ liệu bồi thêm vào bản ghi dùng chung; nét đứt là điểm loại bỏ.

*Nói:*
> Đây là phóng to của giai đoạn hai. Chuỗi này chạy cho **mỗi** câu hỏi, và các câu chạy song song theo từng đợt.
>
> Ba điểm về cách đọc hình:
>
> Một — các tác tử giao tiếp **một chiều**. Chúng truyền nhau một bản ghi dùng chung, mỗi tác tử bồi thêm một lớp dữ liệu; đó là các nhãn trên mũi tên liền. Không có tranh luận qua lại.
>
> Hai — hai hộp màu khác là hai tác tử **thuần tính toán**, Verifier và Formatter, không gọi mô hình ngôn ngữ nào.
>
> Ba — đường nét đứt là điểm loại bỏ. Mỗi câu bị loại được ghi kèm mã lý do và dẫn tới **sinh lại một câu mới**, không vá câu cũ.

Trước khi bóc từng tác tử, em xin nói về thứ **bao ngoài** chuỗi này — bộ điều phối. Nó không soạn nội dung, chỉ lo một việc: thu đủ N câu đạt chuẩn, đúng phân bố yêu cầu. Và cách nó phân việc chính là đóng góp đầu tiên.

> **◆ Đóng góp 1 — Lập lịch chuẩn đầu ra least-covered-first có bù hụt**
> - *Dùng gì:* mức Bloom được rải bằng round-robin có trọng số theo phân bố người dùng khai; chuẩn đầu ra thì mỗi câu mới luôn nhắm vào chuẩn **đang được phủ ít nhất**, và phép đếm này tính cả các câu **đang sinh dở** trong đợt song song. Khi một câu thất bại, hạn ngạch của nó được giải phóng lại.
> - *Ý tưởng từ đâu:* thang Bloom là dùng trực tiếp từ [8]; việc gắn câu hỏi với Bloom thì tương đồng tinh thần với [23]. Nhưng **cơ chế lập lịch hạn ngạch có bù hụt này không tìm thấy tương đương** trong các tài liệu được cung cấp — đây là phần đề xuất.
> - *Hiệu quả (định tính):* phân bố **tự cân bằng**. Nếu chọn theo chỉ số tuần tự, một câu rớt giữa đợt sẽ khiến chuẩn đầu ra của nó bị bỏ trống vĩnh viễn. Cơ chế này trùng khớp với round-robin thuần khi mọi câu thành công, và tự bù chuẩn bị hụt khi có câu rớt. Đây là tính chất của cơ chế, không phải một số đo thí nghiệm.

*Nếu bị hỏi — song song có làm giảm chi phí không:* không. Nó cải thiện **độ trễ** — ghi nhận vận hành khoảng 28 giây mỗi câu so với khoảng 51 giây khi chạy tuần tự — nhưng số lời gọi mô hình không đổi, nên chi phí token không giảm.

*Rút gọn:* nói ba điểm đọc hình, rồi để đóng góp 1 sang slide 5 gộp với các đóng góp khác.

---

## Slide 5 — Đọc sơ đồ 2 (trọng tâm)

*Trên màn hình:* Bảng năm tác tử. Hai dòng xanh (Verifier, Formatter) là thuần tính toán. Câu chốt: hai trong năm tác tử chạy bằng chương trình.

*Cách trình bày:* đi từng dòng của bảng. Tác tử nào **có đóng góp** thì dừng lại đọc trọn khối ◆; tác tử nào chỉ đi mượn kỹ thuật thì nói một câu rồi qua.

*Nói — mở:*
> Bảng này là năm tác tử theo đúng thứ tự trên sơ đồ. Em đi từng dòng, và dừng lại ở những chỗ hệ thống tự đề xuất.

### Tác tử 1 — Writer

> Writer đọc thẳng tài liệu PDF nguyên bản và sinh **lõi** câu hỏi: đề, đáp án, lời giải từng bước, một trích dẫn nguyên văn làm bằng chứng nguồn, và một biểu thức kiểm chứng máy đọc được. Nó **bị cấm** sinh phương án nhiễu — việc đó để tác tử sau.
>
> Ở đây có hai kỹ thuật đi mượn có điều chỉnh, em nói nhanh: lời giải bắt buộc trình bày từng bước, số bước tối thiểu tăng theo mức Bloom — điều chỉnh từ chain-of-thought [5], nhưng khác ở chỗ chuỗi bước này là **sản phẩm cuối** cho học sinh chứ không phải nháp bỏ đi. Và tài liệu được giao **toàn văn** cho mô hình thay vì cắt đoạn.
>
> Còn đây là đóng góp:

> **◆ Đóng góp 5 — Kiểm soát độ khó hai trục**
> - *Dùng gì:* độ khó bị khống chế trên **hai trục độc lập**. Trục thứ nhất là số bước suy luận, ràng buộc bằng mức Bloom. Trục thứ hai là **độ nặng phép tính**, ràng buộc bằng một bộ điều kiện leo thang: cấm dùng bộ số kinh điển của dạng bài, mức giữa buộc phải có dữ kiện mà người học tự biến đổi mới ra, mức cao nhất buộc ra bài chứa tham số, bài ngược, hoặc phối hợp kỹ thuật.
> - *Ý tưởng từ đâu:* **"Không thể xác nhận từ mã nguồn hoặc tài liệu được cung cấp"** rằng kỹ thuật này bắt nguồn từ một bài báo cụ thể. Nó xuất phát từ một quan sát vận hành — khi chỉ ràng buộc mức Bloom, mô hình đáp ứng đúng *hình thức* của mức nhận thức nhưng vẫn chọn bộ số liệu dễ nhất.
> - *Hiệu quả (định tính):* ngăn hiện tượng độ khó thực tế **không đổi** giữa các mức Bloom. Không có số đo thực nghiệm cho đóng góp này.

### Tác tử 2 — Distractor

> Distractor lo ba phương án nhiễu. Điểm khác thường là nó đảo ngược thứ tự thông thường — không tính đáp án đúng rồi bịa vài số quanh đó, mà chọn lỗi trước.

> **◆ Đóng góp 6 — Mô tả lỗi phải dẫn ra đúng giá trị phương án**
> - *Dùng gì:* quy trình ba bước — chọn **trước** một lỗi điển hình của học sinh, áp lỗi đó **vào chính bài toán** để tính ra giá trị sai, rồi ghi giá trị đó thành phương án. Mỗi phương án kèm một **mô tả chuỗi bước làm sai**, ràng buộc sao cho ai thực hiện đúng chuỗi đó sẽ ra đúng giá trị ấy. Hệ thống có sẵn danh mục quan niệm sai lầm theo chủ đề để chọn lỗi.
> - *Ý tưởng từ đâu:* việc đặt quan niệm sai lầm làm trung tâm là **tương đồng tinh thần** với DiVERT [9], LookAlike [10] và Nagai–Uto [29] — nhưng ba bài đó theo hướng huấn luyện mô hình, còn ở đây triển khai bằng **prompting có ràng buộc, không huấn luyện**. Riêng ràng buộc "mô tả lỗi phải tái lập đúng giá trị" là phần **không tìm thấy tương đương**.
> - *Hiệu quả (định tính):* nó biến "phương án nhiễu có hợp lý không" — vốn là một phẩm chất **chủ quan** — thành một **mệnh đề kiểm chứng được**. Chính mệnh đề này sau đó được Critic chấm, và nó cũng là điều kiện để đóng góp 4 (loại trừ đa đáp án) chạy được.

### Tác tử 3 — Verifier (thuần tính toán)

> Verifier là tác tử thuần tính toán thứ nhất, **không gọi mô hình ngôn ngữ**. Nền của nó là kiểm chứng bằng chương trình: biểu thức kiểm chứng mà Writer viết ra được **chạy thật** bằng thư viện tính toán ký hiệu, kèm đối chiếu số học nhiều điểm, cho hơn hai mươi loại bài. Đáp án do đó được **máy tính lại**, không phải do mô hình tự nhận là đúng.
>
> Kỹ thuật nền này là điều chỉnh từ PAL và Program-of-Thought [6][7]: ở đó chương trình được sinh ra để **giải** bài, còn ở đây chương trình **kiểm chứng độc lập** lời giải — tạo ra hai nguồn kết quả để đối chiếu. Trên nền đó, Verifier mang **ba đóng góp**:

> **◆ Đóng góp 4 — Loại trừ đa đáp án**
> - *Dùng gì:* chạy **chính bộ kiểm chứng đó trên cả ba phương án nhiễu**. Nếu một nhiễu nào cũng được xác nhận là đúng thì **cả câu bị loại**.
> - *Ý tưởng từ đâu:* đề xuất của hệ thống; chỉ khả thi nhờ ràng buộc ở đóng góp 6 rằng nhiễu phải cùng dạng, cùng đơn vị với đáp án.
> - *Hiệu quả (định tính):* cho một **bằng chứng máy** rằng đề có nhiều hơn một đáp án đúng — lớp lỗi mà chấm bằng mô hình ngôn ngữ dễ bỏ sót.

> **◆ Đóng góp 3 — Tự sửa đáp án**
> - *Dùng gì:* nếu đáp án ghi trong câu **không khớp** kết quả máy, nhưng một phương án nhiễu **lại khớp**, hệ thống hoán đổi hai bên, viết lại các tham chiếu số trong lời giải cho nhất quán, và ghi chú lại thao tác.
> - *Ý tưởng từ đâu:* đề xuất của hệ thống.
> - *Hiệu quả (định tính):* cứu lớp câu **đúng về bản chất nhưng dán nhầm nhãn** — nếu vứt cả câu thì phí trọn ba lời gọi mô hình đã bỏ ra để sinh nó.

> **◆ Đóng góp 2 — Chính sách "không khớp ≠ sai"**
> - *Dùng gì:* khi máy ra kết quả lệch với đáp án, câu **không bị loại ngay**. Nó được giữ lại, **không bị trừ điểm**, nhưng bị ép vào hàng chờ người duyệt tay.
> - *Ý tưởng từ đâu:* đề xuất của hệ thống, dựa trên một quan sát trong quá trình chạy.
> - *Hiệu quả (ghi nhận vận hành):* theo tài liệu hệ thống, phần lớn ca lệch là do **biểu thức kiểm chứng viết chưa đúng đề**, chứ không phải mô hình giải sai — chỉ khoảng **1/12** số ca lệch là sai thật. Xin nhấn mạnh đây là **ghi nhận vận hành**, không phải kết quả của một thí nghiệm có đối chứng. Chính sách này là một đánh đổi có ý thức, nghiêng về độ bao phủ vì đã có tầng con người phía sau.

> Verifier còn soát một tập lỗi soạn trắc nghiệm kinh điển — phương án trùng nhau, từ tuyệt đối kiểu "luôn luôn", thang số lệch — điều chỉnh từ bộ hướng dẫn của Haladyna [12], chỉ lấy phần diễn đạt được thành vị từ máy kiểm.

### Tác tử 4 — Critic

> Critic là tác tử chấm, và nó chạy trên một mô hình **nhẹ hơn** mô hình sinh — lập luận là chấm dễ hơn sinh, dùng mô hình lớn cho việc chấm là lãng phí. Với **mỗi** tiêu chí, nó bắt buộc viết nhận định **trước**, cho điểm **sau** — chống thói cho điểm bừa rồi bịa lý do. Hai điểm này điều chỉnh từ MT-Bench [13] và RMTS [14], chuyển miền từ chấm bài luận sang chấm câu trắc nghiệm.
>
> Đáng nói là trong sáu tiêu chí rubric có tiêu chí **nhất quán lỗi–giá trị** — nó chính là chỗ mệnh đề kiểm chứng được ở đóng góp 6 được đưa ra chấm, bắt lớp lỗi "giải thích một đằng, con số một nẻo" mà kiểm chứng ký hiệu không thấy.

### Tác tử 5 — Formatter (thuần tính toán)

> Formatter là tác tử thuần tính toán thứ hai: đóng gói bản ghi, trộn ngẫu nhiên vị trí đáp án đúng vào bốn chỗ rồi viết lại tham chiếu nhãn trong lời giải, và phân luồng câu về đúng hàng chờ. Việc trộn dựa trên phát hiện rằng mô hình ngôn ngữ thiên lệch vị trí khi chọn [15] — nhưng hệ thống xử lý ở phía **sinh**.

*Nói — chốt:*
> Tóm lại, câu chốt dưới màn hình là điểm quan trọng nhất của cả hai sơ đồ: **hai trong năm tác tử chạy hoàn toàn bằng chương trình**. Nguyên tắc đằng sau là "việc gì máy tính được chính xác thì không giao cho mô hình ngôn ngữ" — và năm trong sáu đóng góp vừa nêu đều mọc ra từ chính nguyên tắc đó.

*Nếu bị hỏi — vì sao không có tác tử sửa lỗi:* lựa chọn có chủ ý. Một câu đã sửa mang theo lịch sử của phiên bản hỏng, và các ràng buộc chéo giữa đáp án, lời giải, biểu thức kiểm chứng và mô tả lỗi rất dễ bất nhất sau khi vá cục bộ. Nên hệ thống **sinh lại** thay vì sửa.

*Rút gọn (nếu chỉ còn ~2 phút):* giữ đủ ba khối của Verifier (đóng góp 2, 3, 4) và đóng góp 6 của Distractor; đóng góp 5 và các kỹ thuật đi mượn nói một câu. Ba đóng góp của Verifier là phần thuyết phục nhất vì chúng gắn với tầng kiểm chứng thuần tính toán.

---

## Slide 6 — Hai sơ đồ nối với nhau thế nào

*Trên màn hình:* Năm giai đoạn thu nhỏ, ô ② tô đậm, mũi tên nét đứt chỉ vào ② kèm chữ "Sơ đồ 2 phóng to giai đoạn này". Câu chốt: sơ đồ 1 là đường đi của tài liệu, sơ đồ 2 là đường đi của một câu hỏi.

*Nói:*
> Slide chốt, để tránh nhầm hai sơ đồ. Sơ đồ một là đường đi của **tài liệu** — chạy một lần cho cả lượt sinh. Sơ đồ hai là đường đi của **một câu hỏi** — chạy lặp lại, mỗi câu một lần, và các câu chạy song song theo từng đợt. Nói gọn: toàn bộ sơ đồ hai nằm trong ô số hai của sơ đồ một.

---

## Slide 7 — Cảm ơn

*Nói:*
> Em xin dừng phần kiến trúc ở đây. Rất mong nhận được câu hỏi của thầy cô, nhất là về tầng kiểm chứng thuần tính toán và bốn đóng góp gắn với nó.

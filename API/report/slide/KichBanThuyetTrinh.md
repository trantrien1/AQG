# Kịch bản thuyết trình

Đi kèm `SlideThuyetTrinh.pdf` (34 trang). Số trang dưới đây khớp số hiển thị ở góc dưới phải mỗi slide.

**Tổng thời lượng:** ~24 phút trình bày + 10 phút hỏi đáp.

**Quy ước trong tài liệu này:**
- *Trên màn hình* — tóm tắt những gì khán giả đang nhìn thấy.
- *Nói* — lời dẫn. Viết theo văn nói, không cần đọc nguyên văn.
- *Nếu bị hỏi* — chi tiết dự phòng, **không nói chủ động**, chỉ dùng khi có câu hỏi.

## Mạch trình bày: sáu đóng góp là xương sống

Deck được dựng để phần đóng góp của hệ thống nổi lên xuyên suốt, chứ không lẫn vào các kỹ thuật đi mượn:

- **Slide 3** nêu trước cả sáu đóng góp, chia hai nhóm — đây là bản đồ cho cả buổi.
- **Huy hiệu `ĐÓNG GÓP`** xuất hiện trên tiêu đề slide 13, 15, 17, 18, 22 — mỗi lần một đóng góp được trình bày.
- **Slide 29** tổng kết lại, gắn mỗi đóng góp với một lỗi cụ thể mà kiến trúc thuần LLM không xử lý được.
- **Slide 31** đánh dấu cả ba đặc điểm kết luận đều dẫn về đóng góp.

Nếu buổi bị rút ngắn: **không bỏ slide 3, 17, 29**.

## Hai nguyên tắc khi nói

**1. Hai con số phải gọi đúng tên.** Slide 17 có tỉ lệ 1/12, slide 25 có 42 → 4 giây. Cả hai là **ghi nhận vận hành**, không phải kết quả thí nghiệm — trên slide đã ghi rõ, và khi nói cũng phải giữ đúng chữ đó. Đây là chỗ dễ bị vặn nhất, và một khi đã nói quá thì không rút lại được.

**2. Slide 18 có một câu phải nói đúng nguyên văn:** *"Không thể xác nhận từ mã nguồn hoặc tài liệu được cung cấp."* Đây là đóng góp duy nhất không truy được về bài báo nào, nên trình bày như đề xuất chứ không phải như kỹ thuật có gốc học thuật.

Phần hạn chế đã được rút khỏi slide theo chủ ý — toàn bộ nằm trong **ghi chú slide 30** và **phụ lục A** cuối tài liệu này.

---

## Phần mở đầu — 3 phút

### Slide 1 — Trang bìa

*Nói:*
> Em xin trình bày báo cáo kỹ thuật về một hệ thống sinh câu hỏi trắc nghiệm Toán tự động. Báo cáo tập trung vào ba thứ: phương pháp, kiến trúc, và các kỹ thuật được sử dụng — cùng với việc đối chiếu từng kỹ thuật với các nghiên cứu đã có.

---

### Slide 2 — Nội dung

*Trên màn hình:* Tám mục. Câu chốt: "Toán có đáp án kiểm chứng được bằng máy — hệ thống dùng tính chất đó làm tài sản kiến trúc."

*Nói:*
> Bố cục gồm tám phần. Nhưng nếu chỉ nhớ một câu duy nhất từ buổi hôm nay, em mong đó là câu ở dưới màn hình.
>
> Khác với sinh câu hỏi đọc hiểu, một câu hỏi Toán có đáp án đúng hay sai **xác định được bằng máy**. Hầu hết các hệ sinh câu hỏi hiện nay không dùng tính chất này — họ để chính mô hình ngôn ngữ tự thẩm định sản phẩm của nó. Hệ thống này thì khai thác nó như một thành phần kiến trúc. Mọi lựa chọn thiết kế còn lại đều xoay quanh đó.

---

### Slide 3 — Sáu đóng góp của hệ thống ★

*Trên màn hình:* Sáu đóng góp chia hai nhóm. Câu chốt: cả sáu bắt nguồn từ một lựa chọn kiến trúc.

*Nói:*
> Trước khi vào chi tiết, em xin nêu trước **sáu kỹ thuật do hệ thống tự đề xuất**. Slide này là bản đồ cho cả phần sau — mỗi kỹ thuật khi xuất hiện sẽ được đánh dấu bằng huy hiệu ĐÓNG GÓP trên tiêu đề, để thầy cô dễ theo dõi.
>
> **Nhóm một — ba kỹ thuật khai thác tầng kiểm chứng.** Loại trừ đa đáp án. Tự sửa đáp án. Và chính sách "không khớp không có nghĩa là sai". Cả ba chỉ khả thi vì hệ thống có một tầng kiểm chứng tất định — em sẽ giải thích tầng này ở slide 16.
>
> **Nhóm hai — ba kỹ thuật biến phẩm chất chủ quan thành thứ kiểm chứng được.** Ràng buộc mô tả lỗi phải dẫn ra đúng giá trị phương án. Kiểm soát độ khó hai trục. Và lập lịch chuẩn đầu ra có bù hụt khi thất bại.
>
> Điểm đáng nói ở câu chốt: cả sáu **không phải sáu ý tưởng rời rạc**. Chúng đều bắt nguồn từ một lựa chọn kiến trúc duy nhất — đưa tính kiểm chứng được vào lõi hệ thống thay vì để mô hình tự thẩm định.

*Lưu ý khi trình bày:* đây là slide bán ý tưởng của cả bài. Đừng đọc lướt — dừng đủ lâu để hội đồng đọc hết sáu dòng.

---

## Phần 1: Bài toán — 2 phút

### Slide 4 — Ba yêu cầu đặc thù

*Trên màn hình:* Ba khối: bám tài liệu / đúng toán học / đo lường được. Câu chốt: hai điểm nghẽn của AQG.

*Nói:*
> Bài toán có ba yêu cầu vượt ra ngoài phạm vi của các hệ sinh câu hỏi thông thường.
>
> **Một** — câu hỏi phải phát sinh từ tài liệu do giảng viên cung cấp, chứ không từ tri thức nền của mô hình.
>
> **Hai** — đây là yêu cầu mấu chốt — đáp án phải được **máy tính lại**. Không phải mô hình nói đúng là đúng.
>
> **Ba** — mỗi câu phải gắn với một mức nhận thức theo thang Bloom và một chuẩn đầu ra, để thứ thu được là một **công cụ đo lường có cấu trúc**.
>
> Hai bài khảo sát — một về sinh câu hỏi, một về sinh phương án nhiễu — đều ghi nhận cùng hai điểm nghẽn: chất lượng, và khả năng kiểm soát. Toàn bộ thiết kế được tổ chức xoay quanh đúng hai điểm nghẽn này.

---

### Slide 5 — Đầu vào và đầu ra

*Trên màn hình:* Cột trái: PDF + cấu hình. Cột phải: mỗi câu mang theo gì.

*Nói:*
> Đầu vào: một tài liệu PDF, cộng một cấu hình sinh do người dùng khai báo.
>
> Đầu ra ở cột phải. Xin lưu ý hai dòng được tô màu, vì cả hai sẽ quay lại xuyên suốt bài:
>
> Thứ nhất — mỗi phương án nhiễu **mang theo mô tả lỗi tương ứng**. Không phải một con số vu vơ, mà là một con đường làm sai cụ thể.
>
> Thứ hai — mỗi câu mang theo một **trích dẫn nguyên văn** từ tài liệu, làm bằng chứng nguồn.
>
> Cả hai đều là **dấu vết để một cơ chế khác kiểm tra lại**. Đó là nguyên tắc thiết kế thống nhất, em sẽ quay lại ở kết luận.

---

## Phần 2: Kiến trúc — 5 phút

### Slide 6 — Năm giai đoạn

*Trên màn hình:* Bảng 5 giai đoạn. Câu chốt: chuẩn bị chạy ngay khi *chọn* tài liệu.

*Nói:*
> Hệ thống vận hành qua năm giai đoạn. Hai giai đoạn đáng chú ý được tô màu: giai đoạn hai là phần đa tác tử chạy song song, giai đoạn bốn là vòng lặp con người.
>
> Điểm đáng nói về mặt phương pháp là câu ở dưới: giai đoạn chuẩn bị được kích hoạt **ngay khi người dùng chọn tài liệu** — tức là trước khi họ cấu hình xong.
>
> Đây thoạt nhìn là một quyết định về trải nghiệm, nhưng nó có hệ quả kiến trúc: nó **buộc** phần đóng gói tài liệu phải tách rời hoàn toàn khỏi phần cấu hình sinh. Đổi lại, hệ thống dùng chính lượt đọc lướt đó để **gợi ý ngược** cấu hình cho người dùng — chủ đề, chuẩn đầu ra, số câu hợp lý.

---

### Slide 7 — Kiến trúc tổng thể *(hình)*

*Nói:*
> Đây là toàn cảnh. Tài liệu đi từ trái sang phải qua năm giai đoạn.
>
> Dải màu đậm ở giữa là chuỗi năm tác tử — nó **nằm bên trong** giai đoạn sinh, và sẽ được phóng to ở slide sau.
>
> Đường nét đứt phía dưới là **vòng phản hồi người dùng**: đánh giá ở khâu duyệt được đưa ngược về bộ điều phối để sinh lại hoặc sinh bổ sung — không cần tải lại tài liệu.
>
> Ba tầng khử trùng lặp ở cuối được xếp theo **chi phí tăng dần**.

*Lưu ý khi trình bày:* chỉ tay vào ba chỗ theo đúng thứ tự trên — dải tác tử, đường nét đứt, ba tầng cuối. Đừng đọc từng hộp.

---

### Slide 8 — Bộ điều phối

*Trên màn hình:* Câu chốt "thu về đủ N câu đạt chuẩn" + ba khối nhiệm vụ.

*Nói:*
> Bộ điều phối có đúng một mục tiêu: thu về đủ N câu đạt chuẩn. Nó **không** soạn nội dung câu hỏi, và **không** tự đánh giá chất lượng. Ba việc nó làm:
>
> **Giao chỉ tiêu trước khi sinh.** Mỗi câu được ấn định sẵn mức Bloom, độ khó và chuẩn đầu ra *trước khi* bất kỳ lời gọi mô hình nào diễn ra. Cách này trái ngược với việc sinh một tập rồi phân loại về sau — nó biến phân bố mong muốn thành **ràng buộc đầu vào**, thay vì một kết quả cần hy vọng.
>
> **Điều phối song song.** Sinh đồng thời theo từng đợt; phần ghép kết quả giữ tuần tự để tránh tranh chấp dữ liệu.
>
> **Quyết định dừng.** Ba điều kiện.

*Nếu bị hỏi về điều kiện dừng:* ngưỡng thất bại liên tiếp được đặt **tương đối** theo số câu yêu cầu — để một mục tiêu lớn không bị dừng sớm oan chỉ vì gặp một chuỗi lỗi tạm thời từ nhà cung cấp mô hình.

*Nếu bị hỏi vì sao kiểm chứng ký hiệu phải tuần tự:* thư viện tính toán ký hiệu không cam kết an toàn đa luồng. Đây là bước thuần CPU và nhanh nên không gây nghẽn.

---

### Slide 9 — Chuỗi năm tác tử

*Trên màn hình:* Bảng 5 tác tử, Verifier và Formatter tô xanh lá. Câu chốt về nguyên tắc thiết kế.

*Nói:*
> Chuỗi xử lý cho **mỗi** câu hỏi gồm năm tác tử. Điểm quan trọng nhất: **hai trong năm tác tử hoàn toàn tất định** — chúng không gọi mô hình ngôn ngữ nào cả. Đó là hai dòng màu xanh.
>
> Ba tác tử còn lại dùng mô hình ngôn ngữ, và cả ba đều đọc trực tiếp tài liệu PDF.
>
> Nguyên tắc ở dưới giải thích sự phân chia này: *việc gì máy tính được chính xác thì không giao cho mô hình ngôn ngữ.*
>
> Tỉ lệ hai trên năm này là **điểm khác biệt căn bản** so với các khung đa tác tử thuần mô hình ngôn ngữ trong các bài báo em khảo sát.
>
> Và xin lưu ý trước: hệ thống **không có tác tử Refiner**. Đây là lựa chọn có chủ ý, em sẽ dành hẳn một slide để giải thích.

---

### Slide 10 — Chuỗi tác tử, chi tiết *(hình)*

*Nói:*
> Đây là chuỗi đó phóng to.
>
> Các tác tử giao tiếp **một chiều**: chúng truyền nhau một bản ghi dùng chung, mỗi tác tử bồi thêm một lớp dữ liệu — đó là các nhãn trên mũi tên liền.
>
> Hai hộp có màu khác là hai tác tử tất định.
>
> Các đường nét đứt là điểm loại bỏ. Mọi câu bị loại đều được ghi kèm **mã lý do**, và dẫn tới **sinh lại một câu mới — không vá câu cũ**.

---

### Slide 11 — Luồng quyết định

*Trên màn hình:* Bảng điều kiện từng cổng.

*Nói:*
> Nói cách khác, mỗi câu ứng viên đi qua một chuỗi cổng lọc nối tiếp, và bị loại ở **cổng đầu tiên không đạt**.
>
> Đáng chú ý là dòng Critic: có ba ngưỡng loại cứng — bám nguồn, tính duy nhất đáp án, và tính nhất quán lỗi–giá trị. Em sẽ giải thích tiêu chí thứ ba khi nói về rubric.

---

## Phần 3: Các kỹ thuật — 8 phút

### Slide 12 — Sinh bám tài liệu toàn văn

*Trên màn hình:* "Không làm gì" / "Vì sao" / "Cái giá". Câu chốt: bám nguồn nới lỏng.

*Nói:*
> Kỹ thuật đầu tiên. Slide này bắt đầu bằng những thứ hệ thống **không** làm: không trích xuất văn bản, không nhận dạng ký tự quang học, không chia tài liệu thành đoạn nhỏ.
>
> Tài liệu gốc được đóng gói **một lần duy nhất** và đính kèm nguyên vẹn cho cả ba tác tử dùng mô hình.
>
> Điều này khiến kiến trúc khác hẳn hướng sinh câu hỏi dựa trên truy xuất đoạn văn: thay vì đưa cho mô hình một đoạn trích rồi hỏi, hệ thống đưa **toàn bộ tài liệu ở dạng gốc** và giao chỉ tiêu.
>
> Lý do là bố cục, ký hiệu toán học, bảng biểu và hình vẽ đều bị **phá huỷ** khi trích văn bản thô — vấn đề kinh niên với học liệu Toán.
>
> Cái giá thì thẳng thắn: token đầu vào cao, và giới hạn cứng về độ dài tài liệu.
>
> Câu chốt ở dưới là một điều chỉnh quan trọng: chính sách bám nguồn được **nới lỏng có kiểm soát**. Câu hỏi được phép là một **bài tập mới** — miễn là công thức, định lý hay phương pháp nằm trong tài liệu. Nới là bắt buộc: nếu đòi mọi con số phải xuất hiện nguyên văn, hệ thống chỉ còn có thể **chép lại bài tập có sẵn**.

*Nếu bị hỏi bám nguồn được thực thi thế nào:* qua hai cơ chế bổ trợ — tác tử soạn đề bắt buộc trích một đoạn nguyên văn làm bằng chứng, và tác tử chấm nhận chính tài liệu đó để đối chiếu từng dữ kiện.

---

### Slide 13 — Lập lịch theo hạn ngạch ★ ĐÓNG GÓP

*Trên màn hình:* Bloom / chuẩn đầu ra, khối cảnh báo về câu đang sinh dở. Huy hiệu ĐÓNG GÓP trên tiêu đề.

*Nói:*
> Đây là đóng góp đầu tiên trong sáu đóng góp em nêu ở slide 3.
>
> Làm sao để bộ câu hỏi thu được phủ **đúng** phân bố yêu cầu? Mức Bloom thì rải bằng round-robin có trọng số. Chuẩn đầu ra thì chọn theo nguyên tắc **least-covered-first**: mỗi câu mới luôn nhắm vào chuẩn đầu ra đang được phủ ít nhất.
>
> Điểm tinh tế nằm ở khối bên phải. Khi chạy song song, số câu **đã chấp nhận** không còn phản ánh số câu **đang được nhắm tới**. Nếu chọn theo chỉ số tuần tự, một câu thất bại giữa đợt sẽ khiến chuẩn đầu ra của nó bị bỏ trống **vĩnh viễn**.
>
> Nên phép đếm phải tính cả các câu đang sinh dở — và phải **giải phóng hạn ngạch khi thất bại**.
>
> Kết quả là phân bố **tự cân bằng lại**: nó trùng khớp với round-robin thuần khi mọi câu đều thành công, và tự bù chuẩn đầu ra bị hụt khi có câu rớt.

---

### Slide 14 — Tách vai và suy luận từng bước

*Trên màn hình:* Hai cột. Bên phải có khối so sánh với chain-of-thought gốc.

*Nói:*
> Hai kỹ thuật gộp chung một slide.
>
> **Tách vai:** tác tử soạn đề chỉ sinh phần lõi và **bị cấm sinh phương án nhiễu**. Việc sinh nhiễu giao hẳn cho tác tử kế tiếp, vốn đã có sẵn đáp án đúng và lời giải làm đầu vào. Mỗi lời gọi tập trung một việc. Giá phải trả là hai lời gọi thay vì một.
>
> **Suy luận từng bước:** lời giải bắt buộc trình bày thành các bước đánh số, với số bước tối thiểu **tăng theo mức Bloom**.
>
> Khối bên phải là điểm khác biệt so với chain-of-thought nguyên bản: ở bài báo gốc, chuỗi suy luận là một **phương tiện** để cải thiện độ chính xác, và thường bị **bỏ đi** sau khi lấy đáp án. Ở đây, nó vừa là phương tiện **vừa là sản phẩm cuối** — vì nó chính là lời giải hiển thị cho học sinh. Nên nó bị ràng buộc về hình thức và độ dài tối thiểu, điều không có trong bài báo gốc.

---

### Slide 15 — Sinh nhiễu error-first ★ ĐÓNG GÓP

*Trên màn hình:* Ba bước (i)(ii)(iii). Câu chốt: mô tả lỗi phải ra đúng giá trị.

*Nói:*
> Đây là đóng góp thứ hai, và là chỗ em muốn dừng lâu một chút.
>
> Quy trình sinh phương án nhiễu **đảo ngược thứ tự thông thường**. Thay vì bịa một con số trông giống đáp án, hệ thống: **chọn trước** một lỗi điển hình của học sinh; **áp lỗi đó vào chính bài toán** để *tính ra* giá trị sai; rồi mới ghi giá trị đó thành phương án.
>
> Kèm theo mỗi phương án là một **mô tả chuỗi bước làm sai**, bị ràng buộc sao cho: ai thực hiện đúng chuỗi đó sẽ ra **đúng** giá trị ấy.
>
> Và đây là ý nghĩa của ràng buộc đó. Tính hợp lý của một phương án nhiễu vốn là một phẩm chất **chủ quan** — rất khó chấm. Ràng buộc này biến nó thành một **mệnh đề kiểm chứng được**. Và chính mệnh đề đó được đưa cho tác tử chấm ở phần sau.

*Nếu bị hỏi lỗi lấy từ đâu:* hệ thống duy trì sẵn một danh mục quan niệm sai lầm phổ biến theo chủ đề. Việc chọn dùng hạt giống ngẫu nhiên **cố định theo nội dung bài**, nên cùng một bài luôn nhận cùng danh sách — bảo đảm tái lập được.

*Nếu bị hỏi có ràng buộc gì thêm:* ba phương án phải dùng ba lỗi **khác nhau**, và phải cùng dạng, cùng đơn vị với đáp án đúng. Ràng buộc cùng dạng này về sau là điều kiện cần cho kỹ thuật loại trừ đa đáp án.

---

### Slide 16 — Kiểm chứng bằng chương trình

*Trên màn hình:* Câu chốt "tách giải toán khỏi tự chấm". Khối so sánh PAL/PoT. Câu chốt cuối: hai nguồn.

*Nói:*
> Đây là chốt chặn cốt lõi — và là nền cho ba đóng góp ở slide sau.
>
> Ý tưởng: **tách năng lực giải toán khỏi năng lực tự chấm** của mô hình ngôn ngữ. Vì hai thứ đó không giống nhau — và mô hình rất hay tự tin vào đáp án sai của chính nó.
>
> Cách làm: tác tử soạn đề bị **buộc** phải viết kèm một **biểu thức kiểm chứng máy đọc được**, theo một trong hơn hai mươi loại đã định nghĩa. Biểu thức đó được **chạy thật** bằng thư viện tính toán ký hiệu. Đáp án do đó được *máy tính lại*, không phải do mô hình tự nhận là đúng.
>
> Bên phải là điểm khác biệt so với PAL và Program-of-Thought — hai bài báo gần nhất về mặt ý tưởng. Ở đó, chương trình được sinh ra để **giải** bài toán, và kết quả chương trình **chính là** câu trả lời. Tức là chỉ có **một nguồn** kết quả duy nhất — không có gì để đối chiếu.
>
> Ở đây, mô hình vẫn tự giải bằng ngôn ngữ tự nhiên, còn chương trình đóng vai trò **kiểm chứng độc lập**. Kết quả là **hai nguồn độc lập** — và hai nguồn thì **phát hiện được bất đồng**.

*Nếu bị hỏi hơn hai mươi loại là những gì:* giải phương trình, đạo hàm, tích phân, giới hạn, định thức, giá trị riêng, tổ hợp, xác suất, số học mô-đun, tương đương logic, tính chất đồ thị, và nhiều loại khác.

*Nếu bị hỏi câu hỏi khái niệm thì sao:* hệ thống cho phép khai báo loại "không kiểm chứng". **Xem mục 3 phụ lục A** — đây là giới hạn phạm vi đáng kể nhất.

---

### Slide 17 — Ba kỹ thuật dẫn xuất ★ ĐÓNG GÓP ×3

*Trên màn hình:* Ba khối, cả ba đều là đóng góp. Khối thứ ba có ghi *(ghi nhận vận hành)*.

*Nói:*
> Và đây là ba đóng góp mở ra từ tầng kiểm chứng vừa nói — gần như miễn phí.
>
> **Loại trừ đa đáp án.** Chạy chính bộ kiểm chứng đó trên **cả ba phương án nhiễu**. Nếu một phương án nhiễu nào cũng được xác nhận là đúng thì **loại cả câu** — vì đó là **bằng chứng máy** cho việc đề có nhiều hơn một đáp án đúng. Đây là lớp lỗi mà một tầng chấm bằng ngôn ngữ rất khó bắt chắc chắn. Kỹ thuật này chỉ khả thi nhờ ràng buộc phương án nhiễu phải cùng dạng với đáp án.
>
> **Tự sửa đáp án.** Nếu đáp án ghi trong câu không khớp kết quả máy tính, *nhưng* một phương án nhiễu lại khớp — hệ thống hoán đổi hai bên và viết lại lời giải cho nhất quán. Nó cứu được lớp câu hỏi **đúng về bản chất nhưng dán nhầm nhãn** — rất phổ biến, và rất phí nếu vứt cả câu.
>
> **Và chính sách quan trọng nhất — "không khớp không có nghĩa là sai".** Khi máy tính ra kết quả lệch với đáp án, câu **không bị loại ngay**. Vì phần lớn ca lệch xuất phát từ việc **biểu thức kiểm chứng được viết không đúng đề**, chứ không phải mô hình giải sai — chỉ khoảng **một trên mười hai** ca lệch là sai thật.
>
> **Đây là ghi nhận vận hành, không phải kết quả thí nghiệm có đối chứng** — như ghi trên slide.
>
> Nên câu được giữ lại, nhưng **bắt buộc chuyển vào hàng chờ duyệt tay**. Một đánh đổi có ý thức giữa precision và recall — nghiêng về recall, vì đã có tầng con người phía sau.

---

### Slide 18 — Kiểm soát độ khó hai trục ★ ĐÓNG GÓP

*Trên màn hình:* Vấn đề ở trên, hai trục ở giữa, khối cảnh báo về cơ sở nghiên cứu ở dưới.

*Nói:*
> Đóng góp thứ năm, xuất phát từ một vấn đề rất thực tế: khi **chỉ** ràng buộc mức Bloom, mô hình đáp ứng đúng **hình thức** của mức nhận thức — nhưng vẫn chọn bộ số liệu dễ nhất có thể. Độ khó thực tế gần như không đổi giữa các mức.
>
> Nên độ khó được khống chế trên **hai trục độc lập**.
>
> **Trục số bước suy luận** — ràng buộc bằng mức Bloom. Mức Vận dụng cao bắt buộc phối hợp từ hai kỹ thuật trở lên.
>
> **Trục độ nặng phép tính** — bộ điều kiện leo thang theo độ khó mục tiêu. Đáng chú ý nhất là ràng buộc **cấm dùng bộ số kinh điển** của dạng bài.
>
> Và em phải nói rõ về cơ sở: **Không thể xác nhận từ mã nguồn hoặc tài liệu được cung cấp** rằng kỹ thuật này bắt nguồn từ một bài báo cụ thể. Nó xuất phát từ chính quan sát vận hành nêu ở trên. Em trình bày nó như một đề xuất.

---

## Phần 4: Kiểm soát chất lượng — 4 phút

### Slide 19 — Đánh giá dựa trên rubric

*Trên màn hình:* Sáu tiêu chí, hai điều chỉnh, câu chốt về nhất quán lỗi–giá trị.

*Nói:*
> Tầng chấm dùng rubric sáu tiêu chí. Hai tiêu chí cuối được tô màu vì chúng là tiêu chí đặc thù của hệ thống này.
>
> Hai điều chỉnh về phương pháp:
>
> **Model bất đối xứng** — tác tử chấm chạy trên một mô hình **nhẹ và rẻ hơn** mô hình sinh. Lập luận: chấm là bài toán dễ hơn sinh.
>
> **Nhận định trước, điểm sau** — với **mỗi** tiêu chí, mô hình bắt buộc phải viết nhận định *rồi mới* được cho điểm. Chống lại thói cho điểm bừa rồi bịa lý do biện minh; ngoài ra nhận định được lưu lại làm **bằng chứng hiển thị cho người duyệt**.
>
> Tiêu chí đáng nói riêng là **nhất quán lỗi–giá trị**. Nó kiểm chính cái mệnh đề em nói ở slide 15: thực hiện đúng chuỗi lỗi đã mô tả **có ra đúng giá trị phương án đó không**? Nó bắt lớp lỗi *"giải thích một đằng, con số một nẻo"* — lớp lỗi mà kiểm chứng ký hiệu **không thấy được**, vì kiểm chứng chỉ soi đáp án đúng.

*Nếu bị hỏi hai điều chỉnh này khác bài báo gốc chỗ nào:* bài báo về mô hình làm giám khảo thiết lập **tính khả dụng** của cách chấm, còn việc chọn model chấm nhẹ hơn là điều chỉnh về **chi phí** của hệ thống. Bài báo về nhận định trước điểm sau làm cho **chấm bài luận** — hệ thống giữ nguyên lý nhưng **chuyển miền** sang trắc nghiệm, với bộ tiêu chí khác hoàn toàn.

---

### Slide 20 — Hai tầng bảo vệ ở khâu chấm

*Trên màn hình:* Fail-open bên trái, soát lỗi soạn đề bên phải.

*Nói:*
> Hai cơ chế bảo vệ.
>
> **Fail-open.** Nếu chính tác tử chấm gặp sự cố, câu **không bị chặn**: hệ thống điền điểm trung tính và để người duyệt quyết định. Nguyên tắc: *một lỗi hạ tầng ở khâu chấm điểm không được phép giết oan cả lượt sinh.* Bổ sung là cơ chế **vớt điểm từng phần** khi đầu ra bị cắt cụt.
>
> **Soát lỗi soạn trắc nghiệm.** Bộ quy tắc rút từ lĩnh vực đo lường giáo dục, hoàn toàn tất định, không gọi mô hình. Ví dụ: từ tuyệt đối kiểu "luôn luôn" trong phương án nhiễu thì học sinh học được mẹo loại trừ. Hay thang số không cân đối — phương án lệch quá xa so với trung vị thì dễ đoán.
>
> Hệ thống chỉ chuyển **tập con** các hướng dẫn ấy — những hướng dẫn **diễn đạt được thành vị từ máy kiểm** — thành quy tắc tự động.

*Nếu bị hỏi fail-open có mặt trái không:* có — xem mục 6 phụ lục A.

---

### Slide 21 — Sinh lại, không vá

*Trên màn hình:* Câu chốt ở trên, hai lập luận: chi phí / trạng thái sạch.

*Nói:*
> Đây là chỗ giải thích vì sao **không có tác tử Refiner**.
>
> Câu bị loại được **thay bằng một câu sinh mới**, không phải sửa cục bộ. Dựa trên hai lập luận.
>
> **Về chi phí:** một vòng sửa cần ít nhất một lời gọi mô hình, cộng chi phí kiểm định lại toàn chuỗi — không rẻ hơn sinh mới bao nhiêu.
>
> **Về tính sạch của trạng thái** — lập luận chính: một câu đã sửa mang theo **lịch sử của phiên bản hỏng**. Các ràng buộc chéo giữa đáp án, lời giải, biểu thức kiểm chứng và mô tả lỗi rất dễ trở nên **bất nhất** sau khi vá cục bộ. Mà đó chính là lớp bất nhất mà tiêu chí nhất quán lỗi–giá trị được dựng ra để bắt.
>
> Nói cách khác: vá cục bộ tức là **tự tạo ra đúng thứ mình đang cố phát hiện**.

*Nếu bị hỏi "đã so sánh với hướng sửa lặp chưa":* trả lời thẳng — đây là lập luận thiết kế, chưa so sánh thực nghiệm.

*Nếu bị hỏi "sao các tác tử không tranh luận với nhau":* các tác tử giao tiếp một chiều theo chuỗi, không thương lượng. Có bài báo cho thấy tranh luận đa tác tử có các chế độ thất bại đáng kể. **Không nói chủ động chuyện này.**

---

### Slide 22 — Phân luồng và nhật ký loại bỏ ★ ĐÓNG GÓP

*Trên màn hình:* Bốn quy tắc phân luồng bên trái, nhật ký bên phải. Câu chốt dưới cùng.

*Nói:*
> Slide này chứa đóng góp thứ ba — cách hệ thống biểu đạt sự không chắc chắn.
>
> Mọi tín hiệu nghi ngờ được quy về hai trạng thái, kèm danh sách lý do. Dòng thứ ba là chi tiết quan trọng nhất: kiểm chứng toán không khớp thì **luôn** chuyển vào diện cần sửa — nhưng **không trừ điểm**. Theo đúng chính sách "không khớp không phải là sai": một câu đúng mà biểu thức kiểm chứng viết lệch vẫn phải được xếp hạng **công bằng**.
>
> Và đó là ý nghĩa của câu dưới cùng: tách bạch giữa **hạ điểm** và **buộc duyệt tay** cho phép hệ thống biểu đạt **sự không chắc chắn** mà **không làm sai lệch thứ hạng chất lượng**.
>
> Bên phải: mọi điểm loại đều được ghi thành bản ghi có **mã lý do** và **nhãn giai đoạn**. Câu bị loại không bị vứt đi mà trở thành **dữ liệu chẩn đoán** — cho phép trả lời *"hệ thống đang hỏng ở khâu nào"*, thay vì chỉ biết *"tỉ lệ đạt thấp"*.

*Nếu bị hỏi về trộn vị trí phương án:* đáp án đúng được xáo ngẫu nhiên vào bốn vị trí, và tham chiếu trong lời giải được viết lại cho khớp. Có bài báo chứng minh mô hình chịu thiên lệch vị trí khi **chọn** phương án — họ khử ở phía chọn, hệ thống chặn từ phía **sinh**.

---

## Phần 5: Phản hồi người dùng — 3 phút

### Slide 23 — Vòng lặp con người

*Trên màn hình:* Năm thao tác bên trái, ba mức phản hồi và ví dụ chỉ thị bên phải.

*Nói:*
> Toàn bộ các thao tác bên trái diễn ra trên **cùng một phiên làm việc**. Sinh lại chỉ thay các câu bị đánh giá kém; các câu còn lại giữ nguyên.
>
> Phản hồi được thu ở ba mức. Mức giữa — **thẻ lý do có cấu trúc** — là một quyết định phương pháp, không phải chi tiết giao diện.
>
> Mỗi thẻ được ánh xạ sang một **chỉ thị hành động** cụ thể. Ví dụ ở khối cam: thẻ "quá dễ" không chỉ được ghi nhận, mà được **dịch** thành chỉ thị yêu cầu tăng số bước biến đổi và cấm hỏi chép lại định nghĩa.
>
> Lợi ích ở câu dưới: phần tổng hợp thẻ là **tất định và không tốn chi phí suy luận**, đồng thời cho ra chỉ thị chính xác hơn so với để mô hình tự diễn giải văn bản tự do.

---

### Slide 24 — Học sở thích trong ngữ cảnh

*Trên màn hình:* RLHF bên trái, hệ thống bên phải, khối đánh đổi ở dưới.

*Nói:*
> Đây là một điều chỉnh **đáng kể** so với bài báo gốc.
>
> Bài báo RLHF: huấn luyện một mô hình phần thưởng từ so sánh của con người, rồi tinh chỉnh chính sách bằng học tăng cường.
>
> Hệ thống giữ lại **tín hiệu** và **mục tiêu**, nhưng **bỏ hoàn toàn phần huấn luyện**. Thay vào đó, phản hồi được tổng hợp thành một khối chỉ dẫn và tiêm thẳng vào ngữ cảnh của các tác tử sinh ở lượt sau.
>
> Đánh đổi rất rõ, và em xin không giấu vế bên phải: hiệu lực **tức thì**, chi phí huấn luyện **bằng không** — nhưng sở thích **không được nội tại hoá** vào trọng số, và hệ thống phải trả **phí token lặp lại ở mọi lượt**.

*Nếu bị hỏi phản hồi có bền không:* hồ sơ sở thích được lưu bền theo phiên làm việc, nên mọi lượt sinh sau vẫn tôn trọng phản hồi đã cho.

*Nếu bị hỏi so với các bài báo về phản hồi chuyên gia:* ở các bài báo đó, phản hồi chủ yếu dùng để **đánh giá hệ thống** hoặc định nghĩa chiến lược **trước khi chạy**. Ở đây nó được đưa trở lại vòng sinh **trong thời gian thực**.

---

## Phần 6: Ngân hàng câu hỏi — 2 phút

### Slide 25 — Khử trùng lặp ba tầng

*Trên màn hình:* Ba tầng. Tầng 3 tô cam. Dòng dưới: *Ghi nhận vận hành: ≈42 giây → ≈4 giây.*

*Nói:*
> Trước khi nhập kho, mỗi câu đi qua ba tầng khử trùng lặp, **xếp theo thứ tự chi phí tăng dần**.
>
> Tầng một và hai bắt lớp trùng hiển nhiên với chi phí gần bằng không.
>
> Tầng ba là tầng **duy nhất** bắt được lớp trùng nguy hiểm nhất — **cùng một bài toán được diễn đạt khác đi, hoặc chỉ thay số liệu**.
>
> Dòng dưới cùng giải thích vì sao phải dùng nhúng: nếu không có vector, hệ thống rơi về so trùng bằng mô hình ngôn ngữ **theo từng cặp** — đúng về chức năng, nhưng độ phức tạp lời gọi là **bậc hai** theo kích thước ngân hàng. **Ghi nhận vận hành** là bước này giảm từ khoảng 42 giây xuống khoảng 4 giây khi chuyển sang dùng nhúng.

*Nếu bị hỏi về câu cũ chưa có vector:* chúng được bổ sung tự động ngay trong lần so đầu tiên, nên không cần bước di trú dữ liệu riêng.

---

### Slide 26 — Khi phát hiện trùng: ai quyết?

*Trên màn hình:* Ba lựa chọn. Câu chốt cuối về nguyên tắc chung.

*Nói:*
> Khi phát hiện trùng, hệ thống **không tự động loại**. Nó trình bày cặp câu trùng kèm loại trùng và điểm số, rồi để người dùng chọn một trong ba.
>
> Lập luận: hai câu tương tự về ngữ nghĩa vẫn có thể **đều hữu ích** — ví dụ làm hai phiên bản của cùng một đề. Chỉ người dùng mới biết ý định sử dụng.
>
> Câu cuối là nguyên tắc chung của cả hệ thống: **khi hệ thống không chắc, nó chuyển việc cho con người kèm lý do — thay vì đoán.**

---

## Phần 7: Đối chiếu nghiên cứu — 3 phút

### Slide 27 — Dùng trực tiếp và có điều chỉnh

*Trên màn hình:* Bảng 10 dòng. Cột phải là "Hệ thống bổ sung gì".

*Nói:*
> Với mỗi kỹ thuật đi mượn, em đối chiếu xem hệ thống **bổ sung gì** so với bài báo gốc.
>
> **Ba dòng đầu là dùng trực tiếp** — nhưng cả ba đều là dùng một *công cụ* hoặc một *thang phân loại*, chứ không phải tái hiện một phương pháp nghiên cứu. Em cố tình giữ nhóm này rất hẹp.
>
> **Bảy dòng còn lại đều có bổ sung hoặc điều chỉnh.** Hai dòng đáng chú ý nhất:
>
> Dòng **kiểm chứng bằng chương trình**: điều chỉnh ở đây là về **bản chất** — chương trình *kiểm chứng* lời giải chứ không *thay thế* nó, tạo ra hai nguồn kết quả để đối chiếu.
>
> Dòng **học sở thích**: bỏ hoàn toàn phần huấn luyện, chỉ giữ tín hiệu và mục tiêu.

---

### Slide 28 — Cùng nguyên lý, hệ thống đi xa hơn

*Trên màn hình:* Bảng 9 dòng. Cột phải là "Hệ thống đi xa hơn ở đâu".

*Nói:*
> Nhóm thứ ba là những kỹ thuật **chia sẻ nguyên lý** với bài báo tương ứng, nhưng cách triển khai khác.
>
> Em giữ kỷ luật này rất chặt: **không khẳng định một kỹ thuật "lấy từ bài báo" nếu mã nguồn không chứng minh được**. Ví dụ dòng đầu: ý tưởng rất gần với hai bài báo về sinh nhiễu theo quan niệm sai lầm, nhưng họ **huấn luyện mô hình**, còn hệ thống đạt cùng mục tiêu mà **không cần huấn luyện**.
>
> Dòng đáng chú ý nhất là **đa tác tử cho AQG**: bốn bài báo cùng chia bài toán cho nhiều tác tử, nhưng cả bốn đều dùng khung thuần mô hình ngôn ngữ. Hệ thống này có **hai trong năm tác tử tất định**.

---

### Slide 29 — Nhìn lại sáu đóng góp ★

*Trên màn hình:* Bảng: mỗi đóng góp ↔ vấn đề nó giải quyết. Câu chốt ở dưới.

*Nói:*
> Và đây là slide chốt của phần đối chiếu — quay lại đúng sáu đóng góp em nêu ở slide 3, lần này gắn mỗi cái với **một vấn đề cụ thể**.
>
> Điểm em muốn nhấn: đây không phải sáu ý tưởng hay ho. Mỗi cái đều gắn với **một lỗi có thật** mà một kiến trúc thuần mô hình ngôn ngữ không xử lý được — đề có hai đáp án đúng, câu đúng nhưng dán nhầm nhãn, chuẩn đầu ra bị bỏ trống khi chạy song song.
>
> Ba đóng góp đầu chỉ khả thi vì có tầng kiểm chứng tất định — đó là lý do em nhấn mạnh tầng này từ đầu buổi.
>
> Và xin nhấn mạnh mức độ của khẳng định: **không tìm thấy tương đương trong phạm vi các tài liệu được cung cấp** — không phải "chưa từng có ai làm".

*Nếu bị hỏi về nguồn tài liệu:* 19 trong 32 tài liệu có sẵn toàn văn trong kho tài liệu của dự án. Số còn lại được trích dẫn theo danh mục tài liệu tham khảo của hệ thống; nội dung của chúng không được kiểm chứng lại trong phạm vi báo cáo này.

---

## Phần 8: Hướng phát triển và kết luận — 3 phút

### Slide 30 — Hướng phát triển

*Trên màn hình:* Ba mục tiêu. Mục 3 tô cam.

*Nói:*
> Hướng phát triển ưu tiên là một nghiên cứu đánh giá bởi chuyên gia đo lường giáo dục, với ba mục tiêu.
>
> Hiệu chuẩn các ngưỡng quyết định. Đo tương quan giữa điểm rubric của mô hình với đánh giá của con người.
>
> Và mục tiêu thứ ba là trung tâm: **kiểm định chính giả thuyết của thiết kế** — tầng kiểm chứng tất định nâng độ chính xác của bộ câu hỏi lên bao nhiêu so với một đường cơ sở thuần mô hình ngôn ngữ.
>
> Toàn bộ thiết kế đặt cược vào giả thuyết đó.

> **Ghi chú:** slide này có **kho dự phòng đầy đủ trong phần notes** — tám mục hạn chế. Xem phụ lục A.

---

### Slide 31 — Kết luận

*Trên màn hình:* Ba khối, cả ba đều gắn nhãn ◆ Đóng góp.

*Nói:*
> Xin tóm lại bằng ba đặc điểm phân biệt hệ thống này với các hệ AQG trong các tài liệu em khảo sát — và cả ba đều dẫn về phần đóng góp.
>
> **Một — hệ thống khai thác tính kiểm chứng được của môn Toán như một tài sản kiến trúc.** Hai trong năm tác tử tất định. Đáp án được máy tính lại. Đa đáp án được phát hiện bằng cách chạy chính bộ kiểm chứng ấy trên các phương án nhiễu. **Ba trong sáu đóng góp mở ra từ đây.**
>
> **Hai — hệ thống nhất quán trong việc biến các phẩm chất chủ quan thành mệnh đề kiểm chứng được.** Bám nguồn thành trích dẫn nguyên văn đối chiếu được. Tính hợp lý của nhiễu thành yêu cầu mô tả lỗi phải ra đúng giá trị. Điểm rubric thành nhận định viết trước điểm. Trong cả ba, hệ thống **không hỏi mô hình "cái này có tốt không"** — nó buộc mô hình tạo ra một **dấu vết mà một cơ chế khác có thể kiểm tra lại**.
>
> **Ba — hệ thống xử lý sự không chắc chắn bằng phân luồng, thay vì bằng loại bỏ.** "Không khớp không phải là sai", fail-open, tự sửa đáp án, và trao quyền quyết định cuối cùng cho người dùng — tất cả theo cùng một nguyên tắc: **khi hệ thống không chắc, nó chuyển việc cho con người kèm lý do, thay vì đoán.**
>
> Các đánh đổi đều được chấp nhận có ý thức — token cao do đính kèm toàn văn, chi phí sinh lại thay vì sửa, độ trễ của chuỗi năm tác tử — tất cả đổi lấy **khả năng kiểm soát** và **khả năng truy vết**.
>
> Em xin hết. Rất mong nhận được câu hỏi của thầy cô.

---

### Slide 32–33 — Tài liệu tham khảo

Không trình bày. Để dành tra cứu khi hỏi đáp.

### Slide 34 — Cảm ơn

Dừng ở đây trong lúc hỏi đáp.

---

## Phụ lục A — Kho hạn chế (chỉ nói khi bị hỏi)

Phần này đã được **rút khỏi slide** theo chủ ý. Nó cũng nằm trong ghi chú của slide 30. Nếu bị hỏi trúng mục nào thì trả lời thẳng mục đó — đừng vòng vo, vì các hạn chế này đều đã được ghi rõ trong báo cáo.

**1. Ngưỡng chưa hiệu chuẩn.** Các ngưỡng loại (0,4 / 0,5 / 0,4) và khử trùng lặp (0,85 / 0,82) là giá trị chọn theo phán đoán kỹ thuật. Không thể xác nhận từ mã nguồn hoặc tài liệu được cung cấp rằng chúng đã được hiệu chuẩn trên dữ liệu gán nhãn của con người. → Mục tiêu 1 ở slide 30.

**2. Chưa có đánh giá thực nghiệm.** Mọi con số nêu trong bài là ghi nhận vận hành. Không có đánh giá so sánh với đường cơ sở, không có nghiên cứu đánh giá bởi con người. → Mục tiêu 2 và 3 ở slide 30.

**3. Giới hạn phạm vi — nghiêm túc nhất.** Tầng kiểm chứng tất định chỉ áp dụng được cho câu hỏi có đáp án tính lại được bằng máy. Với câu khái niệm, nhận định hay chứng minh, tầng kiểm chứng tự vô hiệu hoá và hệ thống thoái hoá về một pipeline sinh–chấm thuần mô hình ngôn ngữ. Mức hưởng lợi tỉ lệ thuận với tỉ trọng câu hỏi tính toán — đại lượng này hiện không được báo cáo lại cho người dùng.

**4. Phụ thuộc mô hình.** Ba trong năm tác tử phụ thuộc một mô hình đa phương thức bên ngoài. Hỗ trợ nhiều nhà cung cấp là khả năng *thay thế*, không phải *độc lập*. Đọc PDF nguyên bản là yêu cầu cứng.

**5. Chi phí.** Ba lời gọi cho một câu thành công, và đó là *cận dưới* — câu bị loại ở tầng chấm đã tiêu trọn ba lời gọi. Mỗi lời gọi mang theo toàn bộ tài liệu. Chạy song song cải thiện độ trễ (khoảng 28 giây/câu so với 51 giây tuần tự) nhưng không giảm chi phí.

**6. Sai lệch đánh giá.** Giám khảo và thí sinh cùng họ mô hình nên thiên lệch có thể tương quan. Fail-open làm loãng tín hiệu: điểm của một số câu phản ánh sự cố hạ tầng chứ không phải chất lượng thật.

**7. Tài liệu đầu vào.** Không có nhận dạng ký tự quang học, nên tài liệu quét mờ làm hỏng khâu đọc mà không có cảnh báo rõ ràng. Tài liệu dài bị cắt theo giới hạn số trang.

**8. Giới hạn khác.** Ngôn ngữ (toàn bộ tài nguyên viết cho tiếng Việt). Danh mục quan niệm sai lầm dựng thủ công. Đổi môn học phải định nghĩa lại toàn bộ tầng kiểm chứng.

---

## Phụ lục B — Sáu câu hỏi dễ gặp nhất

**1. "Đâu là đóng góp của em, đâu là của người ta?"**
→ Câu này deck đã chuẩn bị sẵn: slide 3 nêu trước sáu đóng góp, slide 27–28 liệt kê rõ cái gì mượn từ đâu và hệ thống bổ sung gì, slide 29 tổng kết. Trả lời bằng cách quay lại slide 29.

**2. "Mô hình tự sinh biểu thức kiểm chứng thì có tự lừa mình không?"**
→ Câu hỏi đúng trọng tâm nhất. Trả lời trung thực: **có rủi ro đó**, và chính sách "không khớp ≠ sai" ra đời vì rủi ro đó. Nhưng biểu thức được **chạy thật bởi một thư viện độc lập**, nên nó vẫn là một nguồn kết quả thứ hai — mô hình không thể quyết định kết quả của phép tính. Đó là khác biệt so với việc để mô hình tự chấm.

**3. "Ngưỡng 0,4 / 0,85 / 0,82 lấy ở đâu ra?"**
→ Phụ lục A mục 1. Trả lời thẳng: chọn theo phán đoán kỹ thuật, chưa hiệu chuẩn trên dữ liệu gán nhãn của con người. Đây là mục tiêu số một ở slide 30.

**4. "Có so sánh với hệ thống nào khác chưa? Có số liệu không?"**
→ Phụ lục A mục 2. Chưa. Mọi con số trong bài là ghi nhận vận hành. Đây là khoảng trống lớn nhất, và là lý do slide 30 tồn tại.

**5. "Sao không cho agent sửa lại câu sai cho đỡ tốn?"**
→ Slide 21. Hai lập luận: chi phí một vòng sửa xấp xỉ sinh mới; và quan trọng hơn — vá cục bộ làm bất nhất các ràng buộc chéo, tức là tự tạo ra đúng lớp lỗi mà hệ thống đang cố phát hiện. Nếu bị truy "đã đo chưa": chưa so sánh thực nghiệm.

**6. "Sao không dùng RAG / chia đoạn tài liệu?"**
→ Slide 12. Vì bố cục, ký hiệu toán học, bảng và hình bị phá huỷ khi trích văn bản thô. Đánh đổi là token cao và giới hạn độ dài. Có bài báo (Savaal) đi hướng trích khái niệm; hệ thống chọn hướng khác.

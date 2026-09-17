# Hai bộ tiêu chí đánh giá câu hỏi được sinh tự động

Tóm tắt tập trung vào **tiêu chí đánh giá**, bỏ qua phần mô hình và số liệu không
liên quan. Nguồn: hai tệp trong cùng thư mục này.

| | QGEval | Moore et al. |
| --- | --- | --- |
| Tệp | `QGEval-2406.05707.pdf` | `MCQ-quality-GPT4-rulebased-2307.08161.pdf` |
| Nơi công bố | EMNLP 2024 (tr. 11783–11803) | ECTEL 2023 (tr. 229–245) |
| Nhóm | Fu, Wei, Hu, Cai, Liu — Xi'an Jiaotong University | Moore, Nguyen, Chen, Stamper — Carnegie Mellon |
| Đối tượng | Câu hỏi tự luận ngắn sinh từ đoạn văn | Câu hỏi **trắc nghiệm** 4 phương án |
| Hình thức | **7 chiều, thang 1–3** (càng cao càng tốt) | **19 lỗi, nhị phân** có/không |
| Ngưỡng kết luận | Không có ngưỡng; báo cáo điểm trung bình | **≤1 lỗi = dùng được, ≥2 = không dùng được** |
| Ai chấm | 3 học viên cao học, 2 vòng | 2 chuyên gia có kinh nghiệm soạn đề |

Hai bộ **bổ sung** nhau chứ không thay thế: QGEval đo *chất lượng diễn đạt và
quan hệ với ngữ liệu*, Moore đo *lỗi kỹ thuật soạn đề trắc nghiệm*. Không bộ nào
kiểm tra đáp án có đúng về mặt toán học hay không — đó là khoảng trống mà cả hai
đều để ngỏ.

---

# PHẦN 1 — QGEval: 7 chiều, thang 1–3

## 1.1 Vì sao là 7 chiều

Họ lấy 100 câu sinh ra, phân tích lỗi bằng tay, thấy **42% có lỗi ở mức nào đó**,
rồi phân loại thành hai nhóm và bàn với hai chuyên gia giáo dục để chốt 7 chiều.

Bảng tỉ lệ loại lỗi họ tìm được (một câu có thể dính nhiều lỗi):

| Loại lỗi | Tỉ lệ |
| --- | --- |
| Lệch với đáp án cho trước | 47,62% |
| Mơ hồ | 30,95% |
| Hỏi thông tin không có trong đoạn văn | 19,05% |
| Chép thừa từ đoạn văn | 16,67% |
| Diễn đạt sai ngữ pháp | 7,14% |
| Mâu thuẫn với đoạn văn | 4,76% |
| Không phải câu hỏi (câu trần thuật, câu cụt) | 2,38% |

Hai nhóm chiều:

- **Nhóm ngôn ngữ** (yêu cầu cơ bản của một văn bản): fluency, clarity,
  conciseness.
- **Nhóm tác vụ** (quan hệ với đoạn văn và đáp án): relevance, consistency,
  answerability, answer consistency.

Họ chứng minh bằng tương quan Pearson + kiểm định Nemeyi rằng 7 chiều **liên hệ
với nhau nhưng vẫn phân biệt được** (tương quan 0,04–0,67). Đáng chú ý: chiều
ngôn ngữ **kéo theo** chiều tác vụ — clarity thấp và consistency thấp thì
answerability tụt theo.

## 1.2 Mô tả neo từng mức điểm (Bảng 7 — phần quan trọng nhất)

Đây là thứ cần bám sát nếu muốn chấm lại theo đúng chuẩn của họ. Dịch sát nghĩa,
giữ nguyên cấu trúc.

### Nhóm ngôn ngữ

**Fluency — độ trôi chảy**
- **1**: Câu hỏi rời rạc, dùng từ thiếu chính xác hoặc sai ngữ pháp nghiêm trọng,
  khó hiểu được ý nghĩa.
- **2**: Hơi thiếu mạch lạc hoặc có lỗi ngữ pháp nhỏ, nhưng không cản trở việc
  hiểu ý câu hỏi.
- **3**: Trôi chảy và đúng ngữ pháp.

**Clarity — độ rõ ràng**
- **1**: Câu hỏi quá rộng hoặc diễn đạt gây rối, khó hiểu hoặc dẫn tới mơ hồ.
  *Đặc biệt: nếu câu sinh ra không phải câu hỏi mà là câu trần thuật thì xếp vào
  mức này.*
- **2**: Không diễn đạt thật rõ và thật cụ thể, nhưng vẫn suy ra được ý câu hỏi
  dựa vào đoạn văn.
- **3**: Rõ ràng, cụ thể, không mơ hồ.

**Conciseness — độ súc tích**
- **1**: Chứa quá nhiều thông tin thừa, khó nhận ra ý định của câu hỏi.
- **2**: Có một ít thông tin thừa nhưng không ảnh hưởng tới việc hiểu.
- **3**: Súc tích, không có thông tin không cần thiết.

### Nhóm tác vụ

**Relevance — độ liên quan**
- **1**: Hoàn toàn không liên quan tới đoạn văn.
- **2**: Có liên quan phần nào nhưng hỏi vào thông tin **không cốt yếu**.
- **3**: Liên quan tới ngữ cảnh và hỏi vào thông tin cốt yếu của đoạn văn.

**Consistency — độ nhất quán**
- **1**: Mâu thuẫn về sự kiện với đoạn văn, hoặc sai logic.
- **2**: Thông tin mà câu hỏi nhắm tới **không được mô tả đầy đủ** trong đoạn văn.
- **3**: Thông tin trong câu hỏi hoàn toàn nhất quán với đoạn văn.

**Answerability — khả năng trả lời được**
- **1**: Không trả lời được dựa trên đoạn văn đã cho.
- **2**: Trả lời được **một phần**, hoặc đáp án chỉ suy ra được ở mức độ nào đó.
- **3**: Trả lời được **dứt khoát** dựa trên đoạn văn.

**Answer Consistency — khớp với đáp án cho trước**
- **1**: Không thể trả lời bằng đáp án đã cho.
- **2**: Đáp án đã cho trả lời được **một phần**.
- **3**: Trả lời được **trực tiếp** bằng đáp án đã cho.

## 1.3 Cách họ tổ chức chấm — điểm cần bắt chước

- **3 người chấm độc lập, lấy trung bình.** Vì vậy điểm ví dụ của họ có giá trị
  lẻ như 1,3333 hay 2,6667.
- **Hai vòng.** Vòng 2 người chấm xem lại các mẫu có thể đã chấm sai: (i) cùng
  một câu mà mình cho điểm khác nhau giữa các lần; (ii) mẫu mà mình lệch 2 điểm
  so với hai người kia trong khi hai người kia giống nhau; (iii) mẫu mà cả ba
  cho 1, 2, 3 khác nhau hoàn toàn.
- **Trình bày cùng lúc 15 câu của cùng một đoạn văn** rồi chấm tuần tự — họ nói
  cách này giúp câu tương tự nhận điểm tương tự.
- **Người chấm không biết câu nào của mô hình nào.**
- Có chạy thử 100 mẫu trước, hai chuyên gia giáo dục soát lại rồi mới chấm thật.
- Sau khi xong, lấy ngẫu nhiên 100 mẫu cho hai chuyên gia soát: độ chính xác của
  nhãn **trên 96%** ở mọi chiều.

**Độ đồng thuận (Krippendorff α) — con số để đối chiếu:**

| Vòng | Flu. | Clar. | Conc. | Rel. | Cons. | Ans. | AnsC. |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Vòng 1 | 0,226 | 0,375 | 0,515 | 0,233 | 0,181 | 0,354 | 0,559 |
| Vòng 2 | 0,427 | 0,576 | 0,755 | 0,437 | 0,445 | 0,661 | 0,800 |

Vòng 1 thấp đáng kể. Chỉ sau vòng rà soát thứ hai α mới lên **0,427–0,800**. Đây
là dải giá trị hợp lý để so sánh — bất kỳ α nào thấp hơn 0,427 thì dòng đó không
đáng tin.

## 1.4 Kết quả họ tìm được (3000 câu, 15 mô hình, 200 đoạn văn)

- **Điểm trung bình mọi chiều đều trên 2**, phần lớn nhãn là 3.
- **Hai chiều yếu nhất là answerability (2,794) và answer consistency (2,588).**
  Ba chiều gần trần: relevance 2,991, fluency 2,967, cons. 2,930.
- Ngay cả **câu tham chiếu do người viết** cũng chỉ đạt trung bình 2,916 — tức
  thang này khó đạt điểm tuyệt đối kể cả với người.
- Mô hình tốt nhất: GPT-4-fewshot (2,929) — **ngang mức câu do người viết**.
- **Bộ tiêu chí có sức phân biệt hạn chế**: trừ answer consistency, năm mô hình
  tốt nhất không khác biệt có ý nghĩa so với năm mô hình kém nhất ở sáu chiều
  còn lại. Họ tự nêu đây là hạn chế và kêu gọi tìm chiều phân biệt mạnh hơn.
- **Mọi độ đo tự động đều tương quan yếu với điểm người** (Pearson −0,4 đến 0,4).
  Độ đo dựa trên LLM tốt hơn nhưng vẫn dưới 0,4 (G-EVAL với GPT-4: 0,356).

## 1.5 Hai hạn chế họ tự nêu

1. Chỉ áp dụng cho tình huống **sinh câu hỏi từ một đoạn văn cộng một đáp án**;
   không áp dụng cho câu hỏi ảnh hay hội thoại. Chiều "độ phức tạp" (suy luận
   nhiều bước) không có trong bộ này.
2. Sức phân biệt giữa các mô hình yếu, như nói ở trên.

---

# PHẦN 2 — Moore et al.: 19 lỗi soạn đề trắc nghiệm

## 2.1 Bối cảnh

Rubric **Item-Writing Flaws (IWF)** rút gọn từ **31 hướng dẫn soạn trắc nghiệm
của Haladyna**. Bản họ dùng gồm **19 mục**, đã được dùng và kiểm định ở các
nghiên cứu trước.

- Dữ liệu: **200 câu trắc nghiệm do sinh viên viết**, 50 câu từ mỗi môn trong
  bốn môn: Hóa đại cương, Hóa sinh, Thống kê, và một môn kỹ năng cộng tác.
- **Ngưỡng: 0 hoặc 1 lỗi = chấp nhận được; từ 2 lỗi trở lên = không chấp nhận
  được.** Ngưỡng này quyết định câu có được dùng làm bài kiểm tra hình thành hay
  không.
- Hai người chấm, sau đó họp giải quyết mọi bất đồng đến khi thống nhất.

## 2.2 Bảng 19 lỗi

Cột mô tả là **đặc điểm của câu KHÔNG mắc lỗi** (nguyên bản họ viết theo hướng
này), kèm % đồng thuận và Cohen's κ giữa hai người chấm.

| # | Lỗi | Câu không mắc lỗi thì phải… | Đồng thuận / κ |
| --- | --- | --- | --- |
| 1 | Ambiguous or unclear information | Đề và mọi phương án viết bằng ngôn ngữ rõ ràng, không mơ hồ | 87,5% / 0,66 |
| 2 | Implausible distractors | Mọi phương án nhiễu đều hợp lý — câu tốt phụ thuộc vào nhiễu hiệu quả | 96,0% / 0,82 |
| 3 | None of the above | Tránh "không phương án nào đúng" vì nó chỉ đo được khả năng loại trừ | 100% / 1,00 |
| 4 | Longest option correct | Tránh để phương án đúng dài hơn và chi tiết hơn, thành gợi ý cho thí sinh | 97,0% / 0,83 |
| 5 | Gratuitous information | Tránh thông tin thừa trong đề không cần để trả lời | 89,5% / 0,71 |
| 6 | True/false question | Các phương án không được là một dãy mệnh đề đúng/sai | 100% / 1,00 |
| 7 | Convergence cues | Tránh gợi ý hội tụ — các phương án là những tổ hợp khác nhau của nhiều thành phần | 89,5% / 0,70 |
| 8 | Logical cues | Tránh manh mối trong đề và phương án đúng giúp thí sinh khôn ngoan đoán ra | 88,0% / 0,68 |
| 9 | All of the above | Tránh "tất cả đều đúng" vì đoán được từ thông tin bộ phận | 100% / 1,00 |
| 10 | Fill-in-blank | Tránh khoét từ ở **giữa** đề để thí sinh điền từ phương án | 100% / 1,00 |
| 11 | Absolute terms | Tránh từ tuyệt đối (không bao giờ, luôn luôn, tất cả) trong phương án — thí sinh biết chúng gần như luôn sai | 100% / 1,00 |
| 12 | Word repeats | Tránh lặp từ giữa đề và phương án đúng | 97,0% / 0,83 |
| 13 | Unfocused stem | Đề phải nêu một câu hỏi rõ và tập trung, **hiểu và trả lời được mà không cần nhìn phương án** | 94,5% / 0,79 |
| 14 | Complex or K-type | Tránh câu có nhiều đáp án đúng, bắt chọn trong các tổ hợp | 94,0% / 0,78 |
| 15 | Grammatical cues | Mọi phương án phải nhất quán ngữ pháp với đề, song song về văn phong và hình thức | 92,5% / 0,76 |
| 16 | Lost sequence | Mọi phương án phải sắp theo **thứ tự thời gian hoặc thứ tự số** | 97,5% / 0,89 |
| 17 | Vague terms | Tránh từ mơ hồ (thường xuyên, thỉnh thoảng) vì ít khi thống nhất được nghĩa thực | 98,5% / 0,93 |
| 18 | More than one correct | Ở dạng chọn một đáp án tốt nhất, phải có **đúng một** đáp án tốt nhất | 100% / 1,00 |
| 19 | Negative worded | Đề phủ định ít đo được kết quả học tập quan trọng và gây rối cho thí sinh | 100% / 1,00 |

## 2.3 Kết quả

**Chất lượng câu do sinh viên viết:** người chấm xác định **111 chấp nhận được,
89 không chấp nhận được** — tức **gần một nửa không dùng được**. Số lỗi trung
bình mỗi câu: 1,6 (người), 2,1 (luật), 4,2 (GPT-4).

**Lỗi phổ biến nhất theo từng phương pháp:**
- Người chấm: **implausible distractors** (nhiễu không hợp lý) — nhiều nhất ở cả
  bốn môn. Ít nhất: vague terms.
- Luật: convergence cues nhiều nhất.
- GPT-4: ambiguous/unclear information nhiều nhất.

**So sánh máy với người:**

| | Luật | GPT-4 |
| --- | --- | --- |
| Khớp trên toàn bộ 3800 phân loại nhị phân | 90,87% | 78,89% |
| Khớp **hoàn toàn cả 19 tiêu chí** của một câu | 15% | 12% |
| Hamming loss | 0,09 | 0,21 |
| Khớp kết luận **dùng được / không dùng được** | 130/200 = **65%** | 123/200 = **62%** |
| F1 trung bình vi mô theo môn | 0,30 · 0,48 · 0,56 · 0,70 | 0,25 · 0,28 · 0,30 · 0,36 |

**Luật thắng GPT-4 ở cả bốn môn.** Cả hai đều **khắt khe hơn người** — gán nhiều
lỗi hơn; GPT-4 có câu bị gán tới 13 lỗi trong khi người và luật không bao giờ
vượt 6.

**Chỗ máy làm tốt:** none of the above, negative worded, longest option correct,
true/false — đều là tiêu chí kiểm được bằng độ dài chuỗi và từ khoá.
**Chỗ máy làm tệ:** logical cues, more than one correct, gratuitous information,
unfocused stem, vague terms.

**Ảnh hưởng của lĩnh vực:** cả hai phương pháp làm tệ hơn ở Hóa và Hóa sinh so
với Thống kê — vì hai môn đó nhiều thuật ngữ và danh từ riêng, làm kỹ thuật xử
lý ngôn ngữ kém hiệu quả. Họ cũng nhận xét **lost sequence phù hợp hơn với môn
có phương án thuần số** như Hóa và Thống kê.

## 2.4 Cách họ hiện thực

- **14–15 tiêu chí bằng luật thuần**: xử lý chuỗi, nhận dạng thực thể, gán nhãn
  từ loại.
- Một số tiêu chí khó phải nhờ mô hình: *ambiguous or unclear information* dùng
  bộ phân loại RoBERTa huấn luyện trên CoLA; *more than one correct* dùng GPT-4
  trả lời câu hỏi.
- Với GPT-4, họ đưa **từng tiêu chí một** kèm định nghĩa, hỏi có/không, và **bắt
  giải thích lý do** — họ nói việc bắt giải thích làm câu trả lời kỹ hơn. Chỉ
  "yes/no" trần thì nhiều khi không rõ là vi phạm hay thoả mãn.

---

# PHẦN 3 — Lưu ý khi trích dẫn hai bài này

**1. Con số "91% / 79%" của Moore et al. KHÔNG phải là recall trên lỗi.**
Đó là tỉ lệ khớp trên **3800 phân loại nhị phân** (200 câu × 19 tiêu chí), mà
phần lớn trong số đó là "không mắc lỗi" ở cả hai phía. Chỉ số đó bị chi phối bởi
âm tính thật nên cao một cách tự nhiên. Muốn nói về khả năng **phát hiện lỗi**
thì phải dùng F1 trung bình vi mô: **0,30–0,70 cho luật** và **0,25–0,36 cho
GPT-4**. Hai chỉ số này chênh nhau rất xa, và trích nhầm sẽ làm hệ thống của mình
trông kém hơn thực tế nhiều.

**2. α của QGEval là giữa BA NGƯỜI chấm, không phải giữa nhiều lượt của một mô
hình.** Chấm cùng một mô hình nhiều lượt rồi tính α chỉ cho **cận trên** của độ
tin cậy — nó đo mô hình có tự nhất quán không, chứ không đo hai người có đồng ý
với nhau không. Khi đối chiếu với dải 0,427–0,800 của họ phải nói rõ điều này.

**3. QGEval chấm trên TOÀN ĐOẠN VĂN.** Ba chiều relevance, consistency,
answerability đều định nghĩa theo đoạn văn nguồn. Nếu chỉ lưu một câu trích dẫn
làm ngữ cảnh thì ba chiều đó bị chấm trên ngữ cảnh hẹp hơn nhiều so với thiết
kế của thang — điểm thấp có thể do lưu trữ chứ không do câu hỏi.

**4. Cả hai đều không kiểm tra đáp án có đúng hay không.** QGEval hỏi "trả lời
được bằng đáp án cho trước không", giả định đáp án cho trước là đúng. Moore hỏi
"có nhiều hơn một đáp án đúng không", không hỏi đáp án được đánh dấu có đúng
không. Với câu hỏi toán, tính đúng đắn của đáp án là chiều **cả hai bộ đều
thiếu**.

**5. Ngưỡng ≤1 lỗi là của Moore, đừng tự đặt lại.** Nếu sửa ngưỡng thì tỉ lệ
"dùng được" không còn so sánh được với con số nào trong tài liệu.

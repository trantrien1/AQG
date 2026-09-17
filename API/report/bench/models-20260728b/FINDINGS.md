# Quét mô hình nhỏ — kết quả và cách đọc

Tài liệu: `pdftest/file_3_trang_61-90.pdf` (30 trang). 20 câu yêu cầu mỗi ô.

## Bố trí

Mọi ô giống nhau trừ **một** thứ là mô hình sinh:

| yếu tố | giá trị | vì sao phải cố định |
|---|---|---|
| tài liệu tới mô hình | ảnh trang (30 ảnh) | mẫu số chung duy nhất mọi nhà đều làm được như nhau; để mô hình thiếu modality `file` tụt xuống trích text là đổi luôn bài toán |
| trần token mỗi lời gọi | 4000 | trần cũ hiệu chỉnh theo độ dài lời văn của OpenAI; mô hình viết dài hơn bị cắt rồi bị tính nhầm là "sinh kém" |
| ngân sách lượt thử | bỏ cuộc sau 60 slot hỏng liên tiếp ⇒ mọi ô dùng hết trần 46 lượt | mặc định dừng sau `max(4, n//3)` slot hỏng liên tiếp, mà chuỗi này reset khi thành công ⇒ mô hình yếu được thử ÍT lượt hơn mô hình khoẻ |
| bộ giải độc lập | `openai/gpt-4.1-mini`, cố định | nếu để nó bám mô hình sinh thì quét bộ sinh sẽ kéo tầng kiểm chứng đổi theo |
| Critic (chấm chất lượng) | = chính mô hình của ô | chủ ý: đo CẢ HỆ THỐNG chạy trên một mô hình nhỏ, không phải xếp hạng bộ sinh dưới một giám khảo chung |

## Bảng

| mô hình | giao ra | lượt thử | nhận/lượt | kiểm chứng độc lập xác nhận | không kiểm được | lệch | token |
|---|---|---|---|---|---|---|---|
| `qwen/qwen3-vl-8b-instruct` | 1 | 46 | 2% | **0** | 1 | 0 | 3,6 M |
| `qwen/qwen3-vl-32b-instruct` | 0 | 46 | 0% | **0** | 0 | 0 | 2,3 M |
| `meta-llama/llama-4-scout` | 1 | 46 | 2% | **0** | 0 | 1 | 7,4 M |
| `openai/gpt-4.1-nano` | 3 | 46 | 7% | **0** | 3 | 0 | 9,1 M |
| *`gpt-4o-mini` (mốc cũ, chat2api)* | *10* | *18* | *56%* | ***10*** | *0* | *0* | *0,27 M* |

Mốc `gpt-4o-mini` chạy chế độ đính file qua chat2api, **không** cùng cách đưa
tài liệu, nên chỉ dùng làm tham chiếu độ lớn chứ không phải một ô của phép quét.
Ô đối chứng cùng chế độ, cùng họ OpenAI là `gpt-4.1-nano`.

## Ba điều số liệu nói

**1. Không câu nào trong cả bốn ô được kiểm chứng độc lập xác nhận.** Tổng cộng
5 câu giao ra: 4 `non_verifiable`, 1 `mismatch`. "Giao ra" và "giao ra và kiểm
chứng được" là hai con số khác nhau, và ở hạng mô hình này con số thứ hai bằng 0.

**2. Rào cản là CỠ mô hình, không phải nhà cung cấp.** `gpt-4.1-nano` cùng hạng
giá $0.1, cùng họ với mô hình mà toàn bộ hệ thống được dựng lên cùng, chạy cùng
cấu hình — vẫn chỉ 7%/lượt và 0 câu được xác nhận. Không có ô đối chứng này thì
mọi thất bại đều đổ được cho "không phải OpenAI".

**3. Giám khảo LLM gần như không tham gia vào các lượt loại.** Trên 179 lượt
loại, tầng Critic chỉ gây ra **1**. Phần còn lại:

| nguyên nhân | số lượt | bản chất |
|---|---|---|
| `writer_empty` | 55 | mô hình không sinh nổi JSON hợp lệ |
| `quote_mismatch` | 70 | luật tất định về trích dẫn nguồn |
| `bad_distractors` | 13 | thiếu trường mô tả lỗi, kiểm bằng code |
| `format_error` (option quá dài) | 18 | luật tất định |
| `duplicate` | 12 | dedup |
| **Critic (LLM chấm)** | **1** | |

Nghĩa là việc Critic đổi theo ô — một biến thứ hai thay đổi cùng mô hình sinh —
về số liệu gần như không tác động. Rủi ro của giám khảo yếu nằm ở chiều ngược
lại (cho qua bừa), và đó đúng là việc của tầng kiểm chứng độc lập đã ghim cố định.

## Một cổng cần soát lại

Trong 70 lượt mang mã `quote_mismatch`, có **20 lượt bị loại CHỈ vì trích dẫn
dài quá 350 ký tự** — không kèm bất kỳ lỗi nào khác. Độ dài bị loại: nhỏ nhất
351, trung vị **367**, tức vượt trần trung bình 17 ký tự. Prompt yêu cầu 15–250
ký tự còn luật chặn ở 350, nên đây là khoảng chênh giữa điều được dặn và điều bị
cưỡng chế.

20/184 lượt ≈ 11%. Nếu nới riêng trần này thì 20 ứng viên đó được đi tiếp — chứ
**không** phải tự động được nhận, vì phía sau còn dedup, distractor validator và
kiểm chứng độc lập. Nên 11% là **cận trên** của phần thất bại quy cho một luật
định dạng, không phải mức cải thiện dự đoán được.

Kiểu hỏng riêng của `qwen3-vl-32b`: nó **không dừng được** — tự sửa lòng vòng
trong một trường JSON ("Không gọn. Có lẽ ta nên chọn...") cho tới khi đụng trần,
nên 36/46 lượt chết ở `writer_empty`. Nới trần 3000→8000 làm nó **tệ hơn** (dump
7,7 KB → 21 KB), đúng phép thử phân biệt: nới ngân sách mà điểm giảm thì lỗi
thuộc về mô hình, không thuộc về cấu hình.

## Đã loại khỏi phép quét, kèm lý do

- `mistralai/mistral-small-3.2-24b-instruct` — nhà cung cấp chặn cứng 5–8 ảnh
  mỗi prompt; tài liệu 30 trang không tới được. Giới hạn hạ tầng.
- `z-ai/glm-4.6v` — mô hình có suy luận; phần suy luận tiêu vào chính trần token
  của câu trả lời nên trả về rỗng. Một trần duy nhất không thể vừa công bằng cho
  mô hình trả lời thẳng vừa cho mô hình suy luận.
- họ Gemini — bỏ theo yêu cầu.

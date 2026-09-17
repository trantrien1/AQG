# Quét với PDF nguyên bản — kết quả

Tài liệu `pdftest/file_3_trang_61-90.pdf` (30 trang), 20 câu yêu cầu mỗi ô,
46 lượt thử mỗi ô, trần 4000 token, bộ giải độc lập `openai/gpt-4.1-mini`.
Tài liệu tới mô hình dạng **PDF nguyên bản** (`raw_pdf_native`, engine ghim
`native`) — đúng cách hệ thống được thiết kế.

| mô hình | $/1M vào | nhận/lượt | khớp nhất quán | lệch | không kiểm được | bác bỏ |
|---|---|---|---|---|---|---|
| `amazon/nova-2-lite-v1` | 0,30 | 4% | 1 | 0 | 0 | 1 |
| `openai/gpt-4.1-nano` | 0,10 | 9% | 2 | 0 | 2 | 0 |
| `openai/gpt-4.1-mini`\* | 0,40 | 15% | 5 | 2 | 0 | 0 |
| `openai/gpt-4o-mini` | 0,15 | **17%** | 3 | 3 | 2 | 0 |

\* Ô này có khiếm khuyết: `gpt-4.1-mini` chính là mô hình đang đóng vai bộ giải
độc lập, nên ở ô đó nó tự kiểm chứng chính mình. Cột *nhận/lượt* vẫn dùng được
(gần như toàn bộ lượt loại đến từ cổng tất định), nhưng các cột kiểm chứng của
riêng ô này **không so được** với ô khác.

Ô `mistralai/mistral-medium-3.1` chưa chạy — hết hạn mức trước khi tới lượt.

## A/B cách đưa tài liệu — câu hỏi đã đặt ra

Cùng `gpt-4.1-nano`, cùng mọi tham số, chỉ đổi cách tài liệu tới mô hình:

| | nhận/lượt | khớp nhất quán | không kiểm được |
|---|---|---|---|
| ảnh từng trang | 7% | **0** | 3 |
| PDF nguyên bản | 9% | **2** | 2 |

Tỉ lệ nhận gần như không đổi (7% → 9%), nhưng **chất lượng kiểm chứng thì đổi
thật**: từ 0 câu được xác nhận lên 2. Nghĩa là ảnh trang **không phải** nguyên
nhân chính của tỉ lệ nhận thấp — kết luận cũ về ngưỡng cỡ mô hình vẫn đứng — 
nhưng nó có làm hỏng khả năng bám tài liệu đủ để không câu nào qua nổi kiểm
chứng. Hai điều này phải nói tách nhau.

## Ngưỡng nằm ở đâu

Thang trong cùng nhà OpenAI, cùng chế độ, cùng ngân sách lượt thử:

    gpt-4.1-nano  $0,10  ->   9%
    gpt-4o-mini   $0,15  ->  17%
    gpt-4.1-mini  $0,40  ->  15%

Bậc nhảy nằm giữa `nano` và `mini`; từ `4o-mini` lên `4.1-mini` thì phẳng.
`amazon/nova-2-lite-v1` ở 4% cho thấy hiệu ứng không chỉ thuộc về giá: nó đắt
gấp ba `gpt-4.1-nano` mà nhận thấp hơn.

Một điểm cần thận trọng: `gpt-4o-mini` từng đạt 10/18 lượt (56%) khi chỉ yêu cầu
10 câu, nay 8/46 (17%) khi yêu cầu 20 câu từ **cùng một tài liệu**. Càng đòi
nhiều câu từ một tài liệu thì tỉ lệ nhận càng giảm, vì cơ chế chống trùng phải
né mọi câu đã nhận. Nên **tỉ lệ nhận không so được giữa hai lượt chạy có số câu
yêu cầu khác nhau** — đây là biến thứ ba, sau chế độ tài liệu và ngân sách lượt
thử.

## Chi phí — tôi ước tính sai 3,7 lần

Dự $1,7 cho hai ô thang OpenAI, thực tế **$6,22**. Nguyên nhân: tôi suy chi phí
mỗi lượt từ smoke test, mà smoke test toàn lượt HỎNG SỚM — hỏng ở Writer thì
không có lời gọi Distractor/Critic/kiểm chứng độc lập nào theo sau. Mô hình càng
thành công thì mỗi lượt càng nhiều lời gọi và càng đắt: `gpt-4o-mini` dùng 170
lời gọi cho 46 lượt (3,7 lời gọi/lượt) ở ~102k token mỗi lời gọi = 17,4M token.

Cache không kéo được con số đó xuống ở chế độ file với các mô hình này.

Số dư còn **$0,70**.

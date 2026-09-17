# Quét mô hình sinh — pdftest/file_3_trang_61-90.pdf

- 20 câu yêu cầu mỗi ô, tài liệu tới mô hình dạng **ảnh trang**
- trần token mỗi lời gọi: **4000** (chung cho mọi ô)
- bộ giải độc lập cố định: `openai/gpt-4.1-mini`
- ngân sách lượt thử chung: bỏ cuộc sau **60** slot hỏng liên tiếp

| mô hình | giao ra | lượt thử | nhận/lượt thử | kiểm chứng độc lập | khớp nhất quán | lệch | không kiểm được | lời gọi | token | phút |
|---|---|---|---|---|---|---|---|---|---|---|
| `openai/gpt-4o-mini` | 8/20 | 46 | **17%** | 0 | 3 | 3 | 2 | 170 | 17,407,222 | 46 |
| `openai/gpt-4.1-mini` | 7/20 | 46 | **15%** | 0 | 5 | 2 | 0 | 145 | 4,611,660 | 36 |

## Lỗi các phép kiểm tất định bắt được

| mô hình | `source_quote_len` |
|---|---|
| `openai/gpt-4o-mini` | 0 |
| `openai/gpt-4.1-mini` | 7 |

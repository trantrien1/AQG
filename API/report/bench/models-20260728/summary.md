# Quét mô hình sinh — pdftest/file_3_trang_61-90.pdf

- 20 câu yêu cầu mỗi ô, tài liệu tới mô hình dạng **ảnh trang**
- trần token mỗi lời gọi: **4000** (chung cho mọi ô)
- bộ giải độc lập cố định: `openai/gpt-4.1-mini`

| mô hình | giao ra | kiểm chứng độc lập | khớp nhất quán | lệch | không kiểm được | lời gọi | token | phút |
|---|---|---|---|---|---|---|---|---|
| `qwen/qwen3-vl-8b-instruct` | 0/20 (0%) | 0 | 0 | 0 | 0 | 10 | 339,383 | 2 |
| `qwen/qwen3-vl-32b-instruct` | 0/20 (0%) | 0 | 0 | 0 | 0 | 6 | 269,444 | 5 |
| `meta-llama/llama-4-scout` | 1/20 (5%) | 0 | 0 | 1 | 0 | 31 | 1,674,855 | 5 |
| `openai/gpt-4.1-nano` | 2/20 (10%) | 0 | 0 | 0 | 2 | 52 | 3,762,019 | 6 |

## Lỗi các phép kiểm tất định bắt được

_Không phép kiểm tất định nào bắt lỗi ở các câu đã giao ra._

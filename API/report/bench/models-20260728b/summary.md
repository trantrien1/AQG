# Quét mô hình sinh — pdftest/file_3_trang_61-90.pdf

- 20 câu yêu cầu mỗi ô, tài liệu tới mô hình dạng **ảnh trang**
- trần token mỗi lời gọi: **4000** (chung cho mọi ô)
- bộ giải độc lập cố định: `openai/gpt-4.1-mini`
- ngân sách lượt thử chung: bỏ cuộc sau **60** slot hỏng liên tiếp

| mô hình | giao ra | lượt thử | nhận/lượt thử | kiểm chứng độc lập | khớp nhất quán | lệch | không kiểm được | lời gọi | token | phút |
|---|---|---|---|---|---|---|---|---|---|---|
| `qwen/qwen3-vl-8b-instruct` | 1/20 | 46 | **2%** | 0 | 0 | 0 | 1 | 117 | 3,628,688 | 28 |
| `qwen/qwen3-vl-32b-instruct` | 0/20 | 46 | **0%** | 0 | 0 | 0 | 0 | 56 | 2,303,159 | 41 |
| `meta-llama/llama-4-scout` | 1/20 | 46 | **2%** | 0 | 0 | 1 | 0 | 143 | 7,405,051 | 29 |
| `openai/gpt-4.1-nano` | 3/20 | 46 | **7%** | 0 | 0 | 0 | 3 | 125 | 9,050,854 | 17 |

## Lỗi các phép kiểm tất định bắt được

_Không phép kiểm tất định nào bắt lỗi ở các câu đã giao ra._

# Chạy AQG trên Colab A100 80GB

Notebook: `API/colab/AQG_Colab_A100.ipynb`. Mở thẳng từ GitHub:

https://colab.research.google.com/github/trantrien1/AQG/blob/colab-gpu-reviewer-fixes/API/colab/AQG_Colab_A100.ipynb

## 1. Chuẩn bị (một lần)

1. Colab → **Runtime → Change runtime type → A100 GPU**, bật **High-RAM**.
   A100 cần gói Colab Pro/Pro+ hoặc pay-as-you-go.
2. (Tuỳ chọn) Thêm `HF_TOKEN` vào **Colab Secrets** (biểu tượng chìa khoá bên
   trái) để tải model nhanh hơn. Hai model mặc định không yêu cầu token.

## 2. Thứ tự chạy

| Ô | Việc | Thời gian |
|---|---|---|
| 1 | Kiểm GPU là A100 80GB | vài giây |
| 2 | Chọn `PRESET` (mặc định `quality`), số câu mỗi tài liệu | — |
| 3 | Gắn Google Drive, tạo thư mục kết quả | vài giây |
| 4 | Clone nhánh `colab-gpu-reviewer-fixes`, cài vLLM | ~5 phút |
| 5 | Ghim snapshot trọng số (SHA) + đặt biến môi trường | vài giây |
| 6 | Định nghĩa hàm bật/tắt server | — |
| 7 | Bật server solver (phi-4, cổng 8001) rồi generator (Qwen-VL, cổng 8000) | 10–25 phút lần đầu (tải ~65GB) |
| 8 | Test đơn vị + thử solver + đo số token ảnh của tài liệu dài nhất | 1–2 phút |
| 9 | **Thí nghiệm 1**: replay hội đồng solver trên 197 câu đã audit | vài phút |
| 10–11 | **Thí nghiệm 2**: sinh ~100 câu (chạy nền) + theo dõi | tuỳ tốc độ, xem ô 11 |
| 12 | Tổng hợp, lỗi soạn đề, phiếu audit mù, phiếu giáo viên | 1 phút |
| 13 | So sánh: từng solver một mình sẽ cấp nhãn thế nào trên câu mới | vài giây |
| 14 | Nén kết quả | vài giây |
| 16 | Tắt server | — |

Preset:

- `quality`: Qwen3-VL-32B FP8 + phi-4 FP8. Chất lượng cao nhất.
- `awq_fallback`: Qwen2.5-VL-32B AWQ. Dùng khi server FP8 không lên được trên A100.
- `fast`: Qwen3-VL-8B + phi-4 bf16. Nhanh, chất lượng thấp hơn.

## 3. Sinh ~100 câu với PDF của bạn

Mặc định: 6 tài liệu Toán 12 trong `pdftest/corpus2/` × 17 câu ≈ 102 câu.

Muốn dùng PDF khác:

1. Đưa file lên Drive (vd `MyDrive/AQG_pdfs/`) hoặc kéo thả vào `/content/`.
2. Ở ô 2, sửa `DOCS` thành đường dẫn tuyệt đối, ví dụ
   `DOCS = ['/content/drive/MyDrive/AQG_pdfs/chuong1.pdf', ...]`.
3. Đặt `QUESTIONS_PER_DOC` sao cho `len(DOCS) × QUESTIONS_PER_DOC ≈ 100`.
   Ví dụ 4 file × 25 câu, hoặc 1 file × 100 câu.
4. Chạy lại ô 2, ô 8 (kiểm lại ngân sách token với tài liệu mới), rồi ô 10–11.

Mỗi tài liệu chỉ gửi tối đa `max_pages` trang đầu cho model (24 trang ở preset
`quality`). Tài liệu dài hơn thì nên cắt thành nhiều file theo chương.

## 4. Kết quả trên Drive (`AQG_runs/<RUN_NAME>/`)

| Đường dẫn | Nội dung |
|---|---|
| `replay/replay_summary.md` | Bảng từng solver, từng cặp (κ), từng hội đồng: key sai còn được cấp nhãn / key đúng giữ nhãn |
| `gen/full_system/seed42/<doc>.json` | Câu hỏi đã giao + câu bị loại |
| `gen/full_system/seed42/<doc>.manifest.json` | Điều kiện chạy: SHA trọng số, họ model, cảnh báo độc lập |
| `gen/suite_summary.md` | Tổng hợp: tỉ lệ nhận, phân bố trạng thái, câu có solver không chạy được |
| `quality/layer1_rules.md` | Lỗi soạn đề phát hiện bằng luật |
| `audit/audit_sheet.csv` | Phiếu audit MÙ: đề + phương án + key, cột `key_correct` để điền |
| `audit/audit_plan_SECRET.json` | Ánh xạ phiếu → trạng thái máy (không đưa người audit xem) |
| `human_eval/ratings_gv*.csv` | Phiếu chấm cho 3 giáo viên, cùng 60 câu |

## 5. Sau khi có kết quả

```bash
# Audit: hai người điền độc lập hai bản sao của audit_sheet.csv
python scripts/audit_sample.py estimate --plan audit/audit_plan_SECRET.json \
    --sheet audit/nguoi_a.csv audit/nguoi_b.csv
# -> tỉ lệ key sai từng tầng (Wilson CI), ước lượng phân tầng, κ, ground_truth_cas.json

# Tổng hợp lại có correctness
python scripts/bench_suite.py --out gen --aggregate-only \
    --ground-truth audit/ground_truth_cas.json

# Giáo viên: nhận CSV về → chuyển JSON → tổng hợp (Krippendorff α)
python scripts/human_eval_packet.py import-csv --csv human_eval/ratings_gv1.csv
python scripts/human_eval_packet.py aggregate --dir human_eval
```

## 6. Dùng GPU Colab cho web app ở máy bạn (tuỳ chọn)

Ô 15 mở hai đường hầm Cloudflare và in ra các dòng cần dán vào `API/.env`, thay
cho khối chat2api. Cần giữ `GEMINI_API_KEY` vì vLLM không phục vụ embedding
(dùng để bắt câu trùng trong ngân hàng câu hỏi). Chế độ đính kèm phải là
`image`: vLLM không đọc nguyên file PDF. Điều khoản Colab hạn chế việc dùng
runtime làm dịch vụ web, nên chỉ dùng cách này để thử ngắn.

## 7. Chạy lại / sự cố

- **Mất kết nối**: chạy lại ô 1→8 rồi ô 10. Tài liệu đã xong được bỏ qua;
  replay cũng tiếp tục từ cache.
- **Server lỗi**: xem bảng *Xử lý sự cố* ở cuối notebook, và log trong
  `/content/vllm_logs/`.

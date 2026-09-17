# Fine-tune LoRA: Qwen3-8B (A) và Qwen3-14B (B)

Các notebook huấn luyện và so sánh hai mô hình soạn câu trắc nghiệm Nguyên hàm – Tích phân có lời giải,
trên dataset `trantrien1/vi-math12-integral-mcq` (1.095 câu `usable`). Chạy trên Colab với **A100 80GB**.

| Thứ tự | Notebook | Việc | GPU | Thời gian (ước tính) |
|---|---|---|---|---|
| 1 | `00_chuan_bi_du_lieu.ipynb` | Chia train/val/test, lưu lên Drive | không | 2 phút |
| 2 | `01_expA_qwen3_8b_lora.ipynb` | **A**: Qwen3-8B + LoRA, sinh đầu ra test | A100 | 30–45 phút |
| 3 | `02_expB_qwen3_14b_lora.ipynb` | **B**: Qwen3-14B + LoRA, sinh đầu ra test | A100 | 50–75 phút |
| 4 | `03_danh_gia_so_sanh.ipynb` | Giám khảo khác họ chấm, báo cáo so sánh | A100 | 15 phút |

Thời gian là ước tính trước khi chạy; số đo thật (giây train, token/s, VRAM đỉnh) được ghi vào báo cáo.

Chuẩn bị: thêm `HF_TOKEN` (quyền đọc dataset riêng tư) vào Colab Secrets; đẩy dataset lên HF trước
(`python dataset/tools/push_to_hub.py`), hoặc chép `questions.jsonl` lên Drive rồi đặt `SOURCE` là đường dẫn đó.

Kết quả nằm trong `MyDrive/AQG_ft/`:

```
data/                      items.jsonl, split.json, stats.md
expA_qwen3_8b_seed42/      config.json, train_summary.json, adapter/, preds/, loss.png, train.log
expB_qwen3_14b_seed42/     như trên
judge_A_B_phi-4_v1/        judge.jsonl, judge_meta.json
report_A_B/                report.md, report.json, summary.png
```

## Thiết kế thí nghiệm

**Dữ liệu.** Tập train có 875 câu, val 54 câu, test 166 câu. Các câu cùng một bài (chép lại, chỉ sửa lời dẫn) được gom
thành nhóm, và cả nhóm nằm chung một tập, để điểm test không bị thổi phồng. Việc chia tập phân tầng theo
chủ đề × mức độ, với seed cố định. Chỉ những câu có lời giải mới được dùng để train (760 câu). Mỗi câu cho ra hai mẫu:

- **gen** (tác vụ chính): cho chủ đề, nội dung, dạng bài, mức độ → mô hình soạn đề, 4 phương án, lời giải và đáp án.
- **solve** (tác vụ phụ): cho đề và phương án → mô hình viết lời giải và `Đáp án: X`. Tác vụ này có đáp án chuẩn nên đo được khách quan.

Tổng cộng khoảng 1.520 mẫu, 0,86 triệu token mỗi epoch (0,52 triệu token tính loss).

**Huấn luyện.** A và B dùng chung mọi thiết lập, chỉ khác model:

- LoRA bf16, không lượng tử hoá, gắn vào mọi lớp tuyến tính; r=32, α=64, dropout 0,05.
- lr 1e-4 theo lịch cosine, warmup 5%, 3 epoch, batch hiệu dụng 16, seed 42.
- Loss chỉ tính trên câu trả lời.
- Hội thoại được dựng bằng chat template của Qwen3 với chế độ suy nghĩ tắt, giống hệt lúc suy luận.
- Adapter cuối là checkpoint có val loss thấp nhất.

**Đầu ra dạng tiêu đề `### Đề bài / ### Phương án / ### Lời giải / ### Đáp án`, không dùng JSON.** Trong chuỗi JSON,
công thức LaTeX phải nhân đôi mọi dấu `\`. Chỉ cần mô hình quên một dấu là `\frac` biến thành ký tự form feed và bản ghi hỏng.

**Các hệ được so sánh** trên cùng câu test:

| Hệ | Ý nghĩa |
|---|---|
| `base` | model gốc, không ví dụ mẫu |
| `base_fs3` | model gốc với 3 ví dụ mẫu cùng nội dung (baseline mạnh; nếu LoRA không hơn hệ này thì chưa cần fine-tune) |
| `lora` | model gốc + adapter |

Thiết kế cho ra bảng 2 × 3, tách được hai tác động: kích thước model (A so với B) và LoRA (base so với lora).

**Chỉ số.**

- *Tác vụ sinh*: tỉ lệ đúng khuôn, tỉ lệ công thức dựng được bằng KaTeX, tỉ lệ giám khảo khớp, tỉ lệ chép gần nguyên
  văn câu train, độ đa dạng, số token mỗi câu, token/s. Chỉ số chính là **tỉ lệ câu dùng được**: đạt cả bốn điều kiện đầu.
- *Giám khảo*: `microsoft/phi-4` (khác họ với Qwen) giải mù câu sinh ra. Giám khảo cũng giải câu test thật để
  biết nó tự sai bao nhiêu. Chỉ số này chỉ là cận trên, vì giám khảo và mô hình có thể cùng sai một cách.
- *Tác vụ giải*: độ chính xác trên câu test, kèm khoảng tin cậy Wilson và phân theo mức độ.
- *So sánh cặp*: bootstrap ghép cặp theo câu test (10.000 lần) và McNemar.
- *Chi phí*: thời gian train, token/s, VRAM đỉnh.

**Quyết định 8B hay 14B.** Với 166 câu test, chênh lệch dưới khoảng 5–7 điểm phần trăm thường nằm trong nhiễu. Chọn 14B khi
khoảng tin cậy của `A.lora → B.lora` nằm hẳn trên 0 và mức hơn đủ lớn so với chi phí (14B train và sinh chậm hơn khoảng 1,7–2 lần).
Ngược lại thì chọn 8B.

## Đề xuất cải thiện (theo mức đáng làm)

1. **Chạy 3 seed** (42, 43, 44) cho cả A và B. Kết luận "14B hơn ít" chỉ đứng được khi chiều chênh lệch giống nhau ở mọi seed.
2. **Giáo viên chấm một mẫu** (khoảng 50 câu mỗi hệ, chấm mù): đáp án đúng, phương án nhiễu hợp lý, đúng mức độ.
   Giám khảo máy chỉ cho cận trên; paper cần con số do người chấm.
3. **Học tăng cường có phần thưởng kiểm chứng được (GRPO) sau SFT.** Phần thưởng gồm: đúng khuôn, KaTeX dựng được,
   giám khảo giải ra đúng đáp án, không chép câu train. Với tác vụ giải thì thưởng khi đúng đáp án. Đây là bước có
   khả năng nâng chất lượng nhiều nhất, và A100 80GB đủ để chạy cho 8B với LoRA.
4. **Làm giàu lời giải.** Nhiều lời giải trong sách rất ngắn. Có thể cho một model mạnh (chế độ suy nghĩ) viết lại lời
   giải từng bước, chỉ giữ bản ra đúng đáp án sách; cách này cũng tạo được lời giải cho 115 câu train đang chỉ có đáp án.
5. **Thêm dữ liệu.** 875 câu train là ít. Có thể thêm các chương khác của Giải tích 12, hoặc câu do chính pipeline sinh
   đã được kiểm chứng.
6. **Dò siêu tham số trên tập val** (không dùng test): r ∈ {16, 64}, lr ∈ {5e-5, 2e-4}, 2–5 epoch, rsLoRA/DoRA
   (script đã có cờ). Thêm xáo phương án (`SHUFFLE_AUG`) để giảm lệch vị trí đáp án ở tác vụ giải.
7. **Độ khó** trong dataset do mô hình gán, chưa có giáo viên xác nhận. Kết quả "điều khiển mức độ" hiện chỉ đo được
   so với nhãn đó.
8. **Đưa vào pipeline** cần một lớp chuyển đổi: writer của pipeline trả thêm trích dẫn nguồn và loại lỗi của phương án
   nhiễu mà dataset không có. Ngoài ra Qwen3-8B/14B chỉ đọc chữ, không đọc được ảnh trang PDF.

## Chạy ngoài Colab

```bash
cd API/notebooks
python -m mcqft.data  --source questions.jsonl --out data
python -m mcqft.train --model Qwen/Qwen3-8B --data data --out exp_a
python -m mcqft.infer --model Qwen/Qwen3-8B --data data --adapter exp_a/adapter --out exp_a/preds
python -m mcqft.judge --data data --preds A=exp_a/preds --out judge
python -m mcqft.report --data data --exp A=exp_a --judge judge --out report --katex-modules <node_modules>
```

Test không cần GPU: `python -m pytest tests/test_mcqft.py` (chạy từ thư mục `API`).

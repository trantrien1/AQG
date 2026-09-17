---
language:
- vi
pretty_name: Trắc nghiệm Nguyên hàm – Tích phân – Ứng dụng (Toán 12)
task_categories:
- multiple-choice
- question-answering
- text-generation
tags:
- math
- vietnamese
- latex
- mcq
size_categories:
- 1K<n<10K
license: other
configs:
- config_name: default
  data_files:
  - split: train
    path: questions.jsonl
---

# Trắc nghiệm Nguyên hàm – Tích phân – Ứng dụng (Toán 12)

Dataset gồm **1.430 câu trắc nghiệm** Giải tích 12 (chương Nguyên hàm, Tích phân
và Ứng dụng), được tách từ 16 file Word. Mỗi câu có 4 phương án, đáp án, và lời
giải chi tiết nếu tài liệu có. Toàn bộ công thức ở dạng LaTeX.

Có **1.095 câu dùng được ngay** (`usable = true`): giải được hoàn toàn bằng chữ,
đủ 4 phương án, đáp án chắc chắn, không thiếu công thức, không trùng, và đã qua
một lượt rà soát bằng tay (xem bên dưới). Trong số đó, 950 câu có lời giải. Mọi
câu `usable` đều có nhãn độ khó. Câu cần nhìn hình vẫn nằm trong file (kèm ảnh) nhưng
có `usable = false`, để dành cho mô hình đọc được ảnh.

## Định dạng

Mỗi dòng của `questions.jsonl` là một câu:

```json
{
  "id": "int_1000",
  "question": "Cho hàm số $y=f(x)=ax^{3}+bx^{2}+cx+d$ ... đồ thị hàm số $y=f'(x)$ cho bởi hình vẽ bên. Tính giá trị $H=f(4)-f(2)$?\n![hình](images/int_1000_36dadc435a.png)",
  "choices": ["A. $H=45$", "B. $H=64$", "C. $H=51$", "D. $H=58$"],
  "answer": "D",
  "solution": "Theo bài ra ...",
  "topic": "Ứng dụng tích phân",
  "subtopic": "Diện tích hình phẳng có đồ thị",
  "difficulty": null,
  "section": "ỨNG DỤNG DIỆN TÍCH CÓ ĐỒ THỊ ĐẠO HÀM",
  "source": {"file": "14  P2  UD tinh DT co do thi  tr319  tr350.docx", "question_number": 1},
  "answer_source": "chon",
  "images": ["images/int_1000_36dadc435a.png"],
  "flags": ["figure_in_question"],
  "review_note": null,
  "duplicate_of": null,
  "usable": false
}
```

| Trường | Ý nghĩa |
|---|---|
| `question` | Đề bài. Công thức nằm trong `$...$`; hình ghi dạng `![hình](images/...)` |
| `choices` | 4 phương án, có tiền tố `A. ` … `D. ` |
| `answer` | Chữ cái đáp án đúng; `null` nếu tài liệu không cho |
| `solution` | Lời giải; rỗng nếu tài liệu chỉ ghi đáp án |
| `topic`, `subtopic` | Chủ đề theo chương/file |
| `section` | Tiêu đề mục gần nhất trong tài liệu, ví dụ "DẠNG 2: ÁP DỤNG TRỰC TIẾP BẢNG NGUYÊN HÀM" |
| `difficulty` | Một trong bốn mức Nhận biết / Thông hiểu / Vận dụng / Vận dụng cao; `null` với câu chưa gán (các câu không `usable`) |
| `review_note` | Ghi chú rà soát tay, có ở câu bị loại vì sai đáp án hoặc đề hỏng |
| `answer_source` | `chon`: lấy từ dòng "Chọn X" trong lời giải. `red_mark`: lấy từ chữ cái phương án tô đỏ (cách đánh dấu đáp án ở phần đề kiểm tra) |
| `flags` | Các vấn đề phát hiện được (bảng dưới) |
| `duplicate_of` | `id` của câu giống hệt xuất hiện trước đó (ở file khác) |
| `usable` | `true` khi không có cờ nào ở hàng "loại" dưới đây |

| Cờ | Số câu | Loại khỏi `usable` |
|---|---|---|
| `no_solution` | 253 | không (đa số là đề kiểm tra, chỉ có đáp án) |
| `duplicate` | 93 | có |
| `no_answer` | 33 | có |
| `duplicate_choices` | 11 | có (tài liệu gốc có hai phương án giống nhau) |
| `formula_missing` | 6 | có (công thức Equation Editor 3.0 chưa chuyển được) |
| `answer_conflict_red_*` | 5 | có ("Chọn X" khác chữ cái tô đỏ) |
| `figure_in_question` | 115 | có (đề hoặc phương án có hình, hoặc nhắc "như hình vẽ"; hình vẽ bằng shape của Word không xuất được thành ảnh) |
| `figure_in_solution` | 10 | có (lời giải dựa vào hình) |
| `figure_removed_from_solution` | 30 | không (hình chỉ minh hoạ trong lời giải, đã bỏ) |
| `no_choices` | 2 | có |
| `omml_unconverted` | 2 | có (công thức Word dạng mới chưa chuyển được) |
| `key_wrong` | 20 | có (đáp án sách sai; `review_note` ghi đáp án đúng) |
| `key_suspect` | 3 | có (phương án có lỗi đánh máy nên đáp án đáng ngờ) |
| `source_corrupted` | 33 | có (đề hoặc phương án dính chữ rác, đề và lời giải không khớp, thiếu dữ kiện) |
| `segmentation_error` | 17 | có (câu bị tách sai, chủ yếu do nội dung nằm trong bảng Word) |
| `figure_implicit` | 2 | có (cần hình dù đề không nói "hình vẽ") |

Phân bố câu `usable`: Tích phân 512, Nguyên hàm 258, Ứng dụng tích phân 191, đề kiểm
tra tổng hợp 134. Đáp án A/B/C/D lần lượt 298/281/256/260.

## Độ khó

Tài liệu gốc không ghi mức độ. Nhãn được gán bằng tay cho từng câu (Claude Opus 5
đọc đề, phương án và lời giải), theo bốn mức nhận thức mà Bộ GD&ĐT dùng khi ra đề:

| Mức | Tiêu chí dùng khi gán |
|---|---|
| Nhận biết | Nhớ định nghĩa, tính chất, công thức trong bảng; áp dụng trực tiếp một bước |
| Thông hiểu | Dùng một kỹ thuật chuẩn một lần (tách tổng, đổi biến đơn giản, một lần từng phần, diện tích khi hàm không đổi dấu); 2–3 bước |
| Vận dụng | Nhiều bước hoặc phối hợp kỹ thuật; xét dấu, phá trị tuyệt đối; tham số phải giải hệ; tự thiết lập diện tích/thể tích; hàm ẩn cơ bản |
| Vận dụng cao | Cần ý tưởng không hiển nhiên: hàm ẩn phức tạp, bất đẳng thức hoặc GTLN–GTNN của tích phân, mô hình thực tế có tối ưu, phối hợp từ ba kỹ thuật |

Phân bố trên 1.095 câu `usable`:

| Chủ đề | Nhận biết | Thông hiểu | Vận dụng | Vận dụng cao |
|---|---|---|---|---|
| Nguyên hàm | 34 | 147 | 62 | 15 |
| Tích phân | 40 | 179 | 194 | 99 |
| Ứng dụng tích phân | 13 | 94 | 69 | 15 |
| Đề kiểm tra tổng hợp | 9 | 84 | 39 | 2 |
| **Tổng** | **96** | **504** | **364** | **131** |

Nhãn do một mô hình gán, **chưa có giáo viên xác nhận**. Trước khi dùng nhãn làm
kết quả nghiên cứu, nên cho giáo viên gán độc lập một mẫu (khoảng 100 câu) rồi
tính độ đồng thuận (Cohen's κ có trọng số).

## Rà soát bằng tay

Trong lúc gán độ khó, từng câu được đọc và kiểm tra lại đáp án khi có thể tính
nhanh. 75 câu bị loại khỏi `usable`, ghi trong `dataset/labels/review.tsv` của mã
nguồn và trường `review_note`: 20 câu đáp án sách sai, 3 câu đáp án đáng ngờ, 33 câu
đề hỏng, 17 câu tách sai, 2 câu cần hình. Câu sai đáp án được loại chứ không sửa,
để dataset không chứa đáp án chưa ai kiểm chứng lần hai. Lượt rà soát này không
giải lại mọi câu, nên vẫn có thể còn đáp án sai.

## Cách dựng

```bash
python dataset/tools/build_dataset.py --src "dataset/<thư mục chứa .docx>" --out dataset/export --labels dataset/labels
npm install katex@0.16 && node dataset/tools/check_latex.js dataset/export/questions.jsonl
```

- **Công thức.** Công thức MathType (đối tượng OLE, MTEF v5) được đọc trực tiếp từ
  dữ liệu nhị phân rồi dịch sang LaTeX. Công thức dán dạng ảnh WMF/EMF vẫn chuyển
  được, vì MathType nhúng dữ liệu MTEF trong ảnh. Tổng cộng 19.457 công thức;
  23 công thức Equation Editor 3.0 chưa hỗ trợ và được gắn cờ `formula_missing`.
- **Kiểm tra.** KaTeX dựng được toàn bộ 17.052 công thức trong file kết quả. Đã so
  một số công thức phức tạp với ảnh xem trước của Word.
- **Font cũ.** Chữ gõ bằng font TCVN3 (`.VnTime`) được chuyển sang Unicode.
- **Đáp án.** Ở các câu có cả "Chọn X" và chữ tô đỏ, hai nguồn khớp nhau 848/853
  lần. 5 câu lệch được gắn cờ và loại.
- **Hình.** Hình vẽ (đồ thị, hình khối) được chép sang `images/`; ảnh WMF/EMF được
  chuyển sang PNG.
- **Nhãn.** `dataset/labels/difficulty.tsv` và `review.tsv` gắn theo `id`, kèm số file
  và số câu để đối chiếu. Nếu cách tách câu thay đổi làm lệch `id`, dòng nhãn đó bị
  bỏ qua và được liệt kê trong `label_warnings` của `build_report.json`.

## Hạn chế

- `difficulty` do mô hình gán, chưa có giáo viên xác nhận (xem mục Độ khó).
- Đáp án và lời giải lấy nguyên từ tài liệu. Lượt rà soát tay đã loại các lỗi thấy
  được, nhưng đáp án **chưa được giải lại độc lập toàn bộ**.
- Câu trùng chỉ được phát hiện khi trùng nguyên văn; câu gần giống vẫn còn.
- Ở phần đề kiểm tra, hình trôi nổi đôi khi được Word neo vào câu liền trước (vd
  hình của câu 16 nằm trong câu 15). Muốn dùng các câu có hình cho mô hình đọc
  ảnh thì cần kiểm tra lại vị trí hình bằng tay.
- Một số lời giải mô tả bảng biến thiên hoặc bảng xét dấu bằng bảng Word; nội dung
  bảng được giữ ở dạng chữ nên có thể khó đọc.

## Nguồn và quyền sử dụng

Nội dung được trích từ bộ tài liệu "Giải tích 12 – Nguyên hàm, Tích phân và Ứng
dụng" của thầy Nguyễn Quốc Hoàn. Bản quyền nội dung thuộc tác giả. Dataset chỉ dùng
cho nghiên cứu; muốn phát hành công khai hoặc dùng thương mại cần có sự đồng ý
của tác giả.

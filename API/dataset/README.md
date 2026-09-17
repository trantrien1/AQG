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

Có **1.284 câu dùng được ngay** (`usable = true`): đủ 4 phương án, đáp án chắc
chắn, không thiếu công thức, không trùng. Trong số đó, 1.118 câu có lời giải.

## Định dạng

Mỗi dòng của `questions.jsonl` là một câu:

```json
{
  "id": "int_1000",
  "question": "Cho hàm số $y=f(x)=ax^{3}+bx^{2}+cx+d$ ... Tính giá trị $H=f(4)-f(2)$?",
  "choices": ["A. $H=45$", "B. $H=64$", "C. $H=51$", "D. $H=58$"],
  "answer": "D",
  "solution": "![hình](images/int_1000_36dadc435a.png)\nTheo bài ra ...",
  "topic": "Ứng dụng tích phân",
  "subtopic": "Diện tích hình phẳng có đồ thị",
  "difficulty": null,
  "section": "ỨNG DỤNG DIỆN TÍCH CÓ ĐỒ THỊ ĐẠO HÀM",
  "source": {"file": "14  P2  UD tinh DT co do thi  tr319  tr350.docx", "question_number": 1},
  "answer_source": "chon",
  "images": ["images/int_1000_36dadc435a.png"],
  "flags": [],
  "duplicate_of": null,
  "usable": true
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
| `difficulty` | **Chưa gán.** Tài liệu gốc không ghi mức độ |
| `answer_source` | `chon`: lấy từ dòng "Chọn X" trong lời giải. `red_mark`: lấy từ chữ cái phương án tô đỏ (cách đánh dấu đáp án ở phần đề kiểm tra) |
| `flags` | Các vấn đề phát hiện được (bảng dưới) |
| `duplicate_of` | `id` của câu giống hệt xuất hiện trước đó (ở file khác) |
| `usable` | `true` khi không có cờ nào ở hàng "loại" dưới đây |

| Cờ | Số câu | Loại khỏi `usable` |
|---|---|---|
| `no_solution` | 242 | không (đa số là đề kiểm tra, chỉ có đáp án) |
| `duplicate` | 93 | có |
| `no_answer` | 33 | có |
| `duplicate_choices` | 11 | có (tài liệu gốc có hai phương án giống nhau) |
| `formula_missing` | 6 | có (công thức Equation Editor 3.0 chưa chuyển được) |
| `answer_conflict_red_*` | 5 | có ("Chọn X" khác chữ cái tô đỏ) |
| `no_choices` | 2 | có |

Phân bố câu `usable`: Tích phân 562, Ứng dụng tích phân 300, Nguyên hàm 264, đề kiểm
tra tổng hợp 158. Đáp án A/B/C/D lần lượt 342/339/303/300.

## Cách dựng

```bash
python dataset/tools/build_dataset.py --src "dataset/<thư mục chứa .docx>" --out dataset/export
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

## Hạn chế

- `difficulty` còn trống. Cần gán bằng người hoặc bằng mô hình phân loại, và phải
  ghi rõ nguồn nhãn.
- Đáp án và lời giải lấy nguyên từ tài liệu, **chưa được kiểm chứng độc lập**. Tài
  liệu gốc có lỗi đánh máy (ví dụ hai phương án giống nhau).
- Câu trùng chỉ được phát hiện khi trùng nguyên văn; câu gần giống vẫn còn.
- Một số lời giải mô tả bảng biến thiên hoặc bảng xét dấu bằng bảng Word; nội dung
  bảng được giữ ở dạng chữ nên có thể khó đọc.

## Nguồn và quyền sử dụng

Nội dung được trích từ bộ tài liệu "Giải tích 12 – Nguyên hàm, Tích phân và Ứng
dụng" của thầy Nguyễn Quốc Hoàn. Bản quyền nội dung thuộc tác giả. Dataset chỉ dùng
cho nghiên cứu; muốn phát hành công khai hoặc dùng thương mại cần có sự đồng ý
của tác giả.

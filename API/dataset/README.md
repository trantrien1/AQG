---
language:
- vi
pretty_name: Toán THPT tiếng Việt – câu hỏi có lời giải (Nguyên hàm – Tích phân và đề thi thử)
task_categories:
- multiple-choice
- question-answering
- text-generation
tags:
- math
- vietnamese
- latex
- mcq
- true-false
- short-answer
size_categories:
- 1K<n<10K
license: other
configs:
- config_name: default
  data_files:
  - split: train
    path: questions.jsonl
dataset_info:
  features:
  - name: id
    dtype: string
  - name: collection
    dtype: string
  - name: type
    dtype: string
  - name: question
    dtype: string
  - name: choices
    list: string
  - name: answer
    dtype: string
  - name: solution
    dtype: string
  - name: topic
    dtype: string
  - name: subtopic
    dtype: string
  - name: difficulty
    dtype: string
  - name: author_difficulty
    dtype: string
  - name: section
    dtype: string
  - name: source
    struct:
    - name: exam
      dtype: string
    - name: file
      dtype: string
    - name: part
      dtype: int64
    - name: question_number
      dtype: int64
  - name: answer_source
    dtype: string
  - name: images
    list: string
  - name: flags
    list: string
  - name: review_note
    dtype: string
  - name: corrections
    list:
    - name: field
      dtype: string
    - name: old
      dtype: string
    - name: new
      dtype: string
    - name: note
      dtype: string
  - name: duplicate_of
    dtype: string
  - name: usable
    dtype: bool
  splits:
  - name: train
    num_examples: 3188
---

# Toán THPT tiếng Việt – câu hỏi có lời giải

Dataset gồm **3.188 câu hỏi Toán THPT**, lấy từ hai nguồn (trường `collection`):

| `collection` | Nguồn | Tổng | `usable` |
|---|---|---|---|
| `nguyen_ham_tich_phan` | Sách *Giải tích 12 – Nguyên hàm, Tích phân và Ứng dụng* (16 file Word) | 1.430 | 1.096 |
| `de_thi_thu` | 52 đề thi thử, đề khảo sát THPT môn Toán (2024–2026) | 1.758 | 1.280 |
| **Tổng** | | **3.188** | **2.376** |

Có ba dạng câu hỏi: trắc nghiệm bốn phương án, trắc nghiệm đúng/sai và trả lời ngắn. Mọi
công thức đều ở dạng LaTeX.

Câu `usable = true` là câu dùng được ngay. Câu này đọc hiểu được hoàn toàn bằng chữ, có đáp
án chắc chắn, không trùng câu khác, và đã được rà soát bằng tay. Tất cả đều có nhãn độ khó
và chủ đề. 2.236 câu `usable` có lời giải; 140 câu còn lại là câu của sách chỉ có đáp án
(130 câu thuộc phần đề kiểm tra). Câu cần nhìn hình vẫn nằm trong file (kèm ảnh) với
`usable = false`, để dành cho mô hình đọc được ảnh.

## Nguồn

**Sách Nguyên hàm – Tích phân.** Bộ tài liệu *Giải tích 12 – Nguyên hàm, Tích phân và Ứng
dụng* của thầy Nguyễn Quốc Hoàn, gồm các chương Nguyên hàm, Tích phân, Ứng dụng tích phân
và một phần đề kiểm tra. Câu ở phần đề kiểm tra được xếp vào một trong ba chủ đề trên theo
nội dung, với `subtopic = "Đề kiểm tra"`.

**Đề thi thử.** 38 đề "phát triển đề minh họa 2024" (đề 50 câu trắc nghiệm); 5 đề thi thử
2025 và 9 đề năm học 2025–2026 theo cấu trúc mới, gồm đề của các Sở GD&ĐT Nghệ An, Thái
Nguyên, Thanh Hóa, Cà Mau, Đà Nẵng và các trường THPT Dương Quảng Hàm, Tạ Quang Bửu, Thọ
Xuân 5. Chỉ lấy câu có lời giải bằng chữ; 437 câu không có lời giải bị bỏ.

## Dạng câu hỏi

| `type` | Mô tả | `choices` | `answer` | `usable` |
|---|---|---|---|---|
| `mcq` | Bốn phương án, một đáp án | `"A. …"` … `"D. …"` | `"A"`–`"D"` | 2.284 |
| `true_false` | Bốn mệnh đề, mỗi mệnh đề Đúng hoặc Sai (Phần II đề mới) | `"a) …"` … `"d) …"` | 4 ký tự Đ/S theo thứ tự a–d, ví dụ `"ĐĐSS"` | 37 |
| `short_answer` | Đáp số là một số (Phần III đề mới) | `[]` | số dạng chữ, dấu phẩy thập phân, ví dụ `"-4"`, `"1,5"` | 55 |

## Định dạng

Mỗi dòng của `questions.jsonl` là một câu. Ví dụ (lời giải được rút gọn):

```json
{
  "id": "thanhhoa26-l2-p2-02",
  "collection": "de_thi_thu",
  "type": "true_false",
  "question": "Cho hàm số $f(x)=x^{3}-3x$.",
  "choices": ["a) Tập xác định của hàm số đã cho là $\\mathbb{R}$.",
              "b) Hàm số $f(x)$ có đạo hàm là $f'(x)=3x^{2}-3$.",
              "c) Hàm số $f(x)$ đồng biến trên khoảng $(-1;1)$.",
              "d) Hàm số $f(x)$ đạt giá trị nhỏ nhất trên đoạn $[-3;2]$ tại $x=1$."],
  "answer": "ĐĐSS",
  "solution": "Cho $f(x)=x^{3}-3x$.\na) Hàm đa thức xác định trên $\\mathbb{R}$, nên đúng.\n…",
  "topic": "Ứng dụng đạo hàm và khảo sát hàm số",
  "subtopic": "Giá trị lớn nhất, nhỏ nhất",
  "difficulty": "Thông hiểu",
  "author_difficulty": null,
  "section": "Phần II – Trắc nghiệm đúng sai",
  "source": {"exam": "Sở GD&ĐT Thanh Hóa – thi thử lần 2, 2026",
             "file": "-2026-mon-Toan-So-GD-Thanh-Hoa-lan-2.docx", "part": 2, "question_number": 2},
  "answer_source": "table",
  "images": [],
  "flags": [],
  "review_note": null,
  "corrections": [],
  "duplicate_of": null,
  "usable": true
}
```

| Trường | Ý nghĩa |
|---|---|
| `id` | Sách: `int_NNNN`. Đề thi: `<mã đề>-<số câu>`, đề cấu trúc mới thêm phần (vd `thanhhoa26-l2-p2-02` là Phần II câu 2) |
| `collection` | `nguyen_ham_tich_phan` hoặc `de_thi_thu` |
| `question` | Đề bài. Công thức trong `$...$`; hình ghi dạng `![hình](images/...)` |
| `choices` | Phương án (trắc nghiệm) hoặc mệnh đề (đúng/sai); rỗng với câu trả lời ngắn |
| `answer` | Đáp án, theo quy ước ở bảng trên; `null` nếu tài liệu không cho |
| `solution` | Lời giải của tài liệu (có thể đã được đính chính, xem `corrections`); rỗng nếu tài liệu chỉ ghi đáp án |
| `topic`, `subtopic` | Chủ đề theo chương trình |
| `difficulty` | Nhận biết / Thông hiểu / Vận dụng / Vận dụng cao, gán bằng tay; có ở mọi câu `usable` |
| `author_difficulty` | Mức độ do tác giả đề ghi (chỉ 11 đề thi có), để đối chiếu |
| `section` | Sách: tiêu đề mục gần nhất, vd "DẠNG 2: ÁP DỤNG TRỰC TIẾP BẢNG NGUYÊN HÀM". Đề thi: phần của đề |
| `source` | `exam` (tên sách hoặc tên đề), `file` (file gốc), `part` (phần của đề mới, còn lại `null`), `question_number` |
| `answer_source` | Đáp án lấy từ đâu (bảng dưới) |
| `images` | Ảnh của câu trong thư mục `images/`, kể cả ảnh đã bỏ khỏi chữ |
| `flags` | Các vấn đề phát hiện được (mục Cờ) |
| `review_note` | Ghi chú rà soát tay: lý do loại câu, lý do sửa (bắt đầu bằng "bản gốc:"), câu trùng với câu nào |
| `corrections` | Các chỗ đã sửa chữ so với tài liệu gốc: `field`, `old`, `new`, `note` |
| `duplicate_of` | `id` của câu chính khi câu này trùng một câu khác |
| `usable` | `true` khi đủ phương án, có đáp án và không có cờ chặn |

| `answer_source` | Nghĩa | Câu `usable` |
|---|---|---|
| `chon` | Dòng "Chọn X" trong lời giải (sách) | 931 |
| `red_mark` | Chữ cái phương án tô đỏ (phần đề kiểm tra của sách) | 153 |
| `star` | Dấu `*` trước chữ cái phương án đúng (đề minh họa 2024) | 1.085 |
| `table` | Bảng đáp án của đề | 99 |
| `solution` | Suy ra từ kết luận của lời giải | 53 |
| `text` | Đáp án ghi ngay trong phần đề (vd "KQ: Đ-S-Đ-S", "Trả lời: 12") | 10 |
| `manual` | Gán tay khi đáp án gốc sai, thiếu, hoặc bộ đọc bắt nhầm (lý do ở `review_note`) | 45 |

Đáp án của 2.284 câu trắc nghiệm `usable` phân bố A/B/C/D = 617/560/556/551.

## Cờ

| Cờ | Sách | Đề thi | Loại khỏi `usable` | Nghĩa |
|---|---|---|---|---|
| `figure_in_question` | 115 | 319 | có | Đề hoặc phương án cần hình (đồ thị, bảng biến thiên dạng ảnh, hình khối) |
| `figure_removed_from_solution` | 30 | 310 | không | Hình trong lời giải chỉ minh hoạ, đã bỏ khỏi chữ |
| `no_solution` | 254 | 0 | không | Tài liệu chỉ ghi đáp án |
| `duplicate` | 129 | 120 | có | Trùng một câu khác (`duplicate_of`) |
| `text_corrected` | 27 | 80 | không | Chữ đã được đính chính (`corrections`) |
| `figure_optional` | 0 | 71 | không | Rà tay: đề và lời giải đọc hiểu được khi bỏ hình |
| `table_removed_from_solution` | 0 | 70 | không | Lời giải có bảng biến thiên/xét dấu dạng ảnh đã bỏ; phần chữ vẫn đủ |
| `figure_removed_from_question` | 0 | 66 | không | Hình minh hoạ trong đề đã bỏ (câu `figure_optional`) |
| `source_corrupted` | 21 | 45 | có | Đề hỏng, thiếu dữ kiện, lời giải của câu khác, hai phương án cùng đúng |
| `no_answer` | 33 | 1 | có | Không xác định được đáp án |
| `solution_realigned` | 0 | 24 | không | Lời giải được ghép lại đúng câu khi file đáp án đánh số lệch |
| `figure_in_solution` | 10 | 12 | có | Lời giải lập luận dựa vào hình |
| `duplicate_choices` | 11 | 2 | có | Hai phương án giống nhau |
| `formula_as_image` | 0 | 13 | có | Công thức chỉ có dạng ảnh |
| `segmentation_error` | 10 | 0 | có | Câu bị tách sai (nội dung nằm trong bảng Word) |
| `key_wrong` | 7 | 0 | có | Đáp án sách sai và không sửa được (không phương án nào đúng, hoặc phải sửa đề) |
| `formula_missing` | 6 | 0 | có | Công thức Equation Editor 3.0 chưa chuyển được |
| `answer_conflict_*` | 5 | 0 | có | "Chọn X" khác chữ cái tô đỏ |
| `omml_unconverted` | 2 | 3 | có | Công thức Word dạng mới chưa chuyển được |
| `solution_trivial` | 0 | 5 | có | Lời giải chỉ nhắc lại đáp án |
| `figure_implicit` | 2 | 1 | có | Cần hình dù đề không có hình |
| `solution_wrong` | 0 | 3 | có | Lời giải sai mà không sửa được nếu không viết lại |
| `formula_text_lost` | 0 | 3 | không | Chữ trong công thức có ký tự không chuyển được (hiện thành `?`) |
| `no_choices` | 2 | 0 | có | Không tách được phương án |
| `solution_tail_cut` | 0 | 1 | không | Đã cắt phần lời giải của câu khác dính ở cuối |
| `solution_typo` | 0 | 1 | có | Lỗi gõ trong lời giải chưa được đính chính |
| `empty_choice` | 0 | 1 | có | Có phương án rỗng |

Số câu tính trên toàn bộ 3.188 câu; một câu có thể mang nhiều cờ.

## Độ khó

Nhãn được gán bằng tay cho từng câu (Claude Opus 5 đọc đề, phương án và lời giải), theo
bốn mức mà Bộ GD&ĐT dùng khi ra đề:

| Mức | Tiêu chí dùng khi gán |
|---|---|
| Nhận biết | Nhớ định nghĩa, tính chất, công thức; áp dụng trực tiếp một bước |
| Thông hiểu | Một kỹ thuật hay quy trình chuẩn làm một lần (đổi biến đơn giản, một lần từng phần, xét dấu đạo hàm, giải phương trình mũ cơ bản); 2–3 bước |
| Vận dụng | Nhiều bước hoặc phối hợp kỹ thuật; phải tự dựng yếu tố hoặc tự thiết lập công thức (diện tích, thể tích, khoảng cách); tham số phải giải hệ; hàm ẩn cơ bản |
| Vận dụng cao | Cần ý tưởng không hiển nhiên: hàm ẩn phức tạp, bất đẳng thức hoặc GTLN–GTNN, bài tham số khó, mô hình thực tế có tối ưu |

Phân bố trên 2.376 câu `usable`:

| Bộ, dạng | Nhận biết | Thông hiểu | Vận dụng | Vận dụng cao |
|---|---|---|---|---|
| Sách, trắc nghiệm | 97 | 500 | 366 | 133 |
| Đề thi, trắc nghiệm | 417 | 463 | 233 | 75 |
| Đề thi, đúng/sai | 0 | 20 | 17 | 0 |
| Đề thi, trả lời ngắn | 0 | 16 | 34 | 5 |
| **Tổng** | **514** | **999** | **650** | **213** |

| Chủ đề | Sách | Đề thi | NB | TH | VD | VDC | Tổng |
|---|---|---|---|---|---|---|---|
| Tích phân | 554 | 37 | 55 | 211 | 217 | 108 | 591 |
| Nguyên hàm | 329 | 46 | 61 | 209 | 89 | 16 | 375 |
| Lũy thừa, mũ và logarit | 0 | 301 | 115 | 106 | 46 | 34 | 301 |
| Ứng dụng đạo hàm và khảo sát hàm số | 0 | 282 | 45 | 148 | 74 | 15 | 282 |
| Ứng dụng tích phân | 213 | 29 | 17 | 116 | 93 | 16 | 242 |
| Khối đa diện | 0 | 171 | 62 | 62 | 35 | 12 | 171 |
| Mặt nón, mặt trụ, mặt cầu | 0 | 121 | 50 | 37 | 32 | 2 | 121 |
| Phương pháp tọa độ trong không gian | 0 | 83 | 40 | 18 | 21 | 4 | 83 |
| Quan hệ song song, vuông góc trong không gian | 0 | 72 | 3 | 42 | 25 | 2 | 72 |
| Tổ hợp và xác suất | 0 | 70 | 21 | 33 | 14 | 2 | 70 |
| Dãy số, cấp số | 0 | 32 | 27 | 4 | 1 | 0 | 32 |
| Các chủ đề khác (số phức, lượng giác, thống kê, …) | 0 | 36 | 18 | 13 | 3 | 2 | 36 |

**So với nhãn của tác giả đề.** 11 đề minh họa 2024 (đề 2–6 và 12–17) có ghi mức độ cho
từng câu. Trên 361 câu `usable` có cả hai nhãn: khớp đúng 60,9%, lệch không quá một mức
99,2%, Cohen's κ = 0,40, κ trọng số bậc hai = 0,66. Nhãn gán thường thấp hơn nhãn tác giả
(89 câu thấp hơn, 52 câu cao hơn); lệch nhiều nhất là 82 câu tác giả ghi Thông hiểu còn
nhãn gán là Nhận biết. Hai nhãn được giữ riêng (`difficulty`, `author_difficulty`) để người
dùng tự chọn. Sách không ghi mức độ nên không có đối chiếu.

Nhãn chưa có giáo viên xác nhận. Trước khi dùng làm kết quả nghiên cứu, nên cho giáo viên
gán độc lập một mẫu rồi tính độ đồng thuận.

## Rà soát tay và đính chính

Từng câu được đọc để gán chủ đề, độ khó và kiểm tra đáp án. File Word gốc giữ nguyên; chỗ
sửa được áp khi dựng dataset và ghi vào trường `corrections`.

- **Câu sai được sửa khi đủ căn cứ, thay vì bị loại.** Căn cứ lấy từ chính lời giải hoặc đáp
  án của tài liệu. 47 câu có đáp án gốc sai (31 ở đề thi, 16 ở sách):
  - đáp án đánh dấu nhầm trong khi lời giải đúng;
  - đáp án và lời giải cùng sai (vd quên bình phương bán kính, lấy nguyên hàm sai dấu, bỏ quên
    vận tốc ban đầu); lời giải được sửa lại cho đúng;
  - phương án đúng bị gõ sai hoặc bị thay bằng công thức rác, được khôi phục theo lời giải.

  Ở sách, 35 câu từng bị loại ở bản trước nay dùng lại được. Đáp án gán tay có
  `answer_source = manual`; lý do ghi trong `review_note`, bắt đầu bằng "bản gốc:".
- **107 câu được đính chính chữ (174 chỗ), gồm 80 câu đề thi và 27 câu sách.** Các lỗi được
  sửa: lỗi gõ trong lời giải hoặc phương án, bước giải sai, cận tích phân trong đề khác lời
  giải, đề bị tách vào phương án, chữ rác của câu khác dính vào đầu đề hoặc cuối lời giải.
- **Câu trùng: 249 câu.** Câu trùng nguyên văn (cùng đề và cùng tập phương án, bỏ qua thứ tự
  và cách viết) được phát hiện tự động, kể cả giữa hai bộ. Các cặp đề gần giống có cùng bộ
  số liệu được rà tay; câu cùng bài nhưng khác phương án nhiễu hoặc cách viết cũng được gắn
  `duplicate`. Có 8 câu đề thi trùng câu trong sách. Ngoài ra, 36 câu của sách lặp lại bài
  đã có ở chương khác hoặc phần đề kiểm tra; bản trước chưa phát hiện các câu này. Bài cùng
  dạng nhưng khác số liệu được giữ.
- **Vẫn bị loại.** Câu không phương án nào đúng, đề hỏng hoặc mâu thuẫn mà không dựng lại
  được, lời giải chỉ nhắc đáp án, hoặc lời giải sai phải viết lại gần như toàn bộ; lý do ở
  `review_note`.

Lượt rà soát không giải lại độc lập mọi câu, nên vẫn có thể còn đáp án sai.

## Cách dựng

```bash
python dataset/tools/build_dataset.py --src "dataset/<thư mục sách>" --out dataset/export --labels dataset/labels
python dataset/tools/build_exams.py --src dataset/De_thi_nhieu_dang_format
python dataset/tools/merge_datasets.py
npm install katex@0.16 && node dataset/tools/check_latex.js dataset/export/combined/questions.jsonl
python dataset/tools/push_to_hub.py --repo <user>/<tên-dataset> --export dataset/export/combined
```

Kết quả nằm ở `dataset/export/combined/`. Cần UnRAR hoặc 7-Zip để mở các đề nén `.rar`.

- **Hai bước dựng riêng rồi gộp.** Sách và đề thi có định dạng khác nhau nên được dựng bằng
  hai công cụ riêng, mỗi công cụ có nhãn tay và đính chính của mình (`dataset/labels/`:
  `difficulty.tsv`, `review.tsv` cho sách; `exams.tsv`, `exams_errata.tsv` cho đề thi).
  Bước gộp đưa hai bộ về cùng schema, áp đính chính cho sách (`integral_errata.tsv`), áp
  nhãn sau khi gộp (`merge.tsv`: sửa đáp án, gỡ cờ, câu trùng giữa hai bộ) và đánh dấu câu
  trùng nguyên văn giữa hai bộ. Đính chính ghi chuỗi cũ và chuỗi mới; chuỗi cũ phải xuất
  hiện đúng một lần, nếu không dòng đó bị bỏ qua và được liệt kê trong phần cảnh báo của
  `build_report.json`.
- **Đề thi.** Hai kiểu tài liệu: lời giải đặt ngay sau từng câu (đáp án đánh dấu `*`), hoặc
  phần đề riêng rồi bảng đáp án và lời giải đánh số "Câu N" theo từng phần. Nội dung trong
  bảng Word (phương án, bảng đáp án Đ/S) cũng được đọc. Khi có nhiều nguồn đáp án, các nguồn
  được so với nhau; lệch nhau thì câu bị gắn cờ cho tới khi rà tay.
- **Công thức.** Công thức MathType được đọc từ dữ liệu nhị phân và dịch sang LaTeX; công
  thức dán dạng ảnh WMF/EMF vẫn chuyển được vì MathType nhúng dữ liệu công thức trong ảnh.
  KaTeX dựng được toàn bộ 39.073 công thức trong file kết quả.
- **Làm sạch.** Chuyển chữ TCVN3 sang Unicode; bỏ dòng quảng cáo, chữ ký người soạn, bảng
  tiêu đề của đề sau bị ghép vào cuối lời giải, phần lời giải của câu khác bị đặt nhầm chỗ,
  và cụm "(tham khảo hình vẽ)" ở câu đã bỏ hình.
- **Hình.** 1.249 ảnh nằm trong `images/`; ảnh WMF/EMF được chuyển sang PNG.

## Hạn chế

- `difficulty` do mô hình gán, chưa có giáo viên xác nhận, và lệch có hệ thống so với nhãn
  của tác giả đề ở ranh giới Nhận biết/Thông hiểu (xem mục Độ khó).
- Đáp án chưa được giải lại độc lập toàn bộ.
- Phân bố chủ đề không đều: gần 51% câu `usable` là nguyên hàm, tích phân và ứng dụng; phần
  còn lại chủ yếu từ bộ đề minh họa 2024. Câu đúng/sai (37) và trả lời ngắn (55) còn ít.
- 140 câu `usable` của sách không có lời giải.
- Câu trùng được rà tay theo độ giống của đề, nên có thể còn sót cặp trùng viết khác nhiều.
- Ở phần đề kiểm tra của sách, hình trôi nổi đôi khi được Word neo vào câu liền trước.
  Muốn dùng các câu có hình cho mô hình đọc ảnh thì cần kiểm tra lại vị trí hình bằng tay.

## Nguồn và quyền sử dụng

Nội dung được trích từ bộ tài liệu "Giải tích 12 – Nguyên hàm, Tích phân và Ứng dụng" của
thầy Nguyễn Quốc Hoàn, và từ đề thi thử, đề khảo sát của các Sở GD&ĐT, các trường THPT và
bộ đề phát triển đề minh họa 2024 chia sẻ trên mạng. Bản quyền nội dung thuộc tác giả và
đơn vị ra đề. Dataset chỉ dùng cho nghiên cứu; muốn phát hành công khai hoặc dùng thương mại
cần có sự đồng ý của tác giả.

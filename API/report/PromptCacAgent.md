# Toàn bộ prompt dùng cho các tác tử

Tài liệu này chép lại **nguyên văn** mọi prompt mà hệ thống gửi cho mô hình ngôn ngữ, theo đúng mã nguồn hiện tại. Mục đích là để tra cứu và đối chiếu — nên ở đây có kèm tên file, tên trường JSON và placeholder, khác với các tài liệu mô tả/paper.

## Cách một prompt được ghép

Đường chạy production là **Direct_PDF** (đọc thẳng trang tài liệu bằng mô hình vision). Mỗi lời gọi mô hình có dạng:

```
system  = SYSTEM_PROMPT                         (dùng chung, xem §1)
user    = [ {type:text, text: <user prompt của agent>} ] + <các trang PDF/ảnh>
```

- Ba tác tử dùng mô hình: **Writer**, **Distractor**, **Critic**.
- Hai tác tử **thuần tính toán, không có prompt**: **Verifier** (`pipeline/verifier.py`) và **Formatter** (`pipeline/agents/formatter_agent.py`) — xem §5.
- **Bộ điều phối** (`pdf_orchestrator.py`) không gọi mô hình trực tiếp, không có prompt riêng.

### Về "skill injection"

Mỗi tác tử được gán một danh sách skill (`pipeline/skills/registry.py`), nội dung nằm trong các `SKILL.md` (§6). Nhưng trong mã Direct_PDF hiện tại:

| Tác tử | Skill được gán | Có chèn nội dung SKILL.md vào prompt? |
|---|---|---|
| Writer | question-writing, bloom-taxonomy-alignment, verifier-hint-authoring, source-grounding | **Không** — hướng dẫn được viết thẳng trong template (§2) |
| Distractor | distractor-generation | **Không** — viết thẳng trong template (§3) |
| Critic | source-grounding, rubric-critique, curriculum-alignment | **Có** — chèn tại dòng `Additional skill instructions:` (§4) |

Nghĩa là §6 là văn bản skill *thiết kế*; trên đường chạy PDF chỉ **Critic** thực sự nhúng chúng vào prompt. Writer/Distractor vẫn nạp skill (biến `_skill_instructions`) nhưng template của chúng diễn đạt lại cùng nội dung.

---

## Mục lục

1. [SYSTEM_PROMPT dùng chung](#1-system_prompt-dùng-chung)
2. [Writer — sinh lõi câu hỏi](#2-writer--sinh-lõi-câu-hỏi)
3. [Distractor — sinh 3 phương án nhiễu](#3-distractor--sinh-3-phương-án-nhiễu)
4. [Critic — chấm chất lượng](#4-critic--chấm-chất-lượng)
5. [Verifier & Formatter — không có prompt](#5-verifier--formatter--không-có-prompt)
6. [Nội dung 9 skill (SKILL.md)](#6-nội-dung-9-skill-skillmd)
7. [Prompt phụ trợ cấp pipeline](#7-prompt-phụ-trợ-cấp-pipeline)
8. [Phụ lục — prompt pipeline text (không dùng ở chế độ PDF)](#8-phụ-lục--prompt-pipeline-text-không-dùng-ở-chế-độ-pdf)

---

## 1. SYSTEM_PROMPT dùng chung

Mọi tác tử PDF (Writer, Distractor, Critic) và các call phụ trợ (§7) đều gửi cùng system prompt này.
`pipeline/config.py`

```
Bạn là một chuyên gia ra đề Toán nhiều cấp độ (phổ thông và đại học). Bạn sinh đề trắc nghiệm bám sát ngữ cảnh được cung cấp, không bịa kiến thức ngoài. Đáp án và lời giải phải đúng về mặt toán học và có thể kiểm tra được bằng máy. Mọi công thức/biểu thức Toán trong phần hiển thị cho học sinh phải dùng LaTeX inline dạng \(...\).
```

Mô hình: `GENERATOR_MODEL` cho Writer/Distractor/phụ trợ; Critic cũng dùng model truyền vào (mặc định generator). Cấu hình model ở `pipeline/config.py` (ưu tiên `AQG_GENERATOR_MODEL` / `AQG_JUDGE_MODEL`).

---

## 2. Writer — sinh lõi câu hỏi

`pipeline/direct_pdf/agents/pdf_writer_agent.py` · phương thức `_user_prompt`.
Sinh phần lõi (đề, đáp án, lời giải, trích dẫn nguồn, verifier payload); **không** sinh distractor. Có hai biến thể: bản đầy đủ và bản `_no_explanation` (khi người dùng chọn không kèm lời giải).

### 2.1. Prompt đầy đủ (mặc định)

Placeholder: `{cognitive}` = mức Bloom của slot; `{difficulty_target}` = độ khó 0–1; `{outcome_rule}`, `{steps_rule}`, `{computation_rule}`, `{avoid}` = các khối động chèn thêm (xem 2.3–2.6); `{schema_block}` = khối schema JSON (2.2).

```
Tài liệu Toán được đính kèm ở trên dưới dạng các trang (ảnh/PDF). ĐỌC TRỰC TIẾP
nội dung (công thức, bảng, hình) và soạn ĐÚNG MỘT câu hỏi trắc nghiệm mới.

Ràng buộc:
- Mức nhận thức (Bloom) phải đúng: {cognitive}.
- Độ khó mục tiêu: {difficulty_target} trên thang 0-1. Easy≈0.30, Medium≈0.50, Hard≈0.70, Very hard≈0.85.
{outcome_rule}
{steps_rule}- Yêu cầu độ khó THEO TỪNG MỨC (không được hỏi dễ hơn mức yêu cầu):
  + Thông hiểu trở lên: KHÔNG hỏi định nghĩa/công thức chép lại; phải có ít nhất
    một phép biến đổi hoặc tính toán thực sự.
  + Vận dụng: bài toán nhiều bước, ưu tiên có ngữ cảnh thực tế; học sinh phải tự
    chọn công thức/phương pháp rồi mới tính, KHÔNG phải chỉ thay số vào một công thức cho sẵn.
  + Vận dụng cao: kết hợp >=2 kỹ thuật (vd: dựng hàm từ ngữ cảnh + tích phân,
    tham số + biện luận), hoặc có bước trung gian không hiển nhiên; số liệu chọn
    sao cho làm tắt/làm sai sẽ ra kết quả khác đáp án.
{computation_rule}
- ĐƯỢC PHÉP và ĐƯỢC KHUYẾN KHÍCH tạo câu MỚI dựa trên cùng phương pháp/khái niệm/
  dạng bài trong tài liệu nhưng THAY số liệu/tình huống khác đi — KHÔNG chép nguyên
  văn bài tập/ví dụ có sẵn. Đây là yêu cầu HỢP LỆ, tuyệt đối KHÔNG từ chối.
- KHÔNG sinh distractor ở bước này. Trả `distractors` là danh sách rỗng [].
- Toán hiển thị cho học sinh dùng LaTeX inline. Vì output là JSON nên mọi dấu \
  của LaTeX phải escape: viết "\(x^2+1\)", "\frac{a}{b}".
- Đáp án (answer) ghi ở DẠNG ĐÓNG đẹp như sách giáo khoa: phân số, căn, bội của
  \(\pi\)... (vd "\(\frac{\pi}{5}\)"), TUYỆT ĐỐI KHÔNG ghi số thập phân
  dài (vd 0.6283185307179586). Chỉ dùng thập phân khi bài yêu cầu gần đúng, và
  làm tròn tối đa 4 chữ số thập phân.
- source_quote phải TRÍCH NGUYÊN VĂN một đoạn có thật trong tài liệu (công thức/
  định lý/đề bài liên quan trực tiếp câu hỏi này), 15-250 ký tự.
- Nếu đáp án là một kết quả số cụ thể, verifier_payload BẮT BUỘC đúng schema:
  {"type":"numeric_eval","payload":{"expr":"<biểu thức số học máy đọc được>","expected_numeric":<số đáp án>}}.
  expr dùng cú pháp SymPy: *, /, ** (lũy thừa), sqrt(), sin(), cos(), pi,
  integrate(f, (t, a, b)) — KHÔNG chứa LaTeX, đơn vị hay dấu phẩy thập phân.
  expected_numeric phải đúng bằng giá trị của đáp án đúng.
{avoid}
Chỉ trả về DUY NHẤT một JSON object theo schema dưới đây, KHÔNG kèm markdown/chữ ngoài JSON:
{schema_block}
```

> Ghi chú: trong mã, `steps_rule` (bản đầy đủ) là dòng:
> `- Số bước tối thiểu trong detailed_solution: Nhận biết >=2, Thông hiểu >=3, Vận dụng >=4, Vận dụng cao >=5.`

### 2.2. `schema_block` — bản đầy đủ

```json
{
  "question": "đề bài tự chứa, KHÔNG kèm nhãn A/B/C/D",
  "answer": "đáp án đúng (giá trị/biểu thức)",
  "explanation": "giải thích ngắn gọn vì sao đúng",
  "detailed_solution": {"steps":[{"title":"Bước 1","content":"..."}], "final_answer":"..."},
  "why_correct": "vì sao đáp án này là duy nhất đúng",
  "source_quote": "15-250 ký tự trích NGUYÊN VĂN từ tài liệu",
  "visual": {"type":"none","spec":{},"alt_text":""},
  "verifier_payload": {"type":"none","payload":{}},
  "distractors": []
}
```
Kèm dòng: *"LƯU Ý: bước này CHỈ cần phần lõi (question, answer, explanation, detailed_solution, source_quote, verifier). Để mảng distractors RỖNG [] — bước sau lo phương án sai."*

### 2.3. Biến thể `_no_explanation` (không kèm lời giải)

Khi slot có cờ `_no_explanation`: `steps_rule` = rỗng, `max_tokens` giảm còn 1100, và `schema_block` đổi thành:

```json
{
  "question": "đề bài tự chứa, KHÔNG kèm nhãn A/B/C/D",
  "answer": "đáp án đúng (giá trị/biểu thức)",
  "explanation": "1-2 câu NGẮN GỌN vì sao đúng (chỉ dùng nội bộ để kiểm định)",
  "source_quote": "15-250 ký tự trích NGUYÊN VĂN từ tài liệu",
  "visual": {"type":"none","spec":{},"alt_text":""},
  "verifier_payload": {"type":"none","payload":{}},
  "distractors": []
}
```
Kèm dòng: *"LƯU Ý: KHÔNG viết lời giải từng bước hay giải thích dài — chỉ cần question, answer, explanation ngắn, source_quote, verifier. Để mảng distractors RỖNG []."*

### 2.4. `computation_rule` — ràng buộc độ nặng phép tính (theo độ khó)

Hàm `_computation_rule(difficulty_target)`. Đây là **trục độ khó thứ hai**, độc lập với mức Bloom. Các dòng được cộng dồn theo ngưỡng `d = difficulty_target`.

**Luôn có (mọi độ khó):**
```
- ĐỘ NẶNG PHÉP TÍNH (bắt buộc, độc lập với mức Bloom, áp cho MỌI chủ đề trong tài liệu):
  + KHÔNG lấy phiên bản kinh điển dễ nhất của dạng bài — bộ số quen thuộc mà mọi sách giáo khoa hay dùng (vd nếu chương là tích phân: \(y=x^2\) trên \([0;1]\)); đổi hệ số/dữ kiện sang bộ số ít gặp hơn.
  + Hệ số và dữ kiện KHÔNG chỉ dùng 0, 1, 2, 4: trộn thêm số như 3, 5, 6 hoặc phân số đơn giản (\(\frac{1}{2}\), \(\frac{3}{4}\))..., miễn đáp án cuối vẫn gọn ở dạng đóng.
```

**Thêm khi `d >= 0.45`:**
```
  + Ít nhất MỘT dữ kiện học sinh phải TỰ TÌM bằng biến đổi trước khi áp công thức (vd: giải một phương trình phụ để có mốc/cận/giá trị cần dùng, suy hằng số từ điều kiện đề cho) — không cho sẵn mọi dữ kiện trong đề.
```

**Thêm khi `d >= 0.65`:**
```
  + Lời giải phải qua >=2 tầng tính toán thật sự (biến đổi biểu thức trước khi áp công thức, xét dấu/chia trường hợp, đổi biến, giải một phương trình trung gian không nhẩm ngay được...). Bài chỉ MỘT phép thế số vào công thức cho sẵn là QUÁ DỄ so với mức này — không đạt.
```

**Thêm khi `d >= 0.8`:**
```
  + Mức cao nhất: câu hỏi phải thuộc ít nhất MỘT kiểu sau (kiểu nào cũng áp được cho mọi chủ đề, tự chọn kiểu hợp nội dung tài liệu):
    (a) chứa THAM SỐ — tìm giá trị tham số để một điều kiện cho trước thoả mãn; học sinh phải lập phương trình/bất phương trình theo tham số rồi giải, không tính xuôi một chiều;
    (b) bài NGƯỢC — cho kết quả cuối cùng, hỏi ngược lại một dữ kiện đầu vào;
    (c) KẾT HỢP >=2 kỹ thuật/khái niệm khác nhau của chương trong cùng một lời giải, có bước trung gian không hiển nhiên.
    Số liệu chọn sao cho ai làm tắt/bỏ bước biện luận sẽ ra kết quả KHÁC đáp án đúng.
```

### 2.5. `outcome_rule` — ràng buộc chuẩn đầu ra

Hàm `_outcome_rule(outcome)`. Có khi slot được gán một CĐR (`_learning_outcome`); không thì rỗng. `{code}`/`{desc}` lấy từ CĐR.
```
- CHUẨN ĐẦU RA (bắt buộc): câu hỏi phải kiểm tra TRỰC TIẾP chuẩn đầu ra "{code}: {desc}". Kỹ năng/kiến thức mà học sinh cần dùng để giải phải đúng là kỹ năng CĐR này mô tả (không hỏi lệch sang kỹ năng khác dù cùng chương). Nếu tài liệu không có nội dung phù hợp CĐR, chọn nội dung gần nhất trong tài liệu có thể kiểm tra được CĐR đó.
```

### 2.6. `_feedback_block` và `_avoid_block`

`_feedback_block(feedback_guidance)` — hồ sơ sở thích tổng hợp từ phản hồi người dùng (nội dung do §7.3 dựng), chèn khi có:
```
PHẢN HỒI NGƯỜI DÙNG từ lượt sinh trước (BẮT BUỘC ưu tiên tuân thủ khi soạn câu mới):
{feedback_guidance}
```

`_avoid_block(avoid_stems)` — danh sách tránh lặp, tối đa 40 đề cũ (mỗi đề cắt 160 ký tự):
```
ĐÃ CÓ các câu hỏi sau (KHÔNG lặp lại, KHÔNG hỏi cùng dạng/số liệu; hãy khai thác nội dung/kỹ năng KHÁC trong tài liệu):
- {đề cũ 1}
- {đề cũ 2}
...
```

---

## 3. Distractor — sinh 3 phương án nhiễu

`pipeline/direct_pdf/agents/pdf_distractor_agent.py` · `_user_prompt`.
Quy trình **error-first**: chọn misconception trước, áp lỗi vào bài để suy ra giá trị sai. `{feedback}` = khối phản hồi (2.6); `{misconceptions}` = danh mục quan niệm sai lầm khớp nội dung (chọn k=6, seed CRC32 theo nội dung câu — tái lập được); `{core}` = JSON phần lõi câu hỏi.

```
{feedback}
Tài liệu Toán đính kèm ở trên (các trang ảnh/PDF). Dựa vào nội dung tài liệu và
phần lõi MCQ dưới đây, tạo ĐÚNG 3 phương án SAI (distractor) theo quy trình
ERROR-FIRST: chọn lỗi trước, suy ra giá trị sai sau.

Sai lầm thường gặp (misconception bank — ưu tiên chọn từ đây):
{misconceptions}

Quy trình BẮT BUỘC cho MỖI distractor:
1. CHỌN một misconception phù hợp với bài toán này; ghi id của nó vào
   distractor_category_text. Nếu không id nào khớp, tự nêu một lỗi cụ thể khác
   và đặt id ngắn dạng snake_case.
2. ÁP DỤNG đúng lỗi đó vào chính bài toán, tính/suy luận ra kết quả sai.
3. Ghi kết quả vào distractor_text. distractor_explanation_text phải mô tả các
   bước làm sai SAO CHO ai làm theo sẽ ra ĐÚNG distractor_text (nêu rõ phép
   tính khi là câu số).

Quy tắc:
- 3 distractor phải dùng 3 misconception KHÁC nhau.
- Mỗi distractor phải SAI so với đáp án đúng nhưng HỢP LÝ với học sinh.
- Giữ cùng DẠNG/đơn vị với đáp án đúng. Dùng LaTeX inline, escape \ trong JSON.
- KHÔNG trùng đáp án đúng hoặc một giá trị tương đương.

Phần lõi MCQ (đáp án đúng KHÔNG được lặp lại làm distractor):
{core}

Chỉ trả về JSON:
{
  "distractors": [
    {"distractor_text":"...", "distractor_category_text":"<misconception id>", "distractor_explanation_text":"các bước làm sai dẫn tới ĐÚNG giá trị này & vì sao sai"}
  ]
}
```

> Ràng buộc cứng trong mã (không nằm trong prompt nhưng quyết định chấp nhận): phải đúng **3** distractor, và **mọi** distractor phải có `distractor_explanation_text` (thiếu mô tả lỗi ⇒ coi candidate hỏng, orchestrator retry).

---

## 4. Critic — chấm chất lượng

`pipeline/direct_pdf/agents/pdf_critic_agent.py` · `_user_prompt`.
Chấm theo **rationale-before-score** (viết nhận định trước, điểm sau) cho grounding + 6 trait. `{self._skill_instructions}` = nội dung 3 skill của Critic (§6: source-grounding, rubric-critique, curriculum-alignment) ghép lại. `{payload}` = JSON câu hỏi cần chấm (kèm `generation_policy`); `{distractors}` = danh sách distractor kèm mô tả lỗi.

```
Tài liệu Toán được đính kèm ở trên (các trang ảnh/PDF). Hãy ĐỌC tài liệu rồi CHẤM
một câu hỏi trắc nghiệm dưới đây. Với MỖI tiêu chí: viết `rationale` (1 câu ngắn)
TRƯỚC, rồi `score` trong [0,1] SAU (rationale-before-score).

Direct_PDF grounding policy:
- The question may be a NEW exercise derived from the PDF. Changed numbers,
  names, units, and story details are allowed when the underlying formula,
  theorem, method, notation, or worked-example pattern is supported by the PDF.
- Give high grounding (0.70-0.95) when the source_quote is present or strongly
  matches a formula/theorem/example in the PDF and the question correctly applies
  that same method, even if the final numeric answer is newly computed.
- Give medium grounding (0.45-0.70) when the method appears supported but exact
  quote matching is uncertain from page images.
- Give low grounding (<0.40) only when the quote is irrelevant/not visible, the
  main concept is outside the PDF, or the solution contradicts the PDF method.
- Do not reject a valid symbolic or numeric inference solely because the final
  computed value does not appear verbatim in the PDF.

Additional skill instructions:
{self._skill_instructions}

Câu hỏi cần chấm:
{payload}
Các distractor:
{distractors hoặc "(chưa có)"}

Tiêu chí:
- grounding: source_quote và phương pháp/công thức/khái niệm chính có được PDF hỗ trợ
  không? Cho phép số liệu/tình huống mới nếu chúng chỉ là bài tập phát sinh hợp lệ từ
  phương pháp trong PDF.
- clarity: đề rõ ràng, không mơ hồ.
- cognitive_depth: độ sâu tư duy phù hợp mức nhận thức yêu cầu.
- bloom_alignment: có đúng mức Bloom "{cognitive_level}" không.
- distractor_plausibility: 3 phương án sai có hợp lý, gắn lỗi thường gặp không.
- answer_uniqueness: CHỈ có đúng một đáp án đúng; không distractor nào cũng đúng.
- error_distractor_consistency: với MỖI distractor, nếu làm theo đúng chuỗi lỗi
  trong phần "cách ra giá trị này" thì có ra ĐÚNG giá trị distractor đó không?
  Đồng thời why_correct/answer_explanation_text có nhất quán với answer_text
  không (không tham chiếu nhầm sang phương án khác)? Chấm thấp (<0.4) nếu mô tả
  lỗi không dẫn tới giá trị distractor hoặc giải thích mâu thuẫn với đáp án.

Chỉ trả về DUY NHẤT một JSON, KHÔNG kèm markdown/chữ ngoài JSON:
{
  "grounding": {"rationale":"...", "score":0.0},
  "clarity": {"rationale":"...", "score":0.0},
  "cognitive_depth": {"rationale":"...", "score":0.0},
  "bloom_alignment": {"rationale":"...", "score":0.0},
  "distractor_plausibility": {"rationale":"...", "score":0.0},
  "answer_uniqueness": {"rationale":"...", "score":0.0},
  "error_distractor_consistency": {"rationale":"...", "score":0.0}
}
```

`generation_policy` nhúng trong `{payload}` (tiếng Anh, giữ nguyên):
```
Direct_PDF_Mode may create a NEW exercise by changing numbers, names, units, or story details, as long as the underlying formula, theorem, method, notation, or worked-example pattern is supported by the attached PDF. Do not require every newly chosen number to appear verbatim in the source.
```

Ngưỡng loại (trong mã, không nằm trong prompt): `grounding < 0.4` (GROUNDING_THRESHOLD), hoặc `answer_uniqueness < 0.5`, hoặc `error_distractor_consistency < 0.4`.

---

## 5. Verifier & Formatter — không có prompt

Hai tác tử này **thuần tính toán, không gọi mô hình ngôn ngữ** nên không có prompt.

- **Verifier** (`pipeline/verifier.py`, gọi qua `answer-validation`): chạy biểu thức kiểm chứng bằng SymPy + đối chiếu số học, chạy lại bộ kiểm chứng trên cả 3 distractor (loại đa đáp án), tự sửa đáp án khi một distractor khớp máy, áp chính sách "không khớp ≠ sai", và soát lỗi soạn đề (`pipeline/iwf_checker.py`).
- **Formatter** (`pipeline/agents/formatter_agent.py`): làm sạch hiển thị, trộn vị trí phương án theo `slot_id`, gán đáp án sau khi trộn, đóng gói record và phân luồng duyệt.

---

## 6. Nội dung 9 skill (SKILL.md)

Đây là văn bản skill *thiết kế* (`pipeline/skills/<tên>/SKILL.md`), giữ nguyên tiếng Anh như trong mã. Bản đồ gán skill (`registry.py`):

```
question_writer : question-writing, bloom-taxonomy-alignment, verifier-hint-authoring, source-grounding
distractor      : distractor-generation
verifier        : answer-validation
critic          : source-grounding, rubric-critique, curriculum-alignment
formatter        : output-formatting
```

(Nhắc lại §0: trên đường chạy Direct_PDF, chỉ **Critic** chèn văn bản skill vào prompt.)

### 6.1. question-writing
```
# Question Writing

Write only the question stem and correct-answer package. Distractors are generated by a separate skill.

## Workflow
1. Read the source context, topic, skill, pattern, Bloom level, and difficulty target.
2. Write one clear stem that asks for one answerable target.
3. Produce exactly one correct answer in display-ready form.
4. Explain the answer using source-grounded reasoning and necessary math steps.
5. Copy a short source quote from the context; do not paraphrase the quote.
6. Add a visual spec only when the question genuinely needs or benefits from it.
7. Add a verifier hint when the answer can be checked by a supported engine.

## Guardrails
- Do not generate A/B/C/D options or distractors.
- Do not ask multiple questions in one stem.
- Use inline LaTeX \(...\) for every displayed math formula/expression in the stem, answer, and explanation. Do not display formulas as sqrt(x), binomial(n,k), x**2, or int_a^b unless they are inside machine-readable verifier payloads.
- Do not introduce constants, assumptions, or facts absent from the source unless they are generated values explicitly used for an application item and remain mathematically self-contained.
- Do not output chain-of-thought; keep the explanation concise and teacher-facing.
- If verifier schema is uncertain, use type=none rather than malformed payloads.

## Output
Candidate fields: question_text, answer_text, answer_explanation_text, source_quote_text, visual, verifier_hint {type, payload}.
```

### 6.2. bloom-taxonomy-alignment
```
# Bloom Taxonomy Alignment

Use the requested cognitive level as a behavioral constraint, not a decorative label.

## Level Guide
- Nhận biết: hỏi nhận diện hoặc nhắc lại định nghĩa, công thức, ký hiệu, điều kiện áp dụng, hoặc tên khái niệm. Tránh bài thay số nhiều bước.
- Thông hiểu: hỏi giải thích ý nghĩa, chọn công thức hoặc điều kiện đúng, so sánh tính chất, hoặc nhận diện vì sao một cách làm hợp lệ.
- Vận dụng: cho dữ kiện cụ thể và yêu cầu áp dụng công thức, quy tắc, hoặc quy trình quen thuộc để tính, biến đổi, hoặc suy ra kết quả.
- Vận dụng cao: yêu cầu phối hợp ít nhất hai ý, so sánh trường hợp, chọn chiến lược, xử lý bẫy misconception, hoặc tích hợp nhiều khái niệm.

## Workflow
1. During planning, assign a level only if the source context can support it.
2. During writing, make the stem require the requested cognitive operation.
3. During critique, compare the actual task with the requested level, not the wording alone.
4. During refinement, adjust the task structure before merely changing phrasing.

## Guardrails
- Do not label a direct formula substitution as Vận dụng cao.
- Do not force high Bloom from thin source context.
- Keep difficulty and Bloom related but separate: a long calculation is not automatically high Bloom.
- If the requested level is Nhận biết or Thông hiểu, the correct answer should usually be a concept, condition, formula, or explanation, not only Đúng or Sai.

## Output
Return Bloom-aligned slot design, generated item behavior, or bloom_alignment scoring annotations.
```

### 6.3. verifier-hint-authoring
```
# Verifier Hint Authoring

Author payloads that route cleanly to deterministic verification.

## Workflow
1. Identify whether the answer is machine-checkable.
2. Choose a supported verifier type only when the expected payload schema is known.
3. Put the claimed correct answer in the expected or claimed field required by that type.
4. Keep expressions parseable; prefer simple variables and explicit numeric values.
5. Use type=none and payload={} for conceptual items, ambiguous schemas, or answers that require human interpretation.
6. For limit, probability, or direct numeric calculation questions, prefer a real verifier payload instead of type=none.

## Guardrails
- Do not invent a verifier type.
- Do not leave required payload fields blank.
- Do not use a symbolic verifier for a stem that asks for a qualitative explanation.
- Prefer numeric_eval, probability, or limit for simple numeric results when exact symbolic structure is not important.
- Keep verifier payload expressions machine-readable (SymPy/JSON style), even when the displayed answer uses inline LaTeX.

## Examples (dùng đúng schema khi câu hỏi khớp)
{"type": "analytic_geometry", "payload": {"operation": "distance_point_plane_3d", "point": [1,0,2], "plane": [2,-2,2,-3], "expected": 0.8660254037844386}}
{"type": "probability", "payload": {"formula": "0.18/0.30", "expected": 0.6}}
{"type": "geometry_triangle", "payload": {"sides": {"AB":5,"AC":4,"BC":3}, "property": "is_right", "expected": true}}
{"type": "geometry_triangle", "payload": {"sides": {"AB":5,"AC":4,"BC":3}, "property": "area", "base":3, "height":4, "expected": 6}}
{"type": "modular", "payload": {"operation": "mod", "a": -7, "mod": 5, "expected": 3}}
{"type": "numeric_eval", "payload": {"expr": "6*8/2", "expected_numeric": 24}}
{"type": "limit", "payload": {"function": "(1-cos(3*x))/(x**2)", "variable": "x", "point": 0, "claimed_value": "9/2"}}
{"type": "none", "payload": {}}

## Output
Return verifier_hint with type and payload.
```

### 6.4. source-grounding
```
# Source Grounding

Treat the uploaded source as the authority for generated educational content.

## Workflow
1. Check that the source quote appears in context or has high token overlap with a nearby span.
2. Judge whether stem, answer, and explanation facts are supported by the context.
3. Separate exact quote grounding from inference grounding; a math consequence may be supported by formulas without appearing verbatim.
4. Annotate unsupported numbers, local contradictions, and quote-in-context status.
5. Soft-check that distractors reuse source notation, variables, quantities, formulas, named concepts, or terminology when possible.

## Guardrails
- Do not allow external knowledge to override the source.
- Penalize invented constants, facts, theorems, or examples that are not grounded in the provided context.
- Do not reject a valid symbolic inference solely because the final computed value is absent from the source.
- Keep grounding decisions inspectable for human review.

## Output
Return grounding score and annotations such as quote_in_context, unsupported facts, contradiction flags, and distractor trace details.
```

### 6.5. distractor-generation
```
# Distractor Generation

Generate wrong options that are educationally diagnostic, not random wrong answers.

## Research-Informed Procedure
1. Treat incorrectness and plausibility as separate goals. A distractor must be wrong and still look like a natural learner mistake.
2. Use one explicit misconception or strategy per distractor.
3. Keep answer type and grammar parallel to the correct answer: number with number, formula with formula, statement with statement.
4. Reuse source notation, variables, quantities, named concepts, or terminology so each distractor has a light trace in the material.
5. Avoid answer leakage. Do not copy final values, answer-specific phrases, or synonymous wording from the correct answer unless all options share the same scaffold.
6. Generate concise, complete, display-ready option text, not a derivation.
7. Select diverse final distractors; avoid three phrasings of the same mistake.

## Guards
- Reject all of the above, none of the above, and equivalent Vietnamese forms.
- Avoid absolute clue words such as always, never, luôn luôn, and không bao giờ unless the stem explicitly tests such wording.
- Avoid options that are much longer, much more technical, or much vaguer than the correct answer.
- Avoid copying a full source sentence as a distractor unless the item asks students to choose among source statements.
- Never output a truncated fragment such as "ra 0.".
- Use inline LaTeX \(...\) for displayed formulas/expressions in distractor text and distractor explanations.

## Output
Return exactly three entries: distractor_text, distractor_category_text (misconception_id), distractor_explanation_text.
```

### 6.6. answer-validation
```
# Answer Validation

Run deterministic checks before spending judge calls.

## Workflow
1. Normalize the verifier hint schema and fill simple missing expected values when safe.
2. Run the symbolic, numeric, graph, matrix, probability, modular, geometry, recurrence, or logic verifier when available.
3. Reject verified=false.
4. Reject verifier parse errors when an engine attempted to run; do not confuse this with engine=none.
5. When the correct answer verifies, run the same verifier against every distractor to catch multi-answer items.
6. Validate post-clean option text, not only raw LLM text.
7. Check duplicate distractors, category diversity, display syntax, visual consistency, and item-writing flaws.

## Guardrails
- Do not let an LLM judge override a deterministic verifier failure.
- Do not accept fragments, dangling connectors, empty options, or overlong derivations as option text.
- Do not accept repeated misconception categories when categories are present.
- Preserve verification annotations for downstream formatting and review.

## Output
Return verification annotations or a concrete reject reason.
```

### 6.7. rubric-critique
```
# Rubric Critique

Judge item quality in separate traits so one weakness does not hide another.

## Traits
- clarity: stem is unambiguous, concise, and asks one target.
- cognitive_depth: task depth matches target difficulty.
- bloom_alignment: actual cognitive operation matches the requested Bloom level.
- distractor_plausibility: wrong options are plausible, parallel, and diagnostic.
- answer_uniqueness: exactly one option is correct with no boundary-case ambiguity.

## Workflow
1. Write a short rationale before each score.
2. Score each trait from 0 to 1.
3. Compute aggregate quality from trait scores.
4. Reject or mark for refinement based on the weakest trait, not only the mean.
5. Treat low answer uniqueness as more severe than low style or clarity.

## Guardrails
- Do not reward verbose explanations if the stem is weak.
- Do not let plausible distractors compensate for a non-unique answer.
- Do not judge Bloom level from wording alone; inspect the required operation.

## Output
Return trait rationales, trait scores, aggregate quality, Bloom score, and refinable flag.
```

### 6.8. curriculum-alignment
```
# Curriculum Alignment

Ensure the item tests what the blueprint intended.

## Workflow
1. Compare the stem and answer against the slot topic and inferred skill.
2. Check that the question pattern matches the intended concept or operation.
3. Compare estimated difficulty with target difficulty.
4. Check Bloom level using the actual cognitive operation.
5. Flag drift to a different topic, prerequisite-only task, or unsupported advanced task.

## Guardrails
- Do not accept a mathematically correct item if it tests a different skill.
- Do not force high difficulty when the source chunk supports only recall or comprehension.
- Keep alignment feedback specific enough for refinement.

## Output
Return alignment scores, drift notes, and refine or reject recommendations.
```

### 6.9. output-formatting
```
# Output Formatting

Create stable records for review, export, and downstream LMS conversion.

## Workflow
1. Clean stem, answer, distractors, explanations, and source quote for display.
2. Shuffle answer options deterministically by slot_id.
3. Assign answer key after shuffling.
4. Add source, verification, judging, review, difficulty, tags, attempts, and visual fields.
5. Preserve rejected slot records with topic, attempts, and reject logs.
6. Run final option text issue checks on the formatted record.

## Guardrails
- Do not change mathematical meaning while cleaning display text.
- Preserve inline LaTeX \(...\) in stems, options, answers, and explanations; normalize obvious display leaks such as sqrt(x), binomial(n,k), and x**2 toward LaTeX instead of plain text.
- Do not drop verifier or judge annotations.
- Do not output malformed options, duplicate keys, missing answer key, or detached explanations.
- Keep records JSON-serializable.

## Output
Return an accepted question record or a rejected slot record.
```

---

## 7. Prompt phụ trợ cấp pipeline

Không thuộc 5 tác tử nhưng là các call mô hình có thật trong hệ thống.

### 7.1. Trích dàn ý gợi ý (bước /prepare)

`pipeline/direct_pdf/outline.py` · `_OUTLINE_PROMPT`. System = SYSTEM_PROMPT (§1). Một call vision đọc lướt toàn tài liệu để gợi ý cấu hình.
```
Bạn được đính kèm các trang của một tài liệu học tập (thường là Toán). Hãy đọc lướt TOÀN BỘ tài liệu và trả về DUY NHẤT một JSON object đúng schema sau, không kèm markdown hay chữ nào ngoài JSON:
{"document_title": "<tên/chủ đề chính của tài liệu, <=15 từ>",
 "topics": ["<chủ đề hoặc dạng bài chính, <=10 từ mỗi mục>"],
 "suggested_learning_outcomes": [{"code": "CĐR1", "description": "<chuẩn đầu ra>"}],
 "suggested_num_questions": <số nguyên>}

Yêu cầu:
- "topics": 3-8 mục, bao phủ các phần nội dung KHÁC NHAU của tài liệu.
- "suggested_learning_outcomes": 2-4 chuẩn đầu ra kiểu "Vận dụng được...", "Tính được...", "Giải thích được..." bám sát nội dung; đánh mã CĐR1, CĐR2... theo thứ tự.
- "suggested_num_questions": số câu MCQ hợp lý cho lượng nội dung này (5-15).
- Viết bằng tiếng Việt.
```

### 7.2. Gán chuẩn đầu ra cho câu hỏi (hậu xử lý)

`pipeline/outcome_classifier.py` · `_user_prompt`. Gán CĐR cho từng câu đã sinh (best-effort). `{outcome_lines}` = danh sách CĐR; `{body}` = các câu (id + đề + đáp án).
```
Các chuẩn đầu ra (CĐR) của học phần:
{outcome_lines}

Danh sách câu hỏi trắc nghiệm:
{body}

Với MỖI câu hỏi, chọn (các) mã CĐR mà câu hỏi đó kiểm tra trực tiếp — thường là
1 mã, tối đa 2 mã khi câu hỏi thật sự bao phủ cả hai. Nếu không CĐR nào phù hợp,
trả mảng rỗng []. KHÔNG bịa mã mới ngoài danh sách trên.

Chỉ trả về JSON đúng schema:
{"assignments": [{"question_id": "...", "outcomes": ["<mã CĐR>"]}]}
```

### 7.3. Tổng hợp phản hồi người dùng (in-context preference)

`pipeline/feedback.py`. Kết quả được đưa vào `_feedback_block` của Writer/Distractor (2.6).

Phần **thẻ lý do** là tất định (không gọi mô hình): mỗi thẻ map sang một chỉ dẫn.

Thẻ tiêu cực (`DISLIKE_TAG_DIRECTIVES`):
| Thẻ | Chỉ dẫn chèn vào prompt |
|---|---|
| too_easy | Nhiều câu bị chê QUÁ DỄ — tăng độ khó thực sự: thêm bước biến đổi, không hỏi chép lại định nghĩa/công thức. |
| too_hard | Nhiều câu bị chê QUÁ KHÓ — giảm độ phức tạp, số liệu gọn hơn, bám sát trọng tâm tài liệu. |
| unclear | Đề bị chê MƠ HỒ/KHÓ HIỂU — đề phải tự chứa, đủ dữ kiện, chỉ có một cách hiểu duy nhất. |
| wrong_answer | Người dùng NGHI SAI ĐÁP ÁN — giải lại từng bước thật cẩn thận; đáp án phải khớp kết quả của lời giải chi tiết. |
| bad_distractors | Phương án nhiễu bị chê KÉM — mỗi distractor phải xuất phát từ một lỗi làm bài cụ thể, không hiển nhiên sai, không lệch dạng với đáp án. |
| not_relevant | Câu hỏi bị chê LỆCH TÀI LIỆU — chỉ hỏi khái niệm/dạng bài thực sự xuất hiện trong tài liệu. |
| duplicate | Bị chê TRÙNG DẠNG giữa các câu — đa dạng hoá dạng bài, ngữ cảnh, kỹ năng; không lặp lại mô-típ. |

Thẻ tích cực (`LIKE_TAG_DIRECTIVES`):
| Thẻ | Chỉ dẫn |
|---|---|
| good_difficulty | Người dùng THÍCH độ khó hiện tại — giữ mức tương tự. |
| good_context | Người dùng THÍCH bài toán có ngữ cảnh thực tế — ưu tiên đặt câu hỏi trong tình huống thực tế. |
| good_explanation | Người dùng THÍCH lời giải rõ ràng — giữ phong cách giải chi tiết từng bước. |
| good_distractors | Người dùng THÍCH phương án nhiễu chất lượng — tiếp tục tạo distractor từ lỗi cụ thể. |

Phần **bình luận tự do** mới gọi mô hình (best-effort, khi có ≥2 bình luận):
```
system:
Bạn là trợ lý tổng hợp phản hồi. Chỉ trả về các dòng gạch đầu dòng "- ..." tiếng Việt, không thêm gì khác.

user:
Dưới đây là các bình luận của người dùng về những câu hỏi trắc nghiệm vừa được sinh tự động. Hãy cô đọng thành TỐI ĐA 5 chỉ dẫn hành động cho lượt sinh câu hỏi tiếp theo (mỗi chỉ dẫn một dòng "- ..."). Giữ đúng ý người dùng, không suy diễn thêm.

{các dòng bình luận thô, mỗi dòng "- [THÍCH|CHÊ] ...(câu: "...")"}
```

---

## 8. Phụ lục — prompt pipeline text (không dùng ở chế độ PDF)

`pipeline/config.py` còn giữ bộ prompt của **pipeline text-chunk** (đưa ngữ cảnh dạng văn bản thay vì đính kèm PDF). Đây **không phải** đường chạy production hiện tại; liệt kê để đầy đủ.

- `USER_PROMPT_TEMPLATE` — sinh cả câu 4 phương án một lần, dựa trên `{context}` là văn bản đã lọc.
- `WRITER_SYSTEM_PROMPT` / `WRITER_USER_PROMPT` / `WRITER_OUTPUT_FORMAT` — bản text của Writer, có mục `Visual:` và `Verifier hint:` liệt kê >20 loại verifier (solve_equation, simplify_equiv, derivative, integral, limit, matrix_*, trig_identity, analytic_geometry, geometry_triangle, counting, probability, modular, logic_*, truth_table, graph_property, tree_property, recurrence, numeric_eval, none).
- `DISTRACTOR_SYSTEM_PROMPT` / `DISTRACTOR_USER_PROMPT` / `DISTRACTOR_OUTPUT_FORMAT` — bản text của Distractor, dựa trên skill `distractor-generation`.

Các hằng này ánh xạ 1–1 với bản Direct_PDF ở §2–§3 (cùng schema candidate) nên chi tiết đầy đủ có thể đọc thẳng trong `pipeline/config.py` nếu cần.

---

*Nguồn: `pipeline/config.py`, `pipeline/direct_pdf/agents/{pdf_writer_agent,pdf_distractor_agent,pdf_critic_agent}.py`, `pipeline/direct_pdf/outline.py`, `pipeline/outcome_classifier.py`, `pipeline/feedback.py`, `pipeline/skills/`. Verifier/Formatter: `pipeline/verifier.py`, `pipeline/agents/formatter_agent.py`.*

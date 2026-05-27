# ĐÁNH GIÁ CHÂN THẬT VÀ PROMPT CẢI TIẾN PIPELINE AQG

> Dựa trên phân tích thực tế từ: `result.json`, `plan.json`, `chunks.json`, `clean_contexts.json`, `meta.json`, `status.json`, `config.json`  
> Job: `46f4064904` | PDF: `toan-thuc-te-nguyen-ham-va-tich-phan-toan-12.pdf` | 12 câu hỏi

---

## PHẦN 1: ĐÁNH GIÁ CHÂN THẬT

### 1.1 Con số không nói dối

| Chỉ số | Giá trị | Đánh giá |
|--------|---------|-----------|
| Câu hỏi sinh được | 12 | ✅ Đạt target |
| Rejected | 0 | ✅ Tốt |
| **Tổng token** | **1,729,837** | 🔴 Thảm họa |
| **Tổng API calls** | **552** | 🔴 Thảm họa |
| **Token / câu** | **~144,153** | 🔴 Cực kỳ tốn kém |
| **Calls / câu** | **~46 calls** | 🔴 Không chấp nhận được |
| Q3 attempts | 3 | 🟡 Đã phải retry |
| Q5 attempts | 2 | 🟡 Đã phải retry |
| Q7 attempts | 3 | 🟡 Đã phải retry |
| Q1 solution steps | 1 (chỉ 1 bước) | 🔴 Lời giải rỗng |
| Q4 solution steps | 1 (chỉ 1 bước) | 🔴 Lời giải rỗng |

**Thực tế**: Để sinh 12 câu hỏi Toán cấp 12, pipeline của bạn đang dùng gần **1.73 triệu token** — tương đương đọc xong khoảng 2,000 trang sách. Đây là mức chi phí không thể scale lên production được. Nếu bạn muốn sinh 100 câu hỏi, ước tính cần ~12 triệu token và ~4,600 API calls — con số đủ để làm API bill ngất.

---

### 1.2 Vấn đề nền tảng: Pipeline đang "học vẹt" từ chính nguồn MCQ

Đây là vấn đề nghiêm trọng nhất mà con số không phản ánh được.

**PDF source** (`prep_0006`, trang 5) chứa sẵn câu hỏi MCQ:
> *"Câu 21: Một quần thể vi khuẩn ban đầu gồm 500 vi khuẩn... Tốc độ tăng trưởng của quần thể vi khuẩn đó cho bởi hàm số P'(t) = k... Sau 1 ngày, số lượng vi khuẩn của quần thể đó đã tăng lên thành 600 vi khuẩn. Tính số lượng vi khuẩn của quần thể đó sau 9 ngày."*

**Câu hỏi được sinh ra (Q2)**:
> *"Một quần thể vi khuẩn ban đầu có 500 vi khuẩn. Tốc độ tăng trưởng của quần thể không đổi theo thời gian và bằng k vi khuẩn/ngày. Sau 1 ngày, quần thể có 600 vi khuẩn. Hỏi sau 9 ngày, quần thể có bao nhiêu vi khuẩn?"*

Pipeline **không sinh câu hỏi mới** — nó đang **paraphrase lại câu hỏi đã có trong sách bài tập**. Khi source PDF là sách bài tập/đề thi, đây là anti-pattern cốt lõi. Thay vì học kiến thức từ lý thuyết để sinh câu hỏi, hệ thống đang đọc câu hỏi cũ và viết lại.

---

### 1.3 Clean Context thực ra rỗng

Mở `clean_contexts.json` ra, chunk `prep_0002`:

```json
{
  "key_definitions": [],
  "key_formulas": [],
  "key_theorems": [],
  "worked_examples": [],
  "misconceptions": [],
  "math_objects": []
}
```

**Tất cả các field quan trọng nhất đều rỗng.** IngestionAgent đã không extract được gì có ý nghĩa. Toàn bộ cấu trúc "clean context" chỉ là wrapper xung quanh raw text — không thêm được giá trị gì cho generator. Pipeline vẫn đang làm việc như thể không có clean context, tức là tốn thêm một agent (IngestionAgent) để sinh ra một file JSON trống.

---

### 1.4 Judge chạy "Fast-path" — không thực sự judge

Q2 có grounding=1.0, quality=0.86 với rationale:
> *"Fast-path: symbolic verification passed and the answer format is concise."*
> *"Fast-path: deterministic verifier confirms the mathematical target."*

**CriticAgent không thực sự chạy** — nó shortcut thành fast-path khi verifier pass, và cho điểm cố định (clarity=0.8, cognitive_depth=0.8, bloom_alignment=0.8). Đây là judge ảo: tốn một LLM call nhưng không sinh ra insight nào.

---

### 1.5 Lời giải chi tiết của nhiều câu gần như trống

Q1 (`detailed_solution`) chỉ có 1 step:
```json
{
  "steps": [{"title": "Kết luận", "content": "Theo định nghĩa nguyên hàm, F'(x) = f(x) ∀x ∈ K."}]
}
```

Q4 chỉ có 1 step tương tự. Đây là "detailed solution" nhưng không có gì để học từ đó. 

---

### 1.6 46 calls/câu — Kiến trúc agent quá nặng

Sơ đồ calls thực tế ước tính:

```
PlannerAgent          →  ~15-20 calls  (plan cho 12 slots × misconceptions × skills)
IngestionAgent        →  ~10-15 calls  (40 chunks × clean context)
QuestionWriterAgent   →  12 calls      (1 per slot, cộng retry)
DistractorAgent       →  12+ calls     (separate từ writer)
VerifierAgent         →  12 calls      
CriticAgent           →  12 calls      (thực ra là fast-path)
RefinerAgent          →  ~5 calls      (các câu cần retry)
FormatterAgent        →  12 calls      
Skills loading        →  overhead      (mỗi agent load skills)
```

**Vấn đề cốt lõi**: Mỗi agent là một LLM call riêng biệt, với system prompt dài + context dài. Skill loading thêm vào overhead đáng kể. Tổng cộng pipeline phình lên ~46 calls/câu trong khi lý thuyết chỉ cần 1-2 calls.

---

### 1.7 Chất lượng câu hỏi: Tốt nhưng chưa đủ thách thức

Nhìn tổng thể, các câu hỏi **đúng về mặt kỹ thuật**, distractor **hợp lý**, explanation **đủ dùng** — đây là điểm tốt. Nhưng:

- Q1 là câu định nghĩa cơ bản nhất của nguyên hàm — quá dễ với học sinh lớp 12 ôn thi
- Q3 cần 3 attempts cho một câu "Nhận biết"
- Q7 cần 3 attempts và grounding thấp hơn (0.8375) — dấu hiệu context không đủ
- Câu "Vận dụng cao" (Q10) về Định lý cơ bản của tích phân có thể gây tranh luận vì không có số liệu cụ thể để compute
- Q4 hỏi về h(t) = ∫₀ᵗ 1/√(1+x²) dx — câu hay nhưng lời giải chỉ có 1 bước

---

## PHẦN 2: PROMPT CẢI TIẾN ~4000 TỪ

---

# MASTER IMPROVEMENT PROMPT: Tái kiến trúc Pipeline AQG Toán

## BỐI CẢNH VÀ MỤC TIÊU

Bạn là kiến trúc sư hệ thống AQG (Automatic Question Generation) cho môn Toán cấp THPT. Pipeline hiện tại đã hoạt động được về mặt chức năng — sinh ra câu hỏi đúng, có explanation, có verifier — nhưng gặp vấn đề nghiêm trọng về hiệu năng và chi phí. Với 12 câu hỏi, pipeline tiêu tốn **1,729,837 tokens** và **552 API calls** — tức ~144,000 tokens và ~46 calls mỗi câu. Đây là con số không thể chấp nhận cho production.

Tài liệu này là specification đầy đủ để bạn **tái kiến trúc** pipeline, không phải patch thêm. Mục tiêu cuối:

- **Target**: Sinh 1 câu hỏi MCQ Toán chất lượng tốt ≤ 5,000 tokens + ≤ 3 LLM calls
- **Throughput**: 100 câu ≤ 500,000 tokens (vs 12 triệu hiện tại)
- **Quality**: Câu hỏi không bị phụ thuộc vào câu hỏi có sẵn trong source
- **Correctness**: Toán học phải đúng, lời giải phải thực sự step-by-step

---

## VẤN ĐỀ 1: LOẠI BỎ SKILLS FRAMEWORK — CHUYỂN VỀ THUẦN PROMPT

### Tại sao skills gây chậm

Skills hiện tại được load cho từng agent call. Mỗi lần agent được invoke, hệ thống cần:
1. Resolve skill path
2. Read skill file từ disk hoặc cache
3. Concatenate vào system prompt
4. Gửi toàn bộ lên LLM

Khi có 8 agents, mỗi agent 1-3 skills, tổng overhead từ skill loading là rất lớn — không phải vì disk I/O mà vì **nó phình system prompt**, tăng input tokens mỗi call.

### Giải pháp: Inline prompt, không skills framework

**Không dùng skills file loading nữa.** Thay vào đó, mỗi agent có một system prompt cố định, ngắn, đã hardcode đủ instructions. Không cần file, không cần resolver, không cần dynamic loading.

Ví dụ thay thế:

```python
# Thay vì:
agent = QuestionWriterAgent()
agent.load_skills(["math_writing", "bloom_taxonomy", "distractor_design"])

# Dùng:
QUESTION_GENERATOR_SYSTEM_PROMPT = """
Bạn là chuyên gia ra đề Toán THPT Việt Nam. Nhiệm vụ: sinh 1 câu MCQ hoàn chỉnh.
[... toàn bộ instruction inline, không load từ file ...]
"""
response = llm.complete(system=QUESTION_GENERATOR_SYSTEM_PROMPT, user=context)
```

**Lợi ích**: System prompt được cache bởi LLM provider (prefix caching). Khi system prompt không thay đổi giữa các calls, provider cache lại và giảm cost đáng kể.

---

## VẤN ĐỀ 2: GỘP 8 AGENTS THÀNH TỐI ĐA 3 BƯỚC

### Kiến trúc hiện tại (8 agents, ~46 calls/câu)

```
IngestionAgent → PlannerAgent → QuestionWriterAgent → DistractorAgent 
→ VerifierAgent → CriticAgent → RefinerAgent → FormatterAgent
```

### Kiến trúc mới đề xuất (3 bước, ≤ 3 calls/câu)

```
Step 1: ContextPrep   (1 call, optional — có thể batch cho toàn bộ PDF)
Step 2: QuestionGen   (1 call — sinh toàn bộ câu hỏi + options + solution)
Step 3: MathVerify    (0 LLM calls — pure Python/SymPy rule validation)
Step 4: LLMJudge      (1 call — chỉ khi rule validation không đủ, optional)
```

**Tổng: 2-3 calls/câu thay vì 46.**

### Chi tiết từng bước

#### Step 1: ContextPrep — Chạy 1 lần cho toàn PDF

IngestionAgent + clean context nên được chạy **batch 1 lần** khi upload PDF, không phải mỗi câu. Output là một mapping `chunk_id → structured_context`. Bước này không cần LLM nếu source là PDF text-based — dùng rule-based extraction + regex cho formulas.

Nếu cần LLM thì batch: 1 call để extract structured context cho tất cả chunks cùng lúc, không gọi riêng từng chunk.

#### Step 2: QuestionGen — 1 LLM call, sinh hoàn chỉnh

Đây là bước duy nhất thực sự cần LLM sáng tạo. Prompt yêu cầu model sinh **tất cả** fields trong một lần:

```json
{
  "stem": "...",
  "options": [
    {"key": "A", "text": "...", "is_correct": false, "error_type": "...", "error_rationale": "..."},
    {"key": "B", "text": "...", "is_correct": true, "error_type": null, "error_rationale": null},
    {"key": "C", "text": "...", "is_correct": false, "error_type": "...", "error_rationale": "..."},
    {"key": "D", "text": "...", "is_correct": false, "error_type": "...", "error_rationale": "..."}
  ],
  "answer_key": "B",
  "solution_steps": [
    {"step": 1, "title": "Đọc đề", "content": "...", "formula_used": "..."},
    {"step": 2, "title": "Áp dụng công thức", "content": "...", "formula_used": "..."},
    {"step": 3, "title": "Tính toán", "content": "...", "formula_used": "..."},
    {"step": 4, "title": "Kết luận", "content": "..."}
  ],
  "verifier_payload": {"type": "numeric_eval", "expression": "...", "expected": 1400},
  "bloom_level": "Thông hiểu",
  "difficulty_score": 0.5,
  "topic": "...",
  "hint": "..."
}
```

**Không có DistractorAgent riêng. Không có FormatterAgent riêng.** Generator sinh luôn distractor + formatting trong cùng call.

#### Step 3: MathVerify — 0 LLM calls

Chạy thuần Python:

```python
def verify_question(q: dict) -> VerifyResult:
    # Rule 1: Schema validation
    validate_schema(q)
    
    # Rule 2: Exactly one correct answer
    correct = [o for o in q["options"] if o["is_correct"]]
    assert len(correct) == 1
    
    # Rule 3: Answer key matches correct option
    assert q["answer_key"] == correct[0]["key"]
    
    # Rule 4: Numeric verification (if payload exists)
    if q.get("verifier_payload", {}).get("type") == "numeric_eval":
        result = eval_safe(q["verifier_payload"]["expression"])
        assert abs(result - q["verifier_payload"]["expected"]) < 1e-6
    
    # Rule 5: SymPy symbolic check (if applicable)
    if q.get("verifier_payload", {}).get("type") == "sympy.diff":
        verify_sympy(q["verifier_payload"])
    
    # Rule 6: Solution has ≥ 3 steps for non-conceptual questions
    if q["bloom_level"] not in ["Nhận biết"]:
        assert len(q["solution_steps"]) >= 3
    
    return VerifyResult(passed=True)
```

**Không LLM, không latency, không token cost.**

#### Step 4: LLMJudge — Chỉ khi cần (optional)

Với câu hỏi computational đã pass SymPy/numeric verify, **bỏ qua LLM judge**. Judge chỉ chạy cho câu conceptual mà rule không đủ đánh giá.

Prompt judge phải ngắn, súc tích, không fast-path:

```
Đánh giá câu MCQ sau theo 3 tiêu chí, mỗi tiêu chí cho điểm 0-1:
1. clarity: câu hỏi rõ ràng, không mơ hồ
2. distractor_quality: 3 phương án sai có plausible misconception
3. bloom_alignment: mức độ nhận thức phù hợp với "{bloom_level}"

Trả về JSON: {"clarity": 0.x, "distractor_quality": 0.x, "bloom_alignment": 0.x, "issues": [...]}
```

---

## VẤN ĐỀ 3: FIX INGESTION — ĐỪNG CHUNK MCQ QUESTIONS

### Vấn đề hiện tại

PDF source chứa sẵn MCQ questions. IngestionAgent đang chunk các câu hỏi này thành context, và QuestionWriterAgent đang paraphrase lại chúng. Kết quả: câu hỏi "mới" thực ra là câu hỏi cũ được viết lại. Đây là anti-pattern nghiêm trọng.

### Giải pháp

**IngestionAgent phải phân loại chunks thành 2 loại:**

```python
CHUNK_TYPES = {
    "theory": "Đoạn lý thuyết, định nghĩa, định lý, công thức — DÙNG ĐỂ SINH CÂU HỎI",
    "example": "Ví dụ minh họa, bài toán mẫu — DÙNG LÀM TEMPLATE, KHÔNG COPY",
    "exercise": "Câu hỏi/bài tập/MCQ có sẵn — CHỈ DÙNG LÀM DISTRACTOR REFERENCE, KHÔNG PARAPHRASE"
}
```

Khi QuestionWriterAgent nhận slot, nó nhận context được filter:
- Nếu slot cần câu **conceptual** (Nhận biết/Thông hiểu): dùng `theory` chunks
- Nếu slot cần câu **application** (Vận dụng): dùng `theory` + `example` chunks
- `exercise` chunks chỉ được dùng để tham khảo misconceptions, không copy

**Thêm instruction cứng vào QuestionGen prompt:**
> "NGHIÊM CẤM: Không paraphrase hoặc viết lại bất kỳ câu hỏi/bài tập nào đã có trong context. Câu hỏi phải tạo tình huống/số liệu mới hoàn toàn, chỉ kiến thức là lấy từ context."

---

## VẤN ĐỀ 4: FIX PLANNER — ĐƠN GIẢN HÓA, KHÔNG OVERENGINEER

### Vấn đề hiện tại

PlannerAgent sinh plan cực kỳ phức tạp: mỗi slot có `inferred_misconceptions` với 5 items, `distractor_spec` chi tiết, `question_spec` nested, `context_quality` matrix, v.v. Tất cả những thứ này được gửi lại vào QuestionWriterAgent như context — phình context, tốn token.

Ngoài ra, nhiều misconception trong plan **rất generic và yếu**:
```
"wrong_form": "Nguyên hàm là phép tính đơn giản"
"rationale": "Nguyên hàm là phép tính đơn giản"
```
Rationale và wrong_form hoàn toàn giống nhau — đây là LLM hallucinate, không có thông tin thực sự.

### Giải pháp

**Xóa PlannerAgent.**

Thay bằng một **blueprint generator** thuần rule-based + 1 LLM call duy nhất cho toàn bộ plan:

```python
def generate_blueprint(chunks: list, config: Config) -> Blueprint:
    # Rule-based distribution (không cần LLM)
    distribution = compute_bloom_distribution(config.num_questions, config.difficulty)
    slots = []
    for i, (chunk, level) in enumerate(zip(selected_chunks, distribution)):
        slot = Slot(
            id=f"q_{i+1:03d}",
            chunk_id=chunk.id,
            bloom_level=level,
            difficulty_target=bloom_to_difficulty(level),
            # Chỉ 2-3 fields thực sự cần thiết
        )
        slots.append(slot)
    return Blueprint(slots=slots)
```

Nếu muốn misconception-aware planning, gọi **1 LLM call duy nhất** để sinh misconceptions cho tất cả slots cùng lúc, không gọi riêng từng slot.

---

## VẤN ĐỀ 5: FIX DETAILED SOLUTION — BẮT BUỘC MULTI-STEP

### Vấn đề hiện tại

Q1 và Q4 có `detailed_solution` chỉ 1 step, nội dung chỉ là kết luận. Đây là lời giải vô dụng — học sinh không học được gì.

### Giải pháp

**Thêm validation cứng trong prompt và verifier:**

```
RULES CHO SOLUTION:
- Câu Nhận biết: ≥ 2 steps (nêu định nghĩa + đối chiếu với đáp án)
- Câu Thông hiểu: ≥ 3 steps (setup → tính toán → kết luận)  
- Câu Vận dụng: ≥ 4 steps (đọc đề → chọn phương pháp → tính toán → kiểm tra)
- Câu Vận dụng cao: ≥ 5 steps (phân tích → thiết lập → tính → kiểm → tổng quát)
- KHÔNG cho phép step title "Kết luận" xuất hiện ở step đầu tiên
- Mỗi step PHẢI có ít nhất 1 công thức hoặc phép tính cụ thể (nếu không phải conceptual)
```

Trong verifier:
```python
def check_solution_quality(q):
    min_steps = {"Nhận biết": 2, "Thông hiểu": 3, "Vận dụng": 4, "Vận dụng cao": 5}
    required = min_steps[q["bloom_level"]]
    actual = len(q["solution_steps"])
    if actual < required:
        raise ValidationError(f"Solution cần ≥ {required} steps, chỉ có {actual}")
```

---

## VẤN ĐỀ 6: RETRY STRATEGY — THÔNG MINH, KHÔNG BRUTE FORCE

### Vấn đề hiện tại

Khi câu bị reject, hệ thống retry toàn bộ pipeline. Q3 và Q7 cần 3 attempts, nghĩa là chúng tốn gấp 3 lần token bình thường.

### Giải pháp: Targeted repair, không full retry

```python
def repair_question(q: dict, errors: list[ValidationError]) -> dict:
    # Phân loại lỗi
    schema_errors = [e for e in errors if e.type == "schema"]
    math_errors = [e for e in errors if e.type == "math"]
    quality_errors = [e for e in errors if e.type == "quality"]
    
    if schema_errors:
        # Fix nhỏ bằng rule, không cần LLM
        q = apply_schema_fix(q, schema_errors)
        return q
    
    if math_errors:
        # Chỉ regenerate solution + verifier_payload
        prompt = f"Câu hỏi này có lỗi tính toán: {math_errors}. Sửa lại solution_steps và verifier_payload. KHÔNG thay đổi stem hoặc options."
        # 1 targeted LLM call
        
    if quality_errors:
        # Chỉ regenerate phần bị lỗi
        if "distractor" in quality_errors[0].field:
            prompt = "Sửa lại 3 options sai..."  # targeted
```

**Không bao giờ gọi full pipeline lại chỉ vì 1 field sai.**

---

## VẤN ĐỀ 7: BATCHING — SINH NHIỀU CÂU TRONG 1 CALL

### Giải pháp hiện tại: 1 call = 1 câu

Với câu Nhận biết và Thông hiểu (câu đơn giản, không cần computation phức tạp), hoàn toàn có thể sinh **3-5 câu trong 1 LLM call**:

```python
BATCH_PROMPT = """
Sinh {n} câu MCQ Toán từ context sau.
Trả về JSON array gồm {n} câu, mỗi câu theo schema:
[câu 1, câu 2, ..., câu {n}]

Context: {context}
Bloom levels cần: {levels}
"""
```

**Tiết kiệm**: 5 câu nhận biết từ cùng 1 chunk → 1 LLM call thay vì 5 calls.

---

## VẤN ĐỀ 8: KIẾN TRÚC TRIỂN KHAI ĐỀ XUẤT

### Codebase mới

```
aqg/
├── pipeline.py          # Orchestrator chính, không agent class
├── prompts/
│   ├── question_gen.py  # System prompt cho generator (inline, không file)
│   ├── judge.py         # System prompt cho judge (chỉ khi cần)
│   └── repair.py        # System prompt cho targeted repair
├── validators/
│   ├── schema.py        # JSON schema validation
│   ├── math_verify.py   # SymPy + numeric eval
│   └── quality.py       # Rule-based quality checks
├── ingestion/
│   ├── chunker.py       # PDF → chunks
│   ├── classifier.py    # Phân loại theory/example/exercise
│   └── context.py       # Build context cho generator
└── blueprint.py         # Rule-based blueprint generation
```

### Flow chính (không agent framework)

```python
async def generate_questions(pdf_path: str, config: Config) -> list[Question]:
    # Step 1: Ingest (1 time, batch)
    chunks = await chunk_pdf(pdf_path)
    classified = classify_chunks(chunks)  # rule-based, no LLM
    
    # Step 2: Blueprint (rule-based, no LLM)
    blueprint = generate_blueprint(classified, config)
    
    # Step 3: Generate (batch by bloom level)
    results = []
    for batch in group_by_difficulty(blueprint.slots):
        # 1 LLM call cho 1-5 câu cùng loại
        raw_qs = await llm_generate_batch(batch, classified)
        
        for q in raw_qs:
            # Step 4: Validate (no LLM)
            errors = validate(q)
            
            if not errors:
                results.append(q)
            else:
                # Step 5: Targeted repair (1 LLM call nếu cần)
                fixed = await targeted_repair(q, errors)
                if fixed:
                    results.append(fixed)
    
    return results
```

---

## BẢNG SO SÁNH: TRƯỚC VÀ SAU

| Tiêu chí | Hiện tại | Mục tiêu |
|----------|----------|---------|
| Calls/câu | ~46 | ≤ 3 |
| Tokens/câu | ~144,000 | ≤ 5,000 |
| Thời gian/câu | ? (chậm) | < 10 giây |
| Agents | 8 | 0 (pure functions) |
| Skills files | Có, dynamic load | Không, inline prompt |
| Retry strategy | Full pipeline | Targeted field repair |
| Source dedup | Không | Có (anti-paraphrase guard) |
| Solution depth | 1-4 steps (inconsistent) | 2-5 steps (enforced) |
| Batch support | Không | Có (3-5 câu/call) |

---

## CHECKLIST THỰC HIỆN

### Ưu tiên cao (làm ngay):
- [ ] Xóa skills file loading, chuyển toàn bộ instruction vào inline system prompt
- [ ] Gộp QuestionWriterAgent + DistractorAgent + FormatterAgent thành 1 `QuestionGeneratorFn`
- [ ] Thêm chunk classifier (theory/example/exercise) vào ingestion
- [ ] Thêm anti-paraphrase guard trong generation prompt
- [ ] Enforce minimum solution steps trong validator

### Ưu tiên trung bình:
- [ ] Implement targeted repair thay vì full retry
- [ ] Thêm batching cho câu cùng bloom level
- [ ] Simplify PlannerAgent thành rule-based blueprint
- [ ] Xóa CriticAgent "fast-path" — hoặc judge thật sự hoặc bỏ hẳn

### Ưu tiên thấp (sau khi có baseline mới):
- [ ] Thêm Fast Mode (không cần plan review)
- [ ] Smart Practice feature
- [ ] Cancel generation button
- [ ] Reject reason display in UI

---

## GHI CHÚ CUỐI

**Về câu hỏi "Có nên chuyển về thuần prompt không?"**: CÓ, và làm ngay. Agent framework hiện tại đang thêm complexity không có giá trị tương xứng. Với AQG Toán, pipeline cần: (1) đọc context, (2) sinh câu theo spec, (3) validate toán học. Ba việc này không cần 8 class agent với skills framework. Một file `pipeline.py` với 3 async functions là đủ — rõ hơn, nhanh hơn, debug dễ hơn.

**Về chất lượng câu hỏi hiện tại**: Câu hỏi đúng toán học, distractor hợp lý — đây là nền tốt. Vấn đề không phải chất lượng mà là **chi phí để đạt được chất lượng đó**. Refactor kiến trúc không phá vỡ chất lượng; nó chỉ loại bỏ overhead vô nghĩa.

**Con số mục tiêu thực tế**: Với 1 LLM call tốt (claude-3-5-haiku hoặc gemini-flash), 1 câu MCQ Toán có thể sinh trong ~2,000-3,000 tokens input + ~800-1,200 tokens output = ~4,000 tokens/câu. So với 144,000 tokens/câu hiện tại, đây là **giảm 36 lần**.

# Pipeline sinh MCQ Toán — Trạng thái hiện tại

> Cập nhật: 2026-05-21

## Tổng quan kiến trúc

```
Upload PDF → IngestionAgent (pymupdf4llm markdown) → chunks.json
    → PlannerAgent (build_rich_plan) → plan.json (draft)
    → User review/edit plan → confirm
    → OrchestratorAgent (background) → result.json
    → Human review → export
```

### 8 Agents

| # | Agent | Vai trò |
|---|-------|---------|
| 1 | IngestionAgent | PDF → markdown → chunks (pymupdf4llm) |
| 2 | PlannerAgent | Sinh rich plan: distribution, slots, misconceptions, warnings |
| 3 | QuestionWriterAgent | Stage 1: stem + answer + reasoning (KHÔNG distractor) |
| 4 | DistractorAgent | Stage 2: 3 distractor gắn misconception cụ thể |
| 5 | VerifierAgent | SymPy/NetworkX verify + distractor validator |
| 6 | CriticAgent | Grounding judge + Multi-trait quality (RMTS) |
| 7 | RefinerAgent | Tinh chỉnh câu yếu (critique loop) |
| 8 | FormatterAgent | Chuẩn hóa output, shuffle options |

### Models đang dùng

```
GENERATOR_MODEL = openai/gpt-4o-mini    (sinh câu hỏi + distractor)
JUDGE_MODEL     = qwen/qwen3.6-flash    (grounding + quality scoring)
```

### LLM provider

Set provider in `API/.env`:

```bash
# Option 1: OpenRouter
AQG_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_GENERATOR_MODEL=openai/gpt-4o-mini
OPENROUTER_JUDGE_MODEL=openai/gpt-4o-mini

# Option 2: OpenAI official
AQG_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_GENERATOR_MODEL=gpt-4o-mini
OPENAI_JUDGE_MODEL=gpt-4o-mini

# Option 3: 9Router / Codex CLI local proxy
AQG_LLM_PROVIDER=9router
OPENAI_API_KEY=sk-...
NINEROUTER_BASE_URL=http://127.0.0.1:20128/v1
NINEROUTER_GENERATOR_MODEL=cx/gpt-5.4
NINEROUTER_JUDGE_MODEL=cx/gpt-5.4
```
python run.py --pdf pdftest/toan-thuc-te-nguyen-ham-va-tich-phan-toan-12.pdf -n 20 --mode fast --no-nli --output output/questions_math.json
`AQG_GENERATOR_MODEL`, `AQG_JUDGE_MODEL`, and `AQG_EMBEDDING_MODEL` override
the provider-specific model names when needed.

## Web UI (Next.js + FastAPI)

### Chạy

```bash
# Backend
cd API
python -m uvicorn web.app:app --host 127.0.0.1 --port 8080

# Frontend
cd web_new
npm run dev   # → http://localhost:3000
```

### Flow UI

```
Upload PDF → Review Chunks → Sinh câu hỏi (config + plan + generate) → Xem câu hỏi
```

- **Upload**: Drop zone, không chọn số câu (chọn ở bước sau)
- **Chunks**: Hiện extraction mode (markdown/plain text), single-doc vs chunked, warning tài liệu dài (80k/120k chars)
- **Sinh câu hỏi** (merged config + generate):
  - Bước 1: Chọn Bloom level, số câu, dạng câu hỏi, lời giải
  - Bước 2: Tạo Plan → hiện distribution (topic/difficulty/type), misconceptions, warnings
  - Bước 3: Edit plan inline (sửa số câu mỗi topic/mức độ) hoặc confirm
  - Bước 4: Pipeline chạy background, hiện progress + agent pipeline animation
- **Xem câu hỏi**: Table view, filter Bloom, approve/reject, export JSON
- **Sidebar**: 3 bước với checkmark xanh khi hoàn thành

### API Endpoints chính

```
POST /upload                    — upload PDF, chạy ingestion sync
GET  /job/{id}/chunks           — trả chunks + metadata
POST /job/{id}/plan/generate    — tạo plan draft
GET  /job/{id}/plan             — lấy plan (ẩn slots mặc định)
PUT  /job/{id}/plan             — edit plan
POST /job/{id}/plan/revise      — structured edit distribution
POST /job/{id}/plan/confirm     — confirm plan
POST /job/{id}/generate         — start generation (cần plan confirmed)
GET  /job/{id}/status           — poll progress
GET  /job/{id}/questions        — lấy kết quả
```

## Plan workflow

- `build_rich_plan()` sinh plan có: distribution (by_topic, by_difficulty, by_type), top_misconceptions, warnings, slots chi tiết
- API trả summary mặc định (ẩn slots), `?include_slots=true` cho debug
- User edit distribution → backend `_apply_summary_distribution()` rebalance slots nội bộ
- Confirm → unlock generation
- Generation gate: `/generate` trả 409 nếu plan chưa confirmed hoặc đang generating

## Cấu trúc thư mục

```
API/
├── pipeline/
│   ├── agents/
│   │   ├── orchestrator.py      # điều phối 8 agents
│   │   ├── planner_agent.py     # rich plan + distribution
│   │   ├── writer_agent.py      # Stage 1 writer
│   │   ├── distractor_agent.py  # Stage 2 distractor
│   │   ├── verifier_agent.py    # symbolic verify
│   │   ├── critic_agent.py      # grounding + multi-trait quality
│   │   ├── refiner_agent.py     # critique loop
│   │   ├── formatter_agent.py   # output formatting
│   │   └── messages.py          # typed inter-agent messages
│   ├── config.py                # models, thresholds, prompts
│   ├── pdf_parser.py            # pymupdf4llm → markdown → chunks
│   ├── blueprint.py             # slot assignment
│   ├── writer.py                # LLM call + parse writer output
│   ├── distractor.py            # LLM call + parse distractors
│   ├── verifier.py              # SymPy/NetworkX engines
│   ├── grounding.py             # grounding + quality + NLI judge
│   ├── filter.py                # distractor validator + dedup
│   └── schema.py                # output schema
├── web/
│   ├── app.py                   # FastAPI endpoints
│   ├── jobs.py                  # background generation runner
│   └── store.py                 # filesystem-based job store
├── web_new/                     # Next.js frontend
│   └── src/
│       ├── app/(dashboard)/     # pages
│       ├── components/          # UI components
│       └── lib/api.ts           # API client + types
└── runs/{job_id}/               # per-job state
    ├── meta.json, status.json, config.json
    ├── source.pdf, chunks.json, plan.json, result.json
    └── errors.log (nếu có)
```

## Thresholds hiện tại (config.py)

```python
QUALITY_THRESHOLD = 0.45          # (hạ từ 0.6 để test)
GROUNDING_THRESHOLD = 0.4         # (hạ từ 0.55 để test)
NUM_SAMPLES_PER_SLOT = 3
NUM_REPAIR_ATTEMPTS = 2
GENERATION_CONTEXT_MAX_CHARS = 1500
```

## VẤN ĐỀ HIỆN TẠI (cần fix)

### 1. Tỉ lệ reject quá cao (CRITICAL)

**Triệu chứng**: 538 rejected / 4 accepted cho 10 câu. Pipeline loop 55+ rounds/slot.

**Nguyên nhân gốc (chưa xác nhận hết)**:
- **Judge model yếu hơn generator**: `qwen/qwen3.6-flash` chấm `gpt-4o-mini` → có thể cho điểm grounding thấp oan vì không hiểu context toán đủ tốt
- **Grounding prompt quá strict**: yêu cầu "MỌI sự kiện có trong ngữ cảnh" — với toán, LLM dùng kiến thức cơ bản (đạo hàm, tích phân) không cần verbatim trong context → bị đánh thấp
- **Source quote matching quá strict**: `find_supported_quote()` yêu cầu quote gần exact match trong context. Nếu LLM paraphrase nhẹ → fail → grounding bị cap 0.4
- **`_run_until_target_accepted` loop vô hạn**: đã thêm cap `target * 8` nhưng vẫn quá nhiều nếu mỗi round đều fail

**Hướng fix cần thử**:
1. Đổi JUDGE_MODEL sang `gpt-4o-mini` (cùng tier với generator) hoặc model mạnh hơn
2. Nới lỏng grounding prompt: cho phép kiến thức toán cơ bản không cần có trong context
3. Fuzzy quote matching (hiện dùng SequenceMatcher, có thể threshold quá cao)
4. Giảm số lần gọi judge: fast-accept nhiều hơn cho câu có verifier=True
5. Log reject reasons vào status.json để debug trên UI

### 2. Retry loop không có cap hợp lý

**Đã fix một phần**: thêm `max_total_attempts = target * 8` trong `_run_until_target_accepted`.

**Cần thêm**: nút Cancel trên UI, persist partial results khi dừng giữa chừng.

### 3. Agent repair loop routing

**Đã implement**:
- Lỗi distractor (option_text_sanity, multi_answer, answer_uniqueness, distractor_plausibility) → route về DistractorAgent với feedback
- Lỗi stem/grounding (grounding, quote, verifier=False, bloom_alignment, clarity) → route về QuestionWriterAgent

**Vấn đề**: nếu gốc lỗi là context quá ngắn, retry bao nhiêu lần cũng không giúp.

### 4. UI chưa có nút Cancel generation

User không thể dừng generation đang chạy. Cần thêm flag trong store mà progress callback check.

### 5. Không có log reject reason trên UI

Frontend chỉ thấy số rejected, không biết TẠI SAO. Cần expose reject reasons trong status hoặc endpoint riêng.

## Đã implement gần đây

### Plan review workflow
- `PlannerAgent.build_rich_plan()` sinh rich plan
- API: generate/get/put/revise/confirm plan
- Frontend: plan review với edit inline (sửa distribution trực tiếp)
- Generation gate: chỉ chạy khi plan confirmed

### Frontend improvements
- Merged Configure + Generate thành 1 trang
- Upload page: bỏ chọn số câu, single-column focused
- Chunks page: hiện extraction mode, single-doc vs chunked, warning tài liệu dài
- Sidebar: 3 bước với step completion indicators
- Plan edit: inline edit distribution (topic/difficulty/type counts)

### Backend improvements
- Generation lock: 409 nếu job đang generating
- `extraction_mode` trong metadata (markdown vs plain_text)
- `_apply_summary_distribution()`: edit distribution → rebalance slots
- Retry rejected slots (1 extra pass sau vòng chính)

## Prompts quan trọng

### Writer System Prompt
```
Bạn là chuyên gia ra đề Toán. Nhiệm vụ: viết đề bài, đáp án đúng và giải thích.
KHÔNG sinh distractor ở bước này — distractor sẽ được sinh riêng.
```

### Writer User Prompt
```
Viết một câu hỏi Toán dạng trắc nghiệm theo yêu cầu (CHỈ stem + đáp án + giải thích).
Chủ đề ngữ cảnh: {topic}
Kỹ năng cần kiểm: {skill}
Mức nhận thức: {cognitive_level} (mục tiêu khó {difficulty_target})
Pattern gợi ý: {pattern}
Ngữ cảnh: {context}
```

### Grounding Judge Prompt
```
Đối chiếu câu hỏi và lời giải với ngữ cảnh được cung cấp.
Cho điểm 0..1 đo mức độ MỌI sự kiện, công thức, định lý dùng trong câu hỏi
và lời giải đều có trong ngữ cảnh.
```

### Quality Judge (Multi-trait RMTS)
5 tiêu chí: clarity, cognitive_depth, bloom_alignment, distractor_plausibility, answer_uniqueness.
Rationale trước, score sau (RMTS pattern).

## Ghi chú cho phiên sau

1. **Ưu tiên #1**: Fix tỉ lệ reject. Thử đổi JUDGE_MODEL trước, nếu vẫn tệ thì xem lại grounding prompt.
2. **Ưu tiên #2**: Thêm nút Cancel + log reject reasons lên UI.
3. **Ưu tiên #3**: Test với tài liệu lớn hơn (nhiều topic) xem distribution có hợp lý không.
4. Trang `/job/{id}/configure` vẫn tồn tại nhưng sidebar không link tới nữa (đã merge vào generate).
5. `test_plan_smoke.py` ở root — chạy được bằng `python -X utf8 test_plan_smoke.py`.
6. Backend cần restart thủ công sau mỗi code change (không dùng --reload).

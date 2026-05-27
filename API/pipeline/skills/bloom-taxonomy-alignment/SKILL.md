---
name: bloom-taxonomy-alignment
description: Align MCQ planning, writing, critique, and refinement with the requested Bloom cognitive level using Vietnamese labels. Use in PlannerAgent, QuestionWriterAgent, CriticAgent, and RefinerAgent whenever cognitive level matters.
---

# Bloom Taxonomy Alignment

Use the requested cognitive level as a behavioral constraint, not a decorative label.

## Level Guide
- `Nhận biết`: hỏi nhận diện hoặc nhắc lại định nghĩa, công thức, ký hiệu, điều kiện áp dụng, hoặc tên khái niệm. Tránh bài thay số nhiều bước.
- `Thông hiểu`: hỏi giải thích ý nghĩa, chọn công thức hoặc điều kiện đúng, so sánh tính chất, hoặc nhận diện vì sao một cách làm hợp lệ.
- `Vận dụng`: cho dữ kiện cụ thể và yêu cầu áp dụng công thức, quy tắc, hoặc quy trình quen thuộc để tính, biến đổi, hoặc suy ra kết quả.
- `Vận dụng cao`: yêu cầu phối hợp ít nhất hai ý, so sánh trường hợp, chọn chiến lược, xử lý bẫy misconception, hoặc tích hợp nhiều khái niệm.

## Workflow
1. During planning, assign a level only if the source context can support it.
2. During writing, make the stem require the requested cognitive operation.
3. During critique, compare the actual task with the requested level, not the wording alone.
4. During refinement, adjust the task structure before merely changing phrasing.

## Guardrails
- Do not label a direct formula substitution as `Vận dụng cao`.
- Do not force high Bloom from thin source context.
- Keep difficulty and Bloom related but separate: a long calculation is not automatically high Bloom.
- If the requested level is `Nhận biết` or `Thông hiểu`, the correct answer should usually be a concept, condition, formula, or explanation, not only `Đúng` or `Sai`.

## Output
Return Bloom-aligned slot design, generated item behavior, or `bloom_alignment` scoring annotations.

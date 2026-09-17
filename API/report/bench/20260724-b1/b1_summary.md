# B1 — System benchmark (pipeline thật, không mô phỏng)

*Sinh lúc: 2026-07-24T05:54:39*

## Tổng hợp

| Metric | Giá trị |
|---|---|
| Số PDF | 4 |
| Yêu cầu / chấp nhận | 40 / 37 |
| Ứng viên bị loại | 28 |
| Acceptance rate (trên mọi ứng viên) | 0.5692 |
| Verified=True / False(kept) / None | 34 / 1 / 2 |
| Answer-key repaired | 0 |
| Hint lỗi (fallback) | 0 |
| Needs revision (routed to human) | 3 |
| Tokens / calls | 611558 / 187 |
| Tổng thời gian | 1494.8s (40.4s / câu chấp nhận) |

## Phân bố reject theo gate

| Gate:reason | Số ca |
|---|---|
| writer | 17 |
| distractor | 6 |
| verifier:rule_validator | 3 |
| verifier:answer_text_mismatch | 1 |
| dedup | 1 |

## Từng PDF

### file_1_trang_1-31.pdf

- accepted 10/10 (candidates 16, rate 0.625)
- verification: {'verified_true': 8, 'verified_false_kept': 1, 'verified_none': 1, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.9233 | grounding_avg 0.926
- bloom: {'Nhận biết': 2, 'Thông hiểu': 1, 'Vận dụng': 5, 'Vận dụng cao': 2}
- cost: 111328 tokens / 37 calls | 351.8s (35.2s/câu)
- reject: {'writer': 5, 'distractor': 1}

### file_2_trang_31-61.pdf

- accepted 10/10 (candidates 18, rate 0.5556)
- verification: {'verified_true': 9, 'verified_false_kept': 0, 'verified_none': 1, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.9072 | grounding_avg 0.932
- bloom: {'Thông hiểu': 3, 'Vận dụng': 3, 'Vận dụng cao': 3, 'Nhận biết': 1}
- cost: 171658 tokens / 44 calls | 400.7s (40.1s/câu)
- reject: {'writer': 3, 'verifier:answer_text_mismatch': 1, 'dedup': 1, 'verifier:rule_validator': 3}

### file_3_trang_61-90.pdf

- accepted 7/10 (candidates 15, rate 0.4667)
- verification: {'verified_true': 7, 'verified_false_kept': 0, 'verified_none': 0, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.8693 | grounding_avg 0.8786
- bloom: {'Nhận biết': 1, 'Thông hiểu': 2, 'Vận dụng': 3, 'Vận dụng cao': 1}
- cost: 141094 tokens / 69 calls | 407.1s (58.2s/câu)
- reject: {'writer': 4, 'distractor': 4}

### file_4_trang_91-het.pdf

- accepted 10/10 (candidates 16, rate 0.625)
- verification: {'verified_true': 10, 'verified_false_kept': 0, 'verified_none': 0, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.8768 | grounding_avg 0.854
- bloom: {'Thông hiểu': 2, 'Vận dụng': 5, 'Vận dụng cao': 2, 'Nhận biết': 1}
- cost: 187478 tokens / 37 calls | 335.2s (33.5s/câu)
- reject: {'writer': 5, 'distractor': 1}

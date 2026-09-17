# B1 — System benchmark (pipeline thật, không mô phỏng)

*Sinh lúc: 2026-07-24T10:43:43*

## Tổng hợp

| Metric | Giá trị |
|---|---|
| Số PDF | 4 |
| Yêu cầu / chấp nhận | 40 / 40 |
| Ứng viên bị loại | 12 |
| Acceptance rate (trên mọi ứng viên) | 0.7692 |
| Verified=True / False(kept) / None | 33 / 2 / 5 |
| Answer-key repaired | 0 |
| Hint lỗi (fallback) | 0 |
| Needs revision (routed to human) | 3 |
| Tokens / calls | 639807 / 150 |
| Tổng thời gian | 1293.5s (32.3s / câu chấp nhận) |

## Phân bố reject theo gate

| Gate:reason | Số ca |
|---|---|
| critic:error_distractor_consistency | 4 |
| writer | 3 |
| critic:answer_uniqueness | 3 |
| dedup | 2 |

## Từng PDF

### file_1_trang_1-31.pdf

- accepted 10/10 (candidates 14, rate 0.7143)
- verification: {'verified_true': 6, 'verified_false_kept': 1, 'verified_none': 3, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.8573 | grounding_avg 0.907
- bloom: {'Nhận biết': 3, 'Thông hiểu': 2, 'Vận dụng': 3, 'Vận dụng cao': 2}
- cost: 120610 tokens / 40 calls | 290.9s (29.1s/câu)
- reject: {'critic:error_distractor_consistency': 2, 'writer': 1, 'dedup': 1}

### file_2_trang_31-61.pdf

- accepted 10/10 (candidates 14, rate 0.7143)
- verification: {'verified_true': 10, 'verified_false_kept': 0, 'verified_none': 0, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.9317 | grounding_avg 0.898
- bloom: {'Nhận biết': 3, 'Thông hiểu': 2, 'Vận dụng': 4, 'Vận dụng cao': 1}
- cost: 159633 tokens / 40 calls | 345.3s (34.5s/câu)
- reject: {'critic:answer_uniqueness': 2, 'writer': 1, 'dedup': 1}

### file_3_trang_61-90.pdf

- accepted 10/10 (candidates 11, rate 0.9091)
- verification: {'verified_true': 8, 'verified_false_kept': 1, 'verified_none': 1, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.9077 | grounding_avg 0.932
- bloom: {'Nhận biết': 2, 'Thông hiểu': 2, 'Vận dụng': 3, 'Vận dụng cao': 3}
- cost: 171657 tokens / 33 calls | 309.9s (31.0s/câu)
- reject: {'critic:answer_uniqueness': 1}

### file_4_trang_91-het.pdf

- accepted 10/10 (candidates 13, rate 0.7692)
- verification: {'verified_true': 9, 'verified_false_kept': 0, 'verified_none': 1, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.905 | grounding_avg 0.948
- bloom: {'Nhận biết': 3, 'Thông hiểu': 2, 'Vận dụng': 3, 'Vận dụng cao': 2}
- cost: 187907 tokens / 37 calls | 347.4s (34.7s/câu)
- reject: {'critic:error_distractor_consistency': 2, 'writer': 1}

# B1 — System benchmark (pipeline thật, không mô phỏng)

*Sinh lúc: 2026-07-23T23:59:27*

## Tổng hợp

| Metric | Giá trị |
|---|---|
| Số PDF | 4 |
| Yêu cầu / chấp nhận | 40 / 34 |
| Ứng viên bị loại | 23 |
| Acceptance rate (trên mọi ứng viên) | 0.5965 |
| Verified=True / False(kept) / None | 22 / 7 / 5 |
| Answer-key repaired | 1 |
| Hint lỗi (fallback) | 0 |
| Needs revision (routed to human) | 7 |
| Tokens / calls | 663269 / 149 |
| Tổng thời gian | 1454.3s (42.8s / câu chấp nhận) |

## Phân bố reject theo gate

| Gate:reason | Số ca |
|---|---|
| writer | 7 |
| verifier:answer_text_mismatch | 5 |
| critic:error_distractor_consistency | 4 |
| critic:answer_uniqueness | 3 |
| verifier:rule_validator | 2 |
| orchestrator | 1 |
| dedup | 1 |

## Từng PDF

### file_1_trang_1-31.pdf

- accepted 4/10 (candidates 9, rate 0.4444)
- verification: {'verified_true': 3, 'verified_false_kept': 0, 'verified_none': 1, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.8875 | grounding_avg 0.9575
- bloom: {'Nhận biết': 1, 'Thông hiểu': 2, 'Vận dụng': 1}
- cost: 62914 tokens / 22 calls | 201.1s (50.3s/câu)
- reject: {'verifier:rule_validator': 1, 'verifier:answer_text_mismatch': 2, 'writer': 1, 'critic:error_distractor_consistency': 1}

### file_2_trang_31-61.pdf

- accepted 10/10 (candidates 17, rate 0.5882)
- verification: {'verified_true': 8, 'verified_false_kept': 1, 'verified_none': 1, 'answer_key_repaired': 1, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.8943 | grounding_avg 0.924
- bloom: {'Thông hiểu': 2, 'Vận dụng': 4, 'Vận dụng cao': 2, 'Nhận biết': 2}
- cost: 177688 tokens / 45 calls | 406.0s (40.6s/câu)
- reject: {'verifier:rule_validator': 1, 'critic:error_distractor_consistency': 1, 'critic:answer_uniqueness': 1, 'verifier:answer_text_mismatch': 2, 'orchestrator': 1, 'writer': 1}

### file_3_trang_61-90.pdf

- accepted 10/10 (candidates 16, rate 0.625)
- verification: {'verified_true': 8, 'verified_false_kept': 0, 'verified_none': 2, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.9323 | grounding_avg 0.945
- bloom: {'Nhận biết': 3, 'Thông hiểu': 2, 'Vận dụng': 4, 'Vận dụng cao': 1}
- cost: 230075 tokens / 44 calls | 407.0s (40.7s/câu)
- reject: {'critic:error_distractor_consistency': 1, 'dedup': 1, 'critic:answer_uniqueness': 2, 'writer': 2}

### file_4_trang_91-het.pdf

- accepted 10/10 (candidates 15, rate 0.6667)
- verification: {'verified_true': 3, 'verified_false_kept': 6, 'verified_none': 1, 'answer_key_repaired': 0, 'verifier_hint_errored': 0, 'source_quote_repaired': 0}
- quality_avg 0.8312 | grounding_avg 0.906
- bloom: {'Thông hiểu': 2, 'Vận dụng': 5, 'Vận dụng cao': 1, 'Nhận biết': 2}
- cost: 192592 tokens / 38 calls | 440.2s (44.0s/câu)
- reject: {'writer': 3, 'critic:error_distractor_consistency': 1, 'verifier:answer_text_mismatch': 1}

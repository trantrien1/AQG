# Tầng 2+3 — chấm bằng mô hình và độ tin cậy

Mô hình chấm: `gpt-4o`, **3 lượt** mỗi câu, 89 câu.

## 7 chiều của QGEval (thang 1–3)

| chiều | điểm trung bình | alpha giữa các lượt |
|---|---|---|
| Trôi chảy (`fluency`) | 2.985 | 0.7471 |
| Rõ ràng (`clarity`) | 2.925 | 0.8965 |
| Súc tích (`conciseness`) | 2.891 | 0.2677 |
| Bám nguồn (`relevance`) | 2.794 | 0.659 |
| Nhất quán với nguồn (`consistency`) | 2.614 | 0.3849 |
| Trả lời được (`answerability`) | 2.341 | 0.4955 |
| Khớp đáp án đã cho (`answer_consistency`) | 2.82 | 0.6351 |

> Alpha ở đây đo độ ổn định giữa các LƯỢT CHẤM của cùng một mô hình, không phải giữa những người chú thích độc lập. Nó là cận **trên** của độ tin cậy: cùng một mô hình, cùng một prompt thì dễ lặp lại chính mình hơn hai người khác nhau.

## Luật và mô hình có đồng ý với nhau không

Trên 14 lỗi mà cả hai cùng xét. Chỗ nào lệch thì ít nhất một bên sai.

| lỗi | n | luật gắn | mô hình gắn | trùng nhau | kappa |
|---|---|---|---|---|---|
| `lost_sequence` | 89 | 37 | 67 | 55% | 0.1717 |
| `unfocused_stem` | 89 | 4 | 3 | 94% | 0.2571 |
| `none_of_the_above` | 89 | 0 | 0 | 100% | — |
| `all_of_the_above` | 89 | 0 | 0 | 100% | — |
| `longest_option_correct` | 89 | 0 | 0 | 100% | — |
| `true_false_question` | 89 | 0 | 0 | 100% | — |
| `complex_k_type` | 89 | 0 | 0 | 100% | — |
| `convergence_cues` | 89 | 0 | 0 | 100% | — |
| `fill_in_blank` | 89 | 0 | 0 | 100% | — |
| `absolute_terms` | 89 | 0 | 0 | 100% | — |
| `vague_terms` | 89 | 0 | 0 | 100% | — |
| `word_repeats` | 89 | 0 | 0 | 100% | — |
| `negative_worded` | 89 | 0 | 0 | 100% | — |
| `more_than_one_correct` | 89 | 0 | 0 | 100% | — |

## Chấp nhận được, tính trên đủ 19 lỗi

**77/89 = 86.5%** (≤1 lỗi).

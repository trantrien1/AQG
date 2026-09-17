# Benchmark suite

Sinh lúc 2026-07-26T07:06:56.230951+00:00. 12 ô có dữ liệu (1 arm × 3 seed × 4 tài liệu).

Ô nào chưa chạy thì KHÔNG có dòng nào trong bảng — bảng này chỉ chứa kết quả thật.

## Theo arm

| Arm | Ô | Câu giao ra | Tỉ lệ nhận | Độc lập xác nhận | Chỉ nhất quán | Chuyển người | Token/câu | Giây/câu |
|---|---|---|---|---|---|---|---|---|
| `full_system` | 12 | 89 | 0.4811 | 70 | 4 | 7 | 26670.9 | 55.2 |

## Correctness (chỉ khi có nhãn ngoài)

- `full_system`: 71/75 key đúng (0.9467), verifier FP 0.0, FN 0.0282

## Biến thiên giữa các seed

- `full_system`:
  - seed 42: 30 câu / 65 ứng viên, 4 ô
  - seed 43: 30 câu / 48 ứng viên, 4 ô
  - seed 44: 29 câu / 72 ứng viên, 4 ô

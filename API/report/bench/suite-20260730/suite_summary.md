# Benchmark suite

Sinh lúc 2026-07-30T18:52:52.346149+00:00. 18 ô có dữ liệu (1 arm × 3 seed × 6 tài liệu).

Ô nào chưa chạy thì KHÔNG có dòng nào trong bảng — bảng này chỉ chứa kết quả thật.

## Theo arm

| Arm | Ô | Câu giao ra | Tỉ lệ nhận | Độc lập xác nhận | Chỉ nhất quán | Chuyển người | Token/câu | Giây/câu |
|---|---|---|---|---|---|---|---|---|
| `full_system` | 18 | 187 | 0.6013 | 108 | 56 | 12 | 19571.5 | 49.2 |

## Correctness (chỉ khi có nhãn ngoài)

Chưa có nhãn ground-truth nào. Không có correctness rate để báo cáo — trạng thái kiểm chứng của pipeline KHÔNG thay thế được nhãn ngoài.

## Biến thiên giữa các seed

- `full_system`:
  - seed 42: 60 câu / 109 ứng viên, 6 ô
  - seed 43: 65 câu / 105 ứng viên, 6 ô
  - seed 44: 62 câu / 97 ứng viên, 6 ô

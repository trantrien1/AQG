"""Fine-tune LoRA cho bài toán sinh câu trắc nghiệm Nguyên hàm – Tích phân.

- ``data``: đọc dataset, chia tập train/val/test theo nhóm câu gần trùng.
- ``prompts``: định dạng hội thoại cho hai tác vụ (soạn câu hỏi, giải câu hỏi).
- ``metrics``: đọc đầu ra của mô hình và tính chỉ số.
- ``train``, ``infer``, ``judge``, ``report``: các bước chạy bằng dòng lệnh.
"""

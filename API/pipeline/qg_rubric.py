"""7 chiều đánh giá câu hỏi của QGEval, kèm mô tả neo cho từng mức điểm.

    Fu, Wei, Hu, Cai, Liu (2024). "QGEval: Benchmarking Multi-dimensional
    Evaluation for Question Generation." EMNLP 2024. arXiv:2406.05707.

Mô tả các mức 1/2/3 dịch từ Bảng 7 (Annotation instructions) của bài báo —
KHÔNG tự đặt, vì thang điểm không neo thì mỗi lượt chấm hiểu một kiểu và con số
trung bình mất nghĩa.

Hai khác biệt so với bố trí gốc, phải nói rõ khi báo cáo:

1. QGEval cho người chú thích đọc TOÀN BỘ đoạn văn nguồn. Ở đây thứ duy nhất
   được lưu lại cùng mỗi câu là một câu trích dẫn nguồn, nên các chiều
   Relevance/Consistency/Answerability được chấm trên một ngữ cảnh HẸP HƠN hẳn.
2. QGEval lấy TRUNG BÌNH điểm của ba người chú thích (nên ví dụ trong bài có
   điểm lẻ như 1,3333). Ở đây ba "người" là ba lượt chấm của cùng một mô hình —
   chúng không độc lập với nhau như ba người thật, nên độ đồng thuận giữa các
   lượt là cận TRÊN của độ tin cậy, không phải ước lượng đúng.
"""
from __future__ import annotations

from typing import Dict, Tuple

#: Thang điểm của QGEval: 1..3, cao hơn là tốt hơn.
SCORE_MIN, SCORE_MAX = 1, 3

LINGUISTIC_DIMENSIONS: Tuple[str, ...] = ('fluency', 'clarity', 'conciseness')
TASK_DIMENSIONS: Tuple[str, ...] = (
    'relevance', 'consistency', 'answerability', 'answer_consistency')
DIMENSIONS: Tuple[str, ...] = LINGUISTIC_DIMENSIONS + TASK_DIMENSIONS

DIMENSION_LABELS_VI: Dict[str, str] = {
    'fluency':            'Trôi chảy',
    'clarity':            'Rõ ràng',
    'conciseness':        'Súc tích',
    'relevance':          'Bám nguồn',
    'consistency':        'Nhất quán với nguồn',
    'answerability':      'Trả lời được',
    'answer_consistency': 'Khớp đáp án đã cho',
}

#: Bảng 7 của QGEval, dịch sát.
ANCHORS: Dict[str, Dict[int, str]] = {
    'fluency': {
        1: 'Câu hỏi lủng củng, dùng từ thiếu chính xác hoặc sai ngữ pháp nặng, '
           'khó hiểu được ý.',
        2: 'Câu hỏi hơi lủng củng hoặc có lỗi ngữ pháp nhỏ, nhưng không cản trở '
           'việc hiểu ý.',
        3: 'Câu hỏi trôi chảy và đúng ngữ pháp.',
    },
    'clarity': {
        1: 'Câu hỏi quá rộng hoặc diễn đạt rối, khó hiểu hoặc gây mơ hồ. Đặc '
           'biệt, nếu câu sinh ra KHÔNG PHẢI câu hỏi mà là câu trần thuật thì '
           'xếp vào mức này.',
        2: 'Câu hỏi diễn đạt chưa thật rõ và cụ thể, nhưng vẫn suy ra được ý '
           'dựa vào ngữ cảnh nguồn.',
        3: 'Câu hỏi rõ ràng, cụ thể, không mơ hồ.',
    },
    'conciseness': {
        1: 'Câu hỏi chứa quá nhiều thông tin thừa, khiến khó nhận ra ý định hỏi.',
        2: 'Câu hỏi có một ít thông tin thừa nhưng không ảnh hưởng việc hiểu ý.',
        3: 'Câu hỏi súc tích, không có thông tin không cần thiết.',
    },
    'relevance': {
        1: 'Câu hỏi hoàn toàn không liên quan tới ngữ cảnh nguồn.',
        2: 'Câu hỏi có liên quan phần nào tới nguồn nhưng hỏi thông tin không '
           'cốt yếu.',
        3: 'Câu hỏi bám ngữ cảnh và hỏi đúng thông tin cốt yếu của nguồn.',
    },
    'consistency': {
        1: 'Câu hỏi mâu thuẫn về dữ kiện với nguồn, hoặc sai logic.',
        2: 'Thông tin mà câu hỏi nhắc tới không được mô tả đầy đủ trong nguồn.',
        3: 'Thông tin trong câu hỏi hoàn toàn nhất quán với nguồn.',
    },
    'answerability': {
        1: 'Không thể trả lời câu hỏi dựa trên ngữ cảnh nguồn.',
        2: 'Chỉ trả lời được một phần dựa trên nguồn, hoặc phải suy đoán thêm.',
        3: 'Trả lời được dứt khoát dựa trên ngữ cảnh nguồn.',
    },
    'answer_consistency': {
        1: 'Đáp án đã cho không trả lời được câu hỏi.',
        2: 'Đáp án đã cho chỉ trả lời được một phần câu hỏi.',
        3: 'Đáp án đã cho trả lời trực tiếp được câu hỏi.',
    },
}


def anchor_block() -> str:
    """Khối mô tả thang điểm để nhúng vào prompt chấm."""
    parts = []
    for dim in DIMENSIONS:
        parts.append(f'{dim} ({DIMENSION_LABELS_VI[dim]}):')
        for score in (1, 2, 3):
            parts.append(f'  {score} = {ANCHORS[dim][score]}')
    return '\n'.join(parts)

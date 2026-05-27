"""Misconception bank — Toán chung (mục 13).

Pool TẤT CẢ misconception thành một danh sách phẳng, KHÔNG nhóm theo môn.
Generator nhận một mẫu ngẫu nhiên (hoặc theo từ khóa của topic) để gợi ý LLM
sinh distractor có ý nghĩa giáo dục.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional


# Mỗi misconception: id ổn định, wrong_form, rationale, keywords (để match topic).
MISCONCEPTIONS: List[Dict[str, object]] = [
    # ===== Phương trình / bất phương trình / khai triển =====
    {'id': 'sign_flip_inequality',
     'keywords': ['bất phương trình', 'inequality', 'số âm'],
     'wrong_form': 'Quên đổi chiều bất phương trình khi nhân/chia với số âm',
     'rationale': 'Khi nhân hai vế của bất phương trình với một số âm phải đảo dấu bất phương trình.'},
    {'id': 'square_of_sum',
     'keywords': ['đẳng thức', 'khai triển', 'a+b', 'bình phương', 'nhân tử'],
     'wrong_form': '(a+b)^2 = a^2 + b^2',
     'rationale': 'Quên số hạng chéo 2ab. Đúng: (a+b)^2 = a^2 + 2ab + b^2.'},
    {'id': 'missing_negative_root',
     'keywords': ['nghiệm', 'phương trình', 'bậc hai', 'căn'],
     'wrong_form': 'x^2 = k => x = sqrt(k) (chỉ một nghiệm dương)',
     'rationale': 'Phải xét cả ± sqrt(k); bỏ nghiệm âm là sai.'},
    {'id': 'wrong_domain',
     'keywords': ['điều kiện', 'xác định', 'mẫu', 'căn'],
     'wrong_form': 'Bỏ qua điều kiện xác định của biểu thức',
     'rationale': 'Phải kiểm tra điều kiện xác định trước khi giải.'},
    {'id': 'viete_sign_swap',
     'keywords': ['Viète', 'tổng nghiệm', 'tích nghiệm', 'phương trình bậc hai'],
     'wrong_form': 'x_1 + x_2 = b/a thay vì −b/a',
     'rationale': 'Đúng: x_1 + x_2 = −b/a, x_1·x_2 = c/a.'},

    # ===== Đạo hàm =====
    {'id': 'missing_chain_rule_factor',
     'keywords': ['đạo hàm', 'dây chuyền', 'hàm hợp', 'sin', 'cos', 'exp', 'ln'],
     'wrong_form': "(sin(g(x)))' = cos(g(x))  (quên nhân g'(x))",
     'rationale': 'Quy tắc dây chuyền: phải nhân với đạo hàm hàm trong.'},
    {'id': 'wrong_inner_function',
     'keywords': ['đạo hàm', 'dây chuyền', 'hàm hợp'],
     'wrong_form': 'Lấy nhầm hàm trong khi áp dụng dây chuyền',
     'rationale': 'Phải xác định đúng cấu trúc f(g(x)).'},
    {'id': 'wrong_trig_derivative_sign',
     'keywords': ['đạo hàm', 'sin', 'cos'],
     'wrong_form': "(sin x)' = -cos x hoặc (cos x)' = sin x",
     'rationale': "Đúng: (sin x)' = cos x, (cos x)' = -sin x."},
    {'id': 'derivative_ln_wrong',
     'keywords': ['đạo hàm', 'log', 'ln'],
     'wrong_form': "(ln x)' = 1",
     'rationale': "(ln x)' = 1/x."},
    {'id': 'product_rule_drop_term',
     'keywords': ['đạo hàm', 'tích'],
     'wrong_form': "(uv)' = u'v' (sai)",
     'rationale': "Đúng: (uv)' = u'v + uv'."},

    # ===== Tích phân =====
    {'id': 'missing_constant_C',
     'keywords': ['tích phân', 'nguyên hàm', 'không xác định'],
     'wrong_form': 'Tích phân không xác định không kèm hằng số C',
     'rationale': 'Mọi nguyên hàm phải kèm hằng số tự do C.'},
    {'id': 'integration_by_parts_wrong_choice',
     'keywords': ['tích phân từng phần', 'LIATE'],
     'wrong_form': 'Chọn u, dv ngược (theo LIATE) khiến tích phân khó hơn',
     'rationale': 'Quy tắc LIATE giúp chọn u đúng để v du đơn giản hơn.'},
    {'id': 'forget_change_bounds',
     'keywords': ['tích phân', 'đổi biến', 'cận'],
     'wrong_form': 'Đổi biến nhưng giữ nguyên cận tích phân theo biến cũ',
     'rationale': 'Khi đổi biến trong tích phân xác định phải đổi cả cận.'},

    # ===== Giới hạn =====
    {'id': 'lhospital_misapplied',
     'keywords': ['giới hạn', 'L\'Hospital', 'lhospital'],
     'wrong_form': "Áp dụng L'Hospital cho dạng không phải 0/0 hoặc ∞/∞",
     'rationale': 'L\'Hospital chỉ dùng cho dạng vô định 0/0 hoặc ∞/∞.'},
    {'id': 'limit_at_infty_wrong',
     'keywords': ['giới hạn', 'vô cùng', 'infty'],
     'wrong_form': 'Coi 1/0 = ∞ là dạng vô định',
     'rationale': '1/0 cho ra ∞ chứ không phải dạng vô định.'},

    # ===== Đẳng thức lượng giác =====
    {'id': 'wrong_cos_addition_sign',
     'keywords': ['cos', 'công thức cộng', 'sin'],
     'wrong_form': 'cos(a+b) = cos a cos b + sin a sin b (sai dấu)',
     'rationale': 'Đúng: cos(a+b) = cos a cos b − sin a sin b.'},
    {'id': 'mix_radian_degree',
     'keywords': ['radian', 'độ', 'lượng giác'],
     'wrong_form': 'Lẫn radian/độ khi tính giá trị lượng giác',
     'rationale': 'Phải nhất quán đơn vị; π rad = 180°.'},
    {'id': 'wrong_pythagorean_identity',
     'keywords': ['lượng giác', 'tan', 'cot', 'sec', 'csc'],
     'wrong_form': '1 + tan^2 x = csc^2 x',
     'rationale': 'Đúng: 1 + tan^2 x = sec^2 x; 1 + cot^2 x = csc^2 x.'},

    # ===== Hình & khoảng cách =====
    {'id': 'pythagoras_misapplied',
     'keywords': ['Pythagoras', 'tam giác', 'vuông'],
     'wrong_form': 'Áp dụng Pythagoras cho tam giác không vuông',
     'rationale': 'Pythagoras chỉ đúng cho tam giác vuông; tam giác bất kỳ dùng định lý cosin.'},
    {'id': 'confuse_perimeter_area',
     'keywords': ['chu vi', 'diện tích'],
     'wrong_form': 'Nhầm chu vi với diện tích',
     'rationale': 'Chu vi là tổng cạnh; diện tích là số đo phần mặt phẳng.'},
    {'id': 'distance_missing_abs',
     'keywords': ['khoảng cách', 'điểm', 'đường thẳng', 'mặt phẳng'],
     'wrong_form': 'Tính khoảng cách điểm-đường thẳng không lấy giá trị tuyệt đối',
     'rationale': 'd = |ax0+by0+c| / sqrt(a^2+b^2); thiếu |·| sẽ ra số âm.'},
    {'id': 'normal_vs_direction_vector',
     'keywords': ['vector', 'pháp tuyến', 'chỉ phương'],
     'wrong_form': 'Nhầm vector pháp tuyến với vector chỉ phương',
     'rationale': 'Hai vector này vuông góc nhau trong mặt phẳng.'},

    # ===== Ma trận & định thức =====
    {'id': 'det_sum_wrong',
     'keywords': ['định thức', 'det', 'tổng', 'ma trận'],
     'wrong_form': 'det(A+B) = det(A) + det(B)',
     'rationale': 'Định thức KHÔNG tuyến tính theo từng ma trận.'},
    {'id': 'transpose_product_order',
     'keywords': ['chuyển vị', 'transpose', 'ma trận'],
     'wrong_form': '(AB)^T = A^T B^T',
     'rationale': 'Đúng: (AB)^T = B^T A^T (đảo thứ tự).'},
    {'id': 'inverse_product_order',
     'keywords': ['nghịch đảo', 'inverse', 'ma trận'],
     'wrong_form': '(AB)^{-1} = A^{-1} B^{-1}',
     'rationale': 'Đúng: (AB)^{-1} = B^{-1} A^{-1}.'},
    {'id': 'matrix_multiply_not_commutative',
     'keywords': ['ma trận', 'nhân', 'AB'],
     'wrong_form': 'Coi AB = BA',
     'rationale': 'Phép nhân ma trận nói chung không giao hoán.'},

    # ===== Đếm & xác suất =====
    {'id': 'permutation_vs_combination',
     'keywords': ['tổ hợp', 'chỉnh hợp', 'hoán vị'],
     'wrong_form': 'Dùng A(n,k) khi cần dùng C(n,k) hoặc ngược lại',
     'rationale': 'Phân biệt thứ tự có/không quan trọng. C(n,k) = A(n,k)/k!.'},
    {'id': 'add_when_not_disjoint',
     'keywords': ['xác suất', 'biến cố', 'xung khắc', 'hợp'],
     'wrong_form': 'P(A ∪ B) = P(A) + P(B) khi A, B không xung khắc',
     'rationale': 'Phải trừ đi P(A ∩ B).'},
    {'id': 'multiply_when_not_independent',
     'keywords': ['xác suất', 'biến cố', 'độc lập', 'giao'],
     'wrong_form': 'P(A ∩ B) = P(A) P(B) khi A, B không độc lập',
     'rationale': 'Phải dùng P(A ∩ B) = P(A) P(B|A).'},
    {'id': 'pigeonhole_floor_vs_ceil',
     'keywords': ['Dirichlet', 'chuồng bồ câu', 'pigeonhole'],
     'wrong_form': 'Dùng ⌊N/k⌋ thay vì ⌈N/k⌉',
     'rationale': 'Tồn tại hộp chứa ít nhất ⌈N/k⌉ vật.'},

    # ===== Modular & ước/bội =====
    {'id': 'gcd_vs_lcm',
     'keywords': ['gcd', 'lcm', 'ước', 'bội'],
     'wrong_form': 'Nhầm gcd với lcm',
     'rationale': 'gcd ước chung lớn nhất; lcm bội chung nhỏ nhất; lcm = a·b/gcd.'},
    {'id': 'mod_negative_wrong',
     'keywords': ['mod', 'modulo', 'âm'],
     'wrong_form': '-7 mod 3 = -1',
     'rationale': 'Trong toán học, kết quả mod luôn ≥ 0; -7 mod 3 = 2.'},
    {'id': 'fermat_when_p_divides_a',
     'keywords': ['Fermat', 'nguyên tố', 'mod'],
     'wrong_form': 'Áp Fermat nhỏ a^(p-1) ≡ 1 (mod p) khi p | a',
     'rationale': 'Định lý đòi hỏi gcd(a, p) = 1. Khi p | a thì a^(p-1) ≡ 0 (mod p).'},

    # ===== Logic =====
    {'id': 'negation_of_implication_wrong',
     'keywords': ['phủ định', 'kéo theo', 'implication', 'mệnh đề'],
     'wrong_form': '¬(P → Q) ≡ ¬P → ¬Q',
     'rationale': 'Đúng: ¬(P → Q) ≡ P ∧ ¬Q.'},
    {'id': 'implication_converse',
     'keywords': ['kéo theo', 'đảo', 'mệnh đề'],
     'wrong_form': 'P → Q ≡ Q → P',
     'rationale': 'Q → P là mệnh đề đảo, không tương đương P → Q.'},
    {'id': 'demorgan_wrong',
     'keywords': ['De Morgan', 'phủ định', 'và', 'hoặc'],
     'wrong_form': '¬(P ∧ Q) ≡ ¬P ∧ ¬Q',
     'rationale': 'Đúng: ¬(P ∧ Q) ≡ ¬P ∨ ¬Q (đảo phép toán).'},
    {'id': 'set_demorgan_wrong',
     'keywords': ['tập hợp', 'phần bù', 'De Morgan'],
     'wrong_form': '(A ∪ B)^c = A^c ∪ B^c',
     'rationale': 'Đúng: (A ∪ B)^c = A^c ∩ B^c.'},

    # ===== Hằng đúng / hằng sai (tautology / contradiction) =====
    {'id': 'tautology_wrong',
     'keywords': ['hằng đúng', 'tautology', 'mệnh đề'],
     'wrong_form': 'Coi P ∧ Q là hằng đúng',
     'rationale': 'P ∧ Q chỉ đúng khi P, Q đều đúng — không phải hằng đúng.'},
    {'id': 'contradiction_wrong',
     'keywords': ['hằng sai', 'contradiction', 'mệnh đề'],
     'wrong_form': 'Coi P ∨ ¬P là hằng sai',
     'rationale': 'P ∨ ¬P là hằng đúng (luật bài trung). Hằng sai là P ∧ ¬P.'},

    # ===== Biểu diễn xâu bít cho tập hợp =====
    {'id': 'set_bitstring_misalign',
     'keywords': ['xâu bít', 'biểu diễn tập', 'bít'],
     'wrong_form': 'Đảo bit (1 ↔ 0) khi biểu diễn tập con',
     'rationale': 'Bit thứ i = 1 nếu phần tử i ∈ tập con; = 0 nếu không.'},
    {'id': 'set_bitstring_full_zero',
     'keywords': ['xâu bít', 'biểu diễn tập'],
     'wrong_form': 'Dùng chuỗi toàn 0 cho tập khác rỗng',
     'rationale': 'Chuỗi toàn 0 chỉ tương ứng với tập rỗng.'},

    # ===== Đồ thị / cây =====
    {'id': 'degree_sum_no_divide',
     'keywords': ['đồ thị', 'bậc', 'cạnh', 'bắt tay'],
     'wrong_form': 'Số cạnh = Σ deg(v) (không chia 2)',
     'rationale': 'Định lý bắt tay: Σ deg(v) = 2|E|, nên |E| = Σ deg(v)/2.'},
    {'id': 'kn_edges_wrong',
     'keywords': ['đồ thị đầy đủ', 'K_n', 'cạnh'],
     'wrong_form': 'K_n có n^2 cạnh',
     'rationale': 'K_n có n(n-1)/2 cạnh.'},
    {'id': 'euler_for_hamilton',
     'keywords': ['Euler', 'Hamilton', 'chu trình', 'đồ thị'],
     'wrong_form': "Áp điều kiện 'mọi đỉnh bậc chẵn' cho chu trình Hamilton",
     'rationale': 'Đó là điều kiện Euler. Hamilton không có điều kiện cần và đủ đơn giản.'},
    {'id': 'tree_n_edges',
     'keywords': ['cây', 'tree', 'cạnh'],
     'wrong_form': 'Cây n đỉnh có n cạnh',
     'rationale': 'Đúng: cây n đỉnh có n − 1 cạnh.'},

    # ===== Hàm số (đơn điệu, cực trị, tiệm cận, GTLN-GTNN) =====
    {'id': 'derivative_zero_implies_extremum',
     'keywords': ['cực trị', 'cực đại', 'cực tiểu', 'đạo hàm'],
     'wrong_form': "f'(x_0) = 0 ⇒ f đạt cực trị tại x_0",
     'rationale': "f'(x_0) = 0 chỉ là điều kiện cần; còn cần đạo hàm đổi dấu qua x_0 hoặc xét f''(x_0)."},
    {'id': 'monotonic_strict_vs_loose',
     'keywords': ['đồng biến', 'nghịch biến', 'đơn điệu'],
     'wrong_form': "f'(x) ≥ 0 trên (a,b) ⇒ f đồng biến nghiêm ngặt",
     'rationale': "f'(x) ≥ 0 chỉ cho đồng biến (loose); muốn nghiêm ngặt cần f' chỉ bằng 0 tại tập rời rạc."},
    {'id': 'extremum_endpoint_missing',
     'keywords': ['GTLN', 'GTNN', 'lớn nhất', 'nhỏ nhất', 'đoạn'],
     'wrong_form': 'Tìm GTLN/GTNN trên đoạn chỉ xét tại điểm tới hạn (bỏ qua hai đầu mút)',
     'rationale': 'Trên đoạn [a,b] phải so sánh f tại các điểm tới hạn VÀ tại f(a), f(b).'},
    {'id': 'asymptote_confuse',
     'keywords': ['tiệm cận', 'tiệm cận đứng', 'tiệm cận ngang'],
     'wrong_form': 'Nhầm tiệm cận đứng với tiệm cận ngang (hoặc ngược lại)',
     'rationale': 'Tiệm cận đứng x=a khi giới hạn tại x=a là vô cùng; tiệm cận ngang y=b khi giới hạn tại x→±∞ là b.'},

    # ===== Ứng dụng tích phân =====
    {'id': 'area_no_absolute',
     'keywords': ['diện tích', 'tích phân'],
     'wrong_form': 'Diện tích = ∫ f(x) dx (không lấy giá trị tuyệt đối khi f đổi dấu)',
     'rationale': 'Diện tích = ∫|f(x)−g(x)| dx; nếu hàm đổi dấu phải tách miền hoặc dùng |·|.'},
    {'id': 'volume_missing_pi',
     'keywords': ['thể tích', 'tròn xoay'],
     'wrong_form': 'V = ∫ f(x)^2 dx (quên π)',
     'rationale': 'Thể tích khối tròn xoay quanh Ox: V = π ∫ f(x)^2 dx.'},

    # ===== Cấp số / dãy số =====
    {'id': 'arithmetic_general_term_off_by_one',
     'keywords': ['cấp số cộng', 'công sai', 'số hạng'],
     'wrong_form': 'u_n = u_1 + n·d',
     'rationale': 'Đúng: u_n = u_1 + (n−1)·d.'},
    {'id': 'geometric_general_term_off_by_one',
     'keywords': ['cấp số nhân', 'công bội', 'số hạng'],
     'wrong_form': 'u_n = u_1 · q^n',
     'rationale': 'Đúng: u_n = u_1 · q^(n−1).'},
    {'id': 'arithmetic_sum_wrong',
     'keywords': ['cấp số cộng', 'tổng', 'S_n'],
     'wrong_form': 'S_n = n · (u_1 + u_n)',
     'rationale': 'Đúng: S_n = n(u_1 + u_n)/2 — chia 2 theo công thức trung bình cộng.'},
    {'id': 'geometric_sum_wrong',
     'keywords': ['cấp số nhân', 'tổng', 'S_n', 'q'],
     'wrong_form': 'S_n = u_1 (1 − q^n)/(q − 1) (sai dấu)',
     'rationale': 'Đúng: S_n = u_1 (1 − q^n)/(1 − q) khi q ≠ 1.'},

    # ===== Số phức =====
    {'id': 'modulus_squared_wrong',
     'keywords': ['số phức', 'mô-đun', 'môđun', '|z|'],
     'wrong_form': '|z|^2 = z^2',
     'rationale': '|z|^2 = z · z̄ (tích z với liên hợp), không phải z bình phương.'},
    {'id': 'complex_conjugate_product',
     'keywords': ['liên hợp', 'số phức'],
     'wrong_form': 'Coi z + z̄ = 0 hoặc z · z̄ = 0',
     'rationale': 'z + z̄ = 2·Re(z); z · z̄ = |z|^2 ≥ 0.'},

    # ===== Vector & hình học không gian =====
    {'id': 'dot_product_zero_means_parallel',
     'keywords': ['tích vô hướng', 'vector', 'song song', 'vuông góc'],
     'wrong_form': 'Tích vô hướng u·v = 0 ⇒ u song song v',
     'rationale': 'Đúng: u·v = 0 ⇒ u vuông góc v; song song khi tích có hướng = 0.'},
    {'id': 'plane_normal_vs_point',
     'keywords': ['mặt phẳng', 'pháp tuyến', 'phương trình'],
     'wrong_form': 'Lấy tọa độ điểm M làm vector pháp tuyến',
     'rationale': 'Vector pháp tuyến là (a,b,c) lấy từ phương trình ax+by+cz+d=0, không liên quan tọa độ điểm.'},

    # ===== Xác suất nâng cao =====
    {'id': 'conditional_probability_swap',
     'keywords': ['xác suất có điều kiện', 'Bayes', 'P(A|B)'],
     'wrong_form': 'P(A|B) = P(B|A)',
     'rationale': 'Đúng: P(A|B) = P(A∩B)/P(B); để đổi sang P(B|A) phải dùng Bayes.'},
    {'id': 'independence_misjudge',
     'keywords': ['độc lập', 'biến cố'],
     'wrong_form': 'Coi A, B độc lập khi A ∩ B = ∅',
     'rationale': 'A∩B = ∅ là xung khắc (mutually exclusive), KHÔNG phải độc lập; trừ khi P(A) hoặc P(B) bằng 0.'},
]


def _score_match(misconception: Dict[str, object], topic: str) -> int:
    """Đếm số keyword của misconception khớp với topic."""
    if not topic:
        return 0
    topic_lower = topic.lower()
    return sum(1 for kw in misconception.get('keywords', [])
               if kw.lower() in topic_lower)


def get_misconceptions(topic: str = '', k: int = 5,
                       seed: Optional[int] = None) -> List[Dict[str, object]]:
    """Lấy k misconception phù hợp với topic. Nếu topic rỗng / không match,
    trả về k misconception ngẫu nhiên (deterministic theo seed)."""
    rng = random.Random(seed)
    if topic:
        scored = [(m, _score_match(m, topic)) for m in MISCONCEPTIONS]
        matched = [m for m, s in scored if s > 0]
        if len(matched) >= k:
            rng.shuffle(matched)
            return matched[:k]
        # bù bằng items ngẫu nhiên còn lại
        rest = [m for m in MISCONCEPTIONS if m not in matched]
        rng.shuffle(rest)
        return (matched + rest)[:k]
    pool = list(MISCONCEPTIONS)
    rng.shuffle(pool)
    return pool[:k]


def format_for_prompt(items: List[Dict[str, object]]) -> str:
    if not items:
        return '(không có)'
    lines = [f"- [{m['id']}] {m['wrong_form']} — {m['rationale']}" for m in items]
    return '\n'.join(lines)

"""Thống kê độ tin cậy của tầng 3 phải đúng, và phải im lặng khi không đủ dữ liệu.

Một hệ số đồng thuận sai nguy hiểm hơn không có hệ số nào: nó biến "mô hình lặp
lại chính nó" thành "kết quả đáng tin". Nên ở đây kiểm cả ca biên — không đủ dữ
liệu, đồng thuận tuyệt đối, bất đồng hoàn toàn — chứ không chỉ ca thường.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location(
    'qeval_mod', ROOT / 'scripts' / 'qeval.py')
qeval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qeval)


# --------------------------------------------------- Krippendorff's alpha
def test_perfect_agreement_is_one():
    units = [[3, 3, 3], [1, 1, 1], [2, 2, 2]]
    assert qeval.krippendorff_alpha(units, 'interval') == 1.0


def test_no_variance_at_all_is_not_reported_as_a_number():
    """Mọi lượt cho cùng một điểm trên MỌI câu: không có phương sai để chuẩn hoá.

    Đây là ca thật sẽ gặp — mô hình chấm nhiệt độ 0 rất dễ cho toàn điểm 3.
    Trả 1.0 ở đây là đúng (không hề bất đồng), nhưng nếu có bất đồng mà mẫu số
    vẫn bằng 0 thì phải trả None chứ không được chia cho 0.
    """
    assert qeval.krippendorff_alpha([[3, 3], [3, 3]], 'interval') == 1.0


def test_disagreement_lowers_alpha_below_one():
    a = qeval.krippendorff_alpha([[1, 3], [3, 1], [2, 2]], 'interval')
    assert a is not None and a < 1.0


def test_ordered_scale_penalises_far_disagreement_more():
    """Thang 1-3 là có thứ tự: lệch 1↔3 phải nặng hơn lệch 1↔2."""
    near = qeval.krippendorff_alpha([[1, 2], [2, 1], [3, 3]], 'interval')
    far = qeval.krippendorff_alpha([[1, 3], [3, 1], [2, 2]], 'interval')
    assert near > far


def test_nominal_metric_treats_all_disagreement_equally():
    a = qeval.krippendorff_alpha([[True, False], [False, True]], 'nominal')
    assert a is not None and a < 0.5


def test_units_with_a_single_rating_are_dropped():
    """Một lượt chấm thì không nói gì về đồng thuận — không được tính vào."""
    assert qeval.krippendorff_alpha([[3]], 'interval') is None
    assert qeval.krippendorff_alpha([], 'interval') is None


def test_missing_values_do_not_crash_the_estimate():
    a = qeval.krippendorff_alpha([[3, None, 3], [1, 1, None]], 'interval')
    assert a == 1.0


# ------------------------------------------------------------ Cohen kappa
def test_kappa_is_one_on_perfect_agreement_with_variance():
    k = qeval.cohen_kappa([True, False, True, False],
                          [True, False, True, False])
    assert k == 1.0


def test_kappa_is_zero_when_agreement_is_only_chance():
    """Hai bên đều gắn cờ 50% nhưng không liên quan nhau -> kappa ~ 0."""
    a = [True, True, False, False]
    b = [True, False, True, False]
    assert abs(qeval.cohen_kappa(a, b)) < 1e-9


def test_kappa_undefined_when_one_side_never_varies():
    """Cả hai cùng nói 'không lỗi' ở mọi câu: trùng 100% nhưng kappa vô nghĩa.

    Đây là ca sẽ gặp nhiều nhất, vì phần lớn lỗi hiếm. Báo kappa = 1 ở đây là
    tuyên bố sai về mức đồng thuận, nên phải trả None.
    """
    assert qeval.cohen_kappa([False] * 5, [False] * 5) is None


def test_kappa_ignores_missing_pairs():
    assert qeval.cohen_kappa([True, None, False], [True, True, False]) == 1.0


# ------------------------------------------------------ bỏ phiếu theo mode
def test_mode_bool_takes_the_majority():
    assert qeval._mode_bool([True, True, False]) is True
    assert qeval._mode_bool([True, False, False]) is False


def test_mode_bool_returns_none_without_votes():
    assert qeval._mode_bool([]) is None
    assert qeval._mode_bool([None, 'x']) is None


def test_a_tie_is_not_counted_as_a_flaw():
    """Hai lượt chia đôi thì chưa đủ căn cứ gắn lỗi."""
    assert qeval._mode_bool([True, False]) is False


# --------------------------------------------------------- nạp ngữ liệu
def test_corpus_loader_drops_duplicate_question_ids(tmp_path):
    """Cùng một câu nằm trong nhiều file báo cáo thì chỉ được đếm MỘT lần.

    Đếm hai lần thì mọi tỉ lệ chất lượng đều lệch theo cách không thấy được.
    """
    q = {'question_id': 'q1', 'stem': 'S?',
         'options': [{'key': 'A', 'text': '1'}], 'answer_key': 'A'}
    for name in ('a.json', 'b.json'):
        (tmp_path / name).write_text(
            __import__('json').dumps({'questions': [q]}), encoding='utf-8')
    assert len(qeval.load_corpus([str(tmp_path)])) == 1


# --------------------------------------------------- dừng sớm khi hỏng xác thực
def test_auth_failure_is_detected_from_the_message():
    """401/token hết hạn phải nhận ra được: mọi lời gọi sau đều hỏng y hệt."""
    assert qeval._is_auth_failure(Exception(
        "Error code: 401 - {'detail': '{\"error\": {\"code\": \"token_expired\"}}'}"))
    assert qeval._is_auth_failure(RuntimeError('Unauthorized'))
    assert qeval._is_auth_failure(RuntimeError('invalid_api_key'))


def test_ordinary_failures_are_not_treated_as_auth_failures():
    """Lỗi tạm thời phải cho chạy tiếp, không được dừng cả lượt chấm."""
    assert not qeval._is_auth_failure(RuntimeError('Connection reset by peer'))
    assert not qeval._is_auth_failure(ValueError('Expecting value: line 1'))
    assert not qeval._is_auth_failure(RuntimeError('rate limit, try again'))


# ------------------------------------------- cau hinh provider cho giam khao
def test_default_provider_never_touches_the_environment(monkeypatch):
    """Đường mặc định KHÔNG được đụng vào env.

    `.env` của dự án khai `AQG_LLM_PROVIDER` hai lần (khối chat2api rồi khối
    openrouter). python-dotenv lấy dòng CUỐI, bộ nạp của pipeline.config lấy
    dòng ĐẦU. Đã xảy ra thật: gọi load_dotenv ở đây khiến cả lượt chấm âm thầm
    đi qua OpenRouter thay vì chat2api, tiêu tiền thật, và không có dấu hiệu
    nào trong log.
    """
    import os
    before = dict(os.environ)
    qeval.configure_judge_provider('chat2api')
    assert dict(os.environ) == before


def test_gemini_provider_sets_only_what_it_needs(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key-123')
    qeval.configure_judge_provider('gemini')
    import os
    assert os.environ['AQG_LLM_PROVIDER'] == 'openai_compatible'
    assert os.environ['OPENAI_COMPATIBLE_BASE_URL'].startswith(
        'https://generativelanguage.googleapis.com')
    assert os.environ['OPENAI_API_KEY'] == 'test-key-123'


def test_single_key_reader_does_not_load_the_whole_file(monkeypatch):
    """Đọc một biến thì chỉ được trả biến đó, không nạp gì vào môi trường."""
    import os
    monkeypatch.delenv('AQG_LLM_PROVIDER', raising=False)
    qeval._env_value_from_dotenv('GEMINI_API_KEY')
    assert 'AQG_LLM_PROVIDER' not in os.environ

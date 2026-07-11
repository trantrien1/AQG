"""Test ràng buộc ĐỘ NẶNG PHÉP TÍNH trong prompt PdfWriter (feedback: phép tính quá dễ)."""
from __future__ import annotations

from pipeline.direct_pdf.agents.messages import PdfWriteRequest
from pipeline.direct_pdf.agents.pdf_writer_agent import PdfWriterAgent, _computation_rule


def test_computation_rule_base_ban_bo_so_kinh_dien():
    rule = _computation_rule(0.3)
    assert 'ĐỘ NẶNG PHÉP TÍNH' in rule
    assert 'kinh điển dễ nhất' in rule
    # muc de: chua ep tu tim du kien / nhieu tang tinh toan
    assert 'TỰ TÌM' not in rule
    assert 'tầng tính toán' not in rule


def test_computation_rule_medium_them_du_kien_tu_tim():
    rule = _computation_rule(0.5)
    assert 'TỰ TÌM' in rule
    assert 'phương trình phụ' in rule
    assert 'tầng tính toán' not in rule


def test_computation_rule_hard_them_nhieu_tang_tinh_toan():
    rule = _computation_rule(0.7)
    assert 'TỰ TÌM' in rule
    assert 'tầng tính toán' in rule
    assert 'QUÁ DỄ' in rule
    # 0.7 chua kich hoat tang cao nhat
    assert 'THAM SỐ' not in rule


def test_computation_rule_very_hard_ep_kieu_bai_kho():
    rule = _computation_rule(0.85)
    assert 'THAM SỐ' in rule
    assert 'NGƯỢC' in rule
    assert 'KẾT HỢP' in rule
    # ky thuat chung, khong khoa vao 1 dang toan: khong nhac ten dang bai
    # cu the trong tang cao nhat
    tier = rule.split('Mức cao nhất')[1]
    for banned in ('tích phân', 'tròn xoay', 'diện tích hình phẳng', 'đạo hàm'):
        assert banned not in tier


def test_computation_rule_gia_tri_hong_ve_muc_medium():
    assert _computation_rule(None) == _computation_rule(0.5)
    assert _computation_rule('abc') == _computation_rule(0.5)


def test_user_prompt_chua_computation_rule_theo_slot():
    writer = PdfWriterAgent(use_skills=False)
    req = PdfWriteRequest(
        attachment_parts=[{'type': 'image_url', 'image_url': {'url': 'data:'}}],
        slot={'slot_id': 's1', 'cognitive_level': 'Vận dụng',
              'difficulty_target': 0.7},
    )
    prompt = writer._user_prompt(req)
    assert 'ĐỘ NẶNG PHÉP TÍNH' in prompt
    assert 'tầng tính toán' in prompt
    # muc de hon thi khong ep nhieu tang
    req_easy = PdfWriteRequest(
        attachment_parts=req.attachment_parts,
        slot={'slot_id': 's2', 'cognitive_level': 'Nhận biết',
              'difficulty_target': 0.3},
    )
    prompt_easy = writer._user_prompt(req_easy)
    assert 'ĐỘ NẶNG PHÉP TÍNH' in prompt_easy
    assert 'tầng tính toán' not in prompt_easy

from pipeline.chunk_context_builder import clean_context_for_chunk
from pipeline.agents.messages import VerifyRequest
from pipeline.agents.verifier_agent import VerifierAgent
from pipeline.agents.orchestrator import OrchestratorAgent
from pipeline.fast_plan import build_fast_plan
from pipeline.generator import _first_json_object
from pipeline.rule_validator import validate_candidate
from pipeline.verifier import verify
from pipeline.agents.formatter_agent import _align_generated_solution, _rewrite_answer_letter_refs


def test_clean_context_strips_inline_exercise_stems():
    raw = (
        "Summary: Cau 21: Mot quan the vi khuan ban dau gom 500 vi khuan. "
        "Toc do tang truong duoc cho boi P'(t)=k t. Sau 1 ngay co 600 vi khuan. "
        "Hoi sau 9 ngay co bao nhieu vi khuan? "
        "Loi giai: Ap dung cong thuc nguyen ham de tinh P(t). "
        "Cau 22: Mot dan con trung co K'(t)=t+2. Hoi sau 10 ngay co bao nhieu con?"
    )

    clean = clean_context_for_chunk(
        "chunk_1",
        {"topic": "Nguyen ham ung dung", "context": raw},
        use_llm=False,
    )

    assert clean["chunk_type"] == "exercise"
    assert clean["existing_question_spans"]
    assert "Cau 21" not in clean["clean_text"]
    assert "Hoi sau 9 ngay" not in clean["clean_text"]
    assert all("Cau 21" not in span for span in clean["source_spans"])


def test_rule_validator_rejects_source_exercise_paraphrase_and_quote():
    source_span = (
        "Cau 21: Mot quan the vi khuan ban dau gom 500 vi khuan. "
        "Sau 1 ngay co 600 vi khuan. Hoi sau 9 ngay co bao nhieu vi khuan?"
    )
    slot = {
        "cognitive_level": "Van dung",
        "question_pattern": "application",
        "existing_question_spans": [source_span],
    }
    candidate = {
        "question_text": (
            "Mot quan the vi khuan ban dau co 500 vi khuan. Sau 1 ngay co "
            "600 vi khuan. Hoi sau 9 ngay quan the co bao nhieu vi khuan?"
        ),
        "answer_text": "1400",
        "answer_explanation_text": "Dung nguyen ham cua toc do tang truong.",
        "source_quote_text": source_span,
        "distractors": [
            {"distractor_text": "900"},
            {"distractor_text": "1000"},
            {"distractor_text": "1800"},
        ],
        "verifier_hint": {"type": "none", "payload": {}},
        "detailed_solution": {
            "steps": [
                {"title": "Du kien", "content": "P(0)=500, P(1)=600."},
                {"title": "Lap ham", "content": "Tich phan toc do tang truong."},
                {"title": "Tinh", "content": "Tinh P(9)."},
                {"title": "Ket luan", "content": "Chon dap an 1400."},
            ]
        },
    }

    issues = validate_candidate(candidate, slot)

    assert any("duplicate_question" in issue for issue in issues)
    assert any("source_quote" in issue for issue in issues)


def test_rule_validator_rejects_metadata_source_quote():
    candidate = {
        "question_text": "Mệnh đề nào đúng về tích phân xác định?",
        "answer_text": "Tính tuyến tính",
        "answer_explanation_text": "Đây là tính chất cơ bản của tích phân.",
        "source_quote_text": "Topic: 2. TÍNH CHẤT CỦA TÍCH PHÂN",
        "distractors": [
            {"distractor_text": "Tính nhân"},
            {"distractor_text": "Tính chia"},
            {"distractor_text": "Tính căn"},
        ],
        "verifier_hint": {"type": "none", "payload": {}},
        "detailed_solution": {
            "steps": [
                {"title": "Bước 1", "content": "Đọc khái niệm."},
                {"title": "Kết luận", "content": "Chọn đáp án đúng."},
            ]
        },
    }

    issues = validate_candidate(candidate, {"cognitive_level": "Nhận biết"})

    assert "quote_mismatch:source_quote_is_metadata" in issues


def test_rule_validator_rejects_irrelevant_source_quote():
    candidate = {
        "question_text": "Menh de nao dung ve tinh tuyen tinh cua tich phan xac dinh?",
        "answer_text": "Tich phan cua tong bang tong cac tich phan.",
        "answer_explanation_text": (
            "Tinh tuyen tinh cho phep tach tich phan cua tong thanh tong "
            "cac tich phan tren cung khoang."
        ),
        "source_quote_text": "Vay the tich ngoi nha la 64 met khoi.",
        "distractors": [
            {"distractor_text": "Tich phan cua tong bang tich cac tich phan."},
            {"distractor_text": "Tich phan luon bang do dai khoang lay tich phan."},
            {"distractor_text": "Doi dau ham duoi dau tich phan khong doi gia tri."},
        ],
        "verifier_hint": {"type": "none", "payload": {}},
        "detailed_solution": {
            "steps": [
                {"title": "Buoc 1", "content": "Nhan dien tinh chat can hoi."},
                {"title": "Ket luan", "content": "Chon menh de ve tinh tuyen tinh."},
            ]
        },
    }

    issues = validate_candidate(candidate, {"cognitive_level": "Nhan biet"})

    assert "quote_mismatch:source_quote_not_relevant" in issues


def test_rule_validator_rejects_generic_area_quote_for_integral_question():
    candidate = {
        "question_text": (
            "Neu ham so f lien tuc va khong am tren doan [a,b], "
            "tich phan cua f co y nghia hinh hoc nao?"
        ),
        "answer_text": "Dien tich hinh phang gioi han boi do thi va truc hoanh.",
        "answer_explanation_text": (
            "Tich phan xac dinh cua ham khong am bieu dien dien tich hinh phang."
        ),
        "source_quote_text": "Dien tich quat tron LCFP la 1,29.40 met vuong.",
        "distractors": [
            {"distractor_text": "Chu vi hinh phang gioi han boi do thi."},
            {"distractor_text": "The tich vat the tron xoay quanh truc hoanh."},
            {"distractor_text": "Do dai doan thang noi hai dau mut do thi."},
        ],
        "verifier_hint": {"type": "none", "payload": {}},
        "detailed_solution": {
            "steps": [
                {"title": "Buoc 1", "content": "Nhan dien y nghia cua tich phan."},
                {"title": "Ket luan", "content": "Chon dien tich hinh phang."},
            ]
        },
    }

    issues = validate_candidate(candidate, {"cognitive_level": "Nhan biet"})

    assert "quote_mismatch:source_quote_not_relevant" in issues


def test_fast_plan_skips_stale_private_use_ocr_context():
    noisy = "\uf028\uf029\uf03d\uf0de " * 20 + "Dien tich quat tron LCFP la"
    dataset = {
        "metadata": {},
        "bad": {
            "context": noisy,
            "clean_context": {
                "chunk_type": "theory",
                "clean_text": noisy,
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 1.0},
            },
        },
        "good": {
            "context": "Hinh phang gioi han boi do thi hai ham so duoc tinh boi cong thuc.",
            "clean_context": {
                "chunk_type": "theory",
                "clean_text": "Hinh phang gioi han boi do thi hai ham so duoc tinh boi cong thuc.",
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 0.5},
            },
        },
    }

    slots = build_fast_plan(dataset, 1, seed=1)

    assert slots[0]["doc_id"] == "good"


def test_fast_plan_skips_weak_label_only_context():
    dataset = {
        "metadata": {},
        "weak": {
            "context": "nhan dien dinh nghia/cong thuc",
            "clean_context": {
                "chunk_type": "exercise",
                "clean_text": "",
                "questionable_skills": ["nhan dien dinh nghia/cong thuc"],
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 0.9},
            },
        },
        "good": {
            "context": "Van toc v(t) lien tuc va quang duong duoc tinh bang tich phan cua van toc.",
            "clean_context": {
                "chunk_type": "exercise",
                "clean_text": "Van toc v(t) lien tuc va quang duong duoc tinh bang tich phan cua van toc.",
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 0.4},
            },
        },
    }

    slots = build_fast_plan(dataset, 1, seed=1)

    assert slots[0]["doc_id"] == "good"

def test_fast_plan_dedupes_repeated_clean_contexts_before_repeating_slots():
    repeated = "Hinh phang gioi han boi do thi hai ham so duoc tinh boi cong thuc."
    dataset = {
        "metadata": {},
        "a": {
            "context": repeated,
            "clean_context": {
                "chunk_type": "theory",
                "clean_text": repeated,
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 0.9},
            },
        },
        "b": {
            "context": repeated,
            "clean_context": {
                "chunk_type": "theory",
                "clean_text": repeated,
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 0.8},
            },
        },
        "c": {
            "context": "Ap dung cong thuc nguyen ham de tinh quang duong trong chuyen dong.",
            "clean_context": {
                "chunk_type": "exercise",
                "clean_text": "Ap dung cong thuc nguyen ham de tinh quang duong trong chuyen dong.",
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 0.4},
            },
        },
    }

    slots = build_fast_plan(dataset, 2, seed=1)

    assert [slot["doc_id"] for slot in slots] == ["a", "c"]


def test_fast_plan_promotes_computation_slots_to_van_dung_bloom():
    dataset = {
        "metadata": {},
        "calc": {
            "context": "Vi du: tinh gia tri tich phan \\int_0^2 (2x+1) dx = 6.",
            "clean_context": {
                "chunk_type": "exercise",
                "clean_text": "Vi du: tinh gia tri tich phan \\int_0^2 (2x+1) dx = 6.",
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 0.7},
            },
        },
    }

    slots = build_fast_plan(dataset, 1, seed=1, difficulty_distribution=[{
        "cognitive_level": "Thong hieu",
        "difficulty_target": 0.5,
        "fraction": 1.0,
    }])

    assert slots[0]["question_pattern"] == "computation"
    assert slots[0]["cognitive_level"] == "Vận dụng"
    assert slots[0]["difficulty_target"] >= 0.65

def test_fast_plan_replaces_noisy_topic_fragments():
    dataset = {
        "metadata": {},
        "noisy": {
            "topic": "2 2 (m/s).",
            "context": "4cos 2 2(m/s).",
            "clean_context": {
                "chunk_type": "exercise",
                "topic": "2 2 (m/s).",
                "title": "2 2 (m/s).",
                "clean_text": "4cos 2 2(m/s).",
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 0.7},
            },
        },
    }

    slots = build_fast_plan(dataset, 1, seed=1)

    assert slots[0]["topic"] == "Toán"

def test_fast_plan_skips_university_parametric_area_context():
    advanced = "Elip duoc tham so hoa x=a cos t, y=b sin t. Dien tich S=1/2 int(x y' - y x') dt."
    dataset = {
        "metadata": {},
        "advanced": {
            "context": advanced,
            "clean_context": {
                "chunk_type": "theory",
                "clean_text": advanced,
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 1.0},
            },
        },
        "good": {
            "context": "Tich phan xac dinh dung de tinh dien tich hinh phang trong chuong trinh THPT.",
            "clean_context": {
                "chunk_type": "theory",
                "clean_text": "Tich phan xac dinh dung de tinh dien tich hinh phang trong chuong trinh THPT.",
                "quality": {"is_usable": True, "noise_level": "low", "generation_value": 0.5},
            },
        },
    }

    slots = build_fast_plan(dataset, 1, seed=1)

    assert slots[0]["doc_id"] == "good"

def test_duplicate_guard_uses_verifier_expression_and_expected_value():
    first = {
        "question_text": "Tinh luong nuoc voi q(t)=20+4t tren [0,1.5].",
        "answer_text": "34,5",
        "source_quote_text": "Luu luong duoc tinh boi tich phan.",
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "integrate(20+4*t, (t, 0, 1.5))", "expected_numeric": 34.5},
        },
    }
    same_expr = {
        "question_text": "Tinh quang duong voi v(t)=20+4t tren [0,1.5].",
        "answer_text": "34,5",
        "source_quote_text": "Quang duong duoc tinh boi tich phan.",
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "integrate(20 + 4*t, (t, 0, 1.5))", "expected_numeric": 34.5},
        },
    }
    same_value = {
        "question_text": "Tinh quang duong cua xe trong mot khoang thoi gian khac.",
        "answer_text": "34,5",
        "source_quote_text": "Quang duong duoc tinh boi tich phan cua van toc.",
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "30 + 4.5", "expected_numeric": 34.5},
        },
    }
    existing = [OrchestratorAgent._accepted_question_ref(first)]

    assert OrchestratorAgent._is_duplicate_question(same_expr, existing) is True
    assert OrchestratorAgent._is_duplicate_question(same_value, existing) is True

def test_duplicate_guard_does_not_block_distinct_verified_area_computations_by_core_only():
    first = {
        "question_text": "Tinh dien tich hinh phang gioi han boi y=x va y=x^2 tren [0,1].",
        "answer_text": "1/6",
        "source_quote_text": "Dien tich hinh phang duoc tinh boi tich phan.",
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "integrate(x-x**2, (x, 0, 1))", "expected_numeric": 1/6},
        },
    }
    second = {
        "question_text": "Mot bon hoa nam giua hai do thi y=2*x+3 va y=x**2+1 tren [0,2] co dien tich bao nhieu?",
        "answer_text": "10/3",
        "source_quote_text": "Dien tich mien giua hai do thi tinh bang tich phan hieu hai ham.",
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "integrate((2*x+3)-(x**2+1), (x, 0, 2))", "expected_numeric": 10/3},
        },
    }
    existing = [OrchestratorAgent._accepted_question_ref(first)]

    assert OrchestratorAgent._is_duplicate_question(second, existing) is False

def test_rewrite_answer_letter_refs_handles_bare_letter_dung_duplicate():
    text = "A \u0111\u00fang \u0111\u00fang vi ket qua khop."

    assert _rewrite_answer_letter_refs(text, "B") == "B \u0111\u00fang vi ket qua khop."

def test_batch_json_parser_accepts_top_level_array():
    parsed = _first_json_object('[{"slot_id":"q_001","question":"Stem?"}]')

    assert parsed == {"questions": [{"slot_id": "q_001", "question": "Stem?"}]}

def test_verifier_rejects_numeric_payload_when_answer_text_disagrees():
    candidate = {
        "question_text": "The tich nuoc sau 10 phut la bao nhieu lit?",
        "answer_text": "140",
        "answer_explanation_text": "Tinh gia tri bieu thuc tong luong nuoc.",
        "source_quote_text": "The tich nuoc trong be duoc tinh boi cong thuc.",
        "distractors": [
            {"distractor_text": "130"},
            {"distractor_text": "150"},
            {"distractor_text": "160"},
        ],
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "50 + 100", "expected_numeric": 150},
        },
        "detailed_solution": {
            "steps": [
                {"title": "Buoc 1", "content": "Xac dinh bieu thuc."},
                {"title": "Buoc 2", "content": "Tinh 50 + 100 = 150."},
                {"title": "Ket luan", "content": "Ket qua dung la 150."},
            ]
        },
    }
    slot = {
        "slot_id": "q_test",
        "cognitive_level": "Thong hieu",
        "question_pattern": "computation",
        "source_chunk_type": "theory",
    }

    resp = VerifierAgent().run(VerifyRequest(candidate=candidate, slot=slot))

    assert resp.rejected is True
    assert "answer_text_mismatch" in resp.reject_reason


def test_verifier_repairs_answer_key_when_verified_distractor_matches_solution():
    candidate = {
        "question_text": "Mot chat diem co van toc \\(v(t)=-4\\) m/s tren \\([0,3]\\). Do doi \\(\\int_0^3 v(t)dt\\) bang bao nhieu?",
        "answer_text": "12",
        "answer_explanation_text": "Ta co I = -12.",
        "source_quote_text": "Tich phan xac dinh duoc tinh bang cong thuc Newton-Leibniz.",
        "distractors": [
            {"distractor_text": "-12", "distractor_explanation_text": "Sai do nham dau."},
            {"distractor_text": "0", "distractor_explanation_text": "Sai vi bo qua ham hang."},
            {"distractor_text": "-4", "distractor_explanation_text": "Sai vi quen nhan do dai khoang."},
        ],
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "integrate(-4, (x, 0, 3))", "expected_numeric": -12},
        },
        "detailed_solution": {
            "steps": [
                {"title": "Buoc 1", "content": "Lap tich phan."},
                {"title": "Buoc 2", "content": "\\(I=-4\\cdot 3=-12\\)."},
                {"title": "Ket luan", "content": "Chon -12."},
            ],
            "final_answer": "-12",
        },
    }
    slot = {
        "slot_id": "q_repair",
        "cognitive_level": "Thong hieu",
        "question_pattern": "computation",
        "source_chunk_type": "exercise",
    }

    resp = VerifierAgent().run(VerifyRequest(candidate=candidate, slot=slot))

    assert resp.rejected is False
    patch = resp.annotations.get("_candidate_patch") or {}
    assert patch.get("answer_text") == "-12"
    assert any(d.get("distractor_text") == "12" for d in patch.get("distractors", []))

def test_verifier_repair_rewrites_contradicting_correct_explanation():
    candidate = {
        "question_text": "Mot be nuoc co luu luong q(t)=20+4t. Sau 1,5 gio co them bao nhieu lit?",
        "answer_text": "39 lit",
        "answer_explanation_text": "Tinh tich phan tren [0,1.5] duoc 39 lit.",
        "why_correct": "Ket qua dung la 39 lit.",
        "source_quote_text": "Luu luong duoc tinh boi tich phan theo thoi gian.",
        "distractors": [
            {"distractor_text": "34,5 lit", "distractor_explanation_text": "Dung nhung bi dat nham o distractor."},
            {"distractor_text": "30 lit", "distractor_explanation_text": "Sai do bo qua phan 4t."},
            {"distractor_text": "20 lit", "distractor_explanation_text": "Sai do chi lay gia tri ban dau."},
        ],
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "integrate(20+4*t, (t, 0, 1.5))", "expected_numeric": 34.5},
        },
        "detailed_solution": {
            "steps": [
                {"title": "Buoc 1", "content": "Lap tich phan."},
                {"title": "Buoc 2", "content": "Tinh duoc 39 lit."},
                {"title": "Buoc 3", "content": "Doi chieu voi cac phuong an."},
                {"title": "Ket luan", "content": "Chon 34,5 lit."},
            ],
            "final_answer": "34,5 lit",
        },
    }
    slot = {
        "slot_id": "q_repair_explanation",
        "cognitive_level": "Van dung",
        "question_pattern": "application",
        "source_chunk_type": "exercise",
    }

    resp = VerifierAgent().run(VerifyRequest(candidate=candidate, slot=slot))

    assert resp.rejected is False
    patch = resp.annotations.get("_candidate_patch") or {}
    assert patch.get("answer_text") == "34,5 lit"
    correct_text = " ".join([
        patch.get("answer_explanation_text", ""),
        patch.get("why_correct", ""),
        " ".join(
            step.get("content", "")
            for step in (patch.get("detailed_solution") or {}).get("steps", [])
        ),
    ])
    assert "39" not in correct_text
    assert "34,5" in correct_text

def test_numeric_eval_verifier_supports_integrate_expression():
    result = verify({
        "type": "numeric_eval",
        "payload": {
            "expr": "integrate(6-t/2, (t, 0, 8))",
            "expected_numeric": 32,
        },
    })

    assert result.verified is True
    assert result.actual == 32.0


def test_verifier_accepts_latex_fraction_answer_text_matching_numeric_payload():
    candidate = {
        "question_text": "Tinh dien tich hinh phang.",
        "answer_text": "\\(\\dfrac{10}{3}\\)",
        "answer_explanation_text": "Tinh tich phan ra 10/3.",
        "source_quote_text": "Dien tich hinh phang duoc tinh boi tich phan.",
        "distractors": [
            {
                "distractor_text": "\\(\\dfrac{8}{3}\\)",
                "distractor_explanation_text": "Sai do bo sot hang tu do, tinh thanh \\(8/3\\).",
            },
            {
                "distractor_text": "\\(3\\)",
                "distractor_explanation_text": "Sai do lam tron \\(10/3\\) thanh \\(3\\).",
            },
            {
                "distractor_text": "\\(4\\)",
                "distractor_explanation_text": "Sai do lam tron len \\(10/3\\) thanh \\(4\\).",
            },
        ],
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "10/3", "expected_numeric": 10 / 3},
        },
        "detailed_solution": {
            "steps": [
                {"title": "Buoc 1", "content": "Lap tich phan."},
                {"title": "Buoc 2", "content": "Tinh duoc 10/3."},
                {"title": "Ket luan", "content": "Chon 10/3."},
                {"title": "Kiem tra", "content": "Doi chieu dap an."},
            ]
        },
        "_fast_full_mcq": True,
    }
    slot = {
        "slot_id": "q_frac",
        "cognitive_level": "Van dung",
        "question_pattern": "application",
        "source_chunk_type": "theory",
    }

    resp = VerifierAgent().run(VerifyRequest(candidate=candidate, slot=slot))

    assert resp.rejected is False


def test_rule_validator_requires_verifier_for_numeric_computation_slots():
    candidate = {
        "question_text": "Dien tich hinh phang bang bao nhieu?",
        "answer_text": "\\(\\dfrac{8}{3}\\)",
        "answer_explanation_text": "Tinh tich phan de duoc ket qua.",
        "source_quote_text": "Dien tich hinh phang duoc tinh boi tich phan.",
        "distractors": [
            {"distractor_text": "\\(\\dfrac{4}{3}\\)"},
            {"distractor_text": "\\(3\\)"},
            {"distractor_text": "\\(4\\)"},
        ],
        "verifier_hint": {"type": "none", "payload": {}},
        "detailed_solution": {
            "steps": [
                {"title": "Buoc 1", "content": "Lap tich phan."},
                {"title": "Buoc 2", "content": "Tinh ra 8/3."},
                {"title": "Ket luan", "content": "Chon 8/3."},
                {"title": "Kiem tra", "content": "Doi chieu dap an."},
            ]
        },
    }
    slot = {
        "cognitive_level": "Van dung",
        "question_pattern": "application",
        "source_chunk_type": "theory",
    }

    issues = validate_candidate(candidate, slot)

    assert "verifier_missing:numeric_computation" in issues


def test_rule_validator_rejects_bare_one_step_integral():
    candidate = {
        "question_text": "Tinh \\(I=\\int_1^3 2x\\,dx\\).",
        "answer_text": "8",
        "answer_explanation_text": "Dung cong thuc Newton-Leibniz.",
        "source_quote_text": "Tich phan xac dinh duoc tinh bang cong thuc Newton-Leibniz.",
        "distractors": [
            {"distractor_text": "9", "distractor_explanation_text": "Thay can tren nhung quen tru can duoi: \\(3^2=9\\)."},
            {"distractor_text": "4", "distractor_explanation_text": "Nhan gia tri hang voi do dai khoang: \\(2(3-1)=4\\)."},
            {"distractor_text": "6", "distractor_explanation_text": "Tinh nham nguyen ham thanh \\(2x\\) roi thay can."},
        ],
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "integrate(2*x, (x, 1, 3))", "expected_numeric": 8},
        },
        "detailed_solution": {
            "steps": [
                {"title": "Buoc 1", "content": "Nguyen ham cua 2x la x^2."},
                {"title": "Buoc 2", "content": "Tinh 3^2-1^2=8."},
            ]
        },
        "_fast_full_mcq": True,
    }

    issues = validate_candidate(candidate, {
        "cognitive_level": "Nhan biet",
        "question_pattern": "computation",
        "source_chunk_type": "theory",
    })

    assert "question_too_trivial:bare_one_step_integral" in issues


def test_rule_validator_rejects_vague_numeric_distractor_rationale():
    candidate = {
        "question_text": "Luu luong nuoc la \\(r(t)=2t+1\\). Trong 3 phut dau co bao nhieu lit?",
        "answer_text": "12",
        "answer_explanation_text": "Tinh \\(\\int_0^3(2t+1)dt=12\\).",
        "source_quote_text": "Luu luong duoc tinh boi cong thuc tich phan theo thoi gian.",
        "distractors": [
            {"distractor_text": "18", "distractor_explanation_text": "Sai do cong nham."},
            {"distractor_text": "9", "distractor_explanation_text": "Bo qua hang \\(+1\\), chi tinh \\(\\int_0^3 2t\\,dt=9\\)."},
            {"distractor_text": "6", "distractor_explanation_text": "Chi lay gia tri tai diem cuoi \\(2\\cdot3=6\\)."},
        ],
        "verifier_hint": {
            "type": "numeric_eval",
            "payload": {"expr": "integrate(2*t+1, (t, 0, 3))", "expected_numeric": 12},
        },
        "detailed_solution": {
            "steps": [
                {"title": "Buoc 1", "content": "Lap tich phan."},
                {"title": "Buoc 2", "content": "Tinh \\(\\int_0^3(2t+1)dt=12\\)."},
                {"title": "Ket luan", "content": "Chon 12."},
                {"title": "Don vi", "content": "Don vi la lit."},
            ]
        },
        "_fast_full_mcq": True,
    }

    issues = validate_candidate(candidate, {
        "cognitive_level": "Van dung",
        "question_pattern": "application",
        "source_chunk_type": "exercise",
    })

    assert "d1:vague_distractor_rationale" in issues


def test_orchestrator_rejects_same_core_antiderivative_pattern():
    first = {
        "question_text": "F la nguyen ham cua f(x)=4cos x va F(0)=3. Tinh F(pi/2).",
        "answer_text": "7",
        "answer_explanation_text": "F(x)=4sin x+3.",
    }
    second = {
        "question_text": "Vat co van toc v(t)=4cos t va s(0)=2. Tinh s(pi/2).",
        "answer_text": "6",
        "answer_explanation_text": "s(t)=4sin t+2.",
    }

    assert OrchestratorAgent._is_duplicate_question(second, [{
        "question_text": first["question_text"],
        "answer_text": first["answer_text"],
        "source_quote": "",
        "core_signature": OrchestratorAgent._core_question_signature(first),
    }])


def test_orchestrator_rejects_same_core_integral_positivity_property():
    first = {
        "question_text": "Menh de dung?",
        "answer_text": (
            "Neu \\(f(x)\\ge 0\\) tren \\([a,b]\\) thi "
            "\\(\\int_a^b f(x)\\,dx\\ge 0\\)."
        ),
        "answer_explanation_text": "Tich phan cua ham khong am tren mot doan la mot so khong am.",
    }
    second = {
        "question_text": "Chon khang dinh dung ve tich phan xac dinh.",
        "answer_text": (
            "Neu ham so f khong am tren [a,b] thi "
            "tich phan cua f tren [a,b] khong am."
        ),
        "answer_explanation_text": "Day la tinh chat don dieu co ban cua tich phan.",
    }

    assert OrchestratorAgent._core_question_signature(first) == "integral_positivity_property"
    assert OrchestratorAgent._is_duplicate_question(second, [{
        "question_text": first["question_text"],
        "answer_text": first["answer_text"],
        "source_quote": "",
        "core_signature": OrchestratorAgent._core_question_signature(first),
    }])

def test_orchestrator_signatures_zero_width_integral_property():
    candidate = {
        "question_text": "Chon menh de dung ve tich phan xac dinh.",
        "answer_text": "\\(\\int_a^a f(x)\\,dx=0\\) voi moi ham kha tich \\(f\\).",
        "answer_explanation_text": "Tich phan tren doan co do dai bang 0 luon bang 0.",
    }

    assert OrchestratorAgent._core_question_signature(candidate) == "integral_zero_interval_property"

def test_orchestrator_collects_spans_from_selected_context_chunks():
    dataset = {
        "metadata": {},
        "a": {
            "context": "clean",
            "clean_context": {
                "existing_question_spans": ["Cau 1: old stem A?"],
            },
        },
        "b": {
            "context": "clean",
            "clean_context": {
                "existing_question_spans": ["Cau 2: old stem B?"],
            },
        },
    }
    slot = {"existing_question_spans": ["Cau 0: base old stem?"]}

    spans = OrchestratorAgent._existing_question_spans_for_context(
        dataset, slot, ["a", "b"],
    )

    assert spans == [
        "Cau 0: base old stem?",
        "Cau 1: old stem A?",
        "Cau 2: old stem B?",
    ]


def test_generated_solution_answer_letter_follows_shuffled_record():
    generated = {
        "steps": [
            {"title": "Buoc 1", "content": "Doi chieu cong thuc voi phuong an \\(A\\). Phuong an A la cach viet cu."},
            {"title": "Ket luan", "content": "Vi vay phuong an dung la A."},
        ],
        "final_answer": "A. old answer text",
    }
    record = {
        "answer_key": "C",
        "options": [
            {"key": "A", "text": "wrong"},
            {"key": "C", "text": "right answer"},
        ],
    }

    aligned = _align_generated_solution(generated, record)

    assert aligned["steps"][-1]["content"] == "Chọn đáp án C: right answer."
    assert aligned["steps"][0]["content"] == (
        "Doi chieu cong thuc voi phuong an C. Phuong an C la cach viet cu."
    )
    assert aligned["final_answer"] == "right answer"

def test_why_correct_answer_letter_refs_follow_shuffled_record():
    text = "Phương án **A** đúng vì dùng đúng công thức."

    assert _rewrite_answer_letter_refs(text, "C") == (
        "Phương án C đúng vì dùng đúng công thức."
    )

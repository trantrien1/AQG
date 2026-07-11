import importlib
import unittest


def _candidate(stem, quote, answer="1,5"):
    return {
        "question_text": stem,
        "answer_text": answer,
        "answer_explanation_text": "Dựa vào dữ kiện trong đề và tính toán trực tiếp.",
        "source_quote_text": quote,
        "distractors": [
            {"distractor_text": "1", "distractor_explanation_text": "Sai."},
            {"distractor_text": "2", "distractor_explanation_text": "Sai."},
            {"distractor_text": "3", "distractor_explanation_text": "Sai."},
        ],
        "verifier_hint": {"type": "none", "payload": {}},
    }


class RuleValidatorTopicAlignmentTests(unittest.TestCase):
    """These cases exercise the STRICT quote-relevance gate (formula-family /
    concept support). That gate is opt-in via AQG_QUOTE_RELEVANCE_STRICT=1;
    the runtime default is lenient (see test_rule_validator_quote_lenient.py).
    """

    @classmethod
    def setUpClass(cls):
        import os
        os.environ['AQG_QUOTE_RELEVANCE_STRICT'] = '1'
        from pipeline import config as cfg
        importlib.reload(cfg)
        from pipeline import rule_validator as rv
        importlib.reload(rv)
        global validate_candidate, validate_record
        validate_candidate = rv.validate_candidate
        validate_record = rv.validate_record

    @classmethod
    def tearDownClass(cls):
        import os
        os.environ.pop('AQG_QUOTE_RELEVANCE_STRICT', None)
        from pipeline import config as cfg
        importlib.reload(cfg)
        from pipeline import rule_validator as rv
        importlib.reload(rv)

    def test_rejects_time_conversion_under_integral_slot(self):
        slot = {"topic": "2. TINH CHAT CUA TICH PHAN", "question_pattern": "conceptual"}
        cand = _candidate(
            "Trong mot bai toan thuc te, thoi gian 1 gio 30 phut duoc viet duoi dang so gio la bao nhieu?",
            "Ta co 1 gio 30 phut = 1,5 gio.",
        )

        issues = validate_candidate(cand, slot)

        self.assertIn("slot_topic_mismatch:missing_integral_support", issues)

    def test_rejects_circle_quote_when_integral_concept_is_required(self):
        slot = {"topic": "2. TINH CHAT CUA TICH PHAN", "question_pattern": "application"}
        cand = _candidate(
            "Cho duong tron tam F(1;0). Lap tich phan tinh dien tich nua duoi cua duong tron.",
            "Phuong trinh duong tron co tam (1; 0)",
            answer="y=-sqrt(9-(x-1)^2)",
        )

        issues = validate_candidate(cand, slot)

        self.assertIn("quote_mismatch:source_quote_not_relevant", issues)

    def test_allows_integral_supported_item(self):
        slot = {"topic": "2. TINH CHAT CUA TICH PHAN", "question_pattern": "conceptual"}
        cand = _candidate(
            "Khi can tinh tich phan int_a^b (2f(x)-3g(x)) dx, nen dung tinh chat nao?",
            "Tich phan cua tong hieu bang tong hieu cac tich phan tuong ung.",
            answer="Tinh tuyen tinh cua tich phan",
        )

        issues = validate_candidate(cand, slot)

        self.assertNotIn("slot_topic_mismatch:missing_integral_support", issues)
        self.assertNotIn("quote_mismatch:source_quote_not_relevant", issues)


    def test_rejects_generic_docling_heading_for_power_antiderivative(self):
        slot = {"topic": "2. TINH CHAT CO BAN CUA NGUYEN HAM", "question_pattern": "conceptual"}
        cand = _candidate(
            "Voi n != -1, cong thuc nguyen ham cua ham so x^n la gi?",
            "Cho f(x), g(x) la hai ham so lien tuc tren K. NGUYEN HAM TICH PHAN BAI. CHUYEN DE IV - NGUYEN HAM - TICH PHAN",
            answer="x^(n+1)/(n+1)+C",
        )

        issues = validate_candidate(cand, slot)

        self.assertIn("quote_mismatch:source_quote_is_metadata", issues)
        self.assertIn("quote_mismatch:source_quote_not_relevant", issues)

    def test_allows_power_antiderivative_with_formula_quote(self):
        slot = {"topic": "2. TINH CHAT CO BAN CUA NGUYEN HAM", "question_pattern": "conceptual"}
        cand = _candidate(
            "Voi n != -1, cong thuc nguyen ham cua ham so x^n la gi?",
            "Nguyen ham cua x^n la x^(n+1)/(n+1)+C voi n != -1.",
            answer="x^(n+1)/(n+1)+C",
        )

        issues = validate_candidate(cand, slot)

        self.assertNotIn("quote_mismatch:source_quote_is_metadata", issues)
        self.assertNotIn("quote_mismatch:source_quote_not_relevant", issues)

    def test_final_record_rejects_generic_source_quote(self):
        record = {
            "stem": "Voi n != -1, cong thuc nguyen ham cua ham so x^n la gi?",
            "answer_key": "A",
            "options": [
                {"key": "A", "text": "x^(n+1)/(n+1)+C"},
                {"key": "B", "text": "x^n+C"},
                {"key": "C", "text": "n*x^(n-1)+C"},
                {"key": "D", "text": "x^(n+1)+C"},
            ],
            "source": {
                "quote": "NGUYEN HAM TICH PHAN BAI. CHUYEN DE IV - NGUYEN HAM - TICH PHAN",
            },
        }

        issues = validate_record(record)

        self.assertIn("quote_mismatch:source_quote_is_metadata", issues)

    def test_rejects_single_heading_as_source_quote(self):
        slot = {"topic": "2. TINH CHAT CO BAN CUA NGUYEN HAM", "question_pattern": "conceptual"}
        cand = _candidate(
            "Neu F(x) la mot nguyen ham cua f(x), ho tat ca cac nguyen ham co dang nao?",
            "TINH CHAT CO BAN CUA NGUYEN HAM.",
            answer="F(x)+C",
        )

        issues = validate_candidate(cand, slot)

        self.assertIn("quote_mismatch:source_quote_is_metadata", issues)

    def test_rejects_concrete_motion_problem_with_generic_quote(self):
        slot = {"topic": "Ung dung nguyen ham trong chuyen dong thang", "question_pattern": "application"}
        cand = _candidate(
            "Mot chat diem co gia toc a(t)=6t, v(0)=2 va s(0)=5. Tinh vi tri tai t=3 giay.",
            "Cho f(x), g(x) la hai ham so lien tuc tren K.",
            answer="32",
        )
        cand["verifier_hint"] = {"type": "numeric_eval", "payload": {"expected_numeric": 32}}

        issues = validate_candidate(cand, slot)

        self.assertIn("quote_mismatch:source_quote_not_relevant", issues)

if __name__ == "__main__":
    unittest.main()

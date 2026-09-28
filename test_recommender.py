import json
import tempfile
import unittest
from pathlib import Path

from recommender import CourseRecommender, StudentProfile, parse_meeting, parse_query


class RecommenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / "academic_data").mkdir()
        catalogue = [
            {"course_code": "CS F301", "title": "Machine Learning", "units": 3,
             "prerequisite_course_codes": ["CS F111"], "prerequisite_expression": "CS F111"},
            {"course_code": "CS F302", "title": "Deep Learning", "units": 3,
             "prerequisite_course_codes": ["CS F211"], "prerequisite_expression": "CS F211"},
        ]
        source = {"source_document": "timetable.pdf", "pdf_page": 2}
        timetable = {"term": "TEST TERM", "campus": "Pilani", "offerings": [
            {"course_code": "CS F301", "computer_code": 1001, "title": "MACHINE LEARNING",
             "credits": {"u": 3}, "cancelled": False, "restricted_to_2026_admissions": False, "source": source},
            {"course_code": "CS F302", "computer_code": 1002, "title": "DEEP LEARNING",
             "credits": {"u": 3}, "cancelled": False, "restricted_to_2026_admissions": False, "source": source},
        ], "sections": [
            {"course_code": "CS F301", "section": "L1", "room": "A1", "meeting_text": "M W F 2", "cancelled": False},
            {"course_code": "CS F302", "section": "L1", "room": "A2", "meeting_text": "Tu Th 3", "cancelled": False},
        ]}
        handouts = [{"course_codes": ["CS F301"], "description": "artificial intelligence, machine learning and neural networks",
                     "scope": "", "topics": [{"topic": "machine learning"}], "attendance_required": False,
                     "has_midsem": False, "has_compre": True, "evaluation_components": [],
                     "source_file": "cs.pdf", "extraction_status": "extracted_unverified"}]
        for path, value in (("academic_data/course_catalogue.json", catalogue),
                            ("academic_data/timetable.json", timetable), ("temp.json", handouts)):
            (root / path).write_text(json.dumps(value))
        (root / "academic_data/programme_categories.json").write_text(json.dumps({
            "programmes": {"COMPUTER SCIENCE": {"CDC": [], "DEL": [{"course_code": "CS F301", "source": source}]}},
            "huel": [],
        }))
        self.engine = CourseRecommender(root)

    def tearDown(self):
        self.temp.cleanup()

    def test_query_parser_and_meeting_parser(self):
        parsed = parse_query("Suggest AI DELs with no midsem and no 8 AM classes")
        self.assertEqual(parsed["category"], "del")
        self.assertTrue(parsed["no_midsem"] and parsed["no_early_classes"])
        self.assertEqual(parse_meeting("M W F 2"), {("Mon", 2), ("Wed", 2), ("Fri", 2)})
        self.assertEqual(parse_meeting("M W 5 Th 10"), {("Mon", 5), ("Wed", 5), ("Thu", 10)})

    def test_no_quiz_query_is_parsed_and_enforced(self):
        self.assertTrue(parse_query("suggest no quizzes AI DEL")["no_quiz"])
        profile = {"degree": "B.E. Computer Science", "completed_courses": ["CS F111"]}
        handout = self.engine.handout_by_code["CS F301"]
        handout["evaluation_weights_sum_to_100"] = True
        result = self.engine.recommend(profile, "machine learning with no quiz")
        self.assertEqual([row["course_code"] for row in result["recommendations"]], ["CS F301"])
        handout["evaluation_components"] = [{"name": "Quiz", "type": "quiz", "raw_text": "Quiz 10%"}]
        result = self.engine.recommend(profile, "machine learning with no quiz")
        self.assertEqual(result["recommendations"], [])

    def test_strict_evidence_and_prerequisites(self):
        profile = {"completed_courses": ["CS F111"], "interests": ["machine learning"]}
        result = self.engine.recommend(profile, "AI course with no midsem")
        self.assertEqual([row["course_code"] for row in result["recommendations"]], ["CS F301"])
        self.assertEqual(result["eligible_candidates"], 1)

    def test_remaining_requirements_never_negative(self):
        profile = StudentProfile(requirement_totals={"CDC": 4}, requirement_completed={"CDC": 6})
        self.assertEqual(profile.remaining_requirements()["CDC"], 0)

    def test_requested_category_is_enforced_and_evidenced(self):
        profile = {"degree": "B.E. Computer Science", "completed_courses": ["CS F111"]}
        result = self.engine.recommend(profile, "Suggest machine learning DELs")
        self.assertEqual([row["course_code"] for row in result["recommendations"]], ["CS F301"])
        claims = [row["claim"] for row in result["recommendations"][0]["evidence"]]
        self.assertIn("verified DEL for B.E. Computer Science", claims)

    def test_ai_abbreviation_affects_ranking(self):
        parsed = parse_query("Suggest AI-related DELs")
        self.assertTrue({"artificial", "intelligence"} <= set(parsed["keywords"]))

    def test_low_midsem_is_ranked(self):
        parsed = parse_query("AI DEL with a small midsem")
        self.assertTrue(parsed["low_midsem"])

    def test_requirements_are_calculated_from_courses(self):
        profile = StudentProfile(degree="B.E. Computer Science", completed_courses=["CS F301"])
        analysis = self.engine.requirement_analysis(profile)
        self.assertEqual(analysis["totals"]["DEL"], 4)
        self.assertEqual(analysis["completed"]["DEL"], 1)
        self.assertEqual(analysis["remaining"]["DEL"], 3)

    def test_central_unit_limit_blocks_candidate(self):
        profile = {"degree": "B.E. Computer Science", "completed_courses": ["CS F111"],
                   "current_registered_units": 24}
        result = self.engine.recommend(profile, "machine learning")
        self.assertEqual(result["recommendations"], [])


if __name__ == "__main__":
    unittest.main()

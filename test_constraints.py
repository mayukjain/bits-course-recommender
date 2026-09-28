import unittest
from pathlib import Path

from constraints import (
    PlannedCourse,
    StudentState,
    evaluate_constraints,
    extract_regulation_clauses,
    extract_equivalent_courses,
    extract_programme_categories,
    extract_timetable,
    extract_timetable_rules,
    normalize_code,
)


ROOT = Path(__file__).resolve().parent


class ConstraintTests(unittest.TestCase):
    def test_normalize_code(self):
        self.assertEqual(normalize_code("cs g 527"), "CS G527")

    def test_all_major_regulation_clauses_are_retained(self):
        clauses = extract_regulation_clauses(ROOT / "Academic-Regulations-2023.pdf")
        ids = {row["clause_id"] for row in clauses}
        self.assertTrue({"1.01", "1.03", "2.05", "2.08", "2.10", "3.13"} <= ids)
        self.assertTrue(all(row["text"] and row["pages"] for row in clauses))

    def test_timetable_extracts_known_course(self):
        timetable = extract_timetable(ROOT / "timetable.pdf")
        rows = [row for row in timetable["offerings"] if row["course_code"] == "AN F314"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["credits"]["u"], 3)
        self.assertEqual(rows[0]["midsem"], {"date": "09/10", "session": "AN1"})
        sections = [row for row in timetable["sections"] if row["course_code"] == "BIO F101"]
        self.assertTrue(any(row["section"].startswith("P") for row in sections))

    def test_deterministic_checks(self):
        student = StudentState("first_degree", {"CS F111"}, 2025)
        planned = [PlannedCourse("CS F211", 30, 6000)]
        catalogue = {"CS F211": {"prerequisite_course_codes": ["CS F111"], "prerequisite_expression": "CS F111"}}
        offerings = [{"course_code": "CS F211", "computer_code": 6000, "cancelled": False,
                      "restricted_to_2026_admissions": True}]
        rules = {row["rule"] for row in evaluate_constraints(student, planned, catalogue, offerings)}
        self.assertEqual(rules, {"semester_unit_limit", "admission_year_restriction"})

    def test_timetable_rules_and_equivalences(self):
        rules = extract_timetable_rules(ROOT / "timetable.pdf")
        self.assertEqual(len(rules), 7)
        self.assertIn("maximum of four", rules[1]["text"])
        groups = extract_equivalent_courses(ROOT / "timetable.pdf")
        self.assertTrue(any(
            {"CS G527", "SS G527"} <= set(group["equivalent_courses"])
            for group in groups
        ))

    def test_programme_categories_have_source_evidence(self):
        categories = extract_programme_categories(ROOT / "bulletin.pdf")
        cs = categories["programmes"]["COMPUTER SCIENCE"]
        del_row = next(row for row in cs["DEL"] if row["course_code"] == "CS F407")
        self.assertEqual(del_row["source"]["pdf_page"], 318)
        self.assertTrue(any(row["course_code"] == "HSS F266" for row in categories["huel"]))


if __name__ == "__main__":
    unittest.main()

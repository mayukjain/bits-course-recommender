import shutil
import unittest
from pathlib import Path

from handout_parser import compact, extract_section, parse_evaluation, parse_handout, extract_pdf_text


class SectionTests(unittest.TestCase):
    def test_policy_keeps_inline_instructor_and_notes(self):
        text = (
            "9. Make-up Policy: Ask the Instructor-in-charge for permission.\n"
            "Keep your handwritten notes.\n"
            "10. Attendance Policy: Attend classes.\n"
        )
        self.assertEqual(
            compact(extract_section(text, r"Make[-\s]*up Policy")),
            "Ask the Instructor-in-charge for permission. Keep your handwritten notes."
        )

    def test_scope_keeps_repeated_phrase_and_stops_at_outcomes(self):
        text = (
            "2. Scope & Objective:\n"
            "Following are the scope and objective of this course: study flight.\n"
            "3. Course Learning Outcomes: Apply principles.\n"
        )
        result = parse_handout(text, "001_AN_F314.pdf")
        self.assertEqual(result['scope'],
                         "Following are the scope and objective of this course: study flight.")

    def test_duration_is_not_a_missing_weight(self):
        text = (
            "Evaluation Scheme:\n"
            "Component             Duration   Weightage       Date\n"
            "Mid Semester Test     90 min                     TBD\n"
            "Comprehensive         3 h        60%             TBD\n"
            "Grading Policy: Below 30% fails.\n"
        )
        rows = parse_evaluation(text)
        self.assertEqual([row['weight'] for row in rows], [None, 60.0])

    def test_raw_marks_weightage_table(self):
        text = (
            "4. EVALUATION\n"
            "The instruments of evaluation are given below:\n"
            "             Component                       Weightage       Week in which due\n"
            "             Viva-I                          15              5th week\n"
            "             Mid. sem. Written report        15              10th week\n"
            "             Final Dissertation*             25              Last day of class work\n"
            "             Final viva-voce*                15              Actual date announced\n"
            "*Final viva-voce is jointly evaluated.\n"
        )
        rows = parse_evaluation(text)
        self.assertEqual([row['name'] for row in rows], [
            'Viva-I', 'Mid. sem. Written report', 'Final Dissertation*',
            'Final viva-voce*'
        ])
        self.assertEqual([row['weight'] for row in rows], [15, 15, 25, 15])
        self.assertEqual([row['weight_basis'] for row in rows], ['weight_column'] * 4)


@unittest.skipUnless(shutil.which('pdftotext'), 'PDF regression checks require pdftotext')
class PDFRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = Path(__file__).parent / 'handouts'
        cls.data = {}
        for pdf in sorted(folder.glob('*.pdf'))[:10]:
            cls.data[pdf.stem] = parse_handout(extract_pdf_text(pdf), str(pdf))

    def test_actual_assessment_weights(self):
        expected = {
            '001_AN_F314': [15, 15, 30, 40],
            '002_BIO_F101': [25, 15, 5, 15, 5, 35],
            '003_BIO_F211': [30, 35, 25, 10],
            '004_BIO_F212': [20, 10, 5, 30, 35],
            '005_BIO_F213': [25, 20, 10, 10, 35],
            '006_BIO_F214': [30, 40, 30],
            '007_BIO_F311': [35, 25, 40],
            '008_BIO_F312': [30, 15, 10, 45],
            '009_BIO_F313': [25, 15, 20, 40],
            '010_BIO_F417': [40, 25, 10, 25],
        }
        for key, weights in expected.items():
            with self.subTest(pdf=key):
                result = self.data[key]
                self.assertEqual([row['weight'] for row in result['evaluation_components']], weights)
                self.assertEqual(result['total_evaluation_weight'], 100)
                self.assertNotIn('other', [row['type'] for row in result['evaluation_components']])

    def test_combined_names_and_clean_metadata(self):
        rows = self.data['002_BIO_F101']['evaluation_components']
        self.assertEqual(rows[4]['name'], 'Lab Viva')
        self.assertEqual(rows[4]['type'], 'viva')
        result = self.data['006_BIO_F214']
        self.assertEqual(result['title'], 'INTEGRATED BIOLOGY')
        self.assertEqual(result['instructor'], 'Pankaj Kumar Sharma')
        self.assertEqual(result['evaluation_components'][2]['name'], 'Quiz(zes) / Assignment(s)*')
        self.assertNotIn('Course Learning Outcomes', result['scope'])

    def test_description_is_not_invented_scope(self):
        result = self.data['003_BIO_F211']
        self.assertIsNone(result['scope'])
        self.assertIn('Biological', result['description'])

    def test_policy_is_complete(self):
        policy = self.data['002_BIO_F101']['makeup_policy']
        self.assertIn('Instructor-in-Charge, before applying', policy)
        self.assertTrue(policy.endswith('No Make-Up will be granted for quiz and assignments.'))
        self.assertTrue(self.data['010_BIO_F417']['makeup_policy'].endswith('Instructor-in-charge'))


class PreferenceTests(unittest.TestCase):
    def test_unknown_is_not_absence(self):
        result = parse_handout('Course Title: Test\n', '001_CS_F101.pdf')
        self.assertIsNone(result['attendance_required'])
        self.assertIsNone(result['has_midsem'])
        self.assertIsNone(result['has_compre'])
        self.assertIsNone(result['makeup_conditions']['excluded_assessments'])

    def test_attendance_exceptions_and_colon_numbering(self):
        result = parse_handout(
            '6: Attendance Policy: Attendance is not compulsory. '
            'Laboratory attendance is a must.\n'
            '7: Chamber Consultation Hour: Saturday.\n', '001_CS_F101.pdf')
        self.assertIsNone(result['attendance_required'])
        self.assertNotIn('Saturday', result['attendance_policy'])

    def test_attendance_minimum_and_source_page(self):
        result = parse_handout(
            'FIRST SEMESTER 2026-27\n\f'
            '6. Attendance Policy: Attendance is mandatory. A minimum of 75% is required.\n'
            '7. Notices: On the portal.\n', '001_CS_F101.pdf')
        self.assertTrue(result['attendance_required'])
        self.assertEqual(result['minimum_attendance_percent'], 75)
        self.assertEqual(result['source_metadata']['attendance_policy']['pages'], [2])
        self.assertEqual(result['semester'], 1)
        self.assertEqual(result['academic_year'], '2026-27')

    def test_explicit_absence_and_makeup_clauses(self):
        result = parse_handout(
            'Evaluation Scheme:\nNo midsem will be held.\n'
            'Make-up Policy: No make-up for quizzes. Prior permission is required. '
            'A medical certificate is required.\n', '001_CS_F101.pdf')
        self.assertFalse(result['has_midsem'])
        self.assertIsNone(result['has_compre'])
        conditions = result['makeup_conditions']
        self.assertEqual(conditions['excluded_assessments'], ['No make-up for quizzes.'])
        self.assertIn('Prior permission is required.', conditions['approval_requirements'])
        self.assertIn('A medical certificate is required.', conditions['documentation_requirements'])

    def test_assessment_details_and_topics(self):
        result = parse_handout(
            'Course Title: Machine Learning\n'
            'Course Description: Deep learning and neural networks.\n'
            'Evaluation Scheme:\n'
            'Component                 Weightage      Remarks\n'
            'Surprise Quizzes (2)      100%           Closed/Open-Book\n'
            'Make-up Policy: No make-up for quizzes.\n', '001_CS_F101.pdf')
        row = result['evaluation_components'][0]
        self.assertEqual(row['count'], 2)
        self.assertEqual(row['announcement'], 'surprise')
        self.assertEqual(row['book_policy'], 'mixed')
        self.assertEqual({topic['topic'] for topic in result['topics']},
                         {'machine learning', 'deep learning', 'neural networks'})
        self.assertIsNone(result['has_midsem'])
        self.assertIsNone(result['has_compre'])


@unittest.skipUnless(shutil.which('pdftotext'), 'Requires Poppler')
class AdditionalLayoutTests(unittest.TestCase):
    def read(self, name):
        path = Path(__file__).parent / 'handouts' / name
        return parse_handout(extract_pdf_text(path), str(path))

    def test_page_footer_is_not_assessment(self):
        result = self.read('018_BIO_G524.pdf')
        self.assertEqual([r['weight'] for r in result['evaluation_components']], [20, 10, 30, 10, 30])
        self.assertFalse(any('BIRLA' in r['name'] for r in result['evaluation_components']))
        self.assertEqual(result['evaluation_components'][2]['name'], 'Experiments and Lab quiz')

    def test_combined_code_and_title(self):
        result = self.read('180_CS_G527.pdf')
        self.assertEqual(result['course_codes'], ['CS G527', 'SS G527'])
        self.assertEqual(result['title'], 'Cloud Computing')

    def test_examination_heading_and_misspelled_weight(self):
        result = self.read('013_BIO_G512.pdf')
        self.assertEqual([r['weight'] for r in result['evaluation_components']], [25, 10, 30, 35])

    def test_table_total_is_not_assessment(self):
        result = self.read('041_BITS_F232.pdf')
        self.assertEqual([r['weight'] for r in result['evaluation_components']], [25, 20, 35, 20])

    def test_explicit_best_four_tutorials(self):
        result = self.read('075_CE_F211.pdf')
        self.assertEqual(result['total_listed_evaluation_weight'], 105)
        self.assertEqual(result['total_evaluation_weight'], 100)
        self.assertTrue(result['evaluation_selection_rules'][0]['applied_to_total'])
        self.assertEqual(len(result['evaluation_components']), 7)

    def test_marks_conversion_requires_declared_total(self):
        result = self.read('203_ECE_F211.pdf')
        self.assertEqual([r['marks'] for r in result['evaluation_components']], [20, 40, 75, 105, 40, 20])
        self.assertAlmostEqual(result['total_evaluation_weight'], 100)
        unknown = self.read('162_CS_F215.pdf')
        self.assertEqual(unknown['total_extracted_marks'], 300)
        self.assertIsNone(unknown['total_evaluation_weight'])

    def test_source_disagreement_is_reported(self):
        result = self.read('207_ECE_F311.pdf')
        row = result['evaluation_components'][-1]
        self.assertEqual(row['weight'], 35)
        self.assertEqual(row['marks'], 120)
        self.assertTrue(any('disagree' in w for w in result['parsing_warnings']))

    def test_pass_fail_and_image_only_documents(self):
        result = self.read('032_BITS_F101-1.pdf')
        self.assertEqual(result['evaluation_scheme_kind'], 'pass_fail')
        self.assertIn('Maximum 6 late submissions', result['evaluation_scheme_text'])
        self.assertIsNone(result['has_midsem'])
        blank = self.read('348_MAC_F214.pdf')
        self.assertEqual(blank['extraction_status'], 'needs_ocr')
        self.assertIsNone(blank['title'])

    def test_bullet_assessment_list(self):
        result = self.read('059_BITS_F468.pdf')
        self.assertEqual([r['weight'] for r in result['evaluation_components']], [10, 10, 30, 50])

    def test_midsemester_report_is_not_a_midsemester_exam(self):
        result = parse_handout(
            'Evaluation Scheme:\n'
            'Component                 Weightage      Date\n'
            'Midsem Report             100%           TBD\n', '001_CS_F101.pdf')
        self.assertIsNone(result['has_midsem'])



class ReviewRegressionTests(unittest.TestCase):
    def test_labels_without_values_do_not_generate_fixed_assessments(self):
        from handout_parser import parse_evaluation
        signatures = [
            'Tut 1 #\nTut 2: Poster 1\nTut 6, 7, 8: Group presentations\nMid-Semester Test',
            'Exp. Report Analysis Visualization\nCycle 1 (or 2) Lab Exam\n'
            'Cycle 2 (or 1) Lab Exam\nComprehensive Quiz\nComprehensive Viva',
            'Evaluative Component\nMid. Sem. Test\nComprehensive Examination\n'
            'Continuous Assessment (lab.',
        ]
        for text in signatures:
            with self.subTest(signature=text):
                self.assertEqual(parse_evaluation(text), [])

    def test_named_fallback_ignores_dates_and_times(self):
        from handout_parser import parse_named_weight_rows
        for date in ['10/10', '10/10/2026', '2026-10-10', 'Oct 10, 2026', '10:30']:
            with self.subTest(date=date):
                rows = parse_named_weight_rows(f'Mid Semester Test 90 minutes 30 {date}')
                self.assertEqual(rows[0]['weight'], 30)
        self.assertEqual(parse_named_weight_rows('Mid Semester Test 90 minutes 10/10'), [])
        self.assertEqual(parse_named_weight_rows('Mid Semester Test 90 minutes 30 40'), [])
        self.assertEqual(parse_named_weight_rows('Mid Semester Test 30 minutes 30% 10/10')[0]['weight'], 30)

    def test_fallback_marks_need_a_declared_total(self):
        from handout_parser import parse_simple_weight_table, parse_indexed_weight_rows
        text = 'Component          Marks          Date\nMid Semester       60             TBD\nComprehensive      140            TBD'
        rows = parse_simple_weight_table(text)
        self.assertEqual([r['marks'] for r in rows], [60, 140])
        self.assertEqual([r['weight'] for r in rows], [None, None])
        declared = parse_simple_weight_table(text.replace('Marks', 'Marks (200)'))
        self.assertEqual([r['weight'] for r in declared], [30, 70])
        indexed = parse_indexed_weight_rows('Component  Marks  Date\n1. Mid Semester\n60 TBD\n2. Comprehensive\n140 TBD')
        self.assertEqual([r['weight'] for r in indexed], [None, None])
        weights = parse_simple_weight_table(text.replace('Marks', 'Weightage'))
        self.assertEqual([r['weight'] for r in weights], [60, 140])
        self.assertTrue(all(r['marks'] is None for r in weights))


if __name__ == '__main__':
    unittest.main()

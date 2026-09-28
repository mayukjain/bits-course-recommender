# Handout ingestion

Run `python handout_parser.py` to process all PDFs in `handouts/` and replace
`temp.json`. Use `python handout_parser.py --limit 10` for the original sample.
Run `python -m unittest -v test_handout_parser` for regression checks.

Extraction prefers Poppler's `pdftotext -layout`. If that executable is unavailable,
it attempts positioned-word extraction with PyMuPDF. The regression PDFs were
validated using Poppler; the PyMuPDF fallback has not been validated here.

## Recommendation fields

- `attendance_policy`: original policy text, when found.
- `attendance_required`: true/false only for recognized explicit wording;
  null for unknown, ambiguous, or conflicting rules (including lecture/lab exceptions).
- `minimum_attendance_percent`: explicitly stated minimum in the attendance section.
- `has_midsem`, `has_compre`: true when an assessment is found, false only when
  explicit absence is found in the evaluation section, otherwise null. A total
  weight of 100 does not establish an exam's absence.
- `evaluation_components`: names, weights, count, announcement status, book policy,
  group/individual work mode, raw text and source evidence. Unknown details are null.
- `makeup_conditions`: verbatim clauses grouped into permissions, exclusions,
  approval, grounds and documentation. These are evidence clauses, not a complete
  per-assessment eligibility model or a leniency score. Missing groups are null.
- `topics`: exact phrase matches in title/description/scope with source evidence.
  This uses a limited vocabulary; it is not exhaustive syllabus extraction.
- `academic_year`, `semester`: extracted from recognized semester headings.
- `source_metadata`: document name, one-based PDF page numbers, section, supporting
  text and verification status. Component evidence may span the whole evaluation
  section. Page numbers refer to PDF pages, not printed page labels.

`extracted` denotes located text, not human verification. Derived properties use
`needs_verification`; missing text uses `not_found`. There are no calibrated
confidence scores. All evaluation schemes remain `needs_verification`, including
schemes whose weights add to 100. Do not use unknown values as negative preferences
or infer academic eligibility from handout descriptions.

The parser handles the original ten sample layouts with regression coverage.
Other layouts may be partial or fail to produce fields; inspect `parsing_warnings`
and verification status before using facts in recommendations. Processing a PDF
successfully does not mean its extraction is complete or accurate.

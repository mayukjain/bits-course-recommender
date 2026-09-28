# Academic data

Run `python constraints.py` from the project root to regenerate this directory.

- `course_catalogue.json`: course codes, titles, units and prerequisites
- `programme_categories.json`: programme CDC/DEL lists and the HUEL pool
- `academic_constraints.json`: regulations, machine-readable rules and source clauses
- `timetable.json`: offerings, sections, rooms, meeting times and exam slots
- `extraction_report.json`: extraction totals

Extracted records include their source document and page where available.
`extracted_unverified` means the value was read from a source but was not manually
checked. Rules marked `manual_review` are not automatically treated as satisfied.

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


COURSE_CODE = re.compile(
    r"\b([A-Z]{2,8})\s+([A-Z])\s*(\d{3}[A-Z]?(?:-\d+)?)\b"
)
CLAUSE_ID = re.compile(r"\b(\d+\.\d+(?:\s+[IVX]+|[a-z])?)\s*$")


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_code(value: str) -> str | None:
    match = COURSE_CODE.search(value.upper().replace("_", " "))
    return f"{match.group(1)} {match.group(2)}{match.group(3)}" if match else None


def pdf_pages(path: Path) -> list[str]:
    if not shutil.which("pdftotext"):
        raise RuntimeError("Poppler pdftotext is required for academic-data extraction")
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.split("\f")


def evidence(document: str, page: int, section: str, text: str) -> dict[str, Any]:
    return {
        "source_document": document,
        "pdf_page": page,
        "section": section,
        "supporting_text": compact(text),
        "verification_status": "extracted_unverified",
    }


def extract_regulation_clauses(path: Path) -> list[dict[str, Any]]:
    """Extract every numbered Academic Regulations clause, including subclauses."""
    found: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for page_number, page in enumerate(pdf_pages(path), 1):
        for raw_line in page.splitlines():
            line = raw_line.rstrip()
            match = CLAUSE_ID.search(line)
            if match:
                clause_id = compact(match.group(1))
                leading = line[: match.start()].strip()
                if current:
                    current["text"] = compact(" ".join(current.pop("lines")))
                    found.append(current)
                current = {
                    "clause_id": clause_id,
                    "pages": [page_number],
                    "lines": [leading] if leading else [],
                    "source_document": path.name,
                    "verification_status": "extracted_unverified",
                }
            elif current:
                if page_number not in current["pages"]:
                    current["pages"].append(page_number)
                stripped = line.strip()
                if stripped and not re.fullmatch(r"\d+", stripped):
                    current["lines"].append(stripped)
    if current:
        current["text"] = compact(" ".join(current.pop("lines")))
        found.append(current)
    return found


def typed_regulation_rules(clauses: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize only rules whose numeric meaning is explicit in the source."""
    by_id = {row["clause_id"]: row for row in clauses}
    specs = [
        ("1.01", "semester_unit_limit", {"first_degree": 25, "higher_degree": 20}),
        ("1.03", "summer_limit", {"maximum_courses": 3, "maximum_units": 10}),
        ("2.08", "additional_elective_limit", {"first_degree": 4}),
        ("2.10", "practice_school_exclusive", {"exclusive_registration": True}),
        ("2.10", "thesis_16_exclusive", {"thesis_units": 16, "exclusive_registration": True}),
        ("2.10", "thesis_9_concurrent_limit", {"thesis_units": 9, "maximum_other_courses": 3, "maximum_other_units": 9}),
    ]
    rules = []
    for clause_id, kind, parameters in specs:
        source = by_id.get(clause_id)
        if source:
            rules.append({
                "rule_id": f"regulation_{clause_id.replace('.', '_')}_{kind}",
                "kind": kind,
                "parameters": parameters,
                "scope": "as stated in source clause",
                "source": source,
                "verification_status": "extracted_unverified",
            })
    return rules


def constraint_registry(
    clauses: list[dict[str, Any]], machine_rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Represent every source clause in code, defaulting to manual review."""
    automated = {rule["source"]["clause_id"] for rule in machine_rules}
    return [
        {
            "rule_id": f"regulation_{row['clause_id'].replace('.', '_').replace(' ', '_')}_{index}",
            "kind": "source_clause",
            "clause_id": row["clause_id"],
            "automation": "partially_automated" if row["clause_id"] in automated else "manual_review",
            "text": row["text"],
            "source": {
                "source_document": row["source_document"],
                "pages": row["pages"],
                "verification_status": row["verification_status"],
            },
        }
        for index, row in enumerate(clauses, 1)
    ]


def extract_bulletin_courses(path: Path) -> list[dict[str, Any]]:
    """Build a normalized catalogue and retain prerequisite statements as evidence."""
    courses: dict[str, dict[str, Any]] = {}
    pages = pdf_pages(path)
    row_tail = re.compile(
        r"^\s*(?P<title>[A-Za-z][A-Za-z0-9&()/',.\- ]{1,}?)"
        r"\s{2,}(?P<units>\d{1,2})(?:\*|\s|$)"
    )
    prereq = re.compile(r"Pre[- ]?requisites?\s*:\s*(.+)", re.I)
    last_codes: list[str] = []
    for page_number, page in enumerate(pages, 1):
        for line in page.splitlines():
            code_matches = list(COURSE_CODE.finditer(line))
            if code_matches:
                last_codes = []
                for index, code_match in enumerate(code_matches):
                    segment_end = code_matches[index + 1].start() if index + 1 < len(code_matches) else len(line)
                    segment = line[code_match.end():segment_end]
                    match = row_tail.match(segment)
                    if not match:
                        continue
                    code = normalize_code(code_match.group())
                    if not code:
                        continue
                    title = compact(match.group("title")).strip("-– ")
                    item = courses.setdefault(code, {
                        "course_code": code,
                        "title": title,
                        "units": int(match.group("units")),
                        "prerequisite_expression": None,
                        "prerequisite_course_codes": [],
                        "restrictions": [],
                        "sources": [],
                    })
                    if len(title) > len(item["title"]):
                        item["title"] = title
                    item["sources"].append(evidence(
                        path.name, page_number, "course catalogue/programme table",
                        line[code_match.start():segment_end],
                    ))
                    last_codes.append(code)
            prerequisite = prereq.search(line)
            if prerequisite and last_codes:
                statement = compact(prerequisite.group(1))
                codes = [normalize_code(m.group()) for m in COURSE_CODE.finditer(statement)]
                for code in last_codes:
                    item = courses[code]
                    item["prerequisite_expression"] = statement
                    item["prerequisite_course_codes"] = list(dict.fromkeys(c for c in codes if c))
                    item["sources"].append(evidence(path.name, page_number, "prerequisite", line))
    description_header = re.compile(
        r"^\s*(?P<code>[A-Z]{2,8}\s+[A-Z]\s*\d{3}[A-Z]?)\s+"
        r"(?P<title>.*?)\s{2,}(?P<credits>\d{1,3}\*?)\s*$"
    )
    for page_number, page in enumerate(pages, 1):
        if "Course Description" not in page and not any(
            re.search(r"Pre[- ]?requisites?\s*:", line, re.I)
            for line in page.splitlines()
        ):
            continue
        width = max((len(line) for line in page.splitlines()), default=0)
        midpoint = width // 2
        columns = [[], []]
        for line in page.splitlines():
            columns[0].append(line[:midpoint])
            columns[1].append(line[midpoint:])
        for column in columns:
            current_code: str | None = None
            pending_prerequisite: list[str] | None = None
            for raw_line in column:
                line = raw_line.strip()
                header = description_header.match(raw_line)
                course_start = COURSE_CODE.match(line)
                if course_start and not header:
                    if current_code and pending_prerequisite:
                        statement = compact(" ".join(pending_prerequisite))
                        item = courses.get(current_code)
                        if item:
                            item["prerequisite_expression"] = statement
                            item["prerequisite_course_codes"] = list(dict.fromkeys(
                                normalize_code(match.group())
                                for match in COURSE_CODE.finditer(statement)
                                if normalize_code(match.group())
                            ))
                            item["sources"].append(evidence(
                                path.name, page_number,
                                "course description prerequisite", statement,
                            ))
                    current_code = normalize_code(course_start.group())
                    pending_prerequisite = None
                    continue
                if header:
                    if current_code and pending_prerequisite:
                        statement = compact(" ".join(pending_prerequisite))
                        item = courses.get(current_code)
                        if item:
                            item["prerequisite_expression"] = statement
                            item["prerequisite_course_codes"] = list(dict.fromkeys(
                                normalize_code(match.group())
                                for match in COURSE_CODE.finditer(statement)
                                if normalize_code(match.group())
                            ))
                    current_code = normalize_code(header.group("code"))
                    pending_prerequisite = None
                    continue
                prerequisite = prereq.search(line)
                if prerequisite and current_code:
                    pending_prerequisite = [prerequisite.group(1)]
                elif pending_prerequisite is not None and line and not description_header.match(raw_line):
                    pending_prerequisite.append(line)
            if current_code and pending_prerequisite:
                statement = compact(" ".join(pending_prerequisite))
                item = courses.get(current_code)
                if item:
                    item["prerequisite_expression"] = statement
                    item["prerequisite_course_codes"] = list(dict.fromkeys(
                        normalize_code(match.group())
                        for match in COURSE_CODE.finditer(statement)
                        if normalize_code(match.group())
                    ))
                    item["sources"].append(evidence(
                        path.name, page_number, "course description prerequisite", statement
                    ))
    return sorted(courses.values(), key=lambda item: item["course_code"])


def extract_programme_categories(path: Path) -> dict[str, Any]:
    """Extract first-degree CDC/DEL lists and the institute-wide HUEL pool."""
    pages = pdf_pages(path)
    starts = [i for i, page in enumerate(pages) if
              "List of Courses for B.E. / M.Sc. / B.Pharm." in page and "CORE COURSES" in page]
    if not starts:
        return {"programmes": {}, "huel": [], "source_document": path.name}
    start = starts[-1]
    programmes: dict[str, dict[str, Any]] = {}
    current_programme: str | None = None
    current_category: str | None = None
    heading_buffer: list[str] = []
    huel: dict[str, dict[str, Any]] = {}
    in_huel = False
    huel_finished = False
    programme_heading = re.compile(r"^[A-Z][A-Z &().,/\-]+$")

    for page_number, page in enumerate(pages[start:], start + 1):
        lines = page.splitlines()
        width = max((len(line) for line in lines), default=0)
        midpoint = width // 2
        columns = ([line[:midpoint] for line in lines], [line[midpoint:] for line in lines])
        for column in columns:
            for raw in column:
                line = compact(raw).strip("*")
                if not line:
                    continue
                if "Pool of Humanities courses for first degree" in line and not huel_finished:
                    in_huel = True
                    current_category = "HUEL"
                    continue
                if in_huel:
                    if line == "Other Courses":
                        in_huel = False
                        huel_finished = True
                        current_category = None
                        continue
                    match = COURSE_CODE.search(line)
                    if match and (code := normalize_code(match.group())):
                        huel.setdefault(code, evidence(path.name, page_number,
                            "Pool of Humanities courses for first degree programmes", raw))
                    continue
                if line.startswith("CORE COURSES"):
                    candidates = [value for value in heading_buffer[-4:] if programme_heading.fullmatch(value)
                                  and value not in {"DISCIPLINE ELECTIVE COURSES", "CORE COURSES"}]
                    if candidates:
                        current_programme = compact(" ".join(candidates))
                        programmes.setdefault(current_programme, {"CDC": [], "DEL": []})
                    current_category = "CDC"
                    heading_buffer.clear()
                    continue
                if line.startswith("DISCIPLINE ELECTIVE COURSES"):
                    current_category = "DEL"
                    heading_buffer.clear()
                    continue
                if line.startswith("Project Type Courses"):
                    current_category = None
                    continue
                if programme_heading.fullmatch(line) and not COURSE_CODE.search(line):
                    heading_buffer.append(line)
                    continue
                match = COURSE_CODE.search(line)
                if current_programme and current_category in {"CDC", "DEL"} and match:
                    code = normalize_code(match.group())
                    if code and not any(row["course_code"] == code for row in programmes[current_programme][current_category]):
                        programmes[current_programme][current_category].append({
                            "course_code": code,
                            "source": evidence(path.name, page_number, f"{current_programme} {current_category}", raw),
                        })
        if in_huel and "COURSE DESCRIPTIONS" in page:
            break
    return {
        "programmes": programmes,
        "huel": [{"course_code": code, "source": source} for code, source in sorted(huel.items())],
        "opel_policy": "Requires programme/batch-specific academic interpretation; not inferred as every course.",
        "source_document": path.name,
        "verification_status": "extracted_unverified",
    }


def extract_timetable(path: Path) -> dict[str, Any]:
    """Extract primary course offerings plus sections and exam slots."""
    pages = pdf_pages(path)
    offerings: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []
    primary = re.compile(
        r"^\s*(?P<com_code>\d+)\s+"
        r"(?P<course>[A-Z]{2,8}\s+[A-Z]\s*\d{3}[A-Z]?(?:-\d+)?)\s+"
        r"(?P<title>.*?)\s{2,}"
        r"(?P<L>\d+|-)\s+(?P<P>\d+|-)\s+(?P<T>\d+|-)\s+(?P<S>\d+|-)\s+"
        r"(?P<U>\d+|-)\s+(?P<section>[LPT]\d+)\s*(?P<rest>.*)$"
    )
    exam = re.compile(r"(?P<date>\d{2}/\d{2})\s+(?P<session>FN1|FN2|AN1|AN2|FN|AN)\b")
    section_line = re.compile(r"^.{70,}?(?P<section>[LPT]\d+)\s+(?P<tail>.+)$")
    current_code: str | None = None
    current_computer_code: int | None = None
    for page_number, page in enumerate(pages, 1):
        for line in page.splitlines():
            match = primary.match(line)
            if not match:
                continuation = section_line.match(line)
                if continuation and current_code:
                    tail = compact(continuation.group("tail"))
                    cancelled = bool(re.search(r"CANC?ELLED", tail, re.I))
                    room = re.search(r"\b([1-7]\d{3})\b", tail)
                    meeting = re.search(
                        r"\b(?:M|T|W|Th|F|S)(?:\s*(?:M|T|W|Th|F|S))*\s+"
                        r"(?:\d{1,2}(?:\s+\d{1,2})*)\b",
                        tail,
                    )
                    sections.append({
                        "course_code": current_code,
                        "computer_code": current_computer_code,
                        "section": continuation.group("section"),
                        "room": room.group(1) if room else None,
                        "meeting_text": meeting.group() if meeting else None,
                        "cancelled": cancelled,
                        "raw_text": tail,
                        "source": evidence(path.name, page_number, "II. Coursewise Timetable section", line),
                    })
                continue
            rest = match.group("rest")
            exams = list(exam.finditer(rest))
            cancelled = "CANCLED" in rest.upper() or "CANCELLED" in rest.upper()
            course_code = normalize_code(match.group("course"))
            current_code = course_code
            current_computer_code = int(match.group("com_code"))
            room = re.search(r"\b([1-7]\d{3})\b", rest)
            meeting = re.search(
                r"\b(?:M|T|W|Th|F|S)(?:\s*(?:M|T|W|Th|F|S))*\s+"
                r"(?:\d{1,2}(?:\s+\d{1,2})*)\b",
                rest,
            )
            offering = {
                "computer_code": int(match.group("com_code")),
                "course_code": course_code,
                "title": compact(match.group("title")),
                "credits": {
                    key.lower(): 0 if match.group(key) == "-" else int(match.group(key))
                    for key in ("L", "P", "T", "S", "U")
                },
                "section": match.group("section"),
                "room": room.group(1) if room else None,
                "meeting_text": meeting.group() if meeting else None,
                "cancelled": cancelled,
                "restricted_to_2026_admissions": int(match.group("com_code")) >= 5000,
                "midsem": ({"date": exams[0].group("date"), "session": exams[0].group("session")} if exams else None),
                "compre": ({"date": exams[1].group("date"), "session": exams[1].group("session")} if len(exams) > 1 else None),
                "raw_tail": compact(rest),
                "source": evidence(path.name, page_number, "II. Coursewise Timetable", line),
            }
            offerings.append(offering)
            sections.append({
                "course_code": course_code,
                "computer_code": int(match.group("com_code")),
                "section": match.group("section"),
                "room": offering["room"],
                "meeting_text": offering["meeting_text"],
                "cancelled": cancelled,
                "raw_text": compact(rest),
                "source": offering["source"],
            })
    return {
        "term": "FIRST SEMESTER 2026-27",
        "campus": "Pilani",
        "session_times": {
            "FN1": "09:00-10:30", "FN2": "11:00-12:30",
            "AN1": "14:00-15:30", "AN2": "16:00-17:30",
            "FN": "09:00-12:00", "AN": "14:00-17:00",
        },
        "offerings": offerings,
        "sections": sections,
        "source_document": path.name,
    }


def extract_timetable_rules(path: Path) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    in_registration = False
    current: dict[str, Any] | None = None
    for page_number, page in enumerate(pdf_pages(path), 1):
        for line in page.splitlines():
            if (
                "INSTRUCTIONS REGARDING REGISTRATION" in line.upper()
                and line.strip() == line.strip().upper()
            ):
                in_registration = True
                continue
            if in_registration and re.match(r"\s*VIII\.", line):
                if current:
                    current["text"] = compact(" ".join(current.pop("lines")))
                    rules.append(current)
                return rules
            if not in_registration:
                continue
            match = re.match(r"\s*(\d+)\.\s+(.+)", line)
            if match:
                if current:
                    current["text"] = compact(" ".join(current.pop("lines")))
                    rules.append(current)
                current = {
                    "rule_id": f"timetable_registration_{match.group(1)}",
                    "kind": "registration_instruction",
                    "automation": "manual_review",
                    "lines": [match.group(2)],
                    "source": {"source_document": path.name, "pdf_page": page_number,
                               "section": "VII. Instructions Regarding Registration"},
                }
            elif current and line.strip():
                current["lines"].append(line.strip(" "))
    return rules


def extract_equivalent_courses(path: Path) -> list[dict[str, Any]]:
    """Extract equivalence groups from timetable section IX."""
    groups: list[dict[str, Any]] = []
    active = False
    for page_number, page in enumerate(pdf_pages(path), 1):
        if "IX." in page and "LIST OF EQUIVALENT COURSES" in page:
            active = True
        if active and "X." in page and "Library" in page:
            break
        if not active:
            continue
        for line in page.splitlines():
            matches = [normalize_code(match.group()) for match in COURSE_CODE.finditer(line)]
            codes = list(dict.fromkeys(code for code in matches if code))
            if len(codes) >= 2:
                groups.append({
                    "canonical_course": codes[0],
                    "equivalent_courses": codes,
                    "source": evidence(path.name, page_number, "IX. List of Equivalent Courses", line),
                })
    return groups


@dataclass
class StudentState:
    degree_level: str
    completed_courses: set[str]
    admission_year: int | None = None


@dataclass
class PlannedCourse:
    course_code: str
    units: int
    computer_code: int | None = None


def evaluate_constraints(
    student: StudentState,
    planned: list[PlannedCourse],
    catalogue: dict[str, dict[str, Any]],
    offerings: list[dict[str, Any]],
    existing_units: int = 0,
) -> list[dict[str, Any]]:
    """Run deterministic rules; unresolved source rules remain outside this function."""
    findings: list[dict[str, Any]] = []
    limit = 25 if student.degree_level == "first_degree" else 20
    units = existing_units + sum(course.units for course in planned)
    if units > limit:
        findings.append({"rule": "semester_unit_limit", "status": "failed", "actual": units, "limit": limit, "source_clause": "1.01"})
    offered = {(row["course_code"], row["computer_code"]): row for row in offerings}
    offered_codes = {row["course_code"] for row in offerings if not row["cancelled"]}
    for course in planned:
        code = normalize_code(course.course_code) or course.course_code
        if code not in offered_codes:
            findings.append({"rule": "currently_offered", "status": "failed", "course_code": code})
        row = offered.get((code, course.computer_code)) if course.computer_code else None
        if row and row["cancelled"]:
            findings.append({"rule": "not_cancelled", "status": "failed", "course_code": code})
        if row and row["restricted_to_2026_admissions"] and student.admission_year != 2026:
            findings.append({"rule": "admission_year_restriction", "status": "failed", "course_code": code})
        item = catalogue.get(code)
        if item:
            missing = sorted(set(item.get("prerequisite_course_codes", [])) - student.completed_courses)
            if missing:
                findings.append({"rule": "prerequisites", "status": "failed", "course_code": code, "missing": missing})
            elif item.get("prerequisite_expression") and not item.get("prerequisite_course_codes"):
                findings.append({"rule": "prerequisites", "status": "manual_review", "course_code": code,
                                 "reason": item["prerequisite_expression"]})
    return findings


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def build_all(root: Path) -> dict[str, Any]:
    output = root / "academic_data"
    output.mkdir(exist_ok=True)
    regulations = extract_regulation_clauses(root / "Academic-Regulations-2023.pdf")
    rules = typed_regulation_rules(regulations)
    courses = extract_bulletin_courses(root / "bulletin.pdf")
    programme_categories = extract_programme_categories(root / "bulletin.pdf")
    timetable = extract_timetable(root / "timetable.pdf")
    timetable_rules = extract_timetable_rules(root / "timetable.pdf")
    equivalents = extract_equivalent_courses(root / "timetable.pdf")
    current_titles: dict[str, str] = {}
    for offering in timetable["offerings"]:
        if offering["title"] and len(offering["title"]) > len(current_titles.get(offering["course_code"], "")):
            current_titles[offering["course_code"]] = offering["title"]
    for course in courses:
        if course["course_code"] in current_titles:
            course["title"] = current_titles[course["course_code"]]
    constraints = {
        "schema_version": 1,
        "regulation_clauses": regulations,
        "machine_rules": rules,
        "rule_registry": constraint_registry(regulations, rules) + timetable_rules,
        "equivalent_course_groups": equivalents,
        "unresolved_rule_policy": "manual_review",
        "source_documents": ["Academic-Regulations-2023.pdf", "bulletin.pdf", "timetable.pdf"],
    }
    write_json(output / "course_catalogue.json", courses)
    write_json(output / "programme_categories.json", programme_categories)
    write_json(output / "academic_constraints.json", constraints)
    write_json(output / "timetable.json", timetable)
    report = {
        "regulation_clauses": len(regulations),
        "machine_rules": len(rules),
        "catalogue_courses": len(courses),
        "programme_category_maps": len(programme_categories["programmes"]),
        "humanities_elective_courses": len(programme_categories["huel"]),
        "timetable_offerings": len(timetable["offerings"]),
        "cancelled_offerings": sum(row["cancelled"] for row in timetable["offerings"]),
        "timetable_sections": len(timetable["sections"]),
        "timetable_registration_rules": len(timetable_rules),
        "equivalent_course_groups": len(equivalents),
    }
    write_json(output / "extraction_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract catalogue, regulations and timetable constraints")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(build_all(args.root.resolve()), indent=2))


if __name__ == "__main__":
    main()

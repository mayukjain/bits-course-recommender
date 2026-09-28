import os
import re
import json
import shutil
import subprocess
import argparse

from handout_preferences import enrich_handout
from handout_quality import validate_record, build_report


def get_match(pattern, text):
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return m.group(1).strip() if m else None


def clean_field(value):
    if not value:
        return None

    value = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", value)

    value = re.sub(r"^[\s:\-–]+", "", value)
    value = re.sub(r"[\s:\-–]+$", "", value)

    return value.strip()

EVALUATION_HEADING = r"(?:(?:Evaluation|Examination|Assessment)[ /]+(?:Schemes?(?: and Schedule)?|Schedule|Pattern|Components?|Grading|Plan|Criteria)(?=[ \t]*(?::|\(|\*|\.|$|[ \t]{2,}Duration))|Evaluation(?=[ \t]*(?::|$)))"
WEIGHT_HEADER = r"(?:Weight(?:age|ag|s)?|Weitage|Weighatge|Weigh(?=\b)|Wt(?:g)?\.?|Percentage)\b"


def clean_layout(text):
    """Blank page furniture without moving characters or PDF page boundaries."""
    pages = []
    for page in text.split("\f"):
        lines = page.splitlines(keepends=True)
        nonempty = [i for i, line in enumerate(lines) if line.strip()]
        edge = set(nonempty[:5] + nonempty[-3:])
        for i, line in enumerate(lines):
            stripped = line.strip()
            furniture = re.match(
                r"^(?:BIRLA INSTITUTE|Pilani Campus|PILANI CAMPUS|AUGS\s*/|AGSR Division|"
                r"Academic (?:Undergraduate|Graduate) Studies|Please Do Not Print|\[Type here\])", stripped, re.I
            )
            page_number = i in edge and re.fullmatch(r"(?:Page\s+)?\d+(?:\s+of\s+\d+)?", stripped, re.I)
            if furniture or page_number:
                lines[i] = re.sub(r"[^\r\n]", " ", line)
        pages.append("".join(lines))
    return "\f".join(pages)


SCOPE_HEADING = r"Scope\s*(?:and|&)\s*Objectives?(?: of (?:the |this )?Course)?"
SECTION_HEADINGS = (
    rf"Course Description|{SCOPE_HEADING}|"
    r"Course Learning Outcomes?|Text\s*Books?|Reference(?: Books?|s)?|"
    rf"Course Plan|Lecture Plan|Lab Manual|{EVALUATION_HEADING}|"
    r"Academic Conduct Policy|Grading Policy|Criterion for NC(?: and Grading Policy)?|"
    r"NC Criteria|Chamber Consultation(?: Hours?)?|Instructor Consultation|"
    r"Make[-\s]*up Policy|Attendance Policy|Attendance(?=[ \t]*(?::|$))|"
    r"(?:Course )?Notices?|Announcements?(?: and Notices)?|Others|Notes?(?:\s*\(if any\))?|"
    r"(?:Office |Chamber )?Consultation Hours?|List of Experiments|General|"
    r"Academic Honesty|Disciplinary Policy|Malpractices|NC Criterion|Important Note|"
    r"Mid[- ]semester [Gg]rading|Grading Procedure|Minimum (?:Passing|Criteria|criterion)|"
    r"Important Course Policies|Prerequisites|Pre-requisites|Office consultation|"
    r"Mid[- ]Semester Evaluation|Marks Distribution|Reading assignments|Open Book Policy|"
    r"Lab(?=:[ \t])|Labs(?=:[ \t])|Project(?=:[ \t])|"
    r"Assignments?\(s\)(?=:[ \t])|Course Outcomes|Learning Outcomes"
)


def compact(text):
    return re.sub(r"\s+", " ", text).strip()


def extract_section(text, heading):
    is_evaluation = heading == r"Evaluation Scheme"
    if is_evaluation:
        heading = EVALUATION_HEADING
        specific = EVALUATION_HEADING.split("|Evaluation(?=")[0] + ")"
        if re.search(r"^[ \t]*(?:\d+[.):]?[ \t]*)?" + specific, text, re.I | re.M):
            heading = specific
    prefix = r"^[ \t]*(?:\d+(?:\.\d+)*[.):][ \t]*|\d+[ \t]+|[IVX]+[.)][ \t]*)?"
    start = re.search(
        prefix + rf"(?:{heading})\b[ \t]*:?[ \t]*",
        text, re.IGNORECASE | re.MULTILINE
    )
    if not start:
        return None
    remaining = text[start.end():]
    boundaries = SECTION_HEADINGS.replace(EVALUATION_HEADING + "|", "") if is_evaluation else SECTION_HEADINGS
    end_prefix = prefix.replace("[ \t]*", "[ \t]{0,24}", 1)
    end = re.compile(
        end_prefix + rf"(?:{boundaries})\b|"
        r"^[ \t]*\(?Instructor[- \t]*in[- \t]*charge"
        r"(?:[ \t,()]*(?:[A-Z]{2,8}[ \t]*[A-Z]\d{3})?\)?)[ \t]*$",
        re.IGNORECASE | re.MULTILINE
    ).search(remaining, 1)
    section = remaining[:end.start()] if end else remaining
    if "make" in heading.lower():
        section = re.split(r"\n[ \t]*\n(?=[ \t]{15,}\S)", section)[0]
    return section.strip("\r\n") if section.strip() else None


def component_type(name):
    if re.search(r"\bmid[-. ]*(?:sem|semester|term)\b", name, re.I) and re.search(r"\b(?:report|seminar|presentation|project)\b", name, re.I) and not re.search(r"\b(?:exam|examination|test)\b", name, re.I):
        return "presentation" if re.search(r"seminar|presentation", name, re.I) else "project"
    patterns = [
        ("midsem", r"\bmid[-.\s]*(?:semester|sem|term)\b"),
        ("compre", r"\bcompre"),
        ("case_study", r"\bcase stud"),
        ("project", r"\bproject"),
        ("viva", r"\bviva"),
        ("quiz", r"\bquiz"),
        ("assignment", r"\bassignment"),
        ("presentation", r"\b(?:presentation|seminar)"),
        ("lab", r"\blab"),
        ("participation", r"\bclass participation"),
        ("test", r"\btest"),
    ]
    return next((kind for kind, pattern in patterns
                 if re.search(pattern, name, re.IGNORECASE)), "other")


def assessment_value_fields(value, block):
    """Keep marks distinct from percentages in all fallback table readers."""
    header_lines = []
    for line in block.splitlines():
        if re.search(r"Component|Duration|Date|Marks|Weight|Percentage", line, re.I):
            header_lines.append(line)
        if len(header_lines) >= 3:
            break
    header = "\n".join(header_lines)
    marks_only = bool(re.search(r"\bMarks\b", header, re.I)) and not re.search(WEIGHT_HEADER + r"|%", header, re.I)
    if not marks_only:
        return {"weight": value, "marks": None, "weight_basis": "weight_column",
                "declared_total_marks": None}
    total = re.search(r"\bMarks\s*\((\d+(?:\.\d+)?)\)|"
                      r"\bTotal Marks\s*:\s*(\d+(?:\.\d+)?)", header, re.I)
    declared = float(next(g for g in total.groups() if g is not None)) if total else None
    if declared is not None and declared <= 0:
        declared = None
    return {"weight": round(value * 100 / declared, 6) if declared else None,
            "marks": value, "weight_basis": "declared_marks_total" if declared else "marks_only",
            "declared_total_marks": declared}


def parse_simple_weight_table(block):
    """Parse aligned Component/Weightage tables whose values are raw marks."""
    lines = block.splitlines()
    header_index = next(
        (
            index for index, line in enumerate(lines)
            if re.search(r"\bComponent\b", line, re.I)
            and re.search(r"\b(?:Weightage|Weight|Marks)\b", line, re.I)
        ),
        None,
    )
    if header_index is None:
        return []

    rows = []
    row_pattern = re.compile(
        r"^\s*(?P<name>.+?)\s{2,}(?P<marks>\d+(?:\.\d+)?)\s{2,}(?P<details>.+?)\s*$"
    )
    for line in lines[header_index + 1:]:
        if not line.strip():
            if rows:
                break
            continue
        if re.match(
            r"^\s*(?:Total|Notes?|The evaluation|Please|Criterion|"
            r"Evaluation will|Grading will)\b",
            line,
            re.I,
        ):
            break
        match = row_pattern.match(line)
        if not match:
            continue
        name = compact(match.group("name")).rstrip(":*-")
        if not name or re.fullmatch(r"(?:total|marks?)", name, re.I):
            continue
        rows.append({
            "row_number": len(rows) + 1,
            "name": name,
            "type": component_type(name),
            **assessment_value_fields(float(match.group("marks")), block),
            "raw_text": compact(line),
        })
    return rows


def parse_indexed_weight_rows(block):
    """Recover rows from numbered tables whose columns were flattened by PDF text."""
    rows = []
    current = None
    pending = None
    orphan_label = None
    for line in block.splitlines():
        start = re.match(r"^\s*(?:\d+[.)]|[ivxlcdm]+[.)])\s*(.*)$", line, re.I)
        if start:
            current = compact(start.group(1))
            pending = current
            if re.match(r"^\d+(?:\.\d+)?\b", current) and orphan_label:
                value_match = re.match(r"(\d+(?:\.\d+)?)\s+(.*)", current)
                if value_match:
                    name = orphan_label
                    value = float(value_match.group(1))
                    rows.append({
                        "row_number": len(rows) + 1,
                        "name": name,
                        "type": component_type(name),
                        **assessment_value_fields(value, block),
                        "raw_text": compact(line),
                    })
                    pending = None
                orphan_label = None
            continue
        if pending and line.strip() and not re.match(
            r"^\s*(?:Total|Notes?|The evaluation)\b", line, re.I
        ):
            pending = compact(pending + " " + line)
            numbers = list(re.finditer(r"(?<![A-Za-z])\d+(?:\.\d+)?", pending))
            if numbers:
                value = float(numbers[0].group())
                name = compact(pending[:numbers[0].start()]).rstrip(":*-") or current
                if name:
                    rows.append({
                        "row_number": len(rows) + 1,
                        "name": name,
                        "type": component_type(name),
                        **assessment_value_fields(value, block),
                        "raw_text": compact(line),
                    })
                pending = None
        elif line.strip() and not re.match(
            r"^\s*(?:Total|Notes?|The evaluation)\b", line, re.I
        ):
            orphan_label = compact(line)
    return rows


def parse_loose_assessment_rows(block):
    """Handle flattened tables where duration and weight share one text line."""
    rows = []
    pattern = re.compile(
        r"^\s*(?P<name>(?:Tut(?:orial)?|Mid[.\- ]?Sem(?:ester)?|"
        r"Comprehensive|Quiz|Assignment|Project|Lab)\b[^0-9\n]*?)"
        r"\s+(?:\d+(?:\.\d+)?\s*(?:min(?:utes?)?|hour(?:s?)?|h)\.?\s*)?"
        r"(?P<weight>\d+(?:\.\d+)?(?:\s*[*#+]\s*\d+(?:\.\d+)?){0,2})"
        r"\s*[*#]?(?=\s|$)",
        re.I,
    )
    for line in block.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", match.group("weight"))]
        name = compact(match.group("name")).rstrip(":*-")
        if not values or not name:
            continue
        rows.append({
            "row_number": len(rows) + 1,
            "name": name,
            "type": component_type(name),
            "weight": sum(values),
            "marks": None,
            "weight_basis": "weight_column",
            "declared_total_marks": None,
            "raw_text": compact(line),
        })
    return rows


def parse_multiline_weight_rows(block):
    """Recover common evaluation rows when PDF extraction separates name and weight."""
    rows = []
    pending_name = None
    name_pattern = re.compile(
        r"^\s*(?:\d+\s+)?(?P<name>"
        r"(?:Mid\.?\s*Sem\.?(?:ester)?\s*Test|"
        r"Comprehensive(?:\s+Examination)?|"
        r"Continuous Assessment(?: of [^0-9]+)?|"
        r"(?:Class )?Participation|"
        r"(?:Lab|Laboratory)(?: Component| Related Activities)?|"
        r"(?:Final )?(?:Report|Seminar|Viva)|"
        r"(?:Tutorial )?Quiz(?:zes)?|"
        r"(?:Project|Assignment)[^0-9]*)"
        r")",
        re.I,
    )
    for line in block.splitlines():
        stripped = compact(line)
        if not stripped:
            continue
        name_match = name_pattern.match(line)
        if name_match:
            pending_name = compact(name_match.group("name")).rstrip(":*-")
        if not pending_name:
            continue
        values = re.findall(r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*%?", stripped)
        if not values:
            continue
        value = float(values[0])
        if value > 100:
            continue
        if re.search(r"(?:marks?|minutes?|hours?|week|date|202\d)", stripped, re.I):
            weights = [float(v) for v in values if float(v) <= 100]
            if not weights:
                continue
            value = weights[0]
        if value <= 0:
            continue
        if any(row["name"].lower() == pending_name.lower() for row in rows):
            continue
        rows.append({
            "row_number": len(rows) + 1,
            "name": pending_name,
            "type": component_type(pending_name),
            "weight": value,
            "marks": None,
            "weight_basis": "weight_column",
            "declared_total_marks": None,
            "raw_text": stripped,
        })
        pending_name = None
    return rows


def parse_numbered_percentage_rows(block):
    """Parse numbered tables where each row's percentage is on a later line."""
    chunks = re.split(r"(?=^\s*\d+[.)]\s*)", block, flags=re.M)
    rows = []
    for chunk in chunks:
        if not re.match(r"^\s*\d+[.)]\s*", chunk):
            continue
        percentages = re.findall(r"(\d+(?:\.\d+)?)\s*%", chunk)
        if len(percentages) != 1:
            continue
        value = float(percentages[0])
        first_line = compact(chunk.splitlines()[0])
        name = re.sub(r"^\d+[.)]\s*", "", first_line)
        name = re.sub(r"\s+\d+(?:\.\d+)?\s*(?:min|mins|minutes?|hours?|h)\b.*$", "", name, flags=re.I)
        name = re.sub(r"\s+\d+(?:\.\d+)?\s*$", "", name)
        name = compact(name).rstrip(":*-")
        if not name or value > 100:
            continue
        rows.append({
            "row_number": len(rows) + 1,
            "name": name,
            "type": component_type(name),
            "weight": value,
            "marks": None,
            "weight_basis": "explicit_percentage",
            "declared_total_marks": None,
            "raw_text": compact(chunk),
        })
    return rows


def parse_flat_weight_rows(block):
    """Parse rows with a component, duration, and raw weight in one line."""
    rows = []
    pattern = re.compile(
        r"^\s*(?P<name>.+?)\s+"
        r"(?:\d+(?:\.\d+)?\s*(?:min(?:utes?)?|hour(?:s?)?|h)\.?\s+|NA\s+)"
        r"(?P<weight>\d+(?:\.\d+)?(?:\s*[*#]\s*\d+(?:\.\d+)?){0,2})"
        r"\s*[*#]?(?:\s|$)",
        re.I,
    )
    for line in block.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        name = compact(match.group("name")).rstrip(":*-")
        values = [float(v) for v in re.findall(r"\d+(?:\.\d+)?", match.group("weight"))]
        if not name or not values:
            continue
        rows.append({
            "row_number": len(rows) + 1,
            "name": name,
            "type": component_type(name),
            "weight": sum(values),
            "marks": None,
            "weight_basis": "weight_column",
            "declared_total_marks": None,
            "raw_text": compact(line),
        })
    return rows


def parse_named_weight_rows(block):
    """Recover assessment rows whose fixed-width columns were flattened."""
    start = re.compile(
        r"^\s*(?:\d+[.)]?\s*)?(?P<name>"
        r"(?:Mid(?:[- ]?Semester|[- ]?Sem|[- ]?Term)?|"
        r"Comprehensive(?: Examination)?|"
        r"(?:Surprise )?Quiz(?:zes)?|"
        r"Attendance(?:[- ]based)?(?: evaluation)?|"
        r"(?:Class )?Participation|"
        r"(?:Lab|Laboratory)(?: Component| Evaluation| Performance)?|"
        r"(?:Final )?Project|"
        r"(?:Minor )?projects?|"
        r"(?:Case )?Stud(?:y|ies)|"
        r"(?:Research|Development) related (?:Report|Presentation)|"
        r"(?:Continuous )?Assessment|"
        r"(?:Tutorial|Tut)(?:s|orials)?|"
        r"(?:Experiment|Exp(?:eriment)?\.?) Report|"
        r"Seminar|Assignment)"
        r"\b.*?)(?=$|\d)",
        re.I,
    )
    rows = []
    for line in block.splitlines():
        match = start.match(line)
        if not match:
            continue
        name = compact(match.group("name")).rstrip(":*-")
        if not name or re.search(r"\btotal\b", name, re.I):
            continue
        tail = line[match.end():]
        tail = re.sub(r"\b\d{1,4}[-/]\d{1,2}(?:[-/]\d{1,4})?\b", " ", tail)
        tail = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", tail)
        tail = re.sub(
            r"\b\d+(?:\.\d+)?(?:\s*(?:-|to)\s*\d+(?:\.\d+)?)?\s*"
            r"(?:min(?:ute)?s?|hrs?|hours?|h|weeks?)\b\.?", " ", tail, flags=re.I
        )
        tail = re.sub(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|"
            r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"\s+\d{1,2}(?:,?\s+\d{4})?\b", " ", tail, flags=re.I
        )
        percentages = re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%", tail)
        numbers = re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])", tail)
        value = float(percentages[0]) if len(percentages) == 1 else (
            float(numbers[0]) if not percentages and len(numbers) == 1 else None
        )
        if value is None or value <= 0 or value > 100:
            continue
        rows.append({
            "row_number": len(rows) + 1,
            "name": name,
            "type": component_type(name),
            **({"weight": value, "marks": None, "weight_basis": "explicit_percentage",
                "declared_total_marks": None} if percentages else assessment_value_fields(value, block)),
            "raw_text": compact(line),
        })
    return rows


def parse_evaluation(text):
    """Read fixed-width layout columns; never infer a weight from a duration."""
    text = clean_layout(text)
    text = re.sub(r"\bWeigh\s*\n", "Weight\n", text, flags=re.I)
    block = extract_section(text, r"Evaluation Scheme")
    if not block:
        block = extract_section(text, EVALUATION_HEADING)
    if block and (
        "Evaluative Component" not in block
        or not re.search(r"\b(?:Component|Assessment)\b", block, re.I)
    ) and (
        extract_section(text, r"Evaluation(?=[ \t]*:)") or ""
    ).find("Evaluative Component") >= 0:
        block = extract_section(text, r"Evaluation(?=[ \t]*:)") 
    elif block and not (
        re.search(r"\b(?:Component|Assessment)\b", block, re.I)
        and re.search(r"\b(?:Weightage|Weight|Marks)\b", block, re.I)
    ):
        alternate = extract_section(text, r"Evaluation(?=[ \t]*:)")
        if alternate and re.search(r"\b(?:Component|Assessment)\b", alternate, re.I):
            block = alternate
    if not block:
        return []
    lines = block.translate(str.maketrans({"[": " ", "]": " "})).splitlines()
    header_index = None
    weight_center = None
    duration_start = None
    marks_column = False
    declared_total = None
    header_candidates = []
    for index, line in enumerate(lines[:30]):
        for pattern, is_marks in ((WEIGHT_HEADER, False), (r"\bMarks\b", True)):
            header = re.search(pattern, line, re.I)
            if not header:
                continue
            nearby = "\n".join(lines[index:min(index + 3, len(lines))])
            table_header = re.search(
                r"Component|Duration|Date|Remarks|Modules|Indicators", nearby, re.I
            )
            short_header = len(compact(line)) < 30 and not re.search(r"[():].*\w{5}", line)
            if (table_header or short_header) and not (line.lstrip().startswith("(") and len(compact(line)) > 40) and not re.match(r"\s*Total [Mm]arks\s*:", line):
                header_candidates.append((is_marks, index, header))
    if header_candidates:
        marks_column, header_index, header = min(header_candidates, key=lambda item: (item[0], item[1]))
        line = lines[header_index]
        weight_center = (header.start() + header.end()) / 2
        if marks_column:
            total = re.search(r"Marks\s*\(\s*(\d+)\s*\)", line, re.I)
            if not total and header_index + 1 < len(lines):
                total = re.search(r"^\s*\((\d+)\)", lines[header_index + 1])
            if not total:
                total = re.search(r"total (?:score|marks)\s*(?:of|out of|:)?\s*(\d{2,4})\b", text, re.I)
            declared_total = float(total.group(1)) if total else None
        for header_line in lines[max(0, header_index - 1):header_index + 1]:
            duration = re.search(r"Duration", header_line, re.I)
            if duration:
                duration_start = duration.start()
    if header_index is None:
        bullet_rows = []
        for line in block.splitlines():
            match = re.match(r"^\s*[●•*-]\s*(\d+(?:\.\d+)?)\s*%\s+(.+)", line)
            if match:
                name = match.group(2).strip().rstrip(":")
                bullet_rows.append({"row_number": len(bullet_rows) + 1, "name": name,
                                    "type": component_type(name), "weight": float(match.group(1)),
                                    "marks": None, "declared_total_marks": None, "raw_text": line.strip()})
        return bullet_rows or parse_indexed_weight_rows(block)

    number_cell = re.compile(
        r"(?<!\S)(?:\d+(?:\.\d+)?[ \t]+\([ \t]*\d+(?:\.\d+)?[ \t]*%[ \t]*\)|"
        r"\d+(?:\.\d+)?[ \t]*%(?:[ \t]+\(\d+[ \t]*M?\))?|"
        r"\d+(?:\.\d+)?(?:[ \t]*\+[ \t]*\d+(?:\.\d+)?)*(?:[ \t]+\(\d+[ \t]*(?:M|[Mm]arks)\))?)(?!\S)"
    )
    duration_cell = re.compile(
        r"\b(?:\d+(?:\.\d+)?[ \t]*(?:minutes?|mins?\.?|hours?|hrs?\.?|h)\b|"
        r"Variable\b|Surprise\b|During tutorial\b)|(?<!\S)-(?!\S)", re.I
    )
    table_lines = []
    first_column_starts = []
    for line in lines[header_index + 1:]:
        if re.match(r"^\s*(?:The evaluation apart|Please\b|Criterion\b|NC Criteria\b|Notes?\s*:|(?:Course )?Total\b|Tentative Schedule|The concerned supervisor)", line, re.I):
            break
        if re.search(r"\bTotal\s+\d+(?:%|\s|$)", line, re.I):
            break
        if re.match(r"^\s*[*#$†]", line) and not re.fullmatch(r"[ \t]{15,}[*#$†][ \t]*", line) and not re.match(r"^\s*[*#$]?(?:Quiz|Assignment|Project|Class Participation|Lab)\b", line, re.I):
            break
        duration_spans = [m.span() for m in duration_cell.finditer(line)]
        candidates = [
            m for m in number_cell.finditer(line)
            if abs((m.start() + m.end()) / 2 - weight_center) <= 18
            and not any(start <= m.start() < end for start, end in duration_spans)
            and ("%" in m.group() or m.start() == 0 or len(line[:m.start()]) - len(line[:m.start()].rstrip()) >= 2)
        ]
        match = min(candidates, key=lambda m: abs((m.start() + m.end()) / 2 - weight_center)) if candidates else None
        if not match:
            percentages = [m for m in number_cell.finditer(line) if "%" in m.group()]
            if len(percentages) == 1 and re.search(r"[A-Za-z]", line[:percentages[0].start()]):
                match = percentages[0]
        if not match and re.match(
            r"\s*(?:Mid|Comprehensive|Quiz|Assignment|Project|Lab|Class)\b",
            line,
            re.I,
        ):
            marks_cells = [
                m for m in number_cell.finditer(line)
                if re.search(r"\b[Mm]arks?\b", m.group())
            ]
            if len(marks_cells) == 1:
                match = marks_cells[0]
        weight = None
        if match:
            if re.match(r"^\s*[*#$†]", line) and re.search(r"\b(?:will|shall|may|must|each)\b", line, re.I):
                break
            percent = re.search(r"(\d+(?:\.\d+)?)\s*%", match.group())
            weight = float(percent.group(1)) if percent else sum(float(n) for n in re.findall(r"\d+(?:\.\d+)?", match.group().split("(")[0]))
            if duration_start is not None and duration_start < weight_center:
                durations = [m for m in duration_cell.finditer(line)
                             if m.start() < match.start() and abs(m.start() - duration_start) <= 12]
                if durations:
                    first_column_starts.append(durations[-1].start())
            else:
                first_column_starts.append(match.start())
        table_lines.append((line, match, weight))
    label_right = min(first_column_starts) if first_column_starts else duration_start
    if label_right is None:
        return parse_simple_weight_table(block) or parse_indexed_weight_rows(block)

    header_mode = re.search(r"\bMode\b", lines[header_index], re.I)
    if header_mode:
        label_right = min(label_right, header_mode.start())
    records = []
    pending = []
    current = None
    start_pattern = re.compile(
        r"^(?:Mid[- ]*(?:Semester|Sem)|Comprehensive|"
        r"(?:Course |Surprise )?Quiz(?:zes|\(zes\))?|"
        r"(?:Practical )?Assignment|Class Participation|"
        r"(?:Tutorial )?Lab|(?:Course )?Project|Case Stud|Viva|Presentation|In-class)\b",
        re.I
    )
    for line, weight_match, weight in table_lines:
        if not line.strip():
            continue
        label = re.sub(r"^\s*(?:\d+[.)]?\s+|[*#$])", "", line[:label_right]).strip()
        label = re.sub(r"\s+-\s*$", "", label)
        starts = bool(start_pattern.search(label))
        combined = current and (
            current["name"].rstrip().endswith(("/", "and", "&", "+", "including", "final"))
            or current["name"].count("(") > current["name"].count(")")
            or component_type(current["name"]) == "other"
            or ("/" in current["name"] and label.islower())
            or (current["name"].lower().endswith("semester") and label.lower() == "presentation")
        )
        if (starts and pending and compact(" ".join(pending)).lower() != "in-class"
                and not pending[-1].rstrip().endswith(("/", "&", "+", "and"))):
            records.append({"name": compact(" ".join(pending)), "weight": None,
                            "raw_lines": pending[:]})
            pending = []
        if weight is not None:
            name = compact(" ".join(pending + ([label] if label else [])))
            pending = []
            current = {"name": name, "weight": weight, "raw_lines": [line.strip()],
                       "explicit_percent": bool(weight_match and "%" in weight_match.group()),
                       "value_text": weight_match.group() if weight_match else None}
            records.append(current)
        elif starts and not combined:
            pending.append(label)
            current = None
        elif current:
            if label:
                current["name"] = compact(current["name"] + " " + label)
            current["raw_lines"].append(line.strip())
        elif label and pending:
            pending.append(label)

    if pending:
        records.append({"name": compact(" ".join(pending)), "weight": None,
                        "raw_lines": pending[:]})
    components = []
    for record in records:
        name = record["name"]
        if not name:
            continue
        value_text = record.get("value_text") or ""
        inline_marks = None
        if record.get("explicit_percent"):
            leading = re.match(r"(\d+(?:\.\d+)?)\s+\(\s*\d+(?:\.\d+)?\s*%", value_text)
            trailing = re.search(r"%\s*\((\d+(?:\.\d+)?)\s*(?:M|[Mm]arks)?\)", value_text)
            match_marks = leading or trailing
            inline_marks = float(match_marks.group(1)) if match_marks else None
        components.append({
            "row_number": len(components) + 1,
            "name": name,
            "type": component_type(name),
            "weight": (round(record["weight"] * 100 / declared_total, 6)
                       if marks_column and not record.get("explicit_percent") and declared_total and record["weight"] is not None
                       else None if marks_column and not record.get("explicit_percent") else record["weight"]),
            "marks": record["weight"] if marks_column and not record.get("explicit_percent") else inline_marks,
            "weight_basis": "explicit_percentage" if record.get("explicit_percent") else "declared_marks_total" if marks_column and declared_total else "marks_only" if marks_column else "weight_column",
            "declared_total_marks": declared_total,
            "raw_text": compact(" ".join(record["raw_lines"]))
        })
    named = parse_named_weight_rows(block)
    current_total = sum(row["weight"] or 0 for row in components)
    named_total = sum(row["weight"] or 0 for row in named)
    if named and abs(named_total - 100) <= 0.1 and abs(current_total - 100) > 0.1:
        return named
    indexed = parse_indexed_weight_rows(block)
    loose = parse_loose_assessment_rows(block)
    if indexed and (
        len(indexed) > len(components)
        or (len(indexed) == len(components) and sum(row["weight"] or 0 for row in indexed) == 100)
    ):
        return indexed
    simple = parse_simple_weight_table(block)
    if components:
        return components
    multiline = parse_multiline_weight_rows(block)
    candidates = [candidate for candidate in (simple, indexed, loose, multiline) if candidate]
    return max(candidates, key=len, default=[])


def extract_pdf_text(pdf_path):
    """Preserve fixed-width columns using Poppler, or positioned PyMuPDF words."""
    if shutil.which("pdftotext"):
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True, capture_output=True, text=True, encoding="utf-8"
        )
        return result.stdout
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("Install Poppler (pdftotext) or PyMuPDF to read PDFs.") from exc
    pages = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            words = sorted(page.get_text("words"), key=lambda word: (word[1], word[0]))
            rows = []
            for word in words:
                if not rows or abs(word[1] - rows[-1][0]) > 3:
                    rows.append((word[1], [word]))
                else:
                    rows[-1][1].append(word)
            rendered = []
            for _, row in rows:
                line = ""
                for word in sorted(row, key=lambda item: item[0]):
                    column = round(word[0] / 4)
                    line += " " * max(1, column - len(line)) + word[4]
                rendered.append(line)
            pages.append("\n".join(rendered))
    return "\f".join(pages)


def parse_metadata(text, pdf_path):
    header = re.split(r"^\s*1[.)]\s*(?:Course Description|Scope)", text, maxsplit=1, flags=re.M | re.I)[0]
    header = header[:5000]
    code_pattern = r"([A-Z]{2,8}(?:\s*/\s*[A-Z]{2,8})*)[ _]*([A-Z])\s*(\d{3}[A-Z]?(?:-\d+)?)"
    code_lines = [line for line in header.splitlines() if re.search(r"Course\s*(?:No\.?|Number|Code)", line, re.I)]
    codes = []
    for line in code_lines:
        for m in re.finditer(code_pattern, line, re.I):
            for department in re.split(r"\s*/\s*", m.group(1)):
                code = f"{department.upper()} {m.group(2).upper()}{m.group(3).upper()}"
                if code not in codes:
                    codes.append(code)
    title = None
    title_match = re.search(r"^\s*Course\s*(?:Title|Name|(?:Number|No\.?)\s*(?:&|and)\s*Title)\s*:?\s*([^\n]+)", header, re.I | re.M)
    if title_match:
        title = clean_field(re.sub(code_pattern, "", title_match.group(1), flags=re.I))
    if not title:
        alternate = re.search(r"^[ \t]*(?:Name|Title) of (?:the )?[Cc]ourse[ \t]*:[ \t]*([^\n]+)", header, re.I | re.M)
        title = clean_field(alternate.group(1)) if alternate else None
    instructor = None
    match = re.search(r"^[ \t]*Instructors?(?:\(s\)|[- \t]*in[- \t]*charge)?[ \t]*:?[ \t]*([^\n]+)", header, re.I | re.M)
    if match:
        instructor = match.group(1).strip()
        tail = header[match.end():].splitlines()[1:]
        for line in tail:
            if not line.strip() or re.search(r"^\s*(?:\d+[.)]|Office|Telephone|Email|Team|Course|Lecture|Tutorial|Instructor)", line, re.I):
                break
            if re.search(r"\bProf\.|\bDr\.", line):
                instructor += " " + line.strip()
            else:
                break
        instructor = clean_field(re.sub(r"\([^)]*@[^)]*\)|\[[^\]]*@[^\]]*(?:\]|$)", "", instructor))
    return {"course_codes": codes, "title": title, "instructor": instructor}


def parse_handout(raw_text, pdf_path):
    raw_text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", raw_text)
    raw_text = clean_layout(raw_text)
    original_text = raw_text
    raw_text = raw_text.replace("\f", "\n")
    clean_text = compact(raw_text)


    course_no = get_match(
        r"Course\s*(?:No\.?|Number)\s*:?\s*"
        r"("
        r"[A-Z]{2,8}\s*[_ ]?\s*[A-Z]\d{3}[A-Z]?(?:-\d+)?"
        r"(?:\s*/\s*[A-Z]{2,8}\s*[_ ]?\s*[A-Z]\d{3}[A-Z]?(?:-\d+)?)*"
        r")",
        clean_text
    )

    course_codes = []

    if course_no:

        for code in course_no.split("/"):

            code = re.sub(
                r"[_\s]+",
                " ",
                code
            ).strip()

            course_codes.append(code)



    if not course_codes:

        filename = os.path.basename(pdf_path)

        match = re.match(
            r"\d+_([A-Z]+)_([A-Z]\d{3}[A-Z]?)",
            filename,
            flags=re.IGNORECASE
        )

        if match:

            course_codes = [
                f"{match.group(1).upper()} {match.group(2).upper()}"
            ]



    course_title = get_match(
        r"Course\s*(?:Title|Name)\s*:?\s*(.*?)"
        r"(?=\s+(?:"
        r"Instructor[-\s]*in[-\s]*charge|"
        r"Instructor\(s\)|"
        r"Instructors?|"
        r"Course Description"
        r")\s*:?)",
        clean_text
    )

    course_title = clean_field(course_title)



    instructor = get_match(
    r"(?:"
    r"Instructor[-\s]*in[-\s]*charge|"
    r"Instructor\(s\)|"
    r"Instructors?"
    r")\s*:?\s*(.*?)"
    r"(?=\s+(?:"
    r"Instructor[-\s]*in[-\s]*charge|"
    r"Instructor\(s\)|"
    r"Instructors?|"
    r"Tutorial/Practical Instructors?|"
    r"Co[-\s]*Instructor|"
    r"Team of|"
    r"Lecture|"
    r"Office\s*:|"
    r"Telephone|"
    r"Email\s*:|"
    r"Google Classroom Code|"
    r"\d+\.\s*Course Description|"
    r"Course Description|"
    r"\d+\.\s*Scope and Objective|"
    r"Scope and Objective"
    r"))",
    clean_text
)

    if instructor:

        instructor = re.sub(
            r"\([^)]*@[^)]*\)|\[[^\]]*@[^\]]*\]",
            "",
            instructor
        )

        instructor = clean_field(instructor)




    metadata = parse_metadata(raw_text, pdf_path)
    course_codes = metadata["course_codes"] or course_codes
    course_title = metadata["title"] or course_title
    instructor = metadata["instructor"] or instructor

    scope_text = extract_section(raw_text, SCOPE_HEADING)
    description_text = extract_section(raw_text, r"Course Description")
    scope = compact(scope_text) if scope_text else None
    description = compact(description_text) if description_text else None
    policy_text = extract_section(raw_text, r"Make[-\s]*up Policy")
    makeup_policy = compact(policy_text) if policy_text else None
    evaluation_components = parse_evaluation(raw_text)

    weights = [
        component["weight"]
        for component in evaluation_components
    ]

    total_weight = (
        sum(weights)
        if weights and all(weight is not None for weight in weights)
        else None
    )

    parsing_warnings = []

    if not scope and re.search(SCOPE_HEADING, raw_text, re.I):
        parsing_warnings.append("Scope heading found but content was not extracted.")
    for field, value in (("title", course_title), ("instructor", instructor)):
        if not value:
            parsing_warnings.append(f"Course {field} was not extracted.")
    if len(compact(raw_text)) < 50:
        parsing_warnings.append("No usable PDF text; OCR or a readable source is required.")

    if not evaluation_components:
        parsing_warnings.append("No evaluation components were extracted.")
    elif total_weight is None:
        parsing_warnings.append("Some evaluation weights were not extracted.")
    elif abs(total_weight - 100) > 0.01:
        parsing_warnings.append(
            f"Evaluation weights total {total_weight}, expected 100."
        )

    data = {
        "course_codes": course_codes,
        "title": course_title,
        "instructor": instructor,
        "scope": scope,
        "description": description,
        "makeup_policy": makeup_policy,
        "evaluation_components": evaluation_components,
        "total_evaluation_weight": total_weight,
        "parsing_warnings": parsing_warnings
    }
    data["evaluation_scheme_text"] = compact(extract_section(raw_text, r"Evaluation Scheme") or "") or None
    data["extraction_status"] = "needs_ocr" if len(compact(raw_text)) < 50 else "partial" if parsing_warnings else "extracted_unverified"
    return validate_record(enrich_handout(data, original_text, pdf_path, extract_section, SCOPE_HEADING), original_text)


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    folder = os.path.join(base_dir, "handouts")
    output_path = os.path.join(base_dir, "temp.json")

    file_paths = sorted(
        os.path.join(folder, filename)
        for filename in os.listdir(folder)
        if filename.lower().endswith(".pdf")
    )

    print("PDF files found:", len(file_paths))

    parser = argparse.ArgumentParser(description="Extract structured handout data.")
    parser.add_argument("--limit", type=int, default=None, help="Process only the first N PDFs (default: all).")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    limit = args.limit
    selected_paths = (
        file_paths if limit is None else file_paths[:limit]
    )

    all_data = []

    for pdf_path in selected_paths:
        try:
            raw_text = extract_pdf_text(pdf_path)
            data = parse_handout(raw_text, pdf_path)
            data["source_file"] = os.path.basename(pdf_path)

            all_data.append(data)

            print(
                data["source_file"],
                "->",
                data["course_codes"],
                "|",
                data["title"],
                "|",
                data["instructor"]
            )

        except Exception as exc:
            all_data.append({
                "source_file": os.path.basename(pdf_path),
                "error": str(exc)
            })
            print(f"Failed: {pdf_path}: {exc}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, indent=4, ensure_ascii=False)

    report_path = os.path.join(base_dir, "extraction_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(build_report(all_data), f, indent=2, ensure_ascii=False)
    print("Processed:", len(all_data))
    print("Quality report:", report_path)


if __name__ == "__main__":
    main()

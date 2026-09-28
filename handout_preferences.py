import os
import re


def compact(text):
    return re.sub(r"\s+", " ", text or "").strip()


TOPIC_PHRASES = (
    "artificial intelligence", "machine learning", "deep learning", "neural networks",
    "natural language processing", "computer vision", "reinforcement learning",
    "data science", "data mining", "algorithms", "data structures", "databases",
    "operating systems", "computer networks", "cybersecurity", "robotics",
    "optimization", "probability", "statistics", "linear algebra", "calculus",
    "aerodynamics", "flight mechanics", "aircraft systems", "propulsion",
    "thermodynamics", "fluid mechanics", "heat transfer", "quantum mechanics",
    "electromagnetism", "signal processing", "control systems", "electronics",
    "genetics", "microbiology", "cell biology", "molecular biology", "biochemistry",
    "biological chemistry", "plant physiology", "animal physiology", "evolution",
    "DNA", "enzymes", "proteins", "carbohydrates", "lipids", "nucleic acids",
    "bioenergetics", "metabolism", "photosynthesis", "biomolecular modeling",
    "molecular modeling", "gene cloning", "recombinant DNA", "biotechnology",
    "economics", "finance", "accounting", "marketing", "psychology", "philosophy",
    "sociology", "literature", "entrepreneurship", "sustainability",
)


def enrich_handout(data, original_text, pdf_path, extract_section, scope_heading):
    text = original_text.replace("\f", "\n")
    filename = os.path.basename(pdf_path)
    sources = {}

    def evidence(excerpt, section, derived=False):
        start = text.find(excerpt) if excerpt else -1
        pages = []
        if start >= 0:
            first = original_text[:start].count("\f") + 1
            last = first + original_text[start:start + len(excerpt)].count("\f")
            pages = list(range(first, last + 1))
        return {
            "source_document": filename,
            "pages": pages,
            "section": section,
            "supporting_text": compact(excerpt) or None,
            "verification_status": (
                "not_found" if not excerpt else
                "needs_verification" if derived or not pages else "extracted"
            ),
        }

    def section_field(key, heading):
        section = extract_section(text, heading)
        sources[key] = evidence(section, heading)
        return compact(section) or None, section

    attendance, attendance_section = section_field("attendance_policy", r"Attendance(?: Policy)?")
    data["attendance_policy"] = attendance
    negative = bool(re.search(
        r"\b(?:no attendance requirement|attendance is (?:not (?:required|mandatory|compulsory|a must)|optional)|"
        r"attendance (?:is )?not compulsory)\b", attendance or "", re.I))
    positive = bool(re.search(
        r"\b(?:attendance (?:is |shall be )?(?:required|mandatory|compulsory|a must)|"
        r"(?:must|required to|expected to) attend (?:all )?(?:classes|lectures))\b",
        attendance or "", re.I))
    data["attendance_required"] = (positive if positive != negative else None)
    minimum = re.search(
        r"(?:at least|minimum(?: of)?|not less than)\s*(\d+(?:\.\d+)?)\s*%",
        attendance or "", re.I)
    data["minimum_attendance_percent"] = float(minimum.group(1)) if minimum else None
    for key in ("attendance_required", "minimum_attendance_percent"):
        sources[key] = evidence(attendance_section, "Attendance", derived=True)
        if data[key] is None:
            sources[key]["verification_status"] = "needs_verification" if attendance else "not_found"

    evaluation = extract_section(text, r"Evaluation Scheme")
    sources["evaluation_components"] = evidence(evaluation, "Evaluation Scheme", derived=True)
    for kind in ("midsem", "compre"):
        present = any(row["type"] == kind for row in data["evaluation_components"])
        exam = r"mid[-\s]*(?:semester|sem)(?:\s+(?:test|exam(?:ination)?))?" if kind == "midsem" else r"comprehensive(?:\s+exam(?:ination)?)?|compre"
        absent = re.search(rf"\bno\s+(?:{exam})\b|\b(?:{exam})\s+(?:will\s+)?(?:not be held|is not conducted)\b", compact(evaluation), re.I)
        value = True if present and not absent else False if absent and not present else None
        key = f"has_{kind}"
        data[key] = value
        sources[key] = evidence(evaluation, "Evaluation Scheme", derived=True)
        if value is None:
            sources[key]["verification_status"] = "needs_verification" if evaluation else "not_found"

    for row in data["evaluation_components"]:
        details = compact(row["name"] + " " + row["raw_text"])
        count = re.search(r"\b(?:quizzes|assignments|projects|tests)\s*\((\d+)\)", row["name"], re.I)
        if not count:
            count = re.search(r"\b(\d+)\s+(?:quizzes|assignments|projects|tests)\b", details, re.I)
        if not count:
            count = re.search(r"\bout of\s+(\d+)\b", details, re.I)
        row["count"] = int(count.group(1)) if count else None
        announced = bool(re.search(r"(?<![\w-])(?:pre[- ]?)?announced\b", details, re.I))
        surprise = bool(re.search(r"\b(?:surprise|unannounced)\b", details, re.I))
        row["announcement"] = "mixed" if announced and surprise else "surprise" if surprise else "announced" if announced else None
        open_book = bool(re.search(r"\b(?:open[- ](?:text)?book|OB)\b", details, re.I))
        closed_book = bool(re.search(r"\b(?:close[ds]?[- ]book|CB)\b", details, re.I))
        if re.search(r"\bclosed?\s*/\s*open[- ]|\bclosed?[- ]book\s*/\s*open\b", details, re.I):
            open_book = closed_book = True
        partial = bool(re.search(r"\bpart(?:ly|ial)\b", details, re.I))
        row["book_policy"] = (
            "mixed" if open_book and closed_book else
            "partly_open" if open_book and partial else
            "partly_closed" if closed_book and partial else
            "open" if open_book else "closed" if closed_book else None
        )
        group = bool(re.search(r"\b(?:group|team)\s+(?:project|assignment|work)|\bin groups\b", details, re.I))
        individual = bool(re.search(r"\bindividual\s+(?:project|assignment|work)\b", details, re.I))
        row["work_mode"] = "group" if group and not individual else "individual" if individual and not group else None
        row["source"] = evidence(evaluation, "Evaluation Scheme", derived=True)

    policy = data.get("makeup_policy")
    policy_section = extract_section(text, r"Make[-\s]*up Policy")
    sources["makeup_policy"] = evidence(policy_section, "Makeup policy")
    statements = [s.strip() for s in re.split(r"(?<=[.!?])\s+", policy or "") if s.strip()]
    conditions = {
        "permitted_assessments": [], "excluded_assessments": [],
        "approval_requirements": [], "accepted_grounds": [], "documentation_requirements": [],
    }
    for sentence in statements:
        if re.search(r"\bno\s+make[- ]?ups?\b|make[- ]?ups?.*\b(?:not|never)\b", sentence, re.I):
            conditions["excluded_assessments"].append(sentence)
        elif re.search(r"make[- ]?ups?.*\b(?:granted|given|conducted|allowed|considered|only)\b", sentence, re.I):
            conditions["permitted_assessments"].append(sentence)
        for key, pattern in (
            ("approval_requirements", r"permission|approval|case[- ]by[- ]case|determined by|decision"),
            ("accepted_grounds", r"genuine|medical|hospital|emergenc"),
            ("documentation_requirements", r"certificat|documents?|request email|application"),
        ):
            if re.search(pattern, sentence, re.I):
                conditions[key].append(sentence)
    data["makeup_conditions"] = {key: value or None for key, value in conditions.items()}
    sources["makeup_conditions"] = evidence(policy_section, "Makeup policy", derived=True)

    topic_sections = [extract_section(text, scope_heading), extract_section(text, r"Course Description")]
    title_match = re.search(r"^[ \t]*Course\s*(?:Title|Name)\s*:?[^\n]*", text, re.I | re.M)
    if title_match:
        topic_sections.append(title_match.group())
    topics = []
    for phrase in TOPIC_PHRASES:
        for section in topic_sections:
            if section and re.search(rf"\b{re.escape(phrase)}\b", section, re.I):
                topics.append({"topic": phrase, "source": evidence(section, "Course description / scope / title", derived=True)})
                break
    data["topics"] = topics
    data["topic_extraction_method"] = "exact_phrase_vocabulary; non-exhaustive"
    sources["topics"] = {
        "source_document": filename,
        "verification_status": "needs_verification" if topics else "not_found",
        "method": data["topic_extraction_method"],
    }

    term = re.search(
        r"\b(First|Second|Summer|I{1,2}|1|2)\s+Semester\s*[,:(-]?\s*(20\d{2})\s*[-–/]\s*(\d{2,4})\b",
        text, re.I
    )
    data["academic_year"] = f"{term.group(2)}-{term.group(3)}" if term else None
    data["semester"] = ({"first": 1, "i": 1, "1": 1, "second": 2, "ii": 2, "2": 2, "summer": "summer"}.get(term.group(1).lower()) if term else None)
    for key in ("academic_year", "semester"):
        sources[key] = evidence(term.group() if term else None, "Semester heading")
    for key, heading in (("scope", scope_heading), ("description", r"Course Description")):
        sources[key] = evidence(extract_section(text, heading), heading)
    for key, heading in (("course_codes", r"Course\s*(?:No\.?|Number)"), ("title", r"Course\s*(?:Title|Name)"), ("instructor", r"Instructors?(?:\(s\)|[- ]*in[- ]*charge)?")):
        match = re.search(rf"^[ \t]*(?:{heading})[^\n]*", text, re.I | re.M)
        sources[key] = evidence(match.group() if match else None, key, derived=True)
    data["source_metadata"] = sources
    data["source_file"] = filename
    data["evaluation_verification_status"] = "needs_verification"
    data["evaluation_weights_sum_to_100"] = data["total_evaluation_weight"] is not None and abs(data["total_evaluation_weight"] - 100) < 0.01
    return data

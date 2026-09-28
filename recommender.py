from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from constraints import PlannedCourse, StudentState, evaluate_constraints, normalize_code


ROOT = Path(__file__).resolve().parent
STOP_WORDS = {
    "a", "an", "and", "are", "course", "courses", "find", "for", "i", "in",
    "is", "me", "need", "of", "on", "prefer", "related", "suggest", "the", "to", "want", "with",
    "del", "dels", "huel", "huels", "opel", "opels", "cdc", "cdcs", "please",
    "no", "without", "quiz", "quizzes", "sugesst", "sugest", "attendance", "requirement",
    "midsem", "mid-sem", "compre", "evaluation", "project", "projects", "project-based",
    "open-book", "makeup", "make-up", "lenient", "small", "low", "lower", "light", "weight",
}
DAY_ALIASES = {
    "m": "Mon", "t": "Tue", "tu": "Tue", "w": "Wed", "th": "Thu", "f": "Fri",
    "s": "Sat", "sa": "Sat", "su": "Sun"
}
DEL_REQUIREMENTS = {
    "BIOTECHNOLOGY": 5,
    "BIOTECHNOLOGY WITH SPECIALIZATION IN APPLIED MOLECULAR BIOLOGY": 5,
    "CHEMICAL ENGINEERING": 5,
    "CHEMICAL ENGINEERING WITH SPECIALIZATION IN ENERGY, ENVIRONMENT, AND SUSTAINABILITY": 5,
    "CHEMISTRY": 4,
    "ECONOMICS": 6,
    "MATHEMATICS": 5,
    "BIOLOGICAL SCIENCES": 4,
    "PHYSICS": 4,
    "PHYSICS WITH SPECIALIZATION IN SPACE SCIENCE AND TECHNOLOGY": 4,
    "SEMICONDUCTOR AND NANOSCIENCE": 7,
}


def _codes(values: list[str]) -> set[str]:
    return {code for value in values if (code := normalize_code(value))}


def _tokens(text: str) -> set[str]:
    words = set()
    for word in re.findall(r"[a-z][a-z0-9+#-]{1,}", text.lower()):
        word = re.sub(r"-related$", "", word)
        if word and word not in STOP_WORDS:
            words.add(word)
    if "ai" in words:
        words.update({"artificial", "intelligence"})
        words.discard("ai")
    if "ml" in words:
        words.update({"machine", "learning"})
        words.discard("ml")
    return words


def parse_query(query: str) -> dict[str, Any]:
    lower = query.lower()
    category = next((name for name in ("cdc", "del", "huel", "opel") if re.search(rf"\b{name}s?\b", lower)), None)
    free_day = None
    for pattern, day in ((r"mondays?", "Mon"), (r"tuesdays?", "Tue"), (r"wednesdays?", "Wed"),
                         (r"thursdays?", "Thu"), (r"fridays?", "Fri"), (r"saturdays?", "Sat")):
        if re.search(pattern, lower) and re.search(r"free|avoid|no class", lower):
            free_day = day
    return {
        "category": category,
        "keywords": sorted(_tokens(query)),
        "no_attendance": bool(re.search(r"no attendance|attendance (?:not required|optional)", lower)),
        "no_quiz": bool(re.search(r"\bno\s+quizz?(?:es)?\b|\bwithout\s+(?:any\s+)?quizz?(?:es)?\b", lower)),
        "no_midsem": bool(re.search(r"no mid[- ]?sem|without (?:a )?mid", lower)),
        "low_midsem": bool(re.search(r"(?:small|low|lower|light)\s+(?:weight(?:age)?\s+)?mid[- ]?sem|mid[- ]?sem.*(?:small|low|lower|light)", lower)),
        "fewer_quizzes": bool(re.search(r"(?:few|fewer|less|minimum)\s+quizz?(?:es)?", lower)),
        "high_project_weight": bool(re.search(r"(?:high|higher|more|maximum)\s+project(?:\s+weight(?:age)?)?|project[- ]based", lower)),
        "low_exam_weight": bool(re.search(r"(?:low|lower|less|minimum)\s+(?:exam|examination)\s+weight", lower)),
        "lenient_makeup": bool(re.search(r"lenient|easy\s+make[- ]?up", lower) and re.search(r"make[- ]?up", lower)),
        "no_compre": bool(re.search(r"no compre|without (?:a )?compre", lower)),
        "project_based": bool(re.search(r"project[- ]based|(?:prefer|with) projects?", lower)),
        "open_book": bool(re.search(r"open[- ]?book", lower)),
        "no_early_classes": bool(re.search(r"no 8\s*(?:am|a\.m\.)|avoid 8\s*(?:am|a\.m\.)|no early", lower)),
        "free_day": free_day,
        "makeup_requested": bool(re.search(r"make[- ]?up", lower)),
    }


def parse_meeting(text: str | None) -> set[tuple[str, int]]:
    if not text:
        return set()
    tokens = re.findall(r"Th|Tu|Sa|Su|M|T|W|F|S|\d{1,2}", text, re.I)
    pending_days: list[str] = []
    slots: set[tuple[str, int]] = set()
    for token in tokens:
        if token.lower() in DAY_ALIASES:
            pending_days.append(DAY_ALIASES[token.lower()])
            continue
        if not pending_days:
            continue
        periods = [int(token)]
        if len(token) == 2 and int(token) > 12 and "0" not in token:
            periods = [int(token[0]), int(token[1])]
        slots.update((day, period) for day in pending_days for period in periods)
        pending_days = []
    return slots


@dataclass
class StudentProfile:
    name: str = "Student"
    campus: str = "Pilani"
    admission_year: int | None = None
    degree: str = ""
    dual_degree: str = ""
    degree_level: str = "first_degree"
    current_semester: str = ""
    current_registered_units: int = 0
    completed_courses: list[str] = field(default_factory=list)
    current_courses: list[str] = field(default_factory=list)
    completed_opel_courses: list[str] = field(default_factory=list)
    minor: str = ""
    interests: list[str] = field(default_factory=list)
    requirement_totals: dict[str, int] = field(default_factory=lambda: {"CDC": 0, "DEL": 0, "HUEL": 0, "OPEL": 0})
    requirement_completed: dict[str, int] = field(default_factory=lambda: {"CDC": 0, "DEL": 0, "HUEL": 0, "OPEL": 0})

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StudentProfile":
        allowed = cls.__dataclass_fields__
        data = {key: value[key] for key in allowed if key in value}
        for key in ("completed_courses", "current_courses", "completed_opel_courses", "interests"):
            if isinstance(data.get(key), str):
                data[key] = [part.strip() for part in data[key].split(",") if part.strip()]
        return cls(**data)

    def remaining_requirements(self) -> dict[str, int]:
        return {kind: max(0, int(self.requirement_totals.get(kind, 0)) - int(self.requirement_completed.get(kind, 0)))
                for kind in ("CDC", "DEL", "HUEL", "OPEL")}


class CourseRecommender:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.catalogue = {row["course_code"]: row for row in self._load("academic_data/course_catalogue.json", [])}
        self.timetable = self._load("academic_data/timetable.json", {})
        self.category_data = self._load("academic_data/programme_categories.json", {"programmes": {}, "huel": []})
        self.policy_data = self._load("academic_data/academic_constraints.json", {})
        self.handouts = self._load("temp.json", [])
        self.handout_by_code: dict[str, dict[str, Any]] = {}
        for handout in self.handouts:
            for code in handout.get("course_codes", []):
                if normalized := normalize_code(code):
                    self.handout_by_code.setdefault(normalized, handout)
        self.offerings: dict[str, list[dict[str, Any]]] = {}
        for row in self.timetable.get("offerings", []):
            self.offerings.setdefault(row["course_code"], []).append(row)
        self.sections: dict[str, list[dict[str, Any]]] = {}
        for row in self.timetable.get("sections", []):
            if not row.get("cancelled"):
                self.sections.setdefault(row["course_code"], []).append(row)

    def _load(self, relative: str, default: Any) -> Any:
        path = self.root / relative
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def stats(self) -> dict[str, Any]:
        return {"catalogue_courses": len(self.catalogue), "current_offerings": len(self.offerings),
                "handouts": len(self.handouts), "term": self.timetable.get("term"),
                "campus": self.timetable.get("campus"),
                "programme_maps": len(self.category_data.get("programmes", {}))}

    @staticmethod
    def _programme_name(degree: str) -> str:
        value = degree.upper().strip()
        value = re.sub(r"^(?:B\.?\s*E\.?|M\.?\s*SC\.?)\s*", "", value)
        return re.sub(r"\s+", " ", value).strip(" .")

    def _category(self, code: str, profile: StudentProfile, requested: str | None) -> tuple[str, dict[str, Any] | None]:
        if not requested:
            return "not_requested", None
        category = requested.upper()
        if category == "HUEL":
            row = next((item for item in self.category_data.get("huel", []) if item["course_code"] == code), None)
            return ("verified", row.get("source")) if row else ("rejected", None)
        if category in {"CDC", "DEL"}:
            wanted = self._programme_name(profile.degree)
            programmes = self.category_data.get("programmes", {})
            programme_name = next((name for name in programmes if self._programme_name(name) == wanted), None)
            if not programme_name:
                return "unknown_programme", None
            row = next((item for item in programmes[programme_name].get(category, []) if item["course_code"] == code), None)
            return ("verified", row.get("source")) if row else ("rejected", None)
        if category == "OPEL":
            analysis = self.requirement_analysis(profile)
            if code in analysis["course_sets"]["CDC"]:
                return "rejected", None
            if code in analysis["course_sets"]["DEL"] and analysis["remaining"]["DEL"] > 0:
                return "rejected", None
            if code in analysis["course_sets"]["HUEL"] and analysis["remaining"]["HUEL"] > 0:
                return "rejected", None
            clause = next((row for row in self.policy_data.get("regulation_clauses", [])
                           if row.get("clause_id") == "2.05"), None)
            source = ({"source_document": clause["source_document"], "pages": clause["pages"],
                       "section": "Clause 2.05"} if clause else None)
            return "verified", source
        return "unknown_policy", None

    def _programme_record(self, degree: str) -> tuple[str | None, dict[str, Any]]:
        wanted = self._programme_name(degree)
        programmes = self.category_data.get("programmes", {})
        name = next((name for name in programmes if self._programme_name(name) == wanted), None)
        return name, programmes.get(name, {}) if name else {}

    def requirement_analysis(self, profile: StudentProfile) -> dict[str, Any]:
        names_and_records = [self._programme_record(profile.degree)]
        if profile.dual_degree:
            names_and_records.append(self._programme_record(profile.dual_degree))
        records = [(name, record) for name, record in names_and_records if name]
        cdc = {row["course_code"] for _, record in records for row in record.get("CDC", [])}
        dels_by_degree = [{row["course_code"] for row in record.get("DEL", [])} for _, record in records]
        dele = set().union(*dels_by_degree) if dels_by_degree else set()
        huel = {row["course_code"] for row in self.category_data.get("huel", [])}
        completed = _codes(profile.completed_courses) | _codes(profile.current_courses)
        totals = {
            "CDC": len(cdc),
            "DEL": sum(DEL_REQUIREMENTS.get(self._programme_name(name or ""), 4) for name, _ in records),
            "HUEL": 3,
            "OPEL": 5,
        }
        completed_counts = {
            "CDC": len(completed & cdc),
            "DEL": sum(min(DEL_REQUIREMENTS.get(self._programme_name(name or ""), 4), len(completed & pool))
                       for (name, _), pool in zip(records, dels_by_degree)),
            "HUEL": len(completed & huel),
            "OPEL": len(_codes(profile.completed_opel_courses)),
        }
        remaining = {kind: max(0, totals[kind] - completed_counts[kind]) for kind in totals}
        return {"totals": totals, "completed": completed_counts, "remaining": remaining,
                "programmes": [name for name, _ in records],
                "course_sets": {"CDC": cdc, "DEL": dele, "HUEL": huel}}

    def _current_slots(self, profile: StudentProfile) -> set[tuple[str, int]]:
        slots: set[tuple[str, int]] = set()
        for code in _codes(profile.current_courses):
            for section in self.sections.get(code, []):
                slots |= parse_meeting(section.get("meeting_text"))
        return slots

    def _eligible(self, code: str, profile: StudentProfile) -> tuple[bool, list[str], list[str], list[dict[str, Any]]]:
        reasons: list[str] = []
        review: list[str] = []
        evidence_rows: list[dict[str, Any]] = []
        completed, current = _codes(profile.completed_courses), _codes(profile.current_courses)
        if code in completed or code in current:
            return False, ["already completed or currently registered"], review, evidence_rows
        for group in self.policy_data.get("equivalent_course_groups", []):
            equivalents = set(group.get("equivalent_courses", []))
            if code in equivalents and (equivalents - {code}) & completed:
                return False, ["an equivalent course is already completed"], review, evidence_rows
        available = [row for row in self.offerings.get(code, []) if not row.get("cancelled")]
        if not available:
            return False, ["not available in the current timetable"], review, evidence_rows
        if all(row.get("restricted_to_2026_admissions") for row in available) and profile.admission_year != 2026:
            return False, ["offering is restricted to the 2026 admission batch"], review, evidence_rows
        item = self.catalogue.get(code, {})
        prerequisites = set(item.get("prerequisite_course_codes", []))
        missing = sorted(prerequisites - completed)
        if missing:
            return False, ["missing prerequisites: " + ", ".join(missing)], review, evidence_rows
        if item.get("prerequisite_expression") and not prerequisites:
            return False, ["prerequisite text cannot be verified deterministically"], review, evidence_rows
        reasons.append("offered this semester")
        evidence_rows.append({"claim": "offered this semester", "status": "supported", "source": available[0].get("source")})
        if prerequisites:
            reasons.append("explicit prerequisites completed")
            prereq_source = next((source for source in item.get("sources", []) if source.get("section") == "prerequisite"),
                                 item.get("sources", [None])[-1] if item.get("sources") else None)
            evidence_rows.append({"claim": "explicit prerequisites completed", "status": "supported", "source": prereq_source})
        return True, reasons, review, evidence_rows

    def recommend(self, profile_value: dict[str, Any], query: str, limit: int = 8,
                  preferences: dict[str, Any] | None = None) -> dict[str, Any]:
        profile = StudentProfile.from_dict(profile_value)
        preferences = preferences or parse_query(query)
        requirements = self.requirement_analysis(profile)
        interest_tokens = _tokens(" ".join(profile.interests))
        query_tokens = set(preferences["keywords"])
        wanted = query_tokens | interest_tokens
        occupied = self._current_slots(profile)
        current_exams: set[tuple[str, str, str]] = set()
        for current_code in _codes(profile.current_courses):
            for row in self.offerings.get(current_code, []):
                for exam_kind in ("midsem", "compre"):
                    exam = row.get(exam_kind)
                    if exam:
                        current_exams.add((exam_kind, exam["date"], exam["session"]))
        results = []
        unknown_counts: dict[str, int] = {}

        for code, rows in self.offerings.items():
            eligible, eligibility, review, claim_evidence = self._eligible(code, profile)
            if not eligible:
                continue
            offering = next(row for row in rows if not row.get("cancelled"))
            exam_clashes = []
            for exam_kind in ("midsem", "compre"):
                exam = offering.get(exam_kind)
                if exam and (exam_kind, exam["date"], exam["session"]) in current_exams:
                    exam_clashes.append(exam_kind)
            if exam_clashes:
                continue
            units = offering.get("credits", {}).get("u") or self.catalogue.get(code, {}).get("units") or 0
            centralized = evaluate_constraints(
                StudentState(profile.degree_level, _codes(profile.completed_courses), profile.admission_year),
                [PlannedCourse(code, units, offering.get("computer_code"))], self.catalogue,
                [row for values in self.offerings.values() for row in values],
                profile.current_registered_units,
            )
            if any(finding.get("status") in {"failed", "manual_review"} for finding in centralized):
                continue
            category_status, category_source = self._category(code, profile, preferences.get("category"))
            if category_status == "rejected":
                continue
            if preferences.get("category") and category_status != "verified":
                continue
            if category_status == "verified":
                eligibility.append(f"verified {preferences['category'].upper()} for {profile.degree}")
                claim_evidence.append({"claim": eligibility[-1], "status": "supported", "source": category_source})
            catalogue = self.catalogue.get(code, {})
            handout = self.handout_by_code.get(code)
            title = offering.get("title") or catalogue.get("title") or code
            descriptive = " ".join(filter(None, [title, handout.get("description") if handout else None,
                                                      handout.get("scope") if handout else None,
                                                      " ".join(topic.get("topic", "") for topic in (handout or {}).get("topics", []))]))
            found = wanted & _tokens(descriptive)
            title_found = wanted & _tokens(title)
            if query_tokens and not (query_tokens & _tokens(descriptive)):
                continue
            score = len(title_found) * 5.0 + len(found - title_found) * 3.0
            matches = [f"matches {', '.join(sorted(found)[:5])}"] if found else []
            unknown = []

            strict_fields = (("no_attendance", "attendance_required", False, "no attendance requirement"),
                             ("no_midsem", "has_midsem", False, "no mid-semester exam"),
                             ("no_compre", "has_compre", False, "no comprehensive exam"))
            rejected = False
            for preference, field_name, desired, label in strict_fields:
                if not preferences[preference]:
                    continue
                actual = handout.get(field_name) if handout else None
                if actual is desired:
                    score += 6
                    matches.append(label + " is explicitly supported")
                    claim_evidence.append({"claim": matches[-1], "status": "supported",
                                           "source": (handout or {}).get("source_metadata", {}).get(field_name)})
                elif actual is None:
                    unknown.append(label)
                    unknown_counts[label] = unknown_counts.get(label, 0) + 1
                    rejected = True
                else:
                    rejected = True
            components = (handout or {}).get("evaluation_components", [])
            midsem_weights = [row["weight"] for row in components if row.get("type") == "midsem" and row.get("weight") is not None]
            quiz_rows_all = [row for row in components if row.get("type") == "quiz" or
                             re.search(r"\bquiz(?:zes|zes|es|z)?\b", row.get("name", ""), re.I)]
            quiz_count = sum(row.get("count") or 1 for row in quiz_rows_all)
            project_weight = sum(row.get("weight") or 0 for row in components if row.get("type") == "project")
            exam_weight = sum(row.get("weight") or 0 for row in components if row.get("type") in {"midsem", "compre"})
            if preferences.get("low_midsem"):
                if not midsem_weights:
                    rejected = True
                else:
                    score += max(0, 40 - min(midsem_weights)) / 4
                    matches.append(f"midsem weight is {min(midsem_weights):g}%")
            if preferences.get("fewer_quizzes"):
                if not handout or not handout.get("evaluation_weights_sum_to_100"):
                    rejected = True
                else:
                    score += max(0, 5 - quiz_count)
                    matches.append(f"{quiz_count} listed quiz component{'s' if quiz_count != 1 else ''}")
            if preferences.get("high_project_weight"):
                if not project_weight:
                    rejected = True
                else:
                    score += project_weight / 5
                    matches.append(f"project weight is {project_weight:g}%")
            if preferences.get("low_exam_weight"):
                if not components:
                    rejected = True
                else:
                    score += max(0, 100 - exam_weight) / 10
                    matches.append(f"listed exam weight is {exam_weight:g}%")
            if preferences.get("lenient_makeup"):
                rejected = True
                unknown.append("makeup-policy leniency")
                unknown_counts["makeup-policy leniency"] = unknown_counts.get("makeup-policy leniency", 0) + 1
            if preferences.get("no_quiz"):
                quiz_rows = [row for row in components if row.get("type") == "quiz" or
                             re.search(r"\bquiz(?:zes|zes|es|z)?\b", " ".join(
                                 [row.get("name", ""), row.get("raw_text", "")]), re.I)]
                complete_scheme = bool(handout and handout.get("extraction_status") == "extracted_unverified"
                                       and handout.get("evaluation_weights_sum_to_100"))
                if quiz_rows or not complete_scheme:
                    rejected = True
                    if not quiz_rows:
                        unknown.append("quiz-free evaluation")
                        unknown_counts["quiz-free evaluation"] = unknown_counts.get("quiz-free evaluation", 0) + 1
                else:
                    score += 6
                    matches.append("no quiz component is listed in the complete evaluation scheme")
                    claim_evidence.append({"claim": matches[-1], "status": "supported",
                                           "source": handout.get("source_metadata", {}).get("evaluation_components")})
            if preferences["project_based"]:
                projects = [row for row in components if row.get("type") == "project" or "project" in row.get("name", "").lower()]
                if projects:
                    score += 5
                    matches.append("project evaluation is listed")
                    claim_evidence.append({"claim": matches[-1], "status": "supported", "source": projects[0].get("source")})
                else:
                    rejected = True
            if preferences["open_book"]:
                if any(row.get("book_policy") in {"open", "partly_open", "mixed"} for row in components):
                    score += 4
                    matches.append("an open-book component is listed")
                    component = next(row for row in components if row.get("book_policy") in {"open", "partly_open", "mixed"})
                    claim_evidence.append({"claim": matches[-1], "status": "supported", "source": component.get("source")})
                else:
                    rejected = True
            if preferences["makeup_requested"]:
                if handout and handout.get("makeup_policy"):
                    score += 1
                    matches.append("make-up policy text is available for review")
                else:
                    unknown.append("make-up policy")

            feasible_sections = []
            for section in self.sections.get(code, []):
                slots = parse_meeting(section.get("meeting_text"))
                if slots & occupied:
                    continue
                if preferences["free_day"] and any(day == preferences["free_day"] for day, _ in slots):
                    continue
                if preferences["no_early_classes"] and any(period == 1 for _, period in slots):
                    continue
                feasible_sections.append(section)
            known_sections = [s for s in self.sections.get(code, []) if parse_meeting(s.get("meeting_text"))]
            if known_sections and not feasible_sections:
                rejected = True
            elif feasible_sections:
                score += 2
                matches.append("a clash-free listed section is available")
                claim_evidence.append({"claim": matches[-1], "status": "supported", "source": feasible_sections[0].get("source")})
            if rejected:
                continue

            if not wanted and not any(preferences.get(k) for k in ("no_attendance", "no_quiz", "no_midsem", "no_compre", "project_based", "open_book")):
                score += 1
            score += math.log1p(max(0, 5 - len(review))) / 10
            results.append({
                "course_code": code, "title": title.title(), "units": offering.get("credits", {}).get("u"),
                "computer_code": offering.get("computer_code"), "score": round(score, 2),
                "requirement": preferences["category"].upper() if preferences["category"] else None,
                "eligibility": eligibility, "matches": matches or ["eligible current offering"],
                "manual_review": review + unknown,
                "policy_findings": centralized,
                "evidence": claim_evidence,
                "sections": [{"section": s.get("section"), "room": s.get("room"), "meeting": s.get("meeting_text")}
                             for s in feasible_sections[:4]],
                "handout": {"attendance_required": handout.get("attendance_required"),
                            "has_midsem": handout.get("has_midsem"), "has_compre": handout.get("has_compre"),
                            "source_file": handout.get("source_file"), "extraction_status": handout.get("extraction_status")}
                           if handout else None,
                "source": offering.get("source"),
            })
        results.sort(key=lambda row: (-row["score"], row["course_code"]))
        return {
            "query": query, "preferences": preferences, "remaining_requirements": requirements["remaining"],
            "requirement_analysis": {key: value for key, value in requirements.items() if key != "course_sets"},
            "recommendations": results[:max(1, min(limit, 25))], "eligible_candidates": len(results),
            "unverified_summary": unknown_counts,
            "notice": ("Requested categories are enforced against the extracted Bulletin programme map. "
                       "If a programme or category cannot be established, the engine returns no category claim."),
        }

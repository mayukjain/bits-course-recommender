from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent import RecommendationAgent
from recommender import CourseRecommender


ROOT = Path(__file__).resolve().parent
PROFILE_FILE = ROOT / "student_profile.json"
REQUIREMENTS = ("CDC", "DEL", "HUEL", "OPEL")


def comma_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def ask(label: str, current: Any = "") -> str:
    suffix = f" [{current}]" if current not in (None, "", [], {}) else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or str(current or "")


def load_profile() -> dict[str, Any]:
    if not PROFILE_FILE.exists():
        return {}
    return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))


def save_profile(profile: dict[str, Any]) -> None:
    PROFILE_FILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")


def edit_profile(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = dict(existing or {})
    print("\nStudent profile\n")
    profile["name"] = ask("Name", profile.get("name", ""))
    profile["campus"] = ask("Campus", profile.get("campus", "Pilani"))
    year = ask("Admission year", profile.get("admission_year", ""))
    profile["admission_year"] = int(year) if year.isdigit() else None
    profile["degree"] = ask("Degree", profile.get("degree", "B.E. Computer Science"))
    profile["dual_degree"] = ask("Dual degree", profile.get("dual_degree", ""))
    profile["degree_level"] = ask(
        "Degree level (first_degree/higher_degree)", profile.get("degree_level", "first_degree")
    )
    profile["current_semester"] = ask("Current semester", profile.get("current_semester", ""))
    units = ask("Currently registered units", profile.get("current_registered_units", 0))
    profile["current_registered_units"] = int(units) if units.isdigit() else 0
    profile["completed_courses"] = comma_list(ask(
        "Completed courses, comma separated", ", ".join(profile.get("completed_courses", []))
    ))
    profile["current_courses"] = comma_list(ask(
        "Current courses, comma separated", ", ".join(profile.get("current_courses", []))
    ))
    profile["minor"] = ask("Minor", profile.get("minor", ""))
    profile["interests"] = comma_list(ask(
        "Interests, comma separated", ", ".join(profile.get("interests", []))
    ))
    totals = dict(profile.get("requirement_totals", {}))
    completed = dict(profile.get("requirement_completed", {}))
    print("\nRequirement counts")
    for kind in REQUIREMENTS:
        total = ask(f"{kind} total", totals.get(kind, 0))
        done = ask(f"{kind} completed", completed.get(kind, 0))
        totals[kind] = int(total) if total.isdigit() else 0
        completed[kind] = int(done) if done.isdigit() else 0
    profile["requirement_totals"] = totals
    profile["requirement_completed"] = completed
    save_profile(profile)
    print(f"\nSaved to {PROFILE_FILE.name}\n")
    return profile


def source_text(source: dict[str, Any] | None) -> str:
    if not source:
        return "source unavailable"
    pages = source.get("pages") or source.get("pdf_page") or "?"
    if isinstance(pages, list):
        pages = ", ".join(map(str, pages))
    section = f", {source['section']}" if source.get("section") else ""
    return f"{source.get('source_document', 'source')}, page {pages}{section}"


def print_result(result: dict[str, Any]) -> None:
    agent = result.get("agent", {})
    print(f"\nParser: {agent.get('intent_provider', 'local')}")
    if agent.get("warning"):
        print(f"Warning: {agent['warning']}")
    preferences = result.get("preferences", {})
    active = [key for key, value in preferences.items() if value not in (False, None, [], "")]
    print("Preferences: " + (", ".join(active) if active else "none"))
    remaining = result.get("remaining_requirements", {})
    print("Remaining: " + ", ".join(f"{key} {remaining.get(key, 0)}" for key in REQUIREMENTS))

    recommendations = result.get("recommendations", [])
    if not recommendations:
        print("\nNo courses satisfy all verified requirements and preferences.\n")
        return

    for index, course in enumerate(recommendations, 1):
        requirement = f" | {course['requirement']}" if course.get("requirement") else ""
        print(f"\n{index}. {course['course_code']} | {course['title']}{requirement}")
        print(f"   Computer code: {course.get('computer_code')} | Units: {course.get('units', '?')}")
        for message in course.get("eligibility", []) + course.get("matches", []):
            print(f"   - {message}")
        for section in course.get("sections", []):
            room = f", room {section['room']}" if section.get("room") else ""
            print(f"   - {section.get('section')}: {section.get('meeting') or 'time unavailable'}{room}")
        if course.get("evidence"):
            print("   Evidence:")
            for item in course["evidence"]:
                print(f"     {item.get('claim')}: {source_text(item.get('source'))}")
    print()


def run_query(agent: RecommendationAgent, profile: dict[str, Any], query: str,
              limit: int, as_json: bool = False) -> None:
    result = agent.run(profile, query, limit)
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_result(result)


def interactive(agent: RecommendationAgent) -> None:
    profile = load_profile()
    if not profile:
        profile = edit_profile()
    while True:
        print("1. Ask for course recommendations")
        print("2. Edit profile")
        print("3. Show data statistics")
        print("4. Exit")
        choice = input("Choice: ").strip()
        if choice == "1":
            query = input("Query: ").strip()
            if query:
                run_query(agent, profile, query, 8)
        elif choice == "2":
            profile = edit_profile(profile)
        elif choice == "3":
            print(json.dumps(agent.engine.stats(), indent=2))
        elif choice in {"4", "q", "quit", "exit"}:
            return
        else:
            print("Invalid choice.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="BITS Academic Course Recommender")
    parser.add_argument("--query", help="Run one recommendation query")
    parser.add_argument("--profile", action="store_true", help="Create or update the student profile")
    parser.add_argument("--json", action="store_true", help="Print query results as JSON")
    parser.add_argument("--limit", type=int, default=8, help="Maximum recommendations")
    args = parser.parse_args()

    agent = RecommendationAgent(CourseRecommender(ROOT))
    profile = load_profile()
    if args.profile:
        profile = edit_profile(profile)
    if args.query:
        if not profile:
            profile = edit_profile()
        run_query(agent, profile, args.query, args.limit, args.json)
        return
    if not args.profile:
        interactive(agent)


if __name__ == "__main__":
    main()

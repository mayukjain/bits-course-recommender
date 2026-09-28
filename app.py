from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import streamlit as st

from agent import RecommendationAgent
from recommender import CourseRecommender

ROOT = Path(__file__).resolve().parent
PROFILE_FILE = ROOT / "student_profile.json"
REQUIREMENTS = ("CDC", "DEL", "HUEL", "OPEL")


def comma_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def load_profile() -> dict[str, Any]:
    if not PROFILE_FILE.exists():
        return {}
    return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))


def save_profile(profile: dict[str, Any]) -> None:
    PROFILE_FILE.write_text(json.dumps(profile, indent=2), encoding="utf-8")


@st.cache_resource
def load_engine() -> CourseRecommender:
    return CourseRecommender(ROOT)


def source_text(source: dict[str, Any] | None) -> str:
    if not source:
        return "Source unavailable"
    pages = source.get("pages") or source.get("pdf_page") or "?"
    if isinstance(pages, list):
        pages = ", ".join(map(str, pages))
    section = f" · {source['section']}" if source.get("section") else ""
    return f"{source.get('source_document', 'source')} · page {pages}{section}"


def profile_form(profile: dict[str, Any]) -> dict[str, Any] | None:
    with st.form("student_profile"):
        first, second = st.columns(2)
        with first:
            name = st.text_input("Name", profile.get("name", ""))
            campuses = ("Pilani", "Goa", "Hyderabad", "Dubai")
            current_campus = profile.get("campus", "Pilani")
            campus = st.selectbox("Campus", campuses, index=campuses.index(current_campus) if current_campus in campuses else 0)
            admission_year = st.number_input("Admission year", 2000, 2035, int(profile.get("admission_year") or 2024))
            degree = st.text_input("Degree", profile.get("degree", "B.E. Computer Science"))
            dual_degree = st.text_input("Dual degree", profile.get("dual_degree", ""))
        with second:
            levels = ("first_degree", "higher_degree")
            degree_level = st.selectbox("Degree level", levels, index=1 if profile.get("degree_level") == "higher_degree" else 0)
            current_semester = st.text_input("Current semester", profile.get("current_semester", ""))
            current_units = st.number_input("Currently registered units", 0, 30, int(profile.get("current_registered_units", 0)))
            minor = st.text_input("Minor", profile.get("minor", ""))
            interests = st.text_input("Interests", ", ".join(profile.get("interests", [])), placeholder="artificial intelligence, economics")

        completed_courses = st.text_area("Completed courses", ", ".join(profile.get("completed_courses", [])), placeholder="CS F111, MATH F111")
        current_courses = st.text_area("Current courses", ", ".join(profile.get("current_courses", [])), placeholder="CS F211, MATH F212")
        st.write("Requirement progress")
        totals = profile.get("requirement_totals", {})
        completed = profile.get("requirement_completed", {})
        requirement_totals: dict[str, int] = {}
        requirement_completed: dict[str, int] = {}
        for column, kind in zip(st.columns(4), REQUIREMENTS):
            with column:
                requirement_totals[kind] = st.number_input(f"{kind} total", min_value=0, value=int(totals.get(kind, 0)), key=f"total_{kind}")
                requirement_completed[kind] = st.number_input(f"{kind} completed", min_value=0, value=int(completed.get(kind, 0)), key=f"done_{kind}")
        submitted = st.form_submit_button("Save profile", use_container_width=True)
    if not submitted:
        return None
    return {
        "name": name, "campus": campus, "admission_year": admission_year,
        "degree": degree, "dual_degree": dual_degree, "degree_level": degree_level,
        "current_semester": current_semester, "current_registered_units": current_units,
        "completed_courses": comma_list(completed_courses), "current_courses": comma_list(current_courses),
        "minor": minor, "interests": comma_list(interests),
        "requirement_totals": requirement_totals, "requirement_completed": requirement_completed,
    }


def show_recommendations(result: dict[str, Any]) -> None:
    remaining = result.get("remaining_requirements", {})
    for column, kind in zip(st.columns(4), REQUIREMENTS):
        column.metric(f"{kind} remaining", remaining.get(kind, 0))
    agent = result.get("agent", {})
    if agent.get("warning"):
        st.warning(agent["warning"])
    st.caption(f"Query parser: {agent.get('intent_provider', 'deterministic')}")
    recommendations = result.get("recommendations", [])
    if not recommendations:
        st.info("No courses satisfy all verified requirements and preferences.")
        return
    for course in recommendations:
        with st.container(border=True):
            requirement = f" · {course['requirement']}" if course.get("requirement") else ""
            st.subheader(f"{course['course_code']} · {course['title']}")
            st.caption(f"Computer code {course.get('computer_code')} · {course.get('units', '?')} units{requirement}")
            for message in course.get("eligibility", []) + course.get("matches", []):
                st.write(f"✓ {message}")
            if course.get("sections"):
                st.write("**Sections**")
                for section in course["sections"]:
                    room = f" · room {section['room']}" if section.get("room") else ""
                    st.write(f"{section.get('section')} · {section.get('meeting') or 'time unavailable'}{room}")
            with st.expander("Sources"):
                for evidence in course.get("evidence", []):
                    st.write(f"**{evidence.get('claim')}**")
                    st.caption(source_text(evidence.get("source")))


def main() -> None:
    st.set_page_config(page_title="BITS Course Recommender", page_icon="🎓", layout="wide")
    st.title("BITS Academic Course Recommender")
    st.caption("Course recommendations from the supplied Bulletin, regulations, timetable and handouts")
    engine = load_engine()
    with st.sidebar:
        st.header("Settings")
        api_key = st.text_input("Gemini API key", type="password", value=os.getenv("GEMINI_API_KEY", ""))
        model = st.text_input("Gemini model", value=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
        stats = engine.stats()
        st.divider()
        st.write(f"Term: {stats.get('term', 'Unknown')}")
        st.write(f"Current offerings: {stats.get('current_offerings', 0)}")
        st.write(f"Handouts: {stats.get('handouts', 0)}")

    profile = load_profile()
    profile_tab, query_tab = st.tabs(("Student profile", "Course search"))
    with profile_tab:
        updated = profile_form(profile)
        if updated is not None:
            save_profile(updated)
            profile = updated
            st.success("Profile saved")
    with query_tab:
        if not profile:
            st.warning("Save a student profile before searching for courses.")
            return
        query = st.text_area("What kind of course are you looking for?", placeholder="Suggest AI DELs with no quiz")
        limit = st.slider("Maximum results", 1, 20, 8)
        if st.button("Find courses", type="primary", use_container_width=True):
            if not query.strip():
                st.warning("Enter a query.")
                return
            if api_key:
                os.environ["GEMINI_API_KEY"] = api_key
            else:
                os.environ.pop("GEMINI_API_KEY", None)
            os.environ["GEMINI_MODEL"] = model
            with st.spinner("Checking courses..."):
                result = RecommendationAgent(engine).run(profile, query.strip(), limit)
            show_recommendations(result)


if __name__ == "__main__":
    main()

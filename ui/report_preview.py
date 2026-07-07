"""ui/report_preview.py — Static preview of the Report screen with mock data.

Run with: streamlit run ui/report_preview.py
"""

import sys
from pathlib import Path  # NOTE: pathlib is not on the approved library list (tech.md)

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st


def main() -> None:
    """Render a static report screen with realistic mock data."""
    st.set_page_config(
        page_title="Report Preview — Mock Interview Stress Tester",
        page_icon="📊",
        layout="centered",
    )

    # --- Mock report data (realistic example) ---
    report: dict = {
        "overall_score": 68,
        "hiring_probability": "Medium",
        "hiring_probability_percent": 68,
        "strongest_category": "System Design",
        "weakest_category": "Behavioral",
        "category_averages": {
            "System Design": 16.5,
            "Coding": 14.0,
            "Behavioral": 11.5,
            "Problem Solving": 13.0,
            "Culture Fit": 13.0,
        },
        "top_3_strengths": [
            "Strong ability to break down complex systems into modular components with clear boundaries",
            "Demonstrated knowledge of distributed systems trade-offs (CAP theorem, consistency models)",
            "Effective use of diagrams and step-by-step walkthroughs to explain architecture decisions",
        ],
        "top_3_improvements": [
            "Behavioral answers lack the STAR format — add specific Situation and measurable Result",
            "Coding solutions skip edge case discussion — explicitly state boundary conditions before coding",
            "Time management during system design — spent too long on storage layer, neglected API design",
        ],
        "critical_moment": "Question 4 (conflict resolution) scored 8/20 — the answer was generic and lacked a specific real-world example. This is a red flag in behavioral rounds at Google.",
        "overall_verdict": "You show solid technical foundations, especially in system design. However, your behavioral answers are a clear weak point that would likely cost you at the onsite stage. Focus on preparing 5-6 STAR-format stories before your interview.",
        "next_interview_tip": "Practice the 'Tell me about a time you disagreed with your manager' question using STAR format. Record yourself and aim for 90 seconds per answer.",
    }

    num_questions: int = 5
    max_score: int = num_questions * 20

    # --- Render the report screen ---
    st.title("📊 Interview Report")

    st.divider()

    # Overall metrics row
    col_score, col_prob = st.columns(2)
    col_score.metric("Overall Score", f"{report['overall_score']}/{max_score}")
    col_prob.metric(
        "Hiring Probability",
        f"{report['hiring_probability']} ({report['hiring_probability_percent']}%)",
    )

    st.divider()

    # Strongest / weakest categories
    col1, col2 = st.columns(2)
    col1.metric("💪 Strongest Category", report["strongest_category"])
    col2.metric("⚠️ Weakest Category", report["weakest_category"])

    st.divider()

    # Category averages
    st.subheader("📈 Category Averages")
    for category, average in report["category_averages"].items():
        col_name, col_bar = st.columns([1, 3])
        col_name.write(f"**{category}**")
        col_bar.progress(average / 20, text=f"{average}/20")

    st.divider()

    # Top 3 strengths
    st.subheader("✅ Top 3 Strengths")
    for i, strength in enumerate(report["top_3_strengths"], 1):
        st.success(f"**{i}.** {strength}")

    # Top 3 improvements
    st.subheader("🔧 Top 3 Areas for Improvement")
    for i, improvement in enumerate(report["top_3_improvements"], 1):
        st.warning(f"**{i}.** {improvement}")

    st.divider()

    # Critical moment
    st.subheader("🚨 Critical Moment")
    st.error(report["critical_moment"])

    st.divider()

    # Overall verdict
    st.subheader("🏆 Overall Verdict")
    st.info(report["overall_verdict"])

    # Next interview tip
    st.subheader("💡 Next Interview Tip")
    st.success(report["next_interview_tip"])

    st.divider()

    # Footer
    st.caption("This is a static preview with mock data. Start a real session for live results.")


if __name__ == "__main__":
    main()

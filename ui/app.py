"""ui/app.py — Streamlit UI for the Mock Interview Stress Tester."""

import streamlit as st

# Orchestrator public API — the ONLY backend interface
from agents.orchestrator import (
    start_session,
    get_current_question,
    submit_answer,
    generate_final_report,
    get_current_state,
)

# Named constants — no magic numbers
from core.config import (
    TOTAL_QUESTIONS,
    MIN_ANSWER_LENGTH,
    WEAK_SCORE_THRESHOLD,
    STRONG_SCORE_THRESHOLD,
    MAX_FOLLOW_UPS,
    HIRING_LOW_MAX,
    HIRING_HIGH_MIN,
    MAX_TOTAL_SCORE,
    STATE_SETUP,
    STATE_RESEARCHING,
    STATE_GENERATING,
    STATE_READY,
    STATE_ASKING,
    STATE_EVALUATING,
    STATE_FOLLOW_UP,
    STATE_NEXT_Q,
    STATE_REPORT,
    STATE_DONE,
    STATE_ERROR,
)

# ---------------------------------------------------------------------------
# INIT BLOCK — All session_state keys initialized here. Idempotent guard.
# ---------------------------------------------------------------------------

if "session_id" not in st.session_state:
    # str | None — UUID returned by start_session; None = no active session
    st.session_state["session_id"] = None

if "error_message" not in st.session_state:
    # str | None — Transient error message for current rerun; cleared on next action
    st.session_state["error_message"] = None

# ---------------------------------------------------------------------------
# SCREEN ROUTING — Determine which screen to render
# ---------------------------------------------------------------------------

_LOADING_STATES: set[str] = {STATE_RESEARCHING, STATE_GENERATING}
_INTERVIEW_STATES: set[str] = {
    STATE_READY, STATE_ASKING, STATE_EVALUATING,
    STATE_FOLLOW_UP, STATE_NEXT_Q,
}
_REPORT_STATES: set[str] = {STATE_REPORT, STATE_DONE}


def _get_active_screen() -> str:
    """Determine which screen to render based on session state."""
    session_id: str | None = st.session_state["session_id"]

    if session_id is None:
        return "setup"

    try:
        state: str = get_current_state(session_id)
    except ValueError:
        st.session_state["session_id"] = None
        st.session_state["error_message"] = (
            "Session is no longer available. Please start a new interview."
        )
        return "setup"

    if state in _LOADING_STATES:
        return "loading"
    elif state in _INTERVIEW_STATES:
        return "interview"
    elif state in _REPORT_STATES:
        return "report"
    elif state == STATE_ERROR:
        return "error"
    else:
        return "setup"


def _reset_session() -> None:
    """Clear session_id and error_message to return to Setup screen."""
    st.session_state["session_id"] = None
    st.session_state["error_message"] = None


def _render_loading_screen() -> None:
    """Render the Loading screen for interrupted session preparation."""
    st.title("Session In Progress")
    st.info(
        "Your interview session is being prepared. "
        "If this screen persists, the session may have been interrupted."
    )
    if st.button("Start New Interview"):
        _reset_session()
        st.rerun()


def _render_setup_screen() -> None:
    """Render the Setup screen with company/role/level form and validation."""
    st.title("Mock Interview Stress Tester")
    st.write("Enter your target company, role, and experience level to begin.")

    # Display any transient error from previous action
    if st.session_state["error_message"]:
        st.error(st.session_state["error_message"])
        st.session_state["error_message"] = None

    # Input fields
    company: str = st.text_input("Company Name", max_chars=200)
    role: str = st.text_input("Role", max_chars=200)
    level: str = st.selectbox(
        "Experience Level",
        options=[
            "Fresher",
            "Junior Engineer",
            "Senior Engineer",
            "Product Manager",
            "Data Scientist",
        ],
    )

    # Submit button
    if st.button("Start Interview"):
        # Client-side validation
        if not company.strip():
            st.error("Please enter a company name.")
            return
        if not role.strip():
            st.error("Please enter a role.")
            return

        # Blocking call with spinner
        with st.spinner("Researching company and generating questions..."):
            try:
                session_id: str = start_session(company, role, level)
                st.session_state["session_id"] = session_id
                st.rerun()
            except Exception:
                st.error("Session creation failed. Please try again.")


def _render_interview_screen(session_id: str) -> None:
    """Render the Interview screen: question display, answer input, evaluation."""
    # Get current state to determine sub-state behavior
    state: str = get_current_state(session_id)

    # Get current question
    try:
        question_dict: dict = get_current_question(session_id)
    except ValueError:
        st.error("Could not load the current question. Please try again.")
        return

    # Display question info (only safe fields: question, category, id)
    st.caption(f"Question {question_dict['id']} of {TOTAL_QUESTIONS}")
    st.caption(f"Category: {question_dict['category']}")
    st.subheader(question_dict["question"])

    # Follow-up indicator
    if state == STATE_FOLLOW_UP:
        st.warning("Follow-up question — expand on your previous answer.")

    # Answer input
    answer: str = st.text_area("Your Answer", max_chars=5000)

    # Submit button
    if st.button("Submit Answer"):
        # Length validation
        if len(answer) < MIN_ANSWER_LENGTH:
            st.error(
                f"Answer must be at least {MIN_ANSWER_LENGTH} characters. "
                f"You entered {len(answer)} characters."
            )
            return

        # Submit to orchestrator
        with st.spinner("Evaluating your answer..."):
            try:
                evaluation: dict = submit_answer(session_id, answer)
            except Exception:
                st.error("Evaluation failed. Please try submitting again.")
                return

        # Display evaluation
        _render_evaluation(evaluation)

        # Follow-up handling
        if "follow_up_question" in evaluation:
            st.warning(evaluation["follow_up_question"])
            st.rerun()
            return

        # State-based navigation
        new_state: str = get_current_state(session_id)
        if new_state == STATE_REPORT:
            st.rerun()
        elif new_state == STATE_NEXT_Q:
            if st.button("Next Question"):
                st.rerun()


def _render_evaluation(evaluation: dict) -> None:
    """Display evaluation scores with color-coded verdict.

    Args:
        evaluation: Evaluation_Dict with scores, total, verdict, and feedback.
    """
    scores: dict = evaluation["scores"]

    # 4 sub-scores in columns
    cols = st.columns(4)
    cols[0].metric("Relevance", f"{scores['relevance']}/5")
    cols[1].metric("Depth", f"{scores['depth']}/5")
    cols[2].metric("Structure", f"{scores['structure']}/5")
    cols[3].metric("Examples", f"{scores['examples']}/5")

    # Total score
    st.metric("Total Score", f"{evaluation['total']}/20")

    # Color-coded verdict
    verdict: str = evaluation["verdict"]
    if verdict == "weak":
        st.error("Verdict: WEAK")
    elif verdict == "good":
        st.warning("Verdict: GOOD")
    else:
        st.success("Verdict: STRONG")

    # Feedback
    st.info(evaluation["feedback"])


def _render_error_screen() -> None:
    """Render the Error screen with message and restart button."""
    st.title("Session Error")
    st.error(
        "This interview session encountered an error and cannot continue. "
        "Please start a new interview."
    )
    if st.button("Start New Interview"):
        _reset_session()
        st.rerun()


def _render_report_screen(session_id: str) -> None:
    """Render the Report screen with full performance breakdown."""
    st.title("Interview Report")

    with st.spinner("Generating your report..."):
        try:
            report: dict = generate_final_report(session_id)
        except Exception:
            st.error("Report generation failed. Please try again.")
            return

    # Overall metrics
    st.metric("Overall Score", f"{report['overall_score']}/{MAX_TOTAL_SCORE}")
    st.metric(
        "Hiring Probability",
        f"{report['hiring_probability']} ({report['hiring_probability_percent']}%)",
    )

    # Strongest / weakest categories
    col1, col2 = st.columns(2)
    col1.metric("Strongest Category", report["strongest_category"])
    col2.metric("Weakest Category", report["weakest_category"])

    # Category averages
    st.subheader("Category Averages")
    for category, average in report["category_averages"].items():
        st.write(f"**{category}:** {average}")

    # Top 3 strengths
    st.subheader("Top 3 Strengths")
    strengths_md = "\n".join(
        f"{i+1}. {' '.join(s.split()).strip()}"
        for i, s in enumerate(report["top_3_strengths"])
    )
    st.markdown(strengths_md)

    # Top 3 improvements
    st.subheader("Top 3 Areas for Improvement")
    improvements_md = "\n".join(
        f"{i+1}. {' '.join(s.split()).strip()}"
        for i, s in enumerate(report["top_3_improvements"])
    )
    st.markdown(improvements_md)

    # Critical moment
    st.info(report["critical_moment"])

    # Overall verdict
    st.write(report["overall_verdict"])

    # Next interview tip
    st.success(report["next_interview_tip"])

    # New session button
    if st.button("Start New Interview"):
        _reset_session()
        st.rerun()


# ---------------------------------------------------------------------------
# MAIN ENTRY POINT — Page config + screen routing
# ---------------------------------------------------------------------------


def main() -> None:
    """Main entry point for the Streamlit UI."""
    st.set_page_config(
        page_title="Mock Interview Stress Tester",
        page_icon="🎯",
        layout="centered",
    )

    screen: str = _get_active_screen()
    session_id: str | None = st.session_state["session_id"]

    if screen == "setup":
        _render_setup_screen()
    elif screen == "loading":
        _render_loading_screen()
    elif screen == "interview":
        _render_interview_screen(session_id)
    elif screen == "report":
        _render_report_screen(session_id)
    elif screen == "error":
        _render_error_screen()


if __name__ == "__main__":
    main()

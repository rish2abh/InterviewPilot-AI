"""ui/app.py — Streamlit UI for the Mock Interview Stress Tester."""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so that `core` and `agents` are importable
# regardless of which directory Streamlit is launched from.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import streamlit as st

# Orchestrator public API — the ONLY backend interface
from agents.orchestrator import (
    start_session,
    get_current_question,
    submit_answer,
    generate_final_report,
    get_current_state,
    get_current_follow_up_text,
)

from core.database import get_session as db_get_session

# Named constants — no magic numbers
from core.config import (
    TOTAL_QUESTIONS,
    MIN_QUESTIONS,
    MAX_QUESTIONS,
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

if "passed_landing" not in st.session_state:
    # bool — Whether the user has clicked "Start" on the landing page
    st.session_state["passed_landing"] = False

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
    # Landing page gate — show landing before anything else
    if not st.session_state["passed_landing"]:
        return "landing"

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
    st.session_state["passed_landing"] = False


def _get_landing_css() -> str:  # Consider splitting this function
    """Return the full CSS block for the landing page animations and styling."""
    return """<style>
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(30px); }
    to { opacity: 1; transform: translateY(0); }
}
@keyframes float {
    0%, 100% { transform: translateY(0px); }
    50% { transform: translateY(-12px); }
}
@keyframes glow {
    0%, 100% { box-shadow: 0 0 5px rgba(139, 92, 246, 0.3); }
    50% { box-shadow: 0 0 25px rgba(139, 92, 246, 0.6); }
}
@keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
}
@keyframes typewriter {
    from { width: 0; }
    to { width: 100%; }
}
@keyframes blink {
    0%, 100% { border-color: transparent; }
    50% { border-color: #a78bfa; }
}
@keyframes slideIn {
    from { opacity: 0; transform: translateX(-20px); }
    to { opacity: 1; transform: translateX(0); }
}
@keyframes particle-drift {
    0% { transform: translateY(0) rotate(0deg); opacity: 1; }
    100% { transform: translateY(-80px) rotate(720deg); opacity: 0; }
}
@keyframes orbit {
    from { transform: rotate(0deg) translateX(10px) rotate(0deg); }
    to { transform: rotate(360deg) translateX(10px) rotate(-360deg); }
}
@keyframes marquee {
    0% { transform: translateX(100%); }
    100% { transform: translateX(-100%); }
}
@keyframes pulse-ring {
    0% { transform: scale(0.9); opacity: 0.7; }
    50% { transform: scale(1.1); opacity: 1; }
    100% { transform: scale(0.9); opacity: 0.7; }
}
@keyframes countUp {
    from { opacity: 0; transform: scale(0.5); }
    to { opacity: 1; transform: scale(1); }
}

/* Particle background */
.particle-bg {
    position: relative;
    overflow: hidden;
}
.particle-bg::before {
    content: '';
    position: absolute;
    width: 100%;
    height: 100%;
    top: 0; left: 0;
    background:
        radial-gradient(2px 2px at 20% 30%, #a78bfa 50%, transparent 100%),
        radial-gradient(2px 2px at 80% 20%, #7c3aed 50%, transparent 100%),
        radial-gradient(2px 2px at 40% 70%, #c4b5fd 50%, transparent 100%),
        radial-gradient(2px 2px at 60% 50%, #8b5cf6 50%, transparent 100%),
        radial-gradient(2px 2px at 10% 80%, #ddd6fe 50%, transparent 100%),
        radial-gradient(2px 2px at 90% 60%, #a78bfa 50%, transparent 100%);
    animation: particle-drift 6s ease-in-out infinite alternate;
    pointer-events: none;
    z-index: 0;
}

.landing-hero {
    text-align: center;
    padding: 3rem 1rem 2rem;
    animation: fadeInUp 0.8s ease-out;
    position: relative;
    z-index: 1;
}
.landing-hero h1 {
    font-size: 3.5rem;
    font-weight: 900;
    background: linear-gradient(135deg, #7c3aed 0%, #a78bfa 30%, #c084fc 60%, #7c3aed 100%);
    background-size: 200% auto;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    animation: shimmer 3s linear infinite;
    margin-bottom: 0.5rem;
}
.typewriter-wrap {
    display: inline-block;
    overflow: hidden;
    white-space: nowrap;
    border-right: 3px solid #a78bfa;
    animation: typewriter 3s steps(44) 0.5s 1 normal both,
               blink 0.75s step-end infinite;
    font-size: 1.4rem;
    color: #6b7280;
    font-weight: 300;
    max-width: fit-content;
    margin: 0.5rem auto 0;
}
.landing-hero .sub-tagline {
    font-size: 1rem;
    color: #9ca3af;
    margin-top: 0.8rem;
    animation: fadeInUp 1.2s ease-out;
}

/* Stats bar */
.stats-bar {
    display: flex;
    justify-content: center;
    gap: 1.2rem;
    padding: 1.5rem 0;
    animation: fadeInUp 1s ease-out;
    flex-wrap: nowrap;
}
.stat-item {
    text-align: center;
    padding: 0.8rem 1rem;
    border-radius: 12px;
    background: rgba(139, 92, 246, 0.05);
    border: 1px solid rgba(139, 92, 246, 0.15);
    transition: all 0.3s ease;
    animation: countUp 0.6s ease-out backwards;
    flex: 1;
    min-width: 0;
}
.stat-item:nth-child(1) { animation-delay: 0.2s; }
.stat-item:nth-child(2) { animation-delay: 0.4s; }
.stat-item:nth-child(3) { animation-delay: 0.6s; }
.stat-item:nth-child(4) { animation-delay: 0.8s; }
.stat-item:hover {
    transform: scale(1.08);
    border-color: #a78bfa;
    box-shadow: 0 4px 20px rgba(139, 92, 246, 0.2);
}
.stat-number {
    font-size: 2.2rem;
    font-weight: 900;
    background: linear-gradient(135deg, #7c3aed, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
}
.stat-label {
    font-size: 0.75rem;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-top: 0.25rem;
}

/* Feature cards */
.feature-card {
    background: linear-gradient(145deg, #1a1a2e 0%, #16213e 100%);
    border: 1px solid rgba(139, 92, 246, 0.2);
    border-radius: 20px;
    padding: 2rem 1.2rem;
    text-align: center;
    transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    animation: fadeInUp 0.8s ease-out backwards;
    min-height: 240px;
    position: relative;
    overflow: hidden;
}
.feature-card::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: conic-gradient(from 0deg, transparent, rgba(139, 92, 246, 0.1), transparent);
    animation: orbit 6s linear infinite;
    pointer-events: none;
}
.feature-card:hover {
    transform: translateY(-8px) scale(1.02);
    border-color: #a78bfa;
    box-shadow: 0 20px 60px rgba(139, 92, 246, 0.3);
}
.feature-icon {
    font-size: 2.8rem;
    margin-bottom: 1rem;
    animation: float 3s ease-in-out infinite;
    display: inline-block;
}
.feature-card h3 {
    color: #e2e8f0;
    font-size: 1.05rem;
    margin-bottom: 0.6rem;
    font-weight: 700;
}
.feature-card p {
    color: #94a3b8;
    font-size: 0.85rem;
    line-height: 1.6;
}

/* Timeline steps */
.timeline-container {
    max-width: 550px;
    margin: 0 auto;
    padding: 1rem 0;
    position: relative;
}
.timeline-container::before {
    content: '';
    position: absolute;
    left: 23px;
    top: 3.5rem;
    bottom: 1rem;
    width: 2px;
    background: linear-gradient(to bottom, #7c3aed, #a78bfa, transparent);
}
.timeline-title {
    text-align: center;
    color: #e2e8f0;
    margin-bottom: 1.5rem;
    font-size: 1.3rem;
    font-weight: 700;
}
.step-row {
    display: flex;
    align-items: center;
    padding: 0.8rem 0;
    animation: slideIn 0.6s ease-out backwards;
    transition: transform 0.2s ease;
}
.step-row:hover {
    transform: translateX(8px);
}
.step-row:nth-child(2) { animation-delay: 0.15s; }
.step-row:nth-child(3) { animation-delay: 0.3s; }
.step-row:nth-child(4) { animation-delay: 0.45s; }
.step-row:nth-child(5) { animation-delay: 0.6s; }
.step-row:nth-child(6) { animation-delay: 0.75s; }
.step-number {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    min-width: 36px;
    border-radius: 50%;
    background: linear-gradient(135deg, #7c3aed, #a78bfa);
    color: white;
    font-weight: 700;
    font-size: 0.85rem;
    margin-right: 1rem;
    box-shadow: 0 0 12px rgba(139, 92, 246, 0.4);
    animation: pulse-ring 2s ease-in-out infinite;
}
.step-text {
    color: #cbd5e1;
    font-size: 1rem;
}

/* Marquee */
.marquee-container {
    overflow: hidden;
    white-space: nowrap;
    padding: 1rem 0;
}
.marquee-track {
    display: inline-block;
    animation: marquee 20s linear infinite;
}
.marquee-item {
    display: inline-block;
    padding: 0.6rem 1.5rem;
    margin: 0 0.75rem;
    border-radius: 30px;
    background: rgba(139, 92, 246, 0.08);
    border: 1px solid rgba(139, 92, 246, 0.2);
    color: #a78bfa;
    font-size: 0.85rem;
    font-weight: 500;
}

/* Divider */
.divider {
    height: 2px;
    background: linear-gradient(90deg, transparent, #7c3aed, #a78bfa, transparent);
    margin: 2rem 0;
    border: none;
}

/* CTA */
.cta-section {
    text-align: center;
    padding: 2rem 0;
    animation: fadeInUp 1.6s ease-out;
}
</style>"""


def _get_landing_hero_html() -> str:
    """Return HTML for the hero section with particle background and typewriter."""
    return (
        '<div class="particle-bg"><div class="landing-hero">'
        '<h1>🎯 Mock Interview Stress Tester</h1>'
        '<div class="typewriter-wrap">'
        'Crack your dream company\'s interview — powered by AI'
        '</div>'
        '<p class="sub-tagline">'
        '🔬 Real-time research &nbsp;•&nbsp; 🎯 Adaptive difficulty '
        '&nbsp;•&nbsp; ⚡ Instant scoring &nbsp;•&nbsp; 📊 Hiring prediction'
        '</p></div></div>'
    )


def _get_stats_bar_html() -> str:
    """Return HTML for the animated stats counter bar."""
    return (
        '<div class="stats-bar">'
        '<div class="stat-item">'
        '<div class="stat-number">2–15</div>'
        '<div class="stat-label">Custom Questions</div></div>'
        '<div class="stat-item">'
        '<div class="stat-number">4</div>'
        '<div class="stat-label">Score Dimensions</div></div>'
        '<div class="stat-item">'
        '<div class="stat-number">20</div>'
        '<div class="stat-label">Max Score / Answer</div></div>'
        '<div class="stat-item">'
        '<div class="stat-number">∞</div>'
        '<div class="stat-label">Companies Supported</div></div>'
        '</div>'
    )


def _get_timeline_html() -> str:
    """Return HTML for the animated how-it-works timeline."""
    return (
        '<div class="timeline-container">'
        '<h3 class="timeline-title">⚙️ How It Works</h3>'
        '<div class="step-row">'
        '<span class="step-number">1</span>'
        '<span class="step-text">Enter your target company, role & experience level</span></div>'
        '<div class="step-row">'
        '<span class="step-number">2</span>'
        '<span class="step-text">AI researches the company\'s real interview patterns</span></div>'
        '<div class="step-row">'
        '<span class="step-number">3</span>'
        '<span class="step-text">Answer 2–15 company-specific adaptive questions (you choose)</span></div>'
        '<div class="step-row">'
        '<span class="step-number">4</span>'
        '<span class="step-text">Get scored instantly — weak answers trigger follow-ups</span></div>'
        '<div class="step-row">'
        '<span class="step-number">5</span>'
        '<span class="step-text">Receive a detailed report with your hiring probability</span></div>'
        '</div>'
    )


def _get_marquee_html() -> str:
    """Return HTML for the scrolling marquee of supported companies/roles."""
    return (
        '<div class="marquee-container"><div class="marquee-track">'
        '<span class="marquee-item">Google</span>'
        '<span class="marquee-item">Amazon</span>'
        '<span class="marquee-item">Microsoft</span>'
        '<span class="marquee-item">Meta</span>'
        '<span class="marquee-item">Apple</span>'
        '<span class="marquee-item">Netflix</span>'
        '<span class="marquee-item">Stripe</span>'
        '<span class="marquee-item">Uber</span>'
        '<span class="marquee-item">Software Engineer</span>'
        '<span class="marquee-item">Product Manager</span>'
        '<span class="marquee-item">Data Scientist</span>'
        '<span class="marquee-item">Frontend Dev</span>'
        '<span class="marquee-item">Backend Dev</span>'
        '<span class="marquee-item">DevOps</span>'
        '<span class="marquee-item">Google</span>'
        '<span class="marquee-item">Amazon</span>'
        '<span class="marquee-item">Microsoft</span>'
        '<span class="marquee-item">Meta</span>'
        '</div></div>'
    )


def _render_landing_screen() -> None:  # Consider splitting this function
    """Render an interactive landing page with animations and rich visuals."""
    # Custom CSS for animations, particles, and interactive styling
    st.markdown(_get_landing_css(), unsafe_allow_html=True)

    # Hero section with particle background and typewriter effect
    st.markdown(_get_landing_hero_html(), unsafe_allow_html=True)

    # Animated stats counter bar — single row with CTA below
    st.markdown(_get_stats_bar_html(), unsafe_allow_html=True)

    # CTA button — directly below stats bar, centered
    _, center_col, _ = st.columns([1, 2, 1])
    with center_col:
        st.markdown(
            '<div class="cta-section">'
            '<p style="color: #a78bfa; font-size: 1.1rem; margin-bottom: 1rem;">'
            '✨ Ready to stress-test yourself?</p></div>',
            unsafe_allow_html=True,
        )
        if st.button(
            "🚀 Start Your Mock Interview",
            use_container_width=True,
            type="primary",
        ):
            st.session_state["passed_landing"] = True
            st.rerun()

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # Interactive feature cards with glow effects
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            '<div class="feature-card" style="animation-delay: 0.1s;">'
            '<div class="feature-icon">🔍</div>'
            '<h3>Live Research</h3>'
            '<p>AI scours the web for your target company\'s real interview '
            'patterns, culture signals, and red flags.</p>'
            '<div class="card-shine"></div></div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            '<div class="feature-card" style="animation-delay: 0.3s;">'
            '<div class="feature-icon">🧠</div>'
            '<h3>Adaptive Questions</h3>'
            '<p>Technical, behavioral, situational — difficulty ramps up. '
            'Weak answers trigger follow-up probes.</p>'
            '<div class="card-shine"></div></div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            '<div class="feature-card" style="animation-delay: 0.5s;">'
            '<div class="feature-icon">⚡</div>'
            '<h3>Instant Scoring</h3>'
            '<p>Every answer graded across 4 dimensions in real-time: '
            'relevance, depth, structure, examples.</p>'
            '<div class="card-shine"></div></div>',
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            '<div class="feature-card" style="animation-delay: 0.7s;">'
            '<div class="feature-icon">📈</div>'
            '<h3>Hiring Probability</h3>'
            '<p>Get a data-driven prediction of your hiring chance plus '
            'a personalized improvement roadmap.</p>'
            '<div class="card-shine"></div></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # Animated timeline — How It Works
    st.markdown(_get_timeline_html(), unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # Testimonial / social proof marquee
    st.markdown(_get_marquee_html(), unsafe_allow_html=True)

    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    # Footer
    st.markdown(
        '<div style="text-align: center; padding: 2rem 0 1rem; '
        'color: #6b7280; font-size: 0.8rem;">'
        'Powered by Gemini 2.0 Flash · Search Grounding · '
        'Multi-Agent Architecture</div>',
        unsafe_allow_html=True,
    )


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
    num_questions: int = st.slider(
        "Number of Questions",
        min_value=MIN_QUESTIONS,
        max_value=MAX_QUESTIONS,
        value=TOTAL_QUESTIONS,
        step=1,
        help=f"Choose between {MIN_QUESTIONS} and {MAX_QUESTIONS} questions for your mock interview.",
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
                session_id: str = start_session(company, role, level, num_questions)
                st.session_state["session_id"] = session_id
                st.rerun()
            except Exception as e:
                st.error(f"Session creation failed: {e}")


def _render_interview_screen(session_id: str) -> None:
    """Render the Interview screen: question display, answer input, evaluation."""
    # Get current state to determine sub-state behavior
    state: str = get_current_state(session_id)

    # Get session's num_questions
    session_data = db_get_session(session_id)
    num_questions: int = session_data.get("num_questions", TOTAL_QUESTIONS) if session_data else TOTAL_QUESTIONS

    # Get current question
    try:
        question_dict: dict = get_current_question(session_id)
    except ValueError:
        st.error("Could not load the current question. Please try again.")
        return

    # Display question info (only safe fields: question, category, id)
    st.caption(f"Question {question_dict['id']} of {num_questions}")
    st.caption(f"Category: {question_dict['category']}")
    st.subheader(question_dict["question"])

    # Follow-up indicator — show the follow-up question from the question dict
    if state == STATE_FOLLOW_UP:
        follow_up_text = get_current_follow_up_text(session_id)
        if follow_up_text:
            st.warning(f"**Follow-up:** {follow_up_text}")
        else:
            st.warning("Follow-up question — expand on your previous answer.")

    # Answer input — key uses question difficulty (1-based index) for stability
    answer_key: str = f"answer_input_q{question_dict['difficulty']}"
    answer: str = st.text_area("Your Answer", max_chars=5000, key=answer_key)

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
            except Exception as e:
                st.error(f"Evaluation failed: {e}")
                return

        # Display evaluation
        _render_evaluation(evaluation)

        # Check post-evaluation state and handle navigation
        new_state: str = get_current_state(session_id)
        if new_state == STATE_FOLLOW_UP:
            # Follow-up triggered — rerun to show follow-up question properly
            st.rerun()
        elif new_state == STATE_REPORT:
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

    # Get session's num_questions for dynamic max score
    session_data = db_get_session(session_id)
    num_questions: int = session_data.get("num_questions", TOTAL_QUESTIONS) if session_data else TOTAL_QUESTIONS
    max_score: int = num_questions * 20

    with st.spinner("Generating your report..."):
        try:
            report: dict = generate_final_report(session_id)
        except Exception:
            st.error("Report generation failed. Please try again.")
            return

    # Overall metrics
    st.metric("Overall Score", f"{report['overall_score']}/{max_score}")
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

    if screen == "landing":
        _render_landing_screen()
    elif screen == "setup":
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

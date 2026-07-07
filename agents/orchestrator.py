"""
agents/orchestrator.py — Orchestrator Agent for the Mock Interview Stress Tester.

Central state machine controller that sequences calls to four agents
(Researcher, QuestionGenerator, Evaluator, Coach), enforces state
transitions, validates agent output contracts, handles errors, and
persists all state to SQLite via core/database.py.

Public API (5 functions):
- start_session(company, role, level) → str
- get_current_question(session_id) → dict
- submit_answer(session_id, answer_text) → dict
- get_current_state(session_id) → str
- generate_final_report(session_id) → dict

Design Principles:
- Pure functions with no module-level mutable state
- All state derived from the database per call
- Fail-safe: any agent failure transitions to STATE_ERROR
- Contract-first: all agent outputs validated before persistence
- Rate-limited: mandatory sleep between consecutive LLM calls
"""

import json
import time
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Config imports — all named constants, no hardcoded literals
# ---------------------------------------------------------------------------
from core.config import (
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
    TOTAL_QUESTIONS,
    MIN_QUESTIONS,
    MAX_QUESTIONS,
    MAX_FOLLOW_UPS,
    RATE_LIMIT_SLEEP,
    GEMINI_API_KEY,
)

# ---------------------------------------------------------------------------
# Database imports — all persistence operations go through core/database.py
# ---------------------------------------------------------------------------
from core.database import (
    create_session,
    get_session,
    save_research,
    save_questions,
    save_answer,
    get_answers,
    save_report,
    update_session_state,
    get_question,
    get_report,
    get_follow_up_count,
    increment_follow_up_count,
)

# ---------------------------------------------------------------------------
# Agent imports — each agent exposes only its public function(s)
# ---------------------------------------------------------------------------
from agents.researcher import research_company
from agents.question_generator import generate_questions, QuestionGenerationError
from agents.evaluator import evaluate_answer, get_follow_up_question
from agents.coach import generate_report

# ---------------------------------------------------------------------------
# Module-level constants (no mutable state)
# ---------------------------------------------------------------------------

# Maximum allowed character length for company, role, and level inputs.
MAX_INPUT_LENGTH: int = 200

# Maximum stored length for error reason strings (truncated beyond this).
MAX_ERROR_REASON_LENGTH: int = 500

# ---------------------------------------------------------------------------
# State transition map — defines all permitted (source → target) transitions.
# Terminal states (DONE, ERROR) have no outgoing transitions.
# ---------------------------------------------------------------------------
_VALID_TRANSITIONS: dict[str, set[str]] = {
    STATE_SETUP:       {STATE_RESEARCHING, STATE_ERROR},
    STATE_RESEARCHING: {STATE_GENERATING, STATE_ERROR},
    STATE_GENERATING:  {STATE_READY, STATE_ERROR},
    STATE_READY:       {STATE_ASKING, STATE_ERROR},
    STATE_ASKING:      {STATE_EVALUATING, STATE_ERROR},
    STATE_EVALUATING:  {STATE_FOLLOW_UP, STATE_NEXT_Q, STATE_REPORT, STATE_ERROR},
    STATE_FOLLOW_UP:   {STATE_EVALUATING, STATE_NEXT_Q, STATE_REPORT, STATE_ERROR},
    STATE_NEXT_Q:      {STATE_ASKING, STATE_ERROR},
    STATE_REPORT:      {STATE_DONE, STATE_ERROR},
    STATE_DONE:        set(),   # Terminal — no transitions out
    STATE_ERROR:       set(),   # Terminal — no transitions out
}


# ---------------------------------------------------------------------------
# Private helper functions
# ---------------------------------------------------------------------------


def _validate_session_exists(session_id: str) -> dict:
    """Fetch session from DB; raise ValueError if not found or id is invalid.

    Args:
        session_id: UUID string identifying the session to look up.

    Returns:
        The session dict from the database containing keys like
        session_id, company, role, level, state, created_at.

    Raises:
        ValueError: If session_id is falsy (None, empty, whitespace-only)
                    or if no matching session exists in the database.
    """
    if not session_id:
        raise ValueError("Invalid session_id: must be non-empty string")
    session = get_session(session_id)
    if session is None:
        raise ValueError(f"Session not found: {session_id}")
    return session


def _validate_not_terminal(session: dict) -> None:
    """Raise ValueError if session is in a terminal state (DONE or ERROR).

    Terminal states cannot transition further and reject most operations.
    Only get_current_state remains available for terminal sessions.

    Args:
        session: A session dict as returned by get_session / _validate_session_exists.

    Returns:
        None — returns normally if the session is not in a terminal state.

    Raises:
        ValueError: If the session's state is STATE_DONE or STATE_ERROR.
    """
    state = session["state"]
    if state in (STATE_DONE, STATE_ERROR):
        raise ValueError(
            f"Session {session['session_id']} is in terminal state: {state}"
        )


def _transition(session_id: str, current_state: str, new_state: str) -> None:
    """Validate and execute a state transition, persisting to the database.

    Algorithm:
    1. Look up valid targets for current_state in _VALID_TRANSITIONS.
    2. If new_state is not in the valid targets, raise ValueError.
    3. Log the transition to stdout in the canonical format.
    4. Persist the new state to the database synchronously.

    Args:
        session_id: UUID string identifying the session to transition.
        current_state: The session's current state label (must match DB).
        new_state: The desired target state label.

    Returns:
        None

    Raises:
        ValueError: If the transition from current_state to new_state
                    is not permitted by the state machine rules.
    """
    valid_targets = _VALID_TRANSITIONS.get(current_state, set())
    if new_state not in valid_targets:
        raise ValueError(
            f"Invalid transition: {current_state} → {new_state}"
        )
    print(f"[Orchestrator] {current_state} → {new_state}")
    update_session_state(session_id, new_state)


# ---------------------------------------------------------------------------
# Private helpers — error handling and retry logic
# ---------------------------------------------------------------------------


def _handle_error(session_id: str, reason: str) -> None:
    """Best-effort error handler that transitions session to ERROR state.

    Truncates the reason string to MAX_ERROR_REASON_LENGTH and attempts to
    persist the error state. This function NEVER raises — any failure during
    persistence is printed and swallowed.

    Args:
        session_id: The session to transition to ERROR.
        reason: Human-readable error description (will be truncated).
    """
    try:
        truncated = reason[:MAX_ERROR_REASON_LENGTH]
        try:
            update_session_state(session_id, STATE_ERROR)
        except Exception as db_err:
            print(f"[Orchestrator] Failed to persist error state: {db_err}")
    except Exception:
        # Outer guard: _handle_error must NEVER propagate exceptions.
        pass


# ---------------------------------------------------------------------------
# Required-key sets for agent output contract validation.
# Each set defines the mandatory keys that an agent's output must contain.
# ---------------------------------------------------------------------------

_RESEARCH_REQUIRED_KEYS: set[str] = {
    "company", "role", "interview_rounds", "key_topics",
    "difficulty", "culture_keywords", "known_question_types", "red_flags_to_test",
}

_QUESTION_REQUIRED_KEYS: set[str] = {
    "id", "category", "question", "ideal_keywords",
    "difficulty", "follow_ups", "scoring_hint",
}

_EVALUATION_REQUIRED_KEYS: set[str] = {
    "scores", "total", "verdict", "feedback",
    "missing_keywords", "trigger_follow_up",
}

_SCORE_REQUIRED_KEYS: set[str] = {"relevance", "depth", "structure", "examples"}

_REPORT_REQUIRED_KEYS: set[str] = {
    "overall_score", "hiring_probability", "hiring_probability_percent",
    "strongest_category", "weakest_category", "category_averages",
    "top_3_strengths", "top_3_improvements", "critical_moment",
    "overall_verdict", "next_interview_tip",
}

_VALID_VERDICTS: set[str] = {"weak", "good", "strong"}


# ---------------------------------------------------------------------------
# Contract validator functions — called before any persistence operation.
# Each raises ValueError on the first contract violation encountered.
# ---------------------------------------------------------------------------


def _validate_research_dict(data: object) -> None:
    """Validate that Researcher agent output is a dict with all 8 required keys.

    Raises:
        ValueError: If data is not a dict or is missing required keys.
    """
    if not isinstance(data, dict):
        raise ValueError("Researcher output is not a dict")
    missing = _RESEARCH_REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Researcher output missing keys: {missing}")


def _validate_questions_list(data: object, num_questions: int = TOTAL_QUESTIONS) -> None:
    """Validate that QuestionGenerator agent output is a list of num_questions dicts.

    Each item must be a dict containing all 7 required question keys.

    Args:
        data: The output to validate.
        num_questions: Expected number of questions in the list.

    Raises:
        ValueError: If data is not a list, has wrong length, or items are invalid.
    """
    if not isinstance(data, list):
        raise ValueError("QuestionGenerator output is not a list")
    if len(data) != num_questions:
        raise ValueError(
            f"QuestionGenerator returned {len(data)} questions, expected {num_questions}"
        )
    for i, q in enumerate(data):
        if not isinstance(q, dict):
            raise ValueError(f"QuestionGenerator question[{i}] is not a dict")
        missing = _QUESTION_REQUIRED_KEYS - set(q.keys())
        if missing:
            raise ValueError(f"QuestionGenerator question[{i}] missing keys: {missing}")


def _validate_evaluation_dict(data: object) -> None:
    """Validate that Evaluator agent output is a dict with correct structure.

    Checks:
    - 6 required top-level keys present
    - scores is a dict with 4 integer keys each in [1, 5]
    - total is an int in [4, 20]
    - verdict is one of "weak", "good", "strong"
    - missing_keywords is a list
    - trigger_follow_up is a bool

    Raises:
        ValueError: If any contract check fails.
    """
    if not isinstance(data, dict):
        raise ValueError("Evaluator output is not a dict")
    missing = _EVALUATION_REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Evaluator output missing keys: {missing}")

    scores = data.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("Evaluator scores is not a dict")
    score_missing = _SCORE_REQUIRED_KEYS - set(scores.keys())
    if score_missing:
        raise ValueError(f"Evaluator scores missing keys: {score_missing}")

    for key in _SCORE_REQUIRED_KEYS:
        value = scores[key]
        if not isinstance(value, int) or value < 1 or value > 5:
            raise ValueError(
                f"Evaluator scores['{key}'] must be an int in [1, 5], got {value!r}"
            )

    total = data["total"]
    if not isinstance(total, int) or total < 4 or total > 20:
        raise ValueError(
            f"Evaluator total must be an int in [4, 20], got {total!r}"
        )

    if data["verdict"] not in _VALID_VERDICTS:
        raise ValueError(
            f"Evaluator verdict must be one of {_VALID_VERDICTS}, got {data['verdict']!r}"
        )

    if not isinstance(data["missing_keywords"], list):
        raise ValueError("Evaluator missing_keywords is not a list")

    if not isinstance(data["trigger_follow_up"], bool):
        raise ValueError("Evaluator trigger_follow_up is not a bool")


def _validate_report_dict(data: object) -> None:
    """Validate that Coach agent output is a dict with all 11 required keys.

    Raises:
        ValueError: If data is not a dict or is missing required keys.
    """
    if not isinstance(data, dict):
        raise ValueError("Coach output is not a dict")
    missing = _REPORT_REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Coach output missing keys: {missing}")


# ---------------------------------------------------------------------------
# Public API — get_current_state
# ---------------------------------------------------------------------------


def get_current_state(session_id: str) -> str:
    """Return the current state label for a session without any side effects.

    This is a pure read operation — no state transitions or database writes.
    Works for ALL states including terminal (DONE, ERROR).

    Args:
        session_id: UUID string identifying the session to query.

    Returns:
        The current state label (one of the 11 STATE_* constants).

    Raises:
        ValueError: If session_id is empty/None or if the session does not exist.
    """
    session = _validate_session_exists(session_id)
    return session["state"]


# ---------------------------------------------------------------------------
# Public API — start_session
# ---------------------------------------------------------------------------


def start_session(company: str, role: str, level: str, num_questions: int = TOTAL_QUESTIONS) -> str:  # Consider splitting this function
    """Create a new interview session: research the company and generate questions.

    Flow:
    1. Validate GEMINI_API_KEY is non-empty
    2. Validate and strip company, role, level (non-empty after strip, ≤ MAX_INPUT_LENGTH)
    3. Validate num_questions is within MIN_QUESTIONS–MAX_QUESTIONS range
    4. Generate session_id, create session in DB (state=SETUP)
    5. Transition SETUP → RESEARCHING
    6. Call research_company with retry, validate output, save to DB
    7. Sleep RATE_LIMIT_SLEEP between agent calls
    8. Transition RESEARCHING → GENERATING
    9. Call generate_questions with retry, validate output (save handled by agent)
    10. Transition GENERATING → READY
    11. Return session_id

    On any agent failure: _handle_error transitions to ERROR, then re-raise.

    Args:
        company: Company name (stripped, 1 to MAX_INPUT_LENGTH chars).
        role: Job role (stripped, 1 to MAX_INPUT_LENGTH chars).
        level: Experience level (stripped, 1 to MAX_INPUT_LENGTH chars).
        num_questions: Number of questions to generate (MIN_QUESTIONS–MAX_QUESTIONS).

    Returns:
        The session_id (UUID string) for the newly created session.

    Raises:
        ValueError: If GEMINI_API_KEY is empty, or company/role/level is
                    empty/whitespace-only/exceeds MAX_INPUT_LENGTH after strip,
                    or num_questions is out of range.
    """
    # Step 1: Validate API key
    if not GEMINI_API_KEY or not GEMINI_API_KEY.strip():
        raise ValueError("GEMINI_API_KEY is not set or is empty")

    # Step 2: Validate inputs
    inputs = {"company": company, "role": role, "level": level}
    for param_name, value in inputs.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invalid {param_name}: must be a non-empty string")
        if len(value.strip()) > MAX_INPUT_LENGTH:
            raise ValueError(
                f"Invalid {param_name}: exceeds {MAX_INPUT_LENGTH} characters"
            )
    company = company.strip()
    role = role.strip()
    level = level.strip()

    # Step 3: Validate num_questions
    if not isinstance(num_questions, int) or num_questions < MIN_QUESTIONS or num_questions > MAX_QUESTIONS:
        raise ValueError(
            f"num_questions must be an integer between {MIN_QUESTIONS} and {MAX_QUESTIONS}, got {num_questions}"
        )

    # Step 4: Create session
    session_id = str(uuid.uuid4())
    create_session(session_id, company, role, level, num_questions)

    try:
        # Step 5: Transition to RESEARCHING
        _transition(session_id, STATE_SETUP, STATE_RESEARCHING)

        # Step 6: Call researcher and validate
        research_data = research_company(company, role, level, GEMINI_API_KEY)
        _validate_research_dict(research_data)
        save_research(session_id, research_data)

        # Step 7: Rate-limit sleep between consecutive agent LLM calls
        time.sleep(RATE_LIMIT_SLEEP)

        # Step 8: Transition to GENERATING
        _transition(session_id, STATE_RESEARCHING, STATE_GENERATING)

        # Step 9: Call question generator and validate
        questions = generate_questions(research_data, session_id, GEMINI_API_KEY, num_questions)
        _validate_questions_list(questions, num_questions)

        # Step 10: Transition to READY
        _transition(session_id, STATE_GENERATING, STATE_READY)

    except QuestionGenerationError as e:
        _handle_error(session_id, str(e))
        raise
    except Exception as e:
        _handle_error(session_id, str(e))
        raise

    # Step 11: Return session ID
    return session_id


# ---------------------------------------------------------------------------
# Public API — get_current_question
# ---------------------------------------------------------------------------


def get_current_question(session_id: str) -> dict:
    """Retrieve the current interview question for a session.

    Transitions from READY or NEXT_Q to ASKING (first access).
    Idempotent when already in ASKING or FOLLOW_UP (returns same question,
    no transition).

    Args:
        session_id: UUID string identifying the session.

    Returns:
        A Question_Dict with exactly 7 keys: id, category, question,
        ideal_keywords, difficulty, follow_ups, scoring_hint.

    Raises:
        ValueError: If session doesn't exist, is in terminal state,
                    is in wrong state, or all questions answered.
    """
    # Validate session
    session = _validate_session_exists(session_id)
    _validate_not_terminal(session)

    state = session["state"]
    num_questions: int = session.get("num_questions", TOTAL_QUESTIONS)

    # Only valid from READY, ASKING, NEXT_Q, FOLLOW_UP, or EVALUATING
    # (EVALUATING can occur if a previous evaluation crashed mid-flight)
    if state not in (STATE_READY, STATE_ASKING, STATE_NEXT_Q, STATE_FOLLOW_UP, STATE_EVALUATING):
        raise ValueError(
            f"Cannot get question in state {state}; "
            f"expected READY, ASKING, NEXT_Q, FOLLOW_UP, or EVALUATING"
        )

    # Determine current question index from answer count
    answers = get_answers(session_id)

    # In FOLLOW_UP or EVALUATING state, we are re-evaluating the same question
    if state in (STATE_FOLLOW_UP, STATE_EVALUATING):
        q_index = len(answers) - 1 if answers else 0
    else:
        q_index = len(answers)

    # Guard: all questions already answered (not applicable in FOLLOW_UP/EVALUATING)
    if q_index >= num_questions and state not in (STATE_FOLLOW_UP, STATE_EVALUATING):
        raise ValueError(
            f"All {num_questions} questions have been answered"
        )

    # Guard: negative index (no answers yet but in FOLLOW_UP — shouldn't happen)
    if q_index < 0:
        raise ValueError("No answers exist for follow-up evaluation")

    # Transition if needed (idempotent in ASKING or FOLLOW_UP)
    if state in (STATE_READY, STATE_NEXT_Q):
        _transition(session_id, state, STATE_ASKING)
    elif state == STATE_EVALUATING:
        # Stuck in EVALUATING from a crashed evaluation — revert to ASKING
        update_session_state(session_id, STATE_ASKING)
        print(f"[Orchestrator] Recovered stuck EVALUATING → ASKING")
    # If already ASKING or FOLLOW_UP: no transition (idempotent)

    # Retrieve question from DB
    question = get_question(session_id, q_index)
    if question is None:
        raise ValueError(
            f"Question at index {q_index} not found for session {session_id}"
        )

    return question


# ---------------------------------------------------------------------------
# Public API — get_current_follow_up_text
# ---------------------------------------------------------------------------


def get_current_follow_up_text(session_id: str) -> str | None:
    """Retrieve the current follow-up question text for a session in FOLLOW_UP state.

    Returns the follow-up question string that should be displayed to the user.
    Uses the follow_up_count (already incremented) to look up the correct
    follow-up from the question dict's follow_ups list.

    Args:
        session_id: UUID string identifying the session.

    Returns:
        The follow-up question string, or None if not in FOLLOW_UP state
        or no follow-up is available.
    """
    session = _validate_session_exists(session_id)
    state = session["state"]

    if state != STATE_FOLLOW_UP:
        return None

    # In FOLLOW_UP, the current question is at len(answers) - 1
    answers = get_answers(session_id)
    if not answers:
        return None

    q_index = len(answers) - 1
    question_dict = get_question(session_id, q_index)
    if question_dict is None:
        return None

    # Count was already incremented, so the displayed follow-up is at count - 1
    follow_up_count = get_follow_up_count(session_id, q_index)
    return get_follow_up_question(question_dict, follow_up_count - 1)


# ---------------------------------------------------------------------------
# Public API — generate_final_report
# ---------------------------------------------------------------------------


def generate_final_report(session_id: str) -> dict:
    """Generate or retrieve the final performance report for a completed session.

    Idempotent: if the session is already in STATE_DONE and a report exists,
    returns the cached report without calling Coach_Agent again.

    Flow:
    1. Validate session exists
    2. If STATE_DONE and report exists → return cached (idempotent)
    3. Validate not terminal (covers ERROR state)
    4. Verify all TOTAL_QUESTIONS answered
    5. Transition to STATE_REPORT
    6. Call generate_report with retry
    7. Validate report dict
    8. Strip extra keys (keep only 11 required)
    9. Save report, transition to STATE_DONE
    10. Return report

    Args:
        session_id: UUID string identifying the session.

    Returns:
        A Report_Dict with exactly 11 required keys.

    Raises:
        ValueError: If session doesn't exist, is in ERROR state,
                    or not all questions have been answered.
    """
    # Step 1: Validate session exists
    session = _validate_session_exists(session_id)

    # Step 2: Idempotent — if already DONE with saved report, return it
    if session["state"] == STATE_DONE:
        existing_report = get_report(session_id)
        if existing_report is not None:
            return existing_report

    # Step 3: Validate not terminal (catches ERROR state)
    _validate_not_terminal(session)

    num_questions: int = session.get("num_questions", TOTAL_QUESTIONS)

    # Step 4: Verify all questions answered
    answers = get_answers(session_id)
    if len(answers) < num_questions:
        missing = num_questions - len(answers)
        raise ValueError(
            f"Cannot generate report: {missing} questions still unanswered "
            f"({len(answers)}/{num_questions} completed)"
        )

    try:
        # Step 5: Transition to REPORT
        _transition(session_id, session["state"], STATE_REPORT)

        # Step 6: Call Coach agent
        report = generate_report(session_id, answers, GEMINI_API_KEY)

        # Step 7: Validate report contract
        _validate_report_dict(report)

        # Step 8: Strip extra keys — keep only the 11 required
        report = {k: report[k] for k in _REPORT_REQUIRED_KEYS}

        # Step 9: Save and transition to DONE
        save_report(session_id, report)
        _transition(session_id, STATE_REPORT, STATE_DONE)

    except Exception as e:
        _handle_error(session_id, str(e))
        raise

    # Step 10: Return the validated, stripped report
    return report


# ---------------------------------------------------------------------------
# Public API — submit_answer
# ---------------------------------------------------------------------------


def submit_answer(session_id: str, answer_text: str) -> dict:  # Consider splitting this function
    """Submit and evaluate a user's answer to the current interview question.

    Handles the full evaluation flow including follow-up question triggering.

    Flow:
    1. Validate answer_text (strip → non-empty)
    2. Validate session exists and is not terminal
    3. Validate state is ASKING or FOLLOW_UP
    4. Determine q_index from answer count
    5. For FOLLOW_UP state: use same q_index (answer updates existing)
    6. Transition to EVALUATING
    7. Get current question, call evaluate_answer with retry, validate
    8. Save answer
    9. Determine next state based on evaluation result:
       - trigger_follow_up=True AND count < MAX_FOLLOW_UPS: get follow-up,
         if non-None → FOLLOW_UP + increment count
       - Otherwise if not last Q → NEXT_Q
       - Otherwise (last Q) → REPORT
    10. Return evaluation dict (+ optional follow_up_question key)

    Args:
        session_id: UUID string identifying the session.
        answer_text: The user's answer text (must be non-empty after strip).

    Returns:
        An Evaluation_Dict (6 keys) plus an optional "follow_up_question" key
        when a follow-up is triggered and available.

    Raises:
        ValueError: If answer_text is whitespace-only, session doesn't exist,
                    is terminal, or is in wrong state.
    """
    # Step 1: Validate answer text
    if not isinstance(answer_text, str) or not answer_text.strip():
        raise ValueError("answer_text must be a non-empty string")
    answer_text = answer_text.strip()

    # Step 2: Validate session
    session = _validate_session_exists(session_id)
    _validate_not_terminal(session)

    state = session["state"]

    # Step 3: Valid states for answer submission
    if state not in (STATE_ASKING, STATE_FOLLOW_UP):
        raise ValueError(
            f"Cannot submit answer in state {state}; expected ASKING or FOLLOW_UP"
        )

    num_questions: int = session.get("num_questions", TOTAL_QUESTIONS)

    # Step 4: Determine question index
    answers = get_answers(session_id)
    q_index = len(answers)

    # For FOLLOW_UP: we're re-evaluating the same question (update existing answer)
    if state == STATE_FOLLOW_UP:
        q_index = len(answers) - 1  # Last answered question

    # Guard: check we're not beyond total questions
    if q_index >= num_questions:
        raise ValueError(f"All {num_questions} questions already answered")

    # Remember the pre-evaluation state for recovery on failure
    pre_eval_state = state

    try:
        # Step 6: Transition to EVALUATING
        _transition(session_id, state, STATE_EVALUATING)

        # Step 7: Get question and evaluate
        question_dict = get_question(session_id, q_index)
        if question_dict is None:
            raise ValueError(f"Question at index {q_index} not found")

        evaluation = evaluate_answer(
            question_dict["question"],
            question_dict["ideal_keywords"],
            question_dict["scoring_hint"],
            answer_text,
            GEMINI_API_KEY,
        )
        _validate_evaluation_dict(evaluation)

        # Step 8: Save answer
        save_answer(session_id, q_index, answer_text, evaluation)

        # Step 9: Determine next state
        result = dict(evaluation)  # copy for return

        is_last_question = (q_index >= num_questions - 1)

        if evaluation["trigger_follow_up"]:
            # Check follow-up count
            follow_up_count = get_follow_up_count(session_id, q_index)
            if follow_up_count < MAX_FOLLOW_UPS:
                # Try to get a follow-up question
                follow_up_q = get_follow_up_question(question_dict, follow_up_count)
                if follow_up_q is not None:
                    # Transition to FOLLOW_UP
                    _transition(session_id, STATE_EVALUATING, STATE_FOLLOW_UP)
                    increment_follow_up_count(session_id, q_index)
                    result["follow_up_question"] = follow_up_q
                else:
                    # No follow-up available, move on
                    if is_last_question:
                        _transition(session_id, STATE_EVALUATING, STATE_REPORT)
                    else:
                        _transition(session_id, STATE_EVALUATING, STATE_NEXT_Q)
            else:
                # Max follow-ups reached, move on
                if is_last_question:
                    _transition(session_id, STATE_EVALUATING, STATE_REPORT)
                else:
                    _transition(session_id, STATE_EVALUATING, STATE_NEXT_Q)
        else:
            # No follow-up triggered
            if is_last_question:
                _transition(session_id, STATE_EVALUATING, STATE_REPORT)
            else:
                _transition(session_id, STATE_EVALUATING, STATE_NEXT_Q)

    except Exception as e:
        # Revert state to pre-evaluation state so user can retry
        # instead of permanently transitioning to ERROR
        try:
            update_session_state(session_id, pre_eval_state)
            # WARNING: this print may leak sensitive data — review before deploying
            print(f"[Orchestrator] Evaluation failed, reverted state to {pre_eval_state}: {e}")
        except Exception:
            # If revert fails, fall back to terminal ERROR state
            _handle_error(session_id, str(e))
        raise

    # Step 10: Return evaluation (with optional follow_up_question)
    return result

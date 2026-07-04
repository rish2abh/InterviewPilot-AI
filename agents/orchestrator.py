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
    MAX_FOLLOW_UPS,
    RATE_LIMIT_SLEEP,
    ERROR_RETRY_SLEEP,
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

# Maximum retry attempts for agent calls on 429 rate-limit errors.
MAX_RETRIES: int = 2

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


def _call_with_retry(agent_fn, args: tuple, session_id: str) -> Any:
    """Call an agent function with automatic retry on 429 rate-limit errors.

    Retries up to MAX_RETRIES times when the exception message contains '429'.
    Sleeps ERROR_RETRY_SLEEP seconds between retries. All other exceptions
    propagate immediately.

    Args:
        agent_fn: The agent callable to invoke.
        args: Positional arguments to unpack into agent_fn.
        session_id: Session context (for logging/diagnostics).

    Returns:
        The return value of agent_fn(*args) on success.

    Raises:
        Exception: Re-raises the original exception if retries are exhausted
                   or the error is not a 429.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            return agent_fn(*args)
        except Exception as e:
            if "429" in str(e) and attempt < MAX_RETRIES:
                print(f"[Orchestrator] 429 error, retry {attempt + 1}/{MAX_RETRIES}")
                time.sleep(ERROR_RETRY_SLEEP)
            else:
                raise

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


def _validate_questions_list(data: object) -> None:
    """Validate that QuestionGenerator agent output is a list of TOTAL_QUESTIONS dicts.

    Each item must be a dict containing all 7 required question keys.

    Raises:
        ValueError: If data is not a list, has wrong length, or items are invalid.
    """
    if not isinstance(data, list):
        raise ValueError("QuestionGenerator output is not a list")
    if len(data) != TOTAL_QUESTIONS:
        raise ValueError(
            f"QuestionGenerator returned {len(data)} questions, expected {TOTAL_QUESTIONS}"
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


def start_session(company: str, role: str, level: str) -> str:
    """Create a new interview session: research the company and generate questions.

    Flow:
    1. Validate GEMINI_API_KEY is non-empty
    2. Validate and strip company, role, level (non-empty after strip, ≤ MAX_INPUT_LENGTH)
    3. Generate session_id, create session in DB (state=SETUP)
    4. Transition SETUP → RESEARCHING
    5. Call research_company with retry, validate output, save to DB
    6. Sleep RATE_LIMIT_SLEEP between agent calls
    7. Transition RESEARCHING → GENERATING
    8. Call generate_questions with retry, validate output (save handled by agent)
    9. Transition GENERATING → READY
    10. Return session_id

    On any agent failure: _handle_error transitions to ERROR, then re-raise.

    Args:
        company: Company name (stripped, 1 to MAX_INPUT_LENGTH chars).
        role: Job role (stripped, 1 to MAX_INPUT_LENGTH chars).
        level: Experience level (stripped, 1 to MAX_INPUT_LENGTH chars).

    Returns:
        The session_id (UUID string) for the newly created session.

    Raises:
        ValueError: If GEMINI_API_KEY is empty, or company/role/level is
                    empty/whitespace-only/exceeds MAX_INPUT_LENGTH after strip.
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

    # Step 3: Create session
    session_id = str(uuid.uuid4())
    create_session(session_id, company, role, level)

    try:
        # Step 4: Transition to RESEARCHING
        _transition(session_id, STATE_SETUP, STATE_RESEARCHING)

        # Step 5: Call researcher with retry and validate
        research_data = _call_with_retry(
            research_company,
            (company, role, level, GEMINI_API_KEY),
            session_id,
        )
        _validate_research_dict(research_data)
        save_research(session_id, research_data)

        # Step 6: Rate-limit sleep between consecutive agent LLM calls
        time.sleep(RATE_LIMIT_SLEEP)

        # Step 7: Transition to GENERATING
        _transition(session_id, STATE_RESEARCHING, STATE_GENERATING)

        # Step 8: Call question generator with retry and validate
        questions = _call_with_retry(
            generate_questions,
            (research_data, session_id, GEMINI_API_KEY),
            session_id,
        )
        _validate_questions_list(questions)

        # Step 9: Transition to READY
        _transition(session_id, STATE_GENERATING, STATE_READY)

    except QuestionGenerationError as e:
        _handle_error(session_id, str(e))
        raise
    except Exception as e:
        _handle_error(session_id, str(e))
        raise

    # Step 10: Return session ID
    return session_id


# ---------------------------------------------------------------------------
# Public API — get_current_question
# ---------------------------------------------------------------------------


def get_current_question(session_id: str) -> dict:
    """Retrieve the current interview question for a session.

    Transitions from READY or NEXT_Q to ASKING (first access).
    Idempotent when already in ASKING (returns same question, no transition).

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

    # Only valid from READY, ASKING, or NEXT_Q
    if state not in (STATE_READY, STATE_ASKING, STATE_NEXT_Q):
        raise ValueError(
            f"Cannot get question in state {state}; "
            f"expected READY, ASKING, or NEXT_Q"
        )

    # Determine current question index from answer count
    answers = get_answers(session_id)
    q_index = len(answers)

    # Guard: all questions already answered
    if q_index >= TOTAL_QUESTIONS:
        raise ValueError(
            f"All {TOTAL_QUESTIONS} questions have been answered"
        )

    # Transition if needed (idempotent in ASKING)
    if state in (STATE_READY, STATE_NEXT_Q):
        _transition(session_id, state, STATE_ASKING)
    # If already ASKING: no transition (idempotent)

    # Retrieve question from DB
    question = get_question(session_id, q_index)
    if question is None:
        raise ValueError(
            f"Question at index {q_index} not found for session {session_id}"
        )

    return question


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

    # Step 4: Verify all questions answered
    answers = get_answers(session_id)
    if len(answers) < TOTAL_QUESTIONS:
        missing = TOTAL_QUESTIONS - len(answers)
        raise ValueError(
            f"Cannot generate report: {missing} questions still unanswered "
            f"({len(answers)}/{TOTAL_QUESTIONS} completed)"
        )

    try:
        # Step 5: Transition to REPORT
        _transition(session_id, session["state"], STATE_REPORT)

        # Step 6: Call Coach agent with retry
        report = _call_with_retry(
            generate_report,
            (session_id, answers),
            session_id,
        )

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


def submit_answer(session_id: str, answer_text: str) -> dict:
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

    # Step 4: Determine question index
    answers = get_answers(session_id)
    q_index = len(answers)

    # For FOLLOW_UP: we're re-evaluating the same question (update existing answer)
    if state == STATE_FOLLOW_UP:
        q_index = len(answers) - 1  # Last answered question

    # Guard: check we're not beyond total questions
    if q_index >= TOTAL_QUESTIONS:
        raise ValueError(f"All {TOTAL_QUESTIONS} questions already answered")

    try:
        # Step 6: Transition to EVALUATING
        _transition(session_id, state, STATE_EVALUATING)

        # Step 7: Get question and evaluate
        question_dict = get_question(session_id, q_index)
        if question_dict is None:
            raise ValueError(f"Question at index {q_index} not found")

        evaluation = _call_with_retry(
            evaluate_answer,
            (
                question_dict["question"],
                question_dict["ideal_keywords"],
                question_dict["scoring_hint"],
                answer_text,
                GEMINI_API_KEY,
            ),
            session_id,
        )
        _validate_evaluation_dict(evaluation)

        # Step 8: Save answer
        save_answer(session_id, q_index, answer_text, evaluation)

        # Step 9: Determine next state
        result = dict(evaluation)  # copy for return

        is_last_question = (q_index >= TOTAL_QUESTIONS - 1)

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
        _handle_error(session_id, str(e))
        raise

    # Step 10: Return evaluation (with optional follow_up_question)
    return result

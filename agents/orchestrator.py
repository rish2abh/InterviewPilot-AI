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
    STATE_FOLLOW_UP:   {STATE_NEXT_Q, STATE_REPORT, STATE_ERROR},
    STATE_NEXT_Q:      {STATE_ASKING, STATE_ERROR},
    STATE_REPORT:      {STATE_DONE, STATE_ERROR},
    STATE_DONE:        set(),   # Terminal — no transitions out
    STATE_ERROR:       set(),   # Terminal — no transitions out
}

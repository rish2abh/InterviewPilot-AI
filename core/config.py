"""
core/config.py — Constants and environment variable loading.

All named constants used across every agent and the orchestrator are
defined here. No hardcoded literals should appear anywhere else in the
codebase. Every number in an agent file must reference one of these names.

Sections
--------
1. API key
2. LLM model + token budgets
3. Rate limiting
4. Answer evaluation thresholds
5. Session / question rules
6. Hiring probability bands
7. Database
8. Orchestrator state machine labels
"""

import os

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# 1. API Key
# ---------------------------------------------------------------------------

# Gemini API key loaded from .env — never hardcode this value.
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# ---------------------------------------------------------------------------
# 2. LLM Model + Token Budgets
# ---------------------------------------------------------------------------

# The only permitted model for every LLM call in this project.
GEMINI_MODEL: str = "gemini-2.0-flash"

# Max output tokens for simple/fast agents (Evaluator).
MAX_TOKENS_SIMPLE: int = 1500

# Max output tokens for complex generation agents (Researcher, QuestionGenerator).
MAX_TOKENS_COMPLEX: int = 2000

# Max output tokens for the long-form final report (Coach).
MAX_TOKENS_REPORT: int = 2000

# ---------------------------------------------------------------------------
# 3. Rate Limiting
# ---------------------------------------------------------------------------

# Whether to enable Gemini Search Grounding for the Researcher agent.
# Set True only on paid tier — grounding adds 3,000–8,000 extra input tokens.
USE_SEARCH_GROUNDING: bool = False

# Seconds to sleep between consecutive LLM calls to respect Gemini rate limits.
RATE_LIMIT_SLEEP: int = 8

# Seconds to sleep before retrying after a non-JSON API / network error.
ERROR_RETRY_SLEEP: int = 35

# ---------------------------------------------------------------------------
# 4. Answer Evaluation Thresholds
# ---------------------------------------------------------------------------

# Minimum character count a user's answer must reach before LLM evaluation
# is triggered. Shorter answers receive a penalty dict immediately.
MIN_ANSWER_LENGTH: int = 50

# Evaluator total (sum of 4 subscores, each 1–5) below this → verdict "weak"
# and trigger_follow_up = True.
WEAK_SCORE_THRESHOLD: int = 12

# Evaluator total above this → verdict "strong". Between WEAK and STRONG → "good".
STRONG_SCORE_THRESHOLD: int = 16

# Maximum number of follow-up questions the system may ask per topic.
MAX_FOLLOW_UPS: int = 2

# ---------------------------------------------------------------------------
# 5. Session / Question Rules
# ---------------------------------------------------------------------------

# Default number of interview questions per session.
TOTAL_QUESTIONS: int = 5

# Minimum number of questions a user can select.
MIN_QUESTIONS: int = 2

# Maximum number of questions a user can select.
MAX_QUESTIONS: int = 15

# Minimum character length for a valid question or follow-up string.
MIN_QUESTION_LENGTH: int = 20

# Exact number of follow-up questions required per question dict.
FOLLOW_UP_COUNT: int = 2

# ---------------------------------------------------------------------------
# 6. Hiring Probability Bands
# ---------------------------------------------------------------------------

# Maximum possible aggregate score across all questions (num_questions × 20 pts).
# This is the default for 5 questions; actual max is computed dynamically.
MAX_TOTAL_SCORE: int = 100

# Aggregate score strictly below this → hiring probability "Low".
HIRING_LOW_MAX: int = 40

# Aggregate score strictly above this → hiring probability "High".
# Scores in [HIRING_LOW_MAX, HIRING_HIGH_MIN] → "Medium".
HIRING_HIGH_MIN: int = 70

# ---------------------------------------------------------------------------
# 7. Database
# ---------------------------------------------------------------------------

# Filename for the SQLite database created at project root.
DB_PATH: str = "interview_sessions.db"

# ---------------------------------------------------------------------------
# 8. Orchestrator State Machine Labels
# ---------------------------------------------------------------------------

# Ordered sequence of valid orchestrator states. Transitions must follow
# this order; skipping states is not permitted (see agents.md).
STATE_SETUP: str = "SETUP"
STATE_RESEARCHING: str = "RESEARCHING"
STATE_GENERATING: str = "GENERATING"
STATE_READY: str = "READY"
STATE_ASKING: str = "ASKING"
STATE_EVALUATING: str = "EVALUATING"
STATE_FOLLOW_UP: str = "FOLLOW_UP"
STATE_NEXT_Q: str = "NEXT_Q"
STATE_REPORT: str = "REPORT"
STATE_DONE: str = "DONE"
STATE_ERROR: str = "ERROR"

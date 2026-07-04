"""
agents/researcher.py — Researcher Agent for the Mock Interview Stress Tester.

Exposes one public function:
- research_company: uses Gemini 2.0 Flash with Search Grounding to discover
  company-specific interview patterns and returns a validated Research_Dict
  with exactly 8 keys.  On unrecoverable API failure, returns a safe
  Default_Dict (all 8 keys + error_flag=True) so downstream agents can
  always proceed.
"""

import json
import re
import time

# NOTE: Using google-genai SDK (not google-generativeai==0.8.3 from tech.md).
# If this is intentional (SDK migration), update tech.md to reflect the approved library.
from google import genai
from google.genai import types

from core.config import (
    GEMINI_MODEL,
    MAX_TOKENS_COMPLEX,
    RATE_LIMIT_SLEEP,
    ERROR_RETRY_SLEEP,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Canonical set of keys the LLM must return.
_REQUIRED_KEYS: tuple[str, ...] = (
    "company",
    "role",
    "interview_rounds",
    "key_topics",
    "difficulty",
    "culture_keywords",
    "known_question_types",
    "red_flags_to_test",
)

# Keys whose values must be non-empty lists of strings.
_LIST_KEYS: frozenset[str] = frozenset(
    {"key_topics", "culture_keywords", "known_question_types", "red_flags_to_test"}
)

# Keys whose values must be non-empty strings.
_STR_KEYS: frozenset[str] = frozenset(
    {"company", "role", "interview_rounds", "difficulty"}
)

# Maximum allowed length for company / role inputs before truncation.
_MAX_INPUT_LENGTH: int = 100

# Valid values for the "difficulty" field in a Research_Dict.
_VALID_DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard", "expert")

# Threshold: if fewer than this many fields can be populated from real data,
# fall back to role-appropriate defaults and set error_flag=True.
_GROUNDING_MIN_FIELDS: int = 5

# System prompt sent with every LLM call.
SYSTEM_PROMPT: str = """You are an expert technical recruiter with deep knowledge of how leading technology companies conduct interviews. Your task is to research the specific interview process for a given company, role, and experience level.

Return a JSON object with EXACTLY these 8 keys and no others:

{
  "company": "<string — canonical company name>",
  "role": "<string — job role as provided>",
  "interview_rounds": "<string — description of interview rounds, e.g. '5 rounds: online assessment, 2 technical, system design, behavioural'>",
  "key_topics": ["<topic1>", "<topic2>", ...],
  "difficulty": "<string — one of: easy, medium, hard, expert>",
  "culture_keywords": ["<value1>", "<value2>", ...],
  "known_question_types": ["<type1>", "<type2>", ...],
  "red_flags_to_test": ["<flag1>", "<flag2>", ...]
}

Rules:
- key_topics: at least 3 technical or functional topics this company is known to test
- culture_keywords: at least 2 values or principles this company emphasises in interviews
- known_question_types: at least 2 categories of questions (e.g. coding, system design, behavioural)
- red_flags_to_test: at least 2 areas where candidates commonly fail for this role/company
- difficulty: reflect realistic difficulty for the experience level provided
- If company-specific data is unavailable, use role-appropriate and level-appropriate industry defaults
- Never return null, empty strings, or empty lists for any key

Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _sanitize_input(value: str, field_name: str) -> str:
    """Validate and sanitize a user-supplied string input.

    Performs the following steps in order:
    1. Strip leading/trailing whitespace.
    2. Raise ValueError if the stripped string is empty.
    3. Truncate to ``_MAX_INPUT_LENGTH`` characters.
    4. Remove all characters that are not alphanumeric, space, or hyphen.
    5. Strip again and raise ValueError if the result is now empty (i.e. the
       original contained only special characters).

    Args:
        value: The raw string to sanitize (company name or role).
        field_name: Human-readable field label used in error messages.

    Returns:
        The sanitized string, safe for use in a search query prompt.

    Raises:
        ValueError: If ``value`` is empty/whitespace-only, or if sanitization
            removes all characters leaving an empty string.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError(
            f"research_company: '{field_name}' must not be empty or whitespace-only"
        )
    # Truncate before sanitizing to bound downstream work.
    truncated = stripped[:_MAX_INPUT_LENGTH]
    # Keep only alphanumeric characters, spaces, and hyphens.
    sanitized = re.sub(r"[^a-zA-Z0-9 \-]", "", truncated).strip()
    if not sanitized:
        raise ValueError(
            f"research_company: '{field_name}' is invalid after sanitization "
            f"(original value contained only special characters)"
        )
    return sanitized


def _safe_llm_call(
    prompt: str,
    system: str,
    client: genai.Client,
    max_tokens: int,
    agent_name: str,
    tools: list | None = None,
) -> dict:
    """Call the Gemini model with retry logic for JSON parse failures and API errors.

    Follows the canonical ``safe_llm_call`` template from ``agents.md``:
    - Attempt 1: make the LLM call, strip markdown, parse JSON.
    - On ``JSONDecodeError`` at attempt 1: sleep ``RATE_LIMIT_SLEEP`` seconds,
      append a JSON-only corrective instruction to the prompt, retry.
    - On ``JSONDecodeError`` at attempt 2: raise ``ValueError``.
    - On any non-JSON ``Exception`` at attempt 1: sleep ``ERROR_RETRY_SLEEP``
      seconds and retry without modifying the prompt.
    - On any non-JSON ``Exception`` at attempt 2: re-raise the original exception.

    Token usage is printed to stdout on every successful call.

    Args:
        prompt: User-side prompt text sent to the model.
        system: System instruction string.
        client: An initialised ``google.genai.Client`` instance.
        max_tokens: Maximum output token count to request.
        agent_name: Human-readable agent name used in log messages.
        tools: Optional list of tools to pass in the generation config.

    Returns:
        A Python dict parsed from the model's JSON response.

    Raises:
        ValueError: If JSON parsing fails on both attempts.
        Exception: Any non-JSON exception that persists after the single retry.
    """
    for attempt in range(2):
        try:
            config = types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
                tools=tools,
            )
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config,
            )
            text = response.text.strip()
            # Extract content from code fences if present (handles prose around fences)
            # First try ```json ... ``` block
            json_fence_match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
            if json_fence_match:
                text = json_fence_match.group(1).strip()
            else:
                # Try generic ``` ... ``` block
                generic_fence_match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
                if generic_fence_match:
                    text = generic_fence_match.group(1).strip()
                else:
                    # No fences found — use the text as-is (already stripped)
                    pass
            result = json.loads(text)
            print(f"[{agent_name}] Success. Tokens: {response.usage_metadata}")
            return result
        except json.JSONDecodeError as e:
            print(f"[{agent_name}] JSON fail attempt {attempt + 1}: {e}")
            if attempt == 0:
                time.sleep(RATE_LIMIT_SLEEP)
                prompt += "\n\nRETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."
            else:
                raise ValueError(f"{agent_name} failed after 2 attempts")
        except Exception as e:
            print(f"[{agent_name}] API error attempt {attempt + 1}: {e}")
            if attempt == 0:
                time.sleep(ERROR_RETRY_SLEEP)
            else:
                raise


def _build_default_dict(company: str, role: str, level: str) -> dict:
    """Build a role-appropriate Default_Dict when the API call is unrecoverable.

    Populates all 8 required Research_Dict keys with generic, role-appropriate
    and level-appropriate values, then appends ``error_flag=True`` to signal
    to downstream agents that the data is not company-specific.

    Difficulty mapping (from spec Requirement 6.4):
    - fresher  → "easy"
    - junior   → "medium"
    - senior   → "hard"
    - lead     → "expert"
    - manager  → "expert"
    - any other level → "medium" (safe fallback)

    ``key_topics`` is populated based on role keywords (Requirement 6.5).
    ``interview_rounds`` always defaults to ``"3 rounds"`` (Requirement 6.6).

    Args:
        company: Sanitized company name (used to populate the ``company`` key).
        role: Sanitized role string (used to populate the ``role`` key and
            to select appropriate generic topics).
        level: Experience level string as provided by the caller.

    Returns:
        A dict with all 8 Research_Dict keys plus ``error_flag=True``.
    """
    difficulty_map: dict[str, str] = {
        "fresher": "easy",
        "junior": "medium",
        "senior": "hard",
        "lead": "expert",
        "manager": "expert",
    }
    difficulty = difficulty_map.get(level.lower(), "medium")

    # Select key_topics based on broad role category keywords.
    role_lower = role.lower()
    if any(kw in role_lower for kw in ("data scientist", "ml", "machine learning", "ai")):
        key_topics = ["machine learning", "statistics", "python", "model evaluation", "data pipelines"]
    elif any(kw in role_lower for kw in ("data engineer", "data analyst", "analytics")):
        key_topics = ["sql", "data modeling", "etl pipelines", "data warehousing", "python"]
    elif any(kw in role_lower for kw in ("product manager", "product owner", "pm")):
        key_topics = ["product strategy", "user research", "metrics", "prioritization", "stakeholder management"]
    elif any(kw in role_lower for kw in ("devops", "sre", "platform", "infrastructure", "cloud")):
        key_topics = ["ci/cd", "containerization", "cloud infrastructure", "monitoring", "incident response"]
    elif any(kw in role_lower for kw in ("frontend", "front end", "ui", "react", "angular", "vue")):
        key_topics = ["javascript", "html/css", "browser rendering", "state management", "performance optimization"]
    elif any(kw in role_lower for kw in ("backend", "back end", "api", "server")):
        key_topics = ["api design", "databases", "system design", "concurrency", "caching"]
    else:
        # Generic software engineering default
        key_topics = ["data structures", "algorithms", "system design", "object-oriented design", "debugging"]

    return {
        "company": company,
        "role": role,
        "interview_rounds": "3 rounds",
        "key_topics": key_topics,
        "difficulty": difficulty,
        "culture_keywords": ["collaboration", "ownership"],
        "known_question_types": ["coding", "behavioural"],
        "red_flags_to_test": ["problem-solving approach", "communication clarity"],
        "error_flag": True,
    }


def _validate_research_dict(raw: dict) -> dict:
    """Validate and clean the LLM-parsed Research_Dict.

    Performs the following checks in order:
    1. Verifies all 8 required keys are present; raises ``ValueError`` on any
       missing key.
    2. For string keys: verifies the value is a non-empty ``str`` after
       stripping whitespace.
    3. For list keys: verifies the value is a non-empty ``list`` where every
       element is a non-empty ``str``.
    4. Strips any extra keys returned by the LLM (keeps only the 8 required).

    Args:
        raw: The dict returned by ``_safe_llm_call`` before validation.

    Returns:
        A clean dict containing exactly the 8 required keys, with all values
        validated.

    Raises:
        ValueError: If any required key is missing, or if any value fails type
            or non-empty validation.
    """
    # Step 1 — all required keys must be present.
    missing = [k for k in _REQUIRED_KEYS if k not in raw]
    if missing:
        raise ValueError(
            f"Researcher: LLM response missing required keys: {missing}"
        )

    # Step 2 & 3 — type and non-empty validation.
    for key in _STR_KEYS:
        val = raw[key]
        if not isinstance(val, str) or not val.strip():
            raise ValueError(
                f"Researcher: key '{key}' must be a non-empty string, got {val!r}"
            )

    # Step 2b — difficulty must be one of the allowed values.
    if raw["difficulty"] not in _VALID_DIFFICULTIES:
        raise ValueError(
            f"Researcher: key 'difficulty' must be one of {_VALID_DIFFICULTIES}, "
            f"got {raw['difficulty']!r}"
        )

    for key in _LIST_KEYS:
        val = raw[key]
        if not isinstance(val, list) or len(val) == 0:
            raise ValueError(
                f"Researcher: key '{key}' must be a non-empty list, got {val!r}"
            )
        for i, item in enumerate(val):
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    f"Researcher: key '{key}[{i}]' must be a non-empty string, got {item!r}"
                )

    # Step 4 — strip extra keys, return only the required 8.
    return {k: raw[k] for k in _REQUIRED_KEYS}


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def research_company(
    company: str,
    role: str,
    level: str,
    api_key: str,
) -> dict:
    """Research a company's interview patterns using Gemini Search Grounding.

    Pipeline:
    1. Validate and sanitize ``company`` and ``role`` inputs.
    2. Sleep ``RATE_LIMIT_SLEEP`` seconds if a prior LLM call preceded this one
       in the session.  The caller (orchestrator) is responsible for passing
       ``is_first_call=True`` only when no prior LLM call has been made;
       this function always sleeps to be safe, as the researcher is never the
       first step when called in a real session (SETUP state precedes it).
    3. Configure Gemini with ``api_key`` and build a ``GenerativeModel`` with
       Search Grounding enabled via ``google_search_retrieval`` tool.
    4. Build a search-optimised prompt using the sanitized inputs and the
       query format defined in the spec:
       ``"{company} {role} interview questions experience {level} 2024 2025"``
    5. Delegate the LLM call to ``_safe_llm_call``.
    6. Validate and strip the returned dict via ``_validate_research_dict``.
    7. Return the validated Research_Dict.
    8. On any unrecoverable exception (API failure after retries, or validation
       failure), return a ``Default_Dict`` via ``_build_default_dict`` with
       ``error_flag=True`` rather than crashing.

    Args:
        company: Company name as entered by the user (1–100 chars, non-empty).
            Special characters (non-alphanumeric, non-space, non-hyphen) are
            removed before use.
        role: Job role as entered by the user (1–100 chars, non-empty).
            Same sanitization as ``company``.
        level: Experience level.  Expected values: fresher, junior, senior,
            lead, manager.  Used verbatim in the prompt and to calibrate the
            Default_Dict difficulty.
        api_key: Gemini API key for this invocation.  Never logged or hardcoded.

    Returns:
        A validated Research_Dict with exactly 8 keys on success:
        ``company`` (str), ``role`` (str), ``interview_rounds`` (str),
        ``key_topics`` (list[str]), ``difficulty`` (str),
        ``culture_keywords`` (list[str]), ``known_question_types`` (list[str]),
        ``red_flags_to_test`` (list[str]).

        On unrecoverable failure: the same 8 keys populated with
        role-appropriate defaults, plus ``error_flag=True``.

    Raises:
        ValueError: If ``company`` or ``role`` is empty, whitespace-only, or
            reduces to an empty string after sanitization.  These are
            programming errors that must be fixed by the caller.
    """
    # ------------------------------------------------------------------
    # Step 1: Input validation and sanitization
    # (ValueError here is intentional — bad inputs must not silently default)
    # ------------------------------------------------------------------
    clean_company = _sanitize_input(company, "company")
    clean_role = _sanitize_input(role, "role")

    # ------------------------------------------------------------------
    # Step 2: Rate-limit sleep
    # The researcher always follows SETUP in the orchestrator state machine,
    # so there will always be session-init work before this call. Sleep here
    # unconditionally to respect the 4-second inter-call rule.
    # ------------------------------------------------------------------
    time.sleep(RATE_LIMIT_SLEEP)

    # ------------------------------------------------------------------
    # Step 3: Configure Gemini with Search Grounding
    # Search grounding is enabled ONLY for the researcher (per tech.md).
    # ------------------------------------------------------------------
    client = genai.Client(api_key=api_key)
    search_tool = types.Tool(google_search=types.GoogleSearch())

    # ------------------------------------------------------------------
    # Step 4: Build the search-optimised prompt
    # Query format from spec: "{company} {role} interview questions
    # experience {level} 2024 2025"
    # ------------------------------------------------------------------
    search_query = f"{clean_company} {clean_role} interview questions experience {level} 2024 2025"
    user_prompt = f"""Research the interview process for the following:

Company: {clean_company}
Role: {clean_role}
Experience Level: {level}

Search query used to find information: "{search_query}"

Based on your search results, return a JSON object describing this company's interview patterns for this role and experience level. If you cannot find specific information about this company, use general industry standards for the role and level.

Return ONLY a JSON object with exactly these 8 keys: company, role, interview_rounds, key_topics, difficulty, culture_keywords, known_question_types, red_flags_to_test."""

    # ------------------------------------------------------------------
    # Steps 5–7: LLM call → validate → return
    # ------------------------------------------------------------------
    try:
        raw = _safe_llm_call(
            prompt=user_prompt,
            system=SYSTEM_PROMPT,
            client=client,
            max_tokens=MAX_TOKENS_COMPLEX,
            agent_name="Researcher",
            tools=[search_tool],
        )
        validated = _validate_research_dict(raw)
        return validated

    except Exception as e:
        # ------------------------------------------------------------------
        # Step 8: Unrecoverable failure — return Default_Dict, never crash
        # (Covers both API errors re-raised by _safe_llm_call and
        # ValueError from _validate_research_dict)
        # ------------------------------------------------------------------
        print(f"[Researcher] Unrecoverable error, returning default dict: {e}")
        return _build_default_dict(clean_company, clean_role, level)

"""
agents/question_generator.py — Question Generator Agent for the Mock Interview Stress Tester.

Exposes one public function and one custom exception:
- QuestionGenerationError: raised on any unrecoverable generation failure.
- generate_questions: takes compressed researcher output and an api_key,
  makes exactly ONE LLM call for all 10 questions, validates structure and
  category distribution, normalises follow-ups, saves to SQLite, and
  returns a list of 10 validated Question_Dict objects.
"""

import json
import re
import time
import uuid

from google import genai
from google.genai import types

from core.config import (
    GEMINI_MODEL,
    MAX_TOKENS_COMPLEX,
    RATE_LIMIT_SLEEP,
    ERROR_RETRY_SLEEP,
    TOTAL_QUESTIONS,
    MIN_QUESTION_LENGTH,
    FOLLOW_UP_COUNT,
)
from core.database import save_questions

# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class QuestionGenerationError(Exception):
    """Raised when question generation fails after exhausting all retry attempts.

    Attributes:
        message: Human-readable description of the failure mode, always
            prefixed with "Question_Generator_Agent" so the orchestrator can
            identify the source reliably.
    """

    def __init__(self, message: str) -> None:
        """Initialise QuestionGenerationError with a descriptive message.

        Args:
            message: Failure description.  Will be stored in ``self.message``
                and forwarded to the base ``Exception`` constructor so that
                ``str(exc)`` returns the same text.
        """
        self.message = message
        super().__init__(message)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

# Valid category strings (exact, case-sensitive).
_VALID_CATEGORIES: frozenset[str] = frozenset(["technical", "behavioral", "situational", "curveball"])

# Per-category fallback follow-up strings used when the LLM returns too few
# or invalid follow-up items.
_FALLBACK_FOLLOW_UPS: dict[str, list[str]] = {
    "technical": [
        "Can you walk me through your technical approach step by step?",
        "What alternative technical solutions did you consider and why did you choose this one?",
    ],
    "behavioral": [
        "Can you provide a specific example from your experience?",
        "What was the outcome and what would you do differently in hindsight?",
    ],
    "situational": [
        "How would you prioritize the competing constraints in that scenario?",
        "What stakeholders would you involve and how would you communicate your decision?",
    ],
    "curveball": [
        "Can you elaborate on your reasoning process for that answer?",
        "How does your answer connect to the core responsibilities of this role?",
    ],
}

# System prompt — must end with the exact required footer per agents.md.
SYSTEM_PROMPT: str = """You are an expert technical interview question designer. Your task is to generate exactly {total} company-specific interview questions based on the research data provided.

QUESTION DISTRIBUTION — distribute categories across {total} questions:
- Use a mix of "technical", "behavioral", "situational", and "curveball" categories
- At least 1 question of each category type when total >= 4
- For fewer than 4 questions, prioritize "technical" and "behavioral"
- "technical" should make up the largest share

DIFFICULTY PROGRESSION — questions MUST get progressively harder:
- Question 1: difficulty 1 (easiest)
- Question {total}: difficulty {total} (hardest)
Each question's difficulty field must equal its 1-based position in the list.

OUTPUT FORMAT — return a JSON object with a "questions" key containing a list of exactly {total} objects. Each object must have exactly these 7 keys:

{{
  "id": "<UUID4 string>",
  "category": "<one of: technical, behavioral, situational, curveball>",
  "question": "<interview question text, at least 20 characters>",
  "ideal_keywords": ["<keyword1>", "<keyword2>", "<keyword3>"],
  "difficulty": <integer 1-{total}>,
  "follow_ups": ["<follow-up question 1>", "<follow-up question 2>"],
  "scoring_hint": "<brief guidance on what a strong answer should cover>"
}}

RULES:
- Every question must be specific to the company, role, and experience level in the research data
- If error_flag is true in research data, base questions on role/level/key_topics only, do not reference the company by name
- ideal_keywords must have at least 3 items per question
- follow_ups must have exactly 2 items per question
- question text must be at least 20 characters
- scoring_hint must be a non-empty string
- All category values must be exactly one of: technical, behavioral, situational, curveball

Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _safe_llm_call(
    prompt: str,
    system: str,
    client: genai.Client,
    max_tokens: int,
    agent_name: str,
) -> dict:
    """Call the Gemini model with retry logic for JSON parse failures and API errors.

    Follows the canonical ``safe_llm_call`` template from ``agents.md`` exactly:
    - 2-attempt loop.
    - On ``JSONDecodeError`` at attempt 0: sleep ``RATE_LIMIT_SLEEP``, append
      corrective instruction, retry.
    - On ``JSONDecodeError`` at attempt 1: raise ``QuestionGenerationError``.
    - On non-JSON ``Exception`` at attempt 0: sleep ``ERROR_RETRY_SLEEP``, retry.
    - On non-JSON ``Exception`` at attempt 1: re-raise wrapped in
      ``QuestionGenerationError``.

    Token usage is printed to stdout on every successful call.

    Args:
        prompt: User-side prompt text sent to the model.
        system: System instruction string.
        client: An initialised ``google.genai.Client`` instance.
        max_tokens: Maximum output token count to request.
        agent_name: Human-readable agent name used in log messages.

    Returns:
        A Python dict parsed from the model's JSON response.

    Raises:
        QuestionGenerationError: If JSON parsing or the API call fails on
            both attempts.
    """
    for attempt in range(3):
        try:
            config = types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            )
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config,
            )
            text = response.text.strip()
            # Strip markdown code fences: ```json ... ``` then ``` ... ```
            json_fence_match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
            if json_fence_match:
                text = json_fence_match.group(1).strip()
            else:
                generic_fence_match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
                if generic_fence_match:
                    text = generic_fence_match.group(1).strip()
            result = json.loads(text)
            print(f"[{agent_name}] Success. Tokens: {response.usage_metadata}")
            return result
        except json.JSONDecodeError as e:
            print(f"[{agent_name}] JSON fail attempt {attempt + 1}: {e}")
            if attempt < 2:
                time.sleep(RATE_LIMIT_SLEEP)
                if attempt == 0:
                    prompt += "\n\nRETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."
            else:
                raise QuestionGenerationError(
                    f"Question_Generator_Agent: JSON parse failure after 3 attempts: {e}"
                )
        except Exception as e:
            error_str = str(e)
            print(f"[{agent_name}] API error attempt {attempt + 1}: {e}")
            if attempt < 2:
                if "429" in error_str:
                    retry_match = re.search(r"retry in (\d+(?:\.\d+)?)s", error_str, re.IGNORECASE)
                    if retry_match:
                        wait_time = int(float(retry_match.group(1))) + 2
                    else:
                        wait_time = 30 * (attempt + 1)
                    print(f"[{agent_name}] Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    time.sleep(ERROR_RETRY_SLEEP)
            else:
                raise QuestionGenerationError(
                    f"Question_Generator_Agent: API error after 3 attempts: {e}"
                )


def _normalize_follow_ups(question: dict) -> dict:
    """Ensure a question's ``follow_ups`` list has exactly ``FOLLOW_UP_COUNT`` valid strings.

    Normalization rules applied in order:
    1. If ``follow_ups`` is not a list, replace it entirely with fallback items.
    2. For each existing item: if it is not a non-empty string, replace it with
       the next available category-appropriate fallback.
    3. If the list is shorter than ``FOLLOW_UP_COUNT``, pad with fallback items.
    4. If the list is longer than ``FOLLOW_UP_COUNT``, trim to ``FOLLOW_UP_COUNT``.

    Fallback strings are selected from ``_FALLBACK_FOLLOW_UPS`` keyed by
    ``question["category"]``; if the category is unrecognised, the
    ``"technical"`` fallback list is used.

    Args:
        question: A single Question_Dict (mutated in-place).  Must contain
            a ``"category"`` key.

    Returns:
        The same dict with ``follow_ups`` normalised to exactly
        ``FOLLOW_UP_COUNT`` valid strings.
    """
    category = question.get("category", "technical")
    fallbacks = _FALLBACK_FOLLOW_UPS.get(category, _FALLBACK_FOLLOW_UPS["technical"])
    fallback_idx = 0

    existing = question.get("follow_ups", [])
    if not isinstance(existing, list):
        existing = []

    normalized: list[str] = []
    for item in existing:
        if isinstance(item, str) and item.strip():
            normalized.append(item)
        else:
            # Replace invalid item with next fallback, cycling if necessary
            normalized.append(fallbacks[fallback_idx % len(fallbacks)])
            fallback_idx += 1

    # Pad if too short
    while len(normalized) < FOLLOW_UP_COUNT:
        normalized.append(fallbacks[fallback_idx % len(fallbacks)])
        fallback_idx += 1

    # Trim if too long
    question["follow_ups"] = normalized[:FOLLOW_UP_COUNT]
    return question


def _assign_ids_and_difficulties(questions: list[dict]) -> list[dict]:
    """Assign UUID4 ids and sequential 1-based difficulty values to all questions.

    Overwrites any existing ``id`` and ``difficulty`` values so that:
    - Every question has a fresh UUID4 ``id`` (generated by this function,
      not trusted from the LLM).
    - Difficulty equals the 1-based position in the list (Q1→1, Q10→10).

    Args:
        questions: List of ``TOTAL_QUESTIONS`` Question_Dict objects.

    Returns:
        The same list with ``id`` and ``difficulty`` fields overwritten.
    """
    for i, q in enumerate(questions):
        q["id"] = str(uuid.uuid4())
        q["difficulty"] = i + 1
    return questions


def validate_questions(questions: list[dict], num_questions: int = TOTAL_QUESTIONS) -> tuple[bool, str]:
    """Validate a list of Question_Dict objects for structural correctness.

    Checks performed (in order):
    1. Exactly ``num_questions`` items in the list.
    2. Each item is a dict.
    3. All 7 required keys present per question.
    4. ``id`` is a non-empty string.
    5. ``category`` is one of the four valid values.
    6. ``question`` text is at least ``MIN_QUESTION_LENGTH`` characters.
    7. ``ideal_keywords`` is a non-empty list of strings.
    8. ``difficulty`` is an integer 1–num_questions.
    9. ``follow_ups`` is a list (normalisation handles length; validated here
       only for type).
    10. ``scoring_hint`` is a non-empty string.

    Args:
        questions: List of dicts to validate.
        num_questions: Expected number of questions.

    Returns:
        A tuple ``(is_valid, reason)`` where ``is_valid`` is True only when
        all checks pass, and ``reason`` is an empty string on success or a
        human-readable failure description on failure.
    """
    if len(questions) != num_questions:
        return False, (
            f"Expected {num_questions} questions, got {len(questions)}"
        )

    required_keys = {"id", "category", "question", "ideal_keywords",
                     "difficulty", "follow_ups", "scoring_hint"}

    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            return False, f"Question[{i}] is not a dict"

        missing = required_keys - set(q.keys())
        if missing:
            return False, f"Question[{i}] missing keys: {missing}"

        if not isinstance(q["id"], str) or not q["id"].strip():
            return False, f"Question[{i}] 'id' must be a non-empty string"

        if q["category"] not in _VALID_CATEGORIES:
            return False, (
                f"Question[{i}] invalid category: {q['category']!r}. "
                f"Must be one of {sorted(_VALID_CATEGORIES)}"
            )

        if not isinstance(q["question"], str) or len(q["question"]) < MIN_QUESTION_LENGTH:
            actual_len = len(q["question"]) if isinstance(q["question"], str) else 0
            return False, (
                f"Question[{i}] 'question' must be at least "
                f"{MIN_QUESTION_LENGTH} chars, got {actual_len}"
            )

        kws = q["ideal_keywords"]
        if not isinstance(kws, list) or len(kws) == 0:
            return False, f"Question[{i}] 'ideal_keywords' must be a non-empty list"
        for j, kw in enumerate(kws):
            if not isinstance(kw, str) or not kw.strip():
                return False, (
                    f"Question[{i}] 'ideal_keywords[{j}]' must be a non-empty string"
                )

        diff = q["difficulty"]
        if not isinstance(diff, int) or not (1 <= diff <= num_questions):
            return False, (
                f"Question[{i}] 'difficulty' must be int 1-{num_questions}, got {diff!r}"
            )

        if not isinstance(q["follow_ups"], list):
            return False, f"Question[{i}] 'follow_ups' must be a list"

        if not isinstance(q["scoring_hint"], str) or not q["scoring_hint"].strip():
            return False, f"Question[{i}] 'scoring_hint' must be a non-empty string"

    return True, ""


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def generate_questions(
    research_data: dict,
    session_id: str,
    api_key: str,
    num_questions: int = TOTAL_QUESTIONS,
) -> list[dict]:
    """Generate exactly num_questions company-specific interview questions from researcher output.

    Pipeline
    --------
    1. **Input validation** — verify ``research_data`` contains all 8 required
       Researcher keys and that ``api_key`` is non-empty.
    2. **Rate-limit sleep** — sleep ``RATE_LIMIT_SLEEP`` seconds (the researcher
       LLM call always precedes this one in the orchestrator flow).
    3. **Research compression** — serialize ``research_data`` with
       ``json.dumps(research_data, separators=(',',':'))`` to minimise tokens.
    4. **LLM call** — configure Gemini (no search grounding), build the prompt
       incorporating compressed research, call ``_safe_llm_call`` with
       ``MAX_TOKENS_COMPLEX``.
    5. **Count check with retry** — if the ``"questions"`` list length ≠
       ``num_questions``, append a corrective instruction, sleep
       ``RATE_LIMIT_SLEEP``, and retry once.  Raise ``QuestionGenerationError``
       if the count is still wrong after retry.
    6. **Structural validation** — call ``validate_questions``.  On failure,
       append a corrective instruction and retry once (with sleep).  Raise
       ``QuestionGenerationError`` on second failure.
    7. **Post-processing** — assign UUIDs and sequential difficulties via
       ``_assign_ids_and_difficulties``, then normalise follow-ups on every
       question via ``_normalize_follow_ups``.
    8. **Database save** — call ``save_questions(session_id, questions)``.
    9. **Return** the validated, normalised list of Question_Dict objects.

    Args:
        research_data: Validated Researcher output dict with at least these 8
            keys: ``company``, ``role``, ``interview_rounds``, ``key_topics``,
            ``difficulty``, ``culture_keywords``, ``known_question_types``,
            ``red_flags_to_test``.  May also contain ``error_flag=True`` for
            unknown companies.
        session_id: UUID string identifying the current interview session.
            Passed directly to ``save_questions``.
        api_key: Gemini API key for this invocation.  Never logged or hardcoded.
        num_questions: Number of questions to generate (2–15).

    Returns:
        A list of exactly ``num_questions`` validated Question_Dict objects,
        each containing exactly these 7 keys: ``id`` (str, UUID4),
        ``category`` (str), ``question`` (str), ``ideal_keywords`` (list[str]),
        ``difficulty`` (int 1–num_questions), ``follow_ups`` (list of exactly
        ``FOLLOW_UP_COUNT`` str), ``scoring_hint`` (str).

    Raises:
        QuestionGenerationError: On any of the following conditions:
            - ``research_data`` is missing required keys or ``api_key`` is empty.
            - The LLM fails to return valid JSON after 2 attempts.
            - The ``"questions"`` list length ≠ ``num_questions`` after retry.
            - Structural validation fails after retry.
            - Database write fails.
    """
    # ------------------------------------------------------------------
    # Step 1: Input validation
    # ------------------------------------------------------------------
    required_research_keys = {
        "company", "role", "interview_rounds", "key_topics",
        "difficulty", "culture_keywords", "known_question_types", "red_flags_to_test",
    }
    missing_keys = required_research_keys - set(research_data.keys())
    if missing_keys:
        raise QuestionGenerationError(
            f"Question_Generator_Agent: research_data missing required keys: {missing_keys}"
        )
    if not isinstance(api_key, str) or not api_key.strip():
        raise QuestionGenerationError(
            "Question_Generator_Agent: api_key must be a non-empty string"
        )

    # ------------------------------------------------------------------
    # Step 2: Rate-limit sleep (researcher call always precedes this)
    # ------------------------------------------------------------------
    time.sleep(RATE_LIMIT_SLEEP)

    # ------------------------------------------------------------------
    # Step 3: Compress research_data (token optimisation per spec)
    # ------------------------------------------------------------------
    compressed_research = json.dumps(research_data, separators=(",", ":"))

    # ------------------------------------------------------------------
    # Step 4: Configure Gemini (no search grounding — researcher only)
    # ------------------------------------------------------------------
    client = genai.Client(api_key=api_key)

    # Build system prompt with num_questions substituted
    system = SYSTEM_PROMPT.format(total=num_questions)

    # Detect error_flag to adjust instruction tone and strip company name
    error_flag = research_data.get("error_flag", False)
    if error_flag:
        # Exclude the company field so the prompt contains no company name reference
        prompt_research = {k: v for k, v in research_data.items() if k != "company"}
        prompt_compressed = json.dumps(prompt_research, separators=(",", ":"))
        company_instruction = (
            "NOTE: Company-specific data is unavailable. "
            "Generate questions based solely on the role, experience level, "
            "and key_topics provided. Do NOT mention the company by name."
        )
    else:
        prompt_compressed = compressed_research
        company_instruction = (
            f"Generate questions tailored specifically to {research_data['company']}."
        )

    user_prompt = (
        f"Generate exactly {num_questions} interview questions based on this research data.\n\n"
        f"Research data (compressed): {prompt_compressed}\n\n"
        f"{company_instruction}\n\n"
        f"Remember: distribute categories appropriately across {num_questions} questions. "
        f"Difficulty must increase from 1 (Q1) to {num_questions} (Q{num_questions})."
    )

    # ------------------------------------------------------------------
    # Steps 5–6: LLM call + count check + structural validation
    # Both share the same retry budget: 1 initial + 1 retry = 2 total.
    # _safe_llm_call handles its own JSON-parse retry internally.
    # Our outer loop handles count and structure failures.
    # ------------------------------------------------------------------
    raw_response: dict | None = None
    questions: list[dict] = []
    current_prompt = user_prompt

    for attempt in range(2):
        if attempt == 1:
            # Sleep before retry (count or validation failure on attempt 0)
            time.sleep(RATE_LIMIT_SLEEP)

        raw_response = _safe_llm_call(
            prompt=current_prompt,
            system=system,
            client=client,
            max_tokens=MAX_TOKENS_COMPLEX,
            agent_name="QuestionGenerator",
        )

        # Extract "questions" list
        if not isinstance(raw_response, dict) or "questions" not in raw_response:
            failure_reason = "'questions' key missing from LLM response"
            if attempt == 0:
                print(f"[QuestionGenerator] {failure_reason}, retrying...")
                current_prompt = (
                    user_prompt
                    + f"\n\nCRITICAL: Your response MUST be a JSON object with a "
                    f"'questions' key containing exactly {num_questions} question objects. "
                    f"RETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."
                )
                continue
            raise QuestionGenerationError(
                f"Question_Generator_Agent: {failure_reason} after 2 attempts"
            )

        questions = raw_response["questions"]

        # Step 5: Count check
        if len(questions) != num_questions:
            failure_reason = (
                f"wrong question count: expected {num_questions}, "
                f"got {len(questions)}"
            )
            if attempt == 0:
                print(f"[QuestionGenerator] {failure_reason}, retrying...")
                current_prompt = (
                    user_prompt
                    + f"\n\nCRITICAL: You returned {len(questions)} questions. "
                    f"You MUST return EXACTLY {num_questions} questions. "
                    f"RETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."
                )
                continue
            raise QuestionGenerationError(
                f"Question_Generator_Agent: {failure_reason} after 2 attempts"
            )

        # Step 6: Structural + distribution validation
        is_valid, reason = validate_questions(questions, num_questions)
        if not is_valid:
            if attempt == 0:
                print(f"[QuestionGenerator] Validation failed: {reason}, retrying...")
                current_prompt = (
                    user_prompt
                    + f"\n\nCRITICAL: Validation failed — {reason}. "
                    f"Fix all issues and return EXACTLY {num_questions} valid questions. "
                    f"RETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."
                )
                continue
            raise QuestionGenerationError(
                f"Question_Generator_Agent: validation failed after 2 attempts — {reason}"
            )

        # Both checks passed — exit the retry loop
        break

    # ------------------------------------------------------------------
    # Step 7: Post-processing — assign UUIDs + sequential difficulties,
    # then normalise follow-ups on every question.
    # ------------------------------------------------------------------
    questions = _assign_ids_and_difficulties(questions)
    for q in questions:
        _normalize_follow_ups(q)

    # ------------------------------------------------------------------
    # Step 8: Persist all questions to SQLite before returning
    # ------------------------------------------------------------------
    try:
        save_questions(session_id, questions)
    except Exception as e:
        raise QuestionGenerationError(
            f"Question_Generator_Agent: database write failed: {e}"
        )

    # ------------------------------------------------------------------
    # Step 9: Return validated, normalised, persisted question list
    # ------------------------------------------------------------------
    return questions

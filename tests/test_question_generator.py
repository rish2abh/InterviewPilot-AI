"""
tests/test_question_generator.py — Unit tests for agents/question_generator.py

This file is the single test module for the Question Generator Agent.
Tests are appended in task order (Task 9, 10, 11, 12, …).

Task 12: Unit tests — retry loop in generate_questions
  Requirement: 2.2, 2.4, 6.1–6.3
"""

import time
import unittest
from unittest.mock import MagicMock, call, patch

import pytest

from agents.question_generator import (
    QuestionGenerationError,
    generate_questions,
)
from core.config import (
    FOLLOW_UP_COUNT,
    RATE_LIMIT_SLEEP,
    TOTAL_QUESTIONS,
)

# ---------------------------------------------------------------------------
# Shared test fixtures / helpers
# ---------------------------------------------------------------------------

# Minimal valid research_data dict with all 8 required keys.
VALID_RESEARCH = {
    "company": "Acme Corp",
    "role": "Software Engineer",
    "interview_rounds": "3",
    "key_topics": "Python, system design",
    "difficulty": "medium",
    "culture_keywords": "innovation, teamwork",
    "known_question_types": "behavioural, technical",
    "red_flags_to_test": "ownership, communication",
}

VALID_API_KEY = "test-api-key"
VALID_SESSION_ID = "session-uuid-1234"


def _make_question(category: str, index: int = 0) -> dict:
    """Return a minimal valid Question_Dict for the given category."""
    return {
        "id": f"llm-id-{index}",
        "category": category,
        "question": "Tell me about a challenging project you worked on recently?",
        "ideal_keywords": ["architecture", "trade-offs", "delivery"],
        "difficulty": index + 1,
        "follow_ups": [
            "Can you elaborate on the trade-offs you made?",
            "What would you do differently next time?",
        ],
        "scoring_hint": "Look for evidence of ownership and technical depth.",
    }


def _make_valid_10_questions() -> list[dict]:
    """
    Return exactly 10 valid questions matching the required distribution:
    4 technical, 3 behavioral, 2 situational, 1 curveball.
    """
    distribution = (
        ["technical"] * 4
        + ["behavioral"] * 3
        + ["situational"] * 2
        + ["curveball"] * 1
    )
    return [_make_question(cat, i) for i, cat in enumerate(distribution)]


def _make_questions_with_bad_category(bad_index: int = 0) -> list[dict]:
    """
    Return 10 questions where the question at bad_index has an invalid category.
    The remaining 9 questions keep the correct distribution minus one technical.
    """
    qs = _make_valid_10_questions()
    qs[bad_index]["category"] = "invalid_category_xyz"
    return qs


# ---------------------------------------------------------------------------
# Task 12: Retry loop in generate_questions
# ---------------------------------------------------------------------------


class TestGenerateQuestionsRetryLoop:
    """Unit tests for the 2-attempt outer retry loop in generate_questions.

    All tests mock:
      - agents.question_generator._safe_llm_call  (control LLM output)
      - core.database.save_questions              (avoid DB writes)
      - time.sleep                                 (track sleep calls)
    """

    # -----------------------------------------------------------------------
    # Test 1: LLM returns 9 questions on attempt 0, 10 questions on attempt 1
    #         → function returns list of 10
    # -----------------------------------------------------------------------
    def test_retry_on_wrong_count_succeeds_on_second_attempt(self) -> None:
        """LLM returns 9 questions on attempt 0, 10 on attempt 1 → returns 10."""
        nine_questions = _make_valid_10_questions()[:9]
        ten_questions = _make_valid_10_questions()

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch("agents.question_generator.save_questions"),
            patch("time.sleep"),
        ):
            mock_llm.side_effect = [
                {"questions": nine_questions},   # attempt 0 → wrong count
                {"questions": ten_questions},    # attempt 1 → correct
            ]

            result = generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        assert isinstance(result, list)
        assert len(result) == TOTAL_QUESTIONS

    # -----------------------------------------------------------------------
    # Test 2: LLM always returns 9 questions → QuestionGenerationError raised
    # -----------------------------------------------------------------------
    def test_always_wrong_count_raises_error(self) -> None:
        """LLM returns 9 questions on both attempts → QuestionGenerationError."""
        nine_questions = _make_valid_10_questions()[:9]

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch("agents.question_generator.save_questions"),
            patch("time.sleep"),
        ):
            mock_llm.return_value = {"questions": nine_questions}

            with pytest.raises(QuestionGenerationError) as exc_info:
                generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        assert "9" in str(exc_info.value) or "count" in str(exc_info.value).lower()

    # -----------------------------------------------------------------------
    # Test 3: LLM returns invalid category on attempt 0, valid on attempt 1
    #         → returns list of 10
    # -----------------------------------------------------------------------
    def test_retry_on_invalid_category_succeeds_on_second_attempt(self) -> None:
        """LLM returns invalid category on attempt 0, valid on attempt 1 → returns 10."""
        bad_questions = _make_questions_with_bad_category(bad_index=0)
        good_questions = _make_valid_10_questions()

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch("agents.question_generator.save_questions"),
            patch("time.sleep"),
        ):
            mock_llm.side_effect = [
                {"questions": bad_questions},   # attempt 0 → validate_questions fails
                {"questions": good_questions},  # attempt 1 → passes
            ]

            result = generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        assert isinstance(result, list)
        assert len(result) == TOTAL_QUESTIONS

    # -----------------------------------------------------------------------
    # Test 4: LLM always returns invalid distribution → QuestionGenerationError
    # -----------------------------------------------------------------------
    def test_always_invalid_distribution_raises_error(self) -> None:
        """LLM always returns wrong category distribution → QuestionGenerationError."""
        # 10 questions, all "technical" — wrong distribution
        all_technical = [_make_question("technical", i) for i in range(TOTAL_QUESTIONS)]

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch("agents.question_generator.save_questions"),
            patch("time.sleep"),
        ):
            mock_llm.return_value = {"questions": all_technical}

            with pytest.raises(QuestionGenerationError) as exc_info:
                generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        error_msg = str(exc_info.value).lower()
        assert "validation" in error_msg or "distribution" in error_msg or "category" in error_msg

    # -----------------------------------------------------------------------
    # Test 5: time.sleep(RATE_LIMIT_SLEEP) called twice when retry is triggered
    #         (once before attempt 0 in Step 2, once before attempt 1 in retry)
    # -----------------------------------------------------------------------
    def test_sleep_called_twice_when_retry_triggered(self) -> None:
        """time.sleep(RATE_LIMIT_SLEEP) is called exactly twice when a retry occurs."""
        nine_questions = _make_valid_10_questions()[:9]
        ten_questions = _make_valid_10_questions()

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch("agents.question_generator.save_questions"),
            patch("agents.question_generator.time") as mock_time,
        ):
            mock_llm.side_effect = [
                {"questions": nine_questions},  # attempt 0 → triggers retry
                {"questions": ten_questions},   # attempt 1 → succeeds
            ]

            generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        # Collect all sleep calls
        sleep_calls = mock_time.sleep.call_args_list

        # Both calls must use RATE_LIMIT_SLEEP
        rate_limit_calls = [c for c in sleep_calls if c == call(RATE_LIMIT_SLEEP)]
        assert len(rate_limit_calls) == 2, (
            f"Expected 2 time.sleep({RATE_LIMIT_SLEEP}) calls, "
            f"got {len(rate_limit_calls)} out of {sleep_calls}"
        )

    # -----------------------------------------------------------------------
    # Test 6: Corrective prompt text is appended when retrying wrong count
    # -----------------------------------------------------------------------
    def test_corrective_prompt_appended_on_wrong_count_retry(self) -> None:
        """When count is wrong on attempt 0, a corrective instruction is appended to the prompt on retry."""
        nine_questions = _make_valid_10_questions()[:9]
        ten_questions = _make_valid_10_questions()

        captured_prompts: list[str] = []

        def capture_llm_call(prompt, system, model, max_tokens, agent_name):
            captured_prompts.append(prompt)
            if len(captured_prompts) == 1:
                return {"questions": nine_questions}   # attempt 0 — wrong count
            return {"questions": ten_questions}        # attempt 1 — correct

        with (
            patch("agents.question_generator._safe_llm_call", side_effect=capture_llm_call),
            patch("agents.question_generator.save_questions"),
            patch("time.sleep"),
        ):
            generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        assert len(captured_prompts) == 2, "Expected exactly 2 _safe_llm_call invocations"

        original_prompt = captured_prompts[0]
        retry_prompt = captured_prompts[1]

        # The retry prompt must be longer (corrective text appended)
        assert len(retry_prompt) > len(original_prompt), (
            "Retry prompt should be longer than the original prompt"
        )

        # The retry prompt must contain some corrective language about count/questions
        retry_lower = retry_prompt.lower()
        assert (
            str(TOTAL_QUESTIONS) in retry_prompt
            or "exactly" in retry_lower
            or "critical" in retry_lower
        ), f"Retry prompt missing corrective count instruction: {retry_prompt[-200:]}"


# ---------------------------------------------------------------------------
# Task 9: QuestionGenerationError and input validation
# ---------------------------------------------------------------------------
# Requirement: 1.6, 9.4


class TestQuestionGenerationErrorAndInputValidation:
    """Unit tests for QuestionGenerationError and generate_questions input validation.

    Covers:
    - QuestionGenerationError is a subclass of Exception
    - exc.message == str(exc)
    - Missing each of the 8 required research keys raises QuestionGenerationError
    - api_key="" raises QuestionGenerationError before time.sleep is called
    - api_key="   " (whitespace-only) raises QuestionGenerationError
    - Valid inputs pass input validation without raising (LLM + db mocked)
    """

    # -----------------------------------------------------------------------
    # Exception class tests
    # -----------------------------------------------------------------------

    def test_question_generation_error_is_subclass_of_exception(self) -> None:
        """QuestionGenerationError must be a subclass of Exception."""
        assert issubclass(QuestionGenerationError, Exception)

    def test_exc_message_equals_str_exc(self) -> None:
        """exc.message must equal str(exc) for any message string."""
        message = "Question_Generator_Agent: some failure occurred"
        exc = QuestionGenerationError(message)
        assert exc.message == str(exc)
        assert exc.message == message

    def test_exc_message_equals_str_exc_empty_string(self) -> None:
        """exc.message == str(exc) even for an empty message string."""
        exc = QuestionGenerationError("")
        assert exc.message == str(exc)
        assert exc.message == ""

    def test_exc_message_equals_str_exc_multiline(self) -> None:
        """exc.message == str(exc) for a multiline message."""
        message = "Question_Generator_Agent: line one\nline two"
        exc = QuestionGenerationError(message)
        assert exc.message == str(exc)

    # -----------------------------------------------------------------------
    # Missing research keys — one test per key
    # -----------------------------------------------------------------------

    def _assert_missing_key_raises(self, key: str) -> None:
        """Helper: remove *key* from a valid research dict, assert error raised."""
        bad_research = {k: v for k, v in VALID_RESEARCH.items() if k != key}
        with pytest.raises(QuestionGenerationError) as exc_info:
            generate_questions(bad_research, VALID_SESSION_ID, VALID_API_KEY)
        assert key in str(exc_info.value) or "missing" in str(exc_info.value).lower()

    def test_missing_key_company_raises(self) -> None:
        """Missing 'company' key raises QuestionGenerationError."""
        self._assert_missing_key_raises("company")

    def test_missing_key_role_raises(self) -> None:
        """Missing 'role' key raises QuestionGenerationError."""
        self._assert_missing_key_raises("role")

    def test_missing_key_interview_rounds_raises(self) -> None:
        """Missing 'interview_rounds' key raises QuestionGenerationError."""
        self._assert_missing_key_raises("interview_rounds")

    def test_missing_key_key_topics_raises(self) -> None:
        """Missing 'key_topics' key raises QuestionGenerationError."""
        self._assert_missing_key_raises("key_topics")

    def test_missing_key_difficulty_raises(self) -> None:
        """Missing 'difficulty' key raises QuestionGenerationError."""
        self._assert_missing_key_raises("difficulty")

    def test_missing_key_culture_keywords_raises(self) -> None:
        """Missing 'culture_keywords' key raises QuestionGenerationError."""
        self._assert_missing_key_raises("culture_keywords")

    def test_missing_key_known_question_types_raises(self) -> None:
        """Missing 'known_question_types' key raises QuestionGenerationError."""
        self._assert_missing_key_raises("known_question_types")

    def test_missing_key_red_flags_to_test_raises(self) -> None:
        """Missing 'red_flags_to_test' key raises QuestionGenerationError."""
        self._assert_missing_key_raises("red_flags_to_test")

    # -----------------------------------------------------------------------
    # api_key validation — must raise BEFORE time.sleep is called
    # -----------------------------------------------------------------------

    def test_empty_api_key_raises_before_sleep(self) -> None:
        """api_key='' raises QuestionGenerationError before time.sleep is called."""
        with (
            patch("agents.question_generator.time") as mock_time,
        ):
            with pytest.raises(QuestionGenerationError) as exc_info:
                generate_questions(VALID_RESEARCH, VALID_SESSION_ID, "")

        # time.sleep must NOT have been called
        mock_time.sleep.assert_not_called()
        assert "api_key" in str(exc_info.value).lower() or "non-empty" in str(exc_info.value).lower()

    def test_whitespace_only_api_key_raises(self) -> None:
        """api_key='   ' (whitespace-only) raises QuestionGenerationError."""
        with pytest.raises(QuestionGenerationError) as exc_info:
            generate_questions(VALID_RESEARCH, VALID_SESSION_ID, "   ")
        assert "api_key" in str(exc_info.value).lower() or "non-empty" in str(exc_info.value).lower()

    def test_whitespace_only_api_key_raises_before_sleep(self) -> None:
        """api_key whitespace-only raises QuestionGenerationError before time.sleep."""
        with (
            patch("agents.question_generator.time") as mock_time,
        ):
            with pytest.raises(QuestionGenerationError):
                generate_questions(VALID_RESEARCH, VALID_SESSION_ID, "   ")

        mock_time.sleep.assert_not_called()

    # -----------------------------------------------------------------------
    # Missing key also raises before time.sleep
    # -----------------------------------------------------------------------

    def test_missing_research_key_raises_before_sleep(self) -> None:
        """Missing a required research key raises before time.sleep is called."""
        bad_research = {k: v for k, v in VALID_RESEARCH.items() if k != "company"}
        with (
            patch("agents.question_generator.time") as mock_time,
        ):
            with pytest.raises(QuestionGenerationError):
                generate_questions(bad_research, VALID_SESSION_ID, VALID_API_KEY)

        mock_time.sleep.assert_not_called()

    # -----------------------------------------------------------------------
    # Valid inputs pass input validation (no raise)
    # -----------------------------------------------------------------------

    def test_valid_inputs_do_not_raise_during_input_validation(self) -> None:
        """Valid research_data and api_key pass input validation without raising.

        The LLM call and database write are mocked so the test exercises only
        the input-validation phase (Step 1) without requiring a real API key.
        """
        ten_questions = _make_valid_10_questions()

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch("agents.question_generator.save_questions"),
            patch("time.sleep"),
        ):
            mock_llm.return_value = {"questions": ten_questions}
            # If input validation raises, this call will propagate it
            result = generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        # Confirm we got past validation and through the full pipeline
        assert isinstance(result, list)
        assert len(result) == TOTAL_QUESTIONS


# ---------------------------------------------------------------------------
# Task 14: Unit tests — _assign_ids_and_difficulties
# ---------------------------------------------------------------------------
# Requirement: 1.5, 3.2, 3.4


import re as _re

from agents.question_generator import _assign_ids_and_difficulties
from core.config import TOTAL_QUESTIONS

_UUID4_PATTERN = r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'


class TestAssignIdsAndDifficulties:
    """Unit tests for the _assign_ids_and_difficulties private helper.

    Covers:
    - LLM-returned id and difficulty values are both overwritten
    - id is a valid UUID4 string after overwrite
    - difficulty equals 1-based index position (Q1=1, Q10=10)
    - All 10 questions receive unique UUIDs (no duplicates)
    - Difficulties are exactly [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    """

    def _make_questions_with_bad_ids_and_difficulties(self) -> list[dict]:
        """Return 10 questions where id='abc' and difficulty=7 for every item."""
        return [
            {
                "id": "abc",
                "category": "technical",
                "question": "Tell me about a challenging project you worked on?",
                "ideal_keywords": ["architecture", "trade-offs", "delivery"],
                "difficulty": 7,
                "follow_ups": [
                    "Can you walk me through your approach?",
                    "What would you do differently?",
                ],
                "scoring_hint": "Look for ownership and technical depth.",
            }
            for _ in range(TOTAL_QUESTIONS)
        ]

    # -----------------------------------------------------------------------
    # Test 1: LLM-returned id="abc" and difficulty=7 are both overwritten;
    #         id is a valid UUID4, difficulty=1 for Q1
    # -----------------------------------------------------------------------

    def test_llm_id_and_difficulty_are_overwritten(self) -> None:
        """LLM id='abc' and difficulty=7 must both be overwritten.

        After _assign_ids_and_difficulties:
        - questions[0]["id"] must be a valid UUID4 (not "abc")
        - questions[0]["difficulty"] must be 1 (not 7)
        """
        questions = self._make_questions_with_bad_ids_and_difficulties()

        result = _assign_ids_and_difficulties(questions)

        first = result[0]

        # id must no longer be "abc"
        assert first["id"] != "abc", (
            f'Expected id to be overwritten, but it is still "abc"'
        )

        # id must match UUID4 format
        assert _re.match(_UUID4_PATTERN, first["id"]), (
            f'Expected valid UUID4, got {first["id"]!r}'
        )

        # difficulty for Q1 (index 0) must be 1, not 7
        assert first["difficulty"] == 1, (
            f"Expected difficulty=1 for Q1, got {first['difficulty']}"
        )

    # -----------------------------------------------------------------------
    # Test 2: All 10 questions receive unique UUIDs (no duplicates)
    # -----------------------------------------------------------------------

    def test_all_questions_get_unique_uuids(self) -> None:
        """All 10 questions must receive distinct UUID4 strings after assignment."""
        questions = self._make_questions_with_bad_ids_and_difficulties()

        result = _assign_ids_and_difficulties(questions)

        ids = [q["id"] for q in result]

        # All IDs must be unique
        assert len(ids) == len(set(ids)), (
            f"Expected {TOTAL_QUESTIONS} unique UUIDs, but found duplicates: {ids}"
        )

        # Each ID must be a valid UUID4
        for i, uid in enumerate(ids):
            assert _re.match(_UUID4_PATTERN, uid), (
                f"Question[{i}] id {uid!r} is not a valid UUID4"
            )

    # -----------------------------------------------------------------------
    # Test 3: Difficulties are exactly [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    # -----------------------------------------------------------------------

    def test_difficulties_are_sequential_1_to_10(self) -> None:
        """After assignment, difficulties must be exactly [1, 2, ..., TOTAL_QUESTIONS]."""
        questions = self._make_questions_with_bad_ids_and_difficulties()

        result = _assign_ids_and_difficulties(questions)

        difficulties = [q["difficulty"] for q in result]
        expected = list(range(1, TOTAL_QUESTIONS + 1))

        assert difficulties == expected, (
            f"Expected difficulties {expected}, got {difficulties}"
        )


# ---------------------------------------------------------------------------
# Task 11: validate_questions boundary cases
# ---------------------------------------------------------------------------
# Requirement: 2.3, 2.5, 4.1–4.3

from agents.question_generator import validate_questions
from core.config import MIN_QUESTION_LENGTH, TOTAL_QUESTIONS


class TestValidateQuestionsBoundaryCases:
    """Unit tests for validate_questions covering count, field, and distribution boundaries.

    All tests call validate_questions directly with crafted inputs and assert
    the exact (bool, str) return value shape. Constants are imported from
    core.config — no hardcoded numbers.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_valid_question(category: str, index: int = 0) -> dict:
        """Return a fully-valid Question_Dict for the given category."""
        return {
            "id": f"valid-id-{index}",
            "category": category,
            "question": "Tell me about a challenging project you worked on recently?",
            "ideal_keywords": ["architecture", "trade-offs", "delivery"],
            "difficulty": max(1, min(index + 1, TOTAL_QUESTIONS)),
            "follow_ups": [
                "Can you elaborate on the trade-offs you made?",
                "What would you do differently next time?",
            ],
            "scoring_hint": "Look for evidence of ownership and technical depth.",
        }

    @staticmethod
    def _valid_10_questions() -> list[dict]:
        """Return exactly 10 valid questions with the required distribution."""
        distribution = (
            ["technical"] * 4
            + ["behavioral"] * 3
            + ["situational"] * 2
            + ["curveball"] * 1
        )
        return [
            TestValidateQuestionsBoundaryCases._make_valid_question(cat, i)
            for i, cat in enumerate(distribution)
        ]

    # ------------------------------------------------------------------
    # Count boundary tests
    # ------------------------------------------------------------------

    def test_nine_questions_returns_false(self) -> None:
        """List of 9 questions → (False, message containing count info)."""
        questions = self._valid_10_questions()[:9]
        ok, reason = validate_questions(questions)
        assert ok is False
        # The message must communicate expected vs actual counts
        assert "9" in reason
        assert str(TOTAL_QUESTIONS) in reason

    def test_eleven_questions_returns_false(self) -> None:
        """List of 11 questions → (False, message containing count info)."""
        extra = self._valid_10_questions() + [
            self._make_valid_question("technical", 10)
        ]
        ok, reason = validate_questions(extra)
        assert ok is False
        assert "11" in reason
        assert str(TOTAL_QUESTIONS) in reason

    # ------------------------------------------------------------------
    # Category field tests
    # ------------------------------------------------------------------

    def test_wrong_case_category_returns_false(self) -> None:
        """category='Technical' (wrong case) → (False, reason mentioning category)."""
        questions = self._valid_10_questions()
        # Replace the first question's category with the wrong-case variant
        questions[0]["category"] = "Technical"
        ok, reason = validate_questions(questions)
        assert ok is False
        reason_lower = reason.lower()
        assert "category" in reason_lower or "technical" in reason_lower

    # ------------------------------------------------------------------
    # Question length test
    # ------------------------------------------------------------------

    def test_short_question_text_returns_false(self) -> None:
        """question='short' (4 chars < MIN_QUESTION_LENGTH) → (False, reason)."""
        questions = self._valid_10_questions()
        short_text = "sho!"  # exactly 4 chars — below MIN_QUESTION_LENGTH (20)
        assert len(short_text) < MIN_QUESTION_LENGTH
        questions[0]["question"] = short_text
        ok, reason = validate_questions(questions)
        assert ok is False
        reason_lower = reason.lower()
        assert (
            "question" in reason_lower
            or str(MIN_QUESTION_LENGTH) in reason
            or str(len(short_text)) in reason
        )

    # ------------------------------------------------------------------
    # ideal_keywords tests
    # ------------------------------------------------------------------

    def test_empty_ideal_keywords_returns_false(self) -> None:
        """ideal_keywords=[] → (False, reason mentioning ideal_keywords)."""
        questions = self._valid_10_questions()
        questions[0]["ideal_keywords"] = []
        ok, reason = validate_questions(questions)
        assert ok is False
        assert "ideal_keywords" in reason.lower() or "keyword" in reason.lower()

    # ------------------------------------------------------------------
    # Difficulty boundary tests
    # ------------------------------------------------------------------

    def test_difficulty_zero_returns_false(self) -> None:
        """difficulty=0 (below valid range 1–10) → (False, reason)."""
        questions = self._valid_10_questions()
        questions[0]["difficulty"] = 0
        ok, reason = validate_questions(questions)
        assert ok is False
        reason_lower = reason.lower()
        assert "difficulty" in reason_lower or "0" in reason

    def test_difficulty_eleven_returns_false(self) -> None:
        """difficulty=11 (above valid range 1–10) → (False, reason)."""
        questions = self._valid_10_questions()
        questions[0]["difficulty"] = 11
        ok, reason = validate_questions(questions)
        assert ok is False
        reason_lower = reason.lower()
        assert "difficulty" in reason_lower or "11" in reason

    # ------------------------------------------------------------------
    # scoring_hint test
    # ------------------------------------------------------------------

    def test_empty_scoring_hint_returns_false(self) -> None:
        """scoring_hint='' → (False, reason mentioning scoring_hint)."""
        questions = self._valid_10_questions()
        questions[0]["scoring_hint"] = ""
        ok, reason = validate_questions(questions)
        assert ok is False
        assert "scoring_hint" in reason.lower() or "scoring" in reason.lower()

    # ------------------------------------------------------------------
    # Valid list tests
    # ------------------------------------------------------------------

    def test_valid_10_questions_correct_distribution_returns_true(self) -> None:
        """Valid 10-question list with correct distribution → (True, '')."""
        questions = self._valid_10_questions()
        ok, reason = validate_questions(questions)
        assert ok is True
        assert reason == ""

    def test_valid_10_questions_wrong_distribution_returns_false(self) -> None:
        """10 valid questions but wrong distribution → (False, reason).

        Distribution: 5 technical, 3 behavioral, 2 situational, 0 curveball.
        This violates the required 4/3/2/1 split.
        """
        distribution = (
            ["technical"] * 5   # 5 instead of 4
            + ["behavioral"] * 3
            + ["situational"] * 2
            # 0 curveball instead of 1
        )
        questions = [
            self._make_valid_question(cat, i)
            for i, cat in enumerate(distribution)
        ]
        ok, reason = validate_questions(questions)
        assert ok is False
        reason_lower = reason.lower()
        assert (
            "distribution" in reason_lower
            or "category" in reason_lower
            or "curveball" in reason_lower
            or "technical" in reason_lower
        )


# ---------------------------------------------------------------------------
# Task 13: Unit tests — _normalize_follow_ups
# ---------------------------------------------------------------------------
# Requirement: 5.1–5.4


from agents.question_generator import _normalize_follow_ups, _FALLBACK_FOLLOW_UPS
from core.config import FOLLOW_UP_COUNT


class TestNormalizeFollowUps:
    """Unit tests for _normalize_follow_ups called directly.

    Covers:
    - Empty list padded to FOLLOW_UP_COUNT using category fallbacks
    - Short list (1 item) padded with one fallback
    - Long list (> FOLLOW_UP_COUNT) trimmed to first FOLLOW_UP_COUNT items
    - Invalid item (None) replaced with fallback, valid item kept
    - Empty string item replaced with fallback, valid item kept
    - Non-list follow_ups replaced entirely with fallbacks
    - Each valid category uses its own fallback strings
    - Unrecognised category falls back to "technical" fallbacks
    """

    # -----------------------------------------------------------------------
    # Helper
    # -----------------------------------------------------------------------

    @staticmethod
    def _q(category: str, follow_ups) -> dict:
        """Build a minimal question dict with the given category and follow_ups."""
        return {
            "id": "test-id",
            "category": category,
            "question": "Tell me about a project you worked on recently?",
            "ideal_keywords": ["one", "two", "three"],
            "difficulty": 1,
            "follow_ups": follow_ups,
            "scoring_hint": "Look for ownership.",
        }

    # -----------------------------------------------------------------------
    # Test 1: empty list padded to FOLLOW_UP_COUNT technical fallbacks
    # -----------------------------------------------------------------------

    def test_empty_list_padded_with_technical_fallbacks(self) -> None:
        """follow_ups=[] padded to exactly FOLLOW_UP_COUNT technical fallback strings."""
        q = self._q("technical", [])
        result = _normalize_follow_ups(q)

        assert result["follow_ups"] == _FALLBACK_FOLLOW_UPS["technical"][:FOLLOW_UP_COUNT]
        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT

    # -----------------------------------------------------------------------
    # Test 2: single valid item padded with one fallback
    # -----------------------------------------------------------------------

    def test_single_valid_item_padded_with_one_fallback(self) -> None:
        """follow_ups with one valid item is padded to FOLLOW_UP_COUNT."""
        valid_item = "valid follow-up question here"
        q = self._q("technical", [valid_item])
        result = _normalize_follow_ups(q)

        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT
        assert result["follow_ups"][0] == valid_item
        # Second slot must be the first fallback (fallback_idx starts at 0, no invalids consumed)
        assert result["follow_ups"][1] == _FALLBACK_FOLLOW_UPS["technical"][0]

    # -----------------------------------------------------------------------
    # Test 3: list longer than FOLLOW_UP_COUNT trimmed to first FOLLOW_UP_COUNT
    # -----------------------------------------------------------------------

    def test_long_list_trimmed_to_follow_up_count(self) -> None:
        """follow_ups with 5 items trimmed to exactly FOLLOW_UP_COUNT."""
        items = ["q1", "q2", "q3", "q4", "q5"]
        q = self._q("technical", items)
        result = _normalize_follow_ups(q)

        assert result["follow_ups"] == ["q1", "q2"]
        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT

    # -----------------------------------------------------------------------
    # Test 4: None item replaced with fallback; valid item kept
    # -----------------------------------------------------------------------

    def test_none_item_replaced_valid_item_kept(self) -> None:
        """follow_ups=[None, valid_str] → [fallback, valid_str]."""
        valid_item = "valid follow-up question here"
        q = self._q("technical", [None, valid_item])
        result = _normalize_follow_ups(q)

        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT
        # First item was None → replaced by the first technical fallback
        assert result["follow_ups"][0] == _FALLBACK_FOLLOW_UPS["technical"][0]
        # Second item was valid → kept as-is
        assert result["follow_ups"][1] == valid_item

    # -----------------------------------------------------------------------
    # Test 5: empty string replaced with fallback; valid item kept
    # -----------------------------------------------------------------------

    def test_empty_string_replaced_valid_item_kept(self) -> None:
        """follow_ups=["", valid_str] → [fallback, valid_str]."""
        valid_item = "valid follow-up question here"
        q = self._q("technical", ["", valid_item])
        result = _normalize_follow_ups(q)

        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT
        # First item was "" → replaced by the first technical fallback
        assert result["follow_ups"][0] == _FALLBACK_FOLLOW_UPS["technical"][0]
        # Second item was valid → kept as-is
        assert result["follow_ups"][1] == valid_item

    # -----------------------------------------------------------------------
    # Test 6: non-list follow_ups replaced entirely
    # -----------------------------------------------------------------------

    def test_non_list_follow_ups_replaced_entirely(self) -> None:
        """follow_ups="string" (not a list) → entirely replaced with fallbacks."""
        q = self._q("technical", "this is a string, not a list")
        result = _normalize_follow_ups(q)

        assert isinstance(result["follow_ups"], list)
        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT
        # Both slots should be filled from the technical fallback list
        for item in result["follow_ups"]:
            assert isinstance(item, str) and item.strip()

    # -----------------------------------------------------------------------
    # Test 7: category "behavioral" uses behavioral fallback strings
    # -----------------------------------------------------------------------

    def test_behavioral_category_uses_behavioral_fallbacks(self) -> None:
        """Empty follow_ups for category="behavioral" uses behavioral fallback strings."""
        q = self._q("behavioral", [])
        result = _normalize_follow_ups(q)

        assert result["follow_ups"] == _FALLBACK_FOLLOW_UPS["behavioral"][:FOLLOW_UP_COUNT]
        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT

    # -----------------------------------------------------------------------
    # Test 8: category "situational" uses situational fallback strings
    # -----------------------------------------------------------------------

    def test_situational_category_uses_situational_fallbacks(self) -> None:
        """Empty follow_ups for category="situational" uses situational fallback strings."""
        q = self._q("situational", [])
        result = _normalize_follow_ups(q)

        assert result["follow_ups"] == _FALLBACK_FOLLOW_UPS["situational"][:FOLLOW_UP_COUNT]
        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT

    # -----------------------------------------------------------------------
    # Test 9: category "curveball" uses curveball fallback strings
    # -----------------------------------------------------------------------

    def test_curveball_category_uses_curveball_fallbacks(self) -> None:
        """Empty follow_ups for category="curveball" uses curveball fallback strings."""
        q = self._q("curveball", [])
        result = _normalize_follow_ups(q)

        assert result["follow_ups"] == _FALLBACK_FOLLOW_UPS["curveball"][:FOLLOW_UP_COUNT]
        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT

    # -----------------------------------------------------------------------
    # Test 10: unrecognised category falls back to "technical" fallbacks
    # -----------------------------------------------------------------------

    def test_unrecognised_category_falls_back_to_technical(self) -> None:
        """Unrecognised category string uses the "technical" fallback list."""
        q = self._q("unknown_category_xyz", [])
        result = _normalize_follow_ups(q)

        assert result["follow_ups"] == _FALLBACK_FOLLOW_UPS["technical"][:FOLLOW_UP_COUNT]
        assert len(result["follow_ups"]) == FOLLOW_UP_COUNT


# ---------------------------------------------------------------------------
# Task 10: Unit tests — _safe_llm_call retry behaviour
# ---------------------------------------------------------------------------
# Requirement: 1.3, 9.1, 9.5, 10.3


class TestSafeLlmCallRetryBehaviour:
    """Unit tests for the _safe_llm_call module-private function.

    Covers:
    - invalid JSON on attempt 0 → time.sleep(RATE_LIMIT_SLEEP) → corrective
      text appended to prompt → retry succeeds
    - invalid JSON on both attempts → QuestionGenerationError raised with
      "JSON parse failure"
    - API exception on attempt 0 → time.sleep(ERROR_RETRY_SLEEP) → retry
      succeeds
    - API exception on both attempts → QuestionGenerationError raised with
      original error text
    - successful call logs "[QuestionGenerator] Success. Tokens:" to stdout
    - max_output_tokens is passed as MAX_TOKENS_COMPLEX in generate_content
      call args
    """

    # Import the private function and the constants we need.
    # These are resolved once here to keep individual tests readable.

    @staticmethod
    def _import_subject():
        """Return (_safe_llm_call, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, MAX_TOKENS_COMPLEX)."""
        from agents.question_generator import _safe_llm_call
        from core.config import ERROR_RETRY_SLEEP, MAX_TOKENS_COMPLEX, RATE_LIMIT_SLEEP
        return _safe_llm_call, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, MAX_TOKENS_COMPLEX

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _make_mock_response(text: str) -> MagicMock:
        """Build a mock Gemini response object with .text and .usage_metadata."""
        mock_resp = MagicMock()
        mock_resp.text = text
        mock_resp.usage_metadata = "prompt_token_count: 10 candidates_token_count: 50"
        return mock_resp

    # -----------------------------------------------------------------------
    # Test 1: invalid JSON on attempt 0
    #   → time.sleep(RATE_LIMIT_SLEEP)
    #   → corrective text appended to prompt
    #   → retry succeeds
    # -----------------------------------------------------------------------
    def test_invalid_json_attempt0_sleeps_and_retries_with_corrective_prompt(
        self, capsys
    ) -> None:
        """
        When attempt 0 returns invalid JSON:
        - time.sleep(RATE_LIMIT_SLEEP) is called
        - the corrective instruction is appended to the prompt on retry
        - the call succeeds on attempt 1 and returns the parsed dict
        """
        _safe_llm_call, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, MAX_TOKENS_COMPLEX = (
            self._import_subject()
        )

        valid_json_text = '{"result": "ok"}'
        model = MagicMock()

        captured_prompts: list[str] = []

        def generate_content_side_effect(contents, generation_config):
            # contents is [system, prompt]
            captured_prompts.append(contents[1])
            if len(captured_prompts) == 1:
                # Attempt 0 — return raw text that is not valid JSON
                return self._make_mock_response("NOT JSON AT ALL !!!")
            # Attempt 1 — return valid JSON
            return self._make_mock_response(valid_json_text)

        model.generate_content.side_effect = generate_content_side_effect

        with patch("agents.question_generator.time") as mock_time:
            result = _safe_llm_call(
                prompt="initial prompt",
                system="system instruction",
                model=model,
                max_tokens=MAX_TOKENS_COMPLEX,
                agent_name="QuestionGenerator",
            )

        # Return value should be the parsed dict from attempt 1
        assert result == {"result": "ok"}

        # time.sleep must have been called with RATE_LIMIT_SLEEP (for JSON retry)
        mock_time.sleep.assert_called_once_with(RATE_LIMIT_SLEEP)

        # generate_content must have been called twice
        assert model.generate_content.call_count == 2

        # The retry prompt (attempt 1) must be longer — corrective text was appended
        assert len(captured_prompts) == 2
        assert len(captured_prompts[1]) > len(captured_prompts[0])
        # The canonical corrective suffix from the implementation
        assert "RETURN ONLY RAW JSON" in captured_prompts[1]

    # -----------------------------------------------------------------------
    # Test 2: invalid JSON on both attempts → QuestionGenerationError with
    #         "JSON parse failure" in the message
    # -----------------------------------------------------------------------
    def test_invalid_json_both_attempts_raises_with_json_parse_failure(self) -> None:
        """
        When both attempts return invalid JSON, QuestionGenerationError is raised
        and its message contains "JSON parse failure".
        """
        _safe_llm_call, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, MAX_TOKENS_COMPLEX = (
            self._import_subject()
        )

        model = MagicMock()
        model.generate_content.return_value = self._make_mock_response(
            "this is not json either"
        )

        with patch("agents.question_generator.time"):
            with pytest.raises(QuestionGenerationError) as exc_info:
                _safe_llm_call(
                    prompt="some prompt",
                    system="system",
                    model=model,
                    max_tokens=MAX_TOKENS_COMPLEX,
                    agent_name="QuestionGenerator",
                )

        assert "JSON parse failure" in str(exc_info.value)
        # generate_content must have been called exactly twice (both attempts exhausted)
        assert model.generate_content.call_count == 2

    # -----------------------------------------------------------------------
    # Test 3: API exception on attempt 0
    #   → time.sleep(ERROR_RETRY_SLEEP)
    #   → retry succeeds
    # -----------------------------------------------------------------------
    def test_api_exception_attempt0_sleeps_error_retry_sleep_and_succeeds(self) -> None:
        """
        When attempt 0 raises a generic Exception (API/network error):
        - time.sleep(ERROR_RETRY_SLEEP) is called
        - attempt 1 succeeds and the parsed dict is returned
        """
        _safe_llm_call, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, MAX_TOKENS_COMPLEX = (
            self._import_subject()
        )

        valid_json_text = '{"status": "success"}'
        model = MagicMock()
        model.generate_content.side_effect = [
            Exception("503 Service Unavailable"),          # attempt 0 — API error
            self._make_mock_response(valid_json_text),     # attempt 1 — success
        ]

        with patch("agents.question_generator.time") as mock_time:
            result = _safe_llm_call(
                prompt="prompt text",
                system="system",
                model=model,
                max_tokens=MAX_TOKENS_COMPLEX,
                agent_name="QuestionGenerator",
            )

        assert result == {"status": "success"}

        # Sleep must have been called with ERROR_RETRY_SLEEP (not RATE_LIMIT_SLEEP)
        mock_time.sleep.assert_called_once_with(ERROR_RETRY_SLEEP)

        # Both attempts were made
        assert model.generate_content.call_count == 2

    # -----------------------------------------------------------------------
    # Test 4: API exception on both attempts → QuestionGenerationError raised
    #         with the original error text in the message
    # -----------------------------------------------------------------------
    def test_api_exception_both_attempts_raises_with_original_error_text(self) -> None:
        """
        When both attempts raise a generic Exception, QuestionGenerationError
        is raised and its message contains the original error text.
        """
        _safe_llm_call, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, MAX_TOKENS_COMPLEX = (
            self._import_subject()
        )

        original_error_message = "connection reset by peer: timeout after 30s"
        model = MagicMock()
        model.generate_content.side_effect = Exception(original_error_message)

        with patch("agents.question_generator.time"):
            with pytest.raises(QuestionGenerationError) as exc_info:
                _safe_llm_call(
                    prompt="prompt",
                    system="system",
                    model=model,
                    max_tokens=MAX_TOKENS_COMPLEX,
                    agent_name="QuestionGenerator",
                )

        assert original_error_message in str(exc_info.value)
        # Both attempts must have been made
        assert model.generate_content.call_count == 2

    # -----------------------------------------------------------------------
    # Test 5: successful call logs "[QuestionGenerator] Success. Tokens:" to
    #         stdout — captured via capsys
    # -----------------------------------------------------------------------
    def test_successful_call_logs_success_tokens_to_stdout(self, capsys) -> None:
        """
        A successful _safe_llm_call prints a line to stdout that contains:
        "[QuestionGenerator] Success. Tokens:"
        """
        _safe_llm_call, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, MAX_TOKENS_COMPLEX = (
            self._import_subject()
        )

        valid_json_text = '{"key": "value"}'
        model = MagicMock()
        model.generate_content.return_value = self._make_mock_response(valid_json_text)

        with patch("agents.question_generator.time"):
            _safe_llm_call(
                prompt="prompt",
                system="system",
                model=model,
                max_tokens=MAX_TOKENS_COMPLEX,
                agent_name="QuestionGenerator",
            )

        captured = capsys.readouterr()
        assert "[QuestionGenerator] Success. Tokens:" in captured.out

    # -----------------------------------------------------------------------
    # Test 6: max_output_tokens is passed as MAX_TOKENS_COMPLEX in the
    #         generate_content call arguments
    # -----------------------------------------------------------------------
    def test_max_output_tokens_passed_as_max_tokens_complex(self) -> None:
        """
        The generation_config dict passed to model.generate_content must
        contain max_output_tokens == MAX_TOKENS_COMPLEX.
        """
        _safe_llm_call, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, MAX_TOKENS_COMPLEX = (
            self._import_subject()
        )

        valid_json_text = '{"ok": true}'
        model = MagicMock()
        model.generate_content.return_value = self._make_mock_response(valid_json_text)

        with patch("agents.question_generator.time"):
            _safe_llm_call(
                prompt="prompt",
                system="system",
                model=model,
                max_tokens=MAX_TOKENS_COMPLEX,
                agent_name="QuestionGenerator",
            )

        # Inspect the call arguments — generate_content(contents, generation_config=...)
        assert model.generate_content.call_count == 1
        _, kwargs = model.generate_content.call_args
        generation_config = kwargs.get("generation_config")
        assert generation_config is not None, (
            "generation_config keyword argument was not passed to generate_content"
        )
        assert generation_config.get("max_output_tokens") == MAX_TOKENS_COMPLEX, (
            f"Expected max_output_tokens={MAX_TOKENS_COMPLEX}, "
            f"got {generation_config.get('max_output_tokens')}"
        )


# ---------------------------------------------------------------------------
# Task 15: Unit tests — error_flag and database
# ---------------------------------------------------------------------------
# Requirement: 7.1–7.3, 8.1–8.4


import sqlite3


class TestErrorFlagAndDatabase:
    """Unit tests for error_flag behaviour and database persistence in generate_questions.

    All tests mock:
      - agents.question_generator._safe_llm_call  (control LLM output)
      - agents.question_generator.save_questions  (track calls / simulate errors)
      - time.sleep                                 (avoid real delays)
    All constants imported from core.config.
    """

    # -----------------------------------------------------------------------
    # Test 1: error_flag=True → company name NOT in the prompt
    # -----------------------------------------------------------------------
    def test_error_flag_true_company_name_absent_from_prompt(self) -> None:
        """error_flag=True → company name must NOT appear anywhere in the prompt
        passed to _safe_llm_call."""
        company_name = "Acme Corp"
        research_with_error_flag = {**VALID_RESEARCH, "error_flag": True, "company": company_name}
        ten_questions = _make_valid_10_questions()
        captured_prompts: list[str] = []

        def capture_prompt(prompt, system, model, max_tokens, agent_name):
            captured_prompts.append(prompt)
            return {"questions": ten_questions}

        with (
            patch("agents.question_generator._safe_llm_call", side_effect=capture_prompt),
            patch("agents.question_generator.save_questions"),
            patch("time.sleep"),
        ):
            generate_questions(research_with_error_flag, VALID_SESSION_ID, VALID_API_KEY)

        assert captured_prompts, "Expected at least one _safe_llm_call invocation"
        for prompt in captured_prompts:
            assert company_name not in prompt, (
                f"Company name '{company_name}' should NOT appear in the prompt "
                f"when error_flag=True, but was found in: {prompt[:300]}"
            )

    # -----------------------------------------------------------------------
    # Test 2: error_flag=False → company name IS in the prompt
    # -----------------------------------------------------------------------
    def test_error_flag_false_company_name_present_in_prompt(self) -> None:
        """error_flag=False → company name MUST appear in the prompt passed to
        _safe_llm_call."""
        company_name = "Acme Corp"
        research_no_error_flag = {**VALID_RESEARCH, "error_flag": False, "company": company_name}
        ten_questions = _make_valid_10_questions()
        captured_prompts: list[str] = []

        def capture_prompt(prompt, system, model, max_tokens, agent_name):
            captured_prompts.append(prompt)
            return {"questions": ten_questions}

        with (
            patch("agents.question_generator._safe_llm_call", side_effect=capture_prompt),
            patch("agents.question_generator.save_questions"),
            patch("time.sleep"),
        ):
            generate_questions(research_no_error_flag, VALID_SESSION_ID, VALID_API_KEY)

        assert captured_prompts, "Expected at least one _safe_llm_call invocation"
        first_prompt = captured_prompts[0]
        assert company_name in first_prompt, (
            f"Company name '{company_name}' MUST appear in the prompt "
            f"when error_flag=False, but was absent from: {first_prompt[:300]}"
        )

    # -----------------------------------------------------------------------
    # Test 3: error_flag key absent → treated as False (no error raised)
    # -----------------------------------------------------------------------
    def test_error_flag_absent_treated_as_false_no_error_raised(self) -> None:
        """When the error_flag key is absent from research_data, generate_questions
        must succeed (treating it as False) and return 10 questions."""
        research_no_flag = {k: v for k, v in VALID_RESEARCH.items() if k != "error_flag"}
        # Confirm key really is absent
        assert "error_flag" not in research_no_flag

        ten_questions = _make_valid_10_questions()

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch("agents.question_generator.save_questions"),
            patch("time.sleep"),
        ):
            mock_llm.return_value = {"questions": ten_questions}
            result = generate_questions(research_no_flag, VALID_SESSION_ID, VALID_API_KEY)

        assert isinstance(result, list)
        assert len(result) == TOTAL_QUESTIONS

    # -----------------------------------------------------------------------
    # Test 4: save_questions called exactly once with all 10 validated questions
    # -----------------------------------------------------------------------
    def test_save_questions_called_exactly_once_with_all_10_questions(self) -> None:
        """save_questions must be called exactly once and receive all TOTAL_QUESTIONS
        validated question dicts."""
        ten_questions = _make_valid_10_questions()

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch("agents.question_generator.save_questions") as mock_save,
            patch("time.sleep"),
        ):
            mock_llm.return_value = {"questions": ten_questions}
            generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        mock_save.assert_called_once()
        _, saved_questions = mock_save.call_args[0]
        assert len(saved_questions) == TOTAL_QUESTIONS, (
            f"save_questions should receive exactly {TOTAL_QUESTIONS} questions, "
            f"got {len(saved_questions)}"
        )

    # -----------------------------------------------------------------------
    # Test 5: save_questions raises sqlite3.Error → QuestionGenerationError
    #         with "database write failed" in the message
    # -----------------------------------------------------------------------
    def test_save_questions_raises_sqlite_error_wraps_in_question_generation_error(self) -> None:
        """When save_questions raises sqlite3.Error, generate_questions must raise
        QuestionGenerationError with 'database write failed' in the message."""
        ten_questions = _make_valid_10_questions()

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch(
                "agents.question_generator.save_questions",
                side_effect=sqlite3.Error("disk I/O error"),
            ),
            patch("time.sleep"),
        ):
            mock_llm.return_value = {"questions": ten_questions}

            with pytest.raises(QuestionGenerationError) as exc_info:
                generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        assert "database write failed" in str(exc_info.value).lower(), (
            f"Expected 'database write failed' in error message, got: {exc_info.value}"
        )

    # -----------------------------------------------------------------------
    # Test 6: save_questions called with the correct session_id
    # -----------------------------------------------------------------------
    def test_save_questions_called_with_correct_session_id(self) -> None:
        """save_questions must be called with the exact session_id passed to
        generate_questions."""
        ten_questions = _make_valid_10_questions()
        expected_session_id = "test-session-id-abc-123"

        with (
            patch("agents.question_generator._safe_llm_call") as mock_llm,
            patch("agents.question_generator.save_questions") as mock_save,
            patch("time.sleep"),
        ):
            mock_llm.return_value = {"questions": ten_questions}
            generate_questions(VALID_RESEARCH, expected_session_id, VALID_API_KEY)

        mock_save.assert_called_once()
        actual_session_id = mock_save.call_args[0][0]
        assert actual_session_id == expected_session_id, (
            f"save_questions called with session_id={actual_session_id!r}, "
            f"expected {expected_session_id!r}"
        )


# ---------------------------------------------------------------------------
# Task 17: Property-based test — P1: Output Count Invariant
# ---------------------------------------------------------------------------
# Requirement: 1.1, 6.1, 6.3

from hypothesis import given, settings
from hypothesis import strategies as st


# Feature: question-generator-agent, Property 1: Output Count Invariant
@settings(max_examples=100)
@given(st.integers(min_value=0, max_value=20))
def test_p1_output_count_invariant(n: int) -> None:
    """Property 1: Output Count Invariant.

    For any list length n (0–20) returned by the LLM, generate_questions
    either returns a list of exactly TOTAL_QUESTIONS dicts or raises
    QuestionGenerationError.  No other list length is ever returned.

    **Validates: Requirements 1.1, 6.1, 6.3**
    """
    # Build a "valid-except-count" question dict template.
    # All 7 fields are individually valid; only the count may differ from
    # TOTAL_QUESTIONS depending on n.
    def _make_valid_q(i: int) -> dict:
        categories = ["technical"] * 4 + ["behavioral"] * 3 + ["situational"] * 2 + ["curveball"] * 1
        category = categories[i % len(categories)]
        return {
            "id": f"llm-id-{i}",
            "category": category,
            "question": "Tell me about a challenging project you worked on recently?",
            "ideal_keywords": ["architecture", "trade-offs", "delivery"],
            "difficulty": (i % 10) + 1,
            "follow_ups": [
                "Can you elaborate on the trade-offs you made?",
                "What would you do differently next time?",
            ],
            "scoring_hint": "Look for evidence of ownership and technical depth.",
        }

    # Generate n questions with valid individual fields.
    llm_questions = [_make_valid_q(i) for i in range(n)]

    # _safe_llm_call always returns the same list on both attempts so that
    # the retry loop cannot succeed unless n == TOTAL_QUESTIONS.
    with (
        patch("agents.question_generator._safe_llm_call") as mock_llm,
        patch("agents.question_generator.save_questions"),
        patch("agents.question_generator.genai.configure"),
        patch("agents.question_generator.genai.GenerativeModel"),
        patch("time.sleep"),
    ):
        mock_llm.return_value = {"questions": llm_questions}

        try:
            result = generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

            # If no exception was raised, the result MUST be a list of exactly
            # TOTAL_QUESTIONS dicts.
            assert isinstance(result, list), (
                f"Expected a list, got {type(result)}"
            )
            assert len(result) == TOTAL_QUESTIONS, (
                f"Expected exactly {TOTAL_QUESTIONS} questions, got {len(result)} "
                f"(LLM returned {n} questions)"
            )
            for q in result:
                assert isinstance(q, dict), (
                    f"Every item in result must be a dict, got {type(q)}"
                )

        except QuestionGenerationError:
            # Raising QuestionGenerationError is also an accepted outcome —
            # the invariant only forbids returning a list of the wrong length.
            pass


# ---------------------------------------------------------------------------
# Task 16: Unit tests — system prompt and rate limit compliance
# ---------------------------------------------------------------------------
# Requirement: 1.2, 1.4, 10.1, 10.4, 10.6

import json as _json

from agents.question_generator import SYSTEM_PROMPT
from core.config import RATE_LIMIT_SLEEP


class TestSystemPromptAndRateLimitCompliance:
    """Unit tests for SYSTEM_PROMPT content and rate-limit / compression behaviour.

    Covers:
    - SYSTEM_PROMPT ends with the exact required JSON-only footer
    - SYSTEM_PROMPT contains the "questions" key instruction
    - SYSTEM_PROMPT contains the exact category distribution strings
    - time.sleep is called with RATE_LIMIT_SLEEP as the first call in
      generate_questions (before any LLM invocation)
    - Research data is serialised with separators=(',',':') — no spaces in
      the JSON that reaches the LLM prompt
    """

    # -----------------------------------------------------------------------
    # Test 1: SYSTEM_PROMPT ends with the exact required suffix
    # -----------------------------------------------------------------------

    def test_system_prompt_ends_with_required_suffix(self) -> None:
        """SYSTEM_PROMPT must end with the canonical JSON-only footer."""
        required_suffix = (
            "Return ONLY a JSON object. No markdown. No explanation. "
            "No text before or after. Pure JSON only."
        )
        assert SYSTEM_PROMPT.endswith(required_suffix), (
            f"SYSTEM_PROMPT does not end with the required suffix.\n"
            f"Last 120 chars: {SYSTEM_PROMPT[-120:]!r}"
        )

    # -----------------------------------------------------------------------
    # Test 2: SYSTEM_PROMPT contains "questions" key instruction
    # -----------------------------------------------------------------------

    def test_system_prompt_contains_questions_key_instruction(self) -> None:
        """SYSTEM_PROMPT must instruct the LLM to use a 'questions' key."""
        assert '"questions"' in SYSTEM_PROMPT or "'questions'" in SYSTEM_PROMPT, (
            "SYSTEM_PROMPT must reference a 'questions' key in the output format"
        )

    # -----------------------------------------------------------------------
    # Test 3: SYSTEM_PROMPT contains the exact distribution strings
    # -----------------------------------------------------------------------

    def test_system_prompt_contains_exact_technical_distribution(self) -> None:
        """SYSTEM_PROMPT must contain the exact string for technical distribution."""
        assert '4 questions with category "technical"' in SYSTEM_PROMPT, (
            "SYSTEM_PROMPT missing: '4 questions with category \"technical\"'"
        )

    def test_system_prompt_contains_exact_behavioral_distribution(self) -> None:
        """SYSTEM_PROMPT must contain the exact string for behavioral distribution."""
        assert '3 questions with category "behavioral"' in SYSTEM_PROMPT, (
            "SYSTEM_PROMPT missing: '3 questions with category \"behavioral\"'"
        )

    def test_system_prompt_contains_exact_situational_distribution(self) -> None:
        """SYSTEM_PROMPT must contain the exact string for situational distribution."""
        assert '2 questions with category "situational"' in SYSTEM_PROMPT, (
            "SYSTEM_PROMPT missing: '2 questions with category \"situational\"'"
        )

    def test_system_prompt_contains_exact_curveball_distribution(self) -> None:
        """SYSTEM_PROMPT must contain the exact string for curveball distribution."""
        assert '1 question with category "curveball"' in SYSTEM_PROMPT, (
            "SYSTEM_PROMPT missing: '1 question with category \"curveball\"'"
        )

    # -----------------------------------------------------------------------
    # Test 4: time.sleep called with RATE_LIMIT_SLEEP as the first call
    #         in generate_questions (before the LLM)
    # -----------------------------------------------------------------------

    def test_time_sleep_called_with_rate_limit_sleep_before_llm(self) -> None:
        """time.sleep(RATE_LIMIT_SLEEP) must be the very first time.sleep call
        in generate_questions, occurring before any LLM invocation."""
        ten_questions = _make_valid_10_questions()

        with (
            patch("agents.question_generator.time.sleep") as mock_sleep,
            patch("agents.question_generator.genai.configure"),
            patch("agents.question_generator.genai.GenerativeModel") as mock_model_cls,
            patch("agents.question_generator.save_questions"),
        ):
            # Set up the mock model to return valid questions
            mock_model = MagicMock()
            mock_model_cls.return_value = mock_model
            mock_response = MagicMock()
            mock_response.text = _json.dumps({"questions": ten_questions})
            mock_response.usage_metadata = "prompt_token_count: 10 candidates_token_count: 50"
            mock_model.generate_content.return_value = mock_response

            generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        # At least one sleep call must have occurred
        assert mock_sleep.call_count >= 1, (
            "time.sleep was never called during generate_questions"
        )

        # The very first sleep call must use RATE_LIMIT_SLEEP
        first_sleep_call = mock_sleep.call_args_list[0]
        assert first_sleep_call == call(RATE_LIMIT_SLEEP), (
            f"First time.sleep call must be call({RATE_LIMIT_SLEEP}), "
            f"got {first_sleep_call}"
        )

        # The LLM must have been called after sleep (sleep_call_count > 0 before
        # generate_content is ever invoked — enforced by the pipeline order)
        assert mock_model.generate_content.call_count >= 1, (
            "generate_content was never called"
        )

    # -----------------------------------------------------------------------
    # Test 5: compressed research uses separators=(',',':') — no spaces in
    #         the serialised JSON that appears in the LLM prompt
    # -----------------------------------------------------------------------

    def test_compressed_research_has_no_spaces_in_prompt(self) -> None:
        """The research_data JSON embedded in the LLM prompt must use
        separators=(',',':') — assert no space after ':' or ',' in the
        JSON portion of the prompt."""
        ten_questions = _make_valid_10_questions()
        captured_prompts: list[str] = []

        def capture_prompt(prompt, system, model, max_tokens, agent_name):
            captured_prompts.append(prompt)
            return {"questions": ten_questions}

        with (
            patch("agents.question_generator._safe_llm_call", side_effect=capture_prompt),
            patch("agents.question_generator.save_questions"),
            patch("agents.question_generator.time.sleep"),
        ):
            generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

        assert captured_prompts, "Expected at least one _safe_llm_call invocation"
        prompt = captured_prompts[0]

        # Build the expected compressed form of the research data
        expected_compressed = _json.dumps(VALID_RESEARCH, separators=(",", ":"))

        # The compressed JSON string must appear verbatim in the prompt
        assert expected_compressed in prompt, (
            f"Expected compressed JSON (no spaces) to appear in the prompt.\n"
            f"Expected to find: {expected_compressed!r}\n"
            f"Prompt snippet: {prompt[:400]!r}"
        )

        # Extra guard: assert the uncompressed (spaced) form is NOT present
        spaced_json = _json.dumps(VALID_RESEARCH)   # default: uses ", " and ": "
        # Only check if the spaced form is meaningfully different
        if spaced_json != expected_compressed:
            assert spaced_json not in prompt, (
                "Prompt contains the uncompressed (spaced) JSON — "
                "separators=(',',':') was not applied"
            )


# ---------------------------------------------------------------------------
# Task 18: Property-based test — P2: Category Distribution Invariant
# ---------------------------------------------------------------------------
# Requirement: 2.1–2.4

from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.question_generator import _REQUIRED_DISTRIBUTION
from core.config import RATE_LIMIT_SLEEP, TOTAL_QUESTIONS


# Feature: question-generator-agent, Property 2: Category Distribution Invariant
@settings(max_examples=100)
@given(
    categories=st.lists(
        st.sampled_from(["technical", "behavioral", "situational", "curveball", "invalid"]),
    )
)
def test_p2_category_distribution_invariant(categories: list[str]) -> None:
    """**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

    For any category list generated by Hypothesis:
    - Pad or trim ``categories`` to exactly TOTAL_QUESTIONS entries.
    - Build a question list whose category sequence mirrors the padded list.
    - Mock ``_safe_llm_call`` to always return those questions (both attempts).
    - Assert: either ``QuestionGenerationError`` is raised OR the returned list
      has a distribution that exactly equals ``_REQUIRED_DISTRIBUTION``.

    A list with any other distribution must never be returned.
    """
    # ------------------------------------------------------------------
    # 1. Pad / trim the generated category list to exactly TOTAL_QUESTIONS
    # ------------------------------------------------------------------
    padded: list[str] = (categories + ["technical"] * TOTAL_QUESTIONS)[:TOTAL_QUESTIONS]

    # ------------------------------------------------------------------
    # 2. Build question dicts using those categories (all other fields valid)
    # ------------------------------------------------------------------
    def _make_q(category: str, idx: int) -> dict:
        return {
            "id": f"llm-id-{idx}",
            "category": category,
            "question": "Tell me about a challenging project you worked on recently?",
            "ideal_keywords": ["architecture", "trade-offs", "delivery"],
            "difficulty": idx + 1,
            "follow_ups": [
                "Can you walk me through your approach step by step?",
                "What would you do differently next time?",
            ],
            "scoring_hint": "Look for evidence of ownership and technical depth.",
        }

    questions_with_given_categories = [_make_q(cat, i) for i, cat in enumerate(padded)]
    llm_response = {"questions": questions_with_given_categories}

    # ------------------------------------------------------------------
    # 3. Run generate_questions with all external dependencies mocked
    # ------------------------------------------------------------------
    raised_error: bool = False
    result: list[dict] | None = None

    with (
        patch("agents.question_generator._safe_llm_call", return_value=llm_response),
        patch("agents.question_generator.save_questions"),
        patch("agents.question_generator.genai.configure"),
        patch("agents.question_generator.genai.GenerativeModel"),
        patch("agents.question_generator.time.sleep"),
    ):
        try:
            result = generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)
        except QuestionGenerationError:
            raised_error = True

    # ------------------------------------------------------------------
    # 4. Assert the invariant
    # ------------------------------------------------------------------
    # Either an error was raised ...
    if raised_error:
        return  # QuestionGenerationError is the correct outcome for bad distributions

    # ... or the returned list must have exactly the required distribution.
    assert result is not None, "generate_questions returned None without raising"
    assert isinstance(result, list), f"Expected list, got {type(result)}"
    assert len(result) == TOTAL_QUESTIONS, (
        f"Returned list length {len(result)} != {TOTAL_QUESTIONS}"
    )

    actual_dist = dict(Counter(q["category"] for q in result))
    assert actual_dist == _REQUIRED_DISTRIBUTION, (
        f"Returned distribution {actual_dist} does not match "
        f"required distribution {_REQUIRED_DISTRIBUTION}"
    )


# ---------------------------------------------------------------------------
# Task 19: Property-based test — P3: Difficulty Sequence Invariant
# ---------------------------------------------------------------------------
# Requirement: 3.2, 3.4

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.question_generator import _assign_ids_and_difficulties


# Feature: question-generator-agent, Property 3: Difficulty Sequence Invariant
@settings(max_examples=100)
@given(
    difficulties=st.lists(
        st.integers(min_value=-5, max_value=15),
        min_size=10,
        max_size=10,
    )
)
def test_difficulty_sequence_invariant(difficulties: list[int]) -> None:
    """P3: Regardless of what difficulty values the LLM returns, after calling
    _assign_ids_and_difficulties the question at 0-based index i always has
    difficulty == i + 1.

    Validates: Requirements 3.2, 3.4
    """
    # Build a valid 10-question list, injecting the generated difficulty values.
    distribution = (
        ["technical"] * 4
        + ["behavioral"] * 3
        + ["situational"] * 2
        + ["curveball"] * 1
    )
    questions: list[dict] = [
        {
            "id": f"llm-id-{i}",
            "category": distribution[i],
            "question": "Tell me about a challenging project you worked on recently?",
            "ideal_keywords": ["architecture", "trade-offs", "delivery"],
            "difficulty": difficulties[i],   # LLM-returned value (may be arbitrary)
            "follow_ups": [
                "Can you walk me through your approach?",
                "What would you do differently?",
            ],
            "scoring_hint": "Look for ownership and technical depth.",
        }
        for i in range(TOTAL_QUESTIONS)
    ]

    # Call _assign_ids_and_difficulties directly — no LLM or mocking needed.
    result = _assign_ids_and_difficulties(questions)

    # Assert: difficulty at index i must be exactly i + 1, for all i in 0..9.
    for i in range(TOTAL_QUESTIONS):
        assert result[i]["difficulty"] == i + 1, (
            f"Expected questions[{i}]['difficulty'] == {i + 1}, "
            f"but got {result[i]['difficulty']} "
            f"(LLM-returned value was {difficulties[i]})"
        )


# ---------------------------------------------------------------------------
# Task 20: Property-based test — P4: Follow-Up Count Invariant
# ---------------------------------------------------------------------------
# Requirement: 5.1–5.4

# Feature: question-generator-agent, Property 4: Follow-Up Count Invariant
@settings(max_examples=100)
@given(
    follow_ups=st.lists(
        st.one_of(st.text(), st.none(), st.integers()),
        min_size=0,
        max_size=6,
    ),
    category=st.sampled_from(["technical", "behavioral", "situational", "curveball"]),
)
def test_p4_follow_up_count_invariant(follow_ups: list, category: str) -> None:
    """P4: Regardless of what follow_ups the LLM returns (wrong types, wrong
    length, None items, integers, empty strings), after calling
    _normalize_follow_ups the question always has exactly FOLLOW_UP_COUNT
    follow-ups and every item is a non-empty string.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    """
    # Build a question dict with the generated follow_ups and category.
    question: dict = {
        "id": "test-id-0",
        "category": category,
        "question": "Tell me about a challenging project you worked on recently?",
        "ideal_keywords": ["architecture", "trade-offs", "delivery"],
        "difficulty": 1,
        "follow_ups": follow_ups,
        "scoring_hint": "Look for evidence of ownership and technical depth.",
    }

    # Call _normalize_follow_ups directly — no LLM or mocking needed.
    result = _normalize_follow_ups(question)

    # Assert: follow_ups length is exactly FOLLOW_UP_COUNT.
    assert len(result["follow_ups"]) == FOLLOW_UP_COUNT, (
        f"Expected exactly {FOLLOW_UP_COUNT} follow_ups, "
        f"got {len(result['follow_ups'])} for input {follow_ups!r}"
    )

    # Assert: every item in follow_ups is a non-empty string.
    for i, item in enumerate(result["follow_ups"]):
        assert isinstance(item, str), (
            f"follow_ups[{i}] must be a string, got {type(item).__name__}: {item!r}"
        )
        assert item.strip() != "", (
            f"follow_ups[{i}] must be non-empty, got empty/whitespace string"
        )


# ---------------------------------------------------------------------------
# Task 21: Property-based test — P5: UUID Identity Invariant
# ---------------------------------------------------------------------------
# Requirement: 1.5

import re


# Feature: question-generator-agent, Property 5: UUID Identity Invariant
@settings(max_examples=100)
@given(
    llm_ids=st.lists(
        st.text(),
        min_size=10,
        max_size=10,
    )
)
def test_p5_uuid_identity_invariant(llm_ids: list[str]) -> None:
    """P5: Regardless of what id values the LLM returns (empty, non-UUID,
    valid UUID strings, arbitrary text), after calling _assign_ids_and_difficulties
    every question's id is a valid UUID4 string and none of the returned ids
    match the original LLM-supplied id values.

    **Validates: Requirements 1.5**
    """
    _UUID4_RE = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    )

    # Build a valid 10-question list with the generated id values.
    distribution = (
        ["technical"] * 4
        + ["behavioral"] * 3
        + ["situational"] * 2
        + ["curveball"] * 1
    )
    questions: list[dict] = [
        {
            "id": llm_ids[i],
            "category": distribution[i],
            "question": "Tell me about a challenging project you worked on recently?",
            "ideal_keywords": ["architecture", "trade-offs", "delivery"],
            "difficulty": i + 1,
            "follow_ups": [
                "Can you walk me through your approach?",
                "What would you do differently?",
            ],
            "scoring_hint": "Look for ownership and technical depth.",
        }
        for i in range(TOTAL_QUESTIONS)
    ]

    # Store the original LLM-supplied ids before mutation.
    original_ids = [q["id"] for q in questions]

    # Call _assign_ids_and_difficulties directly — no LLM or mocking needed.
    result = _assign_ids_and_difficulties(questions)

    # Assert: every id in the result matches UUID4 format.
    for i in range(TOTAL_QUESTIONS):
        assert _UUID4_RE.match(result[i]["id"]), (
            f"questions[{i}]['id'] = {result[i]['id']!r} does not match UUID4 format "
            f"(LLM-supplied value was {original_ids[i]!r})"
        )

    # Assert: no returned id matches the LLM-supplied id for that position.
    for i in range(TOTAL_QUESTIONS):
        assert result[i]["id"] != original_ids[i], (
            f"questions[{i}]['id'] should differ from the LLM-supplied value "
            f"{original_ids[i]!r}, but they are the same"
        )

# ---------------------------------------------------------------------------
# Task 24: Property-based test — P8: Input Validation Completeness
# ---------------------------------------------------------------------------
# Requirement: 1.6, 9.1

from hypothesis import given, settings
from hypothesis import strategies as st

# The 8 required research keys that generate_questions validates in Step 1.
REQUIRED_RESEARCH_KEYS = frozenset({
    "company", "role", "interview_rounds", "key_topics",
    "difficulty", "culture_keywords", "known_question_types",
    "red_flags_to_test",
})


# Feature: question-generator-agent, Property 8: Input Validation Completeness
@settings(max_examples=100)
@given(
    keys_to_remove=st.frozensets(
        st.sampled_from(list(REQUIRED_RESEARCH_KEYS)), min_size=1
    ),
)
def test_p8_missing_keys_raises_before_sleep(keys_to_remove: frozenset) -> None:
    """P8: For any non-empty subset of the 8 required research keys removed
    from a valid research_data dict, generate_questions raises
    QuestionGenerationError before time.sleep is ever called.

    **Validates: Requirements 1.6, 9.1**
    """
    from unittest.mock import patch

    # Build research_data with the specified keys removed.
    incomplete_research = {
        k: v for k, v in VALID_RESEARCH.items() if k not in keys_to_remove
    }

    with patch("agents.question_generator.time") as mock_time:
        with pytest.raises(QuestionGenerationError):
            generate_questions(incomplete_research, VALID_SESSION_ID, VALID_API_KEY)

    # time.sleep must NOT have been called — validation happens before sleep.
    mock_time.sleep.assert_not_called()


# Feature: question-generator-agent, Property 8: Input Validation Completeness
@settings(max_examples=100)
@given(
    api_key=st.from_regex(r'^\s*$', fullmatch=True),
)
def test_p8_invalid_api_key_raises_before_sleep(api_key: str) -> None:
    """P8: For any empty or whitespace-only api_key string, generate_questions
    raises QuestionGenerationError before time.sleep is ever called.

    **Validates: Requirements 1.6, 9.1**
    """
    from unittest.mock import patch

    with patch("agents.question_generator.time") as mock_time:
        with pytest.raises(QuestionGenerationError):
            generate_questions(VALID_RESEARCH, VALID_SESSION_ID, api_key)

    # time.sleep must NOT have been called — validation happens before sleep.
    mock_time.sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Task 23: Property-based test — P7: Rate Limit Compliance
# ---------------------------------------------------------------------------
# Requirement: 1.4, 6.2

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.question_generator import generate_questions
from core.config import RATE_LIMIT_SLEEP, TOTAL_QUESTIONS


# Feature: question-generator-agent, Property 7: Rate Limit Compliance
@settings(max_examples=100)
@given(trigger_retry=st.booleans())
def test_p7_rate_limit_compliance(trigger_retry: bool) -> None:
    """P7: Rate Limit Compliance.

    - time.sleep(RATE_LIMIT_SLEEP) is always the first time.sleep call in any
      invocation of generate_questions (the unconditional Step 2 sleep).
    - When a retry is triggered (LLM returns wrong count on first attempt),
      a second time.sleep(RATE_LIMIT_SLEEP) call is made before the retry.

    **Validates: Requirements 1.4, 6.2**
    """
    ten_questions = _make_valid_10_questions()
    nine_questions = _make_valid_10_questions()[:9]

    if trigger_retry:
        # First call returns 9 questions (triggers retry), second returns 10
        llm_side_effect = [
            {"questions": nine_questions},
            {"questions": ten_questions},
        ]
    else:
        # First call returns 10 valid questions (no retry needed)
        llm_side_effect = [
            {"questions": ten_questions},
        ]

    with (
        patch("agents.question_generator._safe_llm_call") as mock_llm,
        patch("agents.question_generator.save_questions"),
        patch("agents.question_generator.time") as mock_time,
    ):
        mock_llm.side_effect = llm_side_effect

        generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

    # Collect all time.sleep calls
    sleep_calls = mock_time.sleep.call_args_list

    # Assert: time.sleep(RATE_LIMIT_SLEEP) is always the first sleep call
    assert len(sleep_calls) >= 1, (
        "time.sleep must be called at least once (Step 2 unconditional sleep)"
    )
    assert sleep_calls[0] == call(RATE_LIMIT_SLEEP), (
        f"First time.sleep call must be call({RATE_LIMIT_SLEEP}), "
        f"got {sleep_calls[0]}"
    )

    if trigger_retry:
        # When retry is triggered, expect exactly 2 RATE_LIMIT_SLEEP calls
        rate_limit_calls = [c for c in sleep_calls if c == call(RATE_LIMIT_SLEEP)]
        assert len(rate_limit_calls) == 2, (
            f"Expected 2 time.sleep({RATE_LIMIT_SLEEP}) calls when retry is triggered, "
            f"got {len(rate_limit_calls)}. All sleep calls: {sleep_calls}"
        )
    else:
        # When no retry, expect exactly 1 RATE_LIMIT_SLEEP call (Step 2 only)
        rate_limit_calls = [c for c in sleep_calls if c == call(RATE_LIMIT_SLEEP)]
        assert len(rate_limit_calls) == 1, (
            f"Expected exactly 1 time.sleep({RATE_LIMIT_SLEEP}) call when no retry, "
            f"got {len(rate_limit_calls)}. All sleep calls: {sleep_calls}"
        )


# ---------------------------------------------------------------------------
# Task 22: Property-based test — P6: Compression Token Efficiency
# ---------------------------------------------------------------------------
# Requirement: 1.2

import json

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from agents.question_generator import generate_questions
from core.config import TOTAL_QUESTIONS

# The 8 required keys that must exist in research_data.
_REQUIRED_RESEARCH_KEYS = [
    "company",
    "role",
    "interview_rounds",
    "key_topics",
    "difficulty",
    "culture_keywords",
    "known_question_types",
    "red_flags_to_test",
]


# Feature: question-generator-agent, Property 6: Compression Token Efficiency
@settings(max_examples=100)
@given(
    research_data=st.fixed_dictionaries(
        {k: st.text(min_size=1) for k in _REQUIRED_RESEARCH_KEYS}
    )
)
def test_p6_compression_token_efficiency(research_data: dict) -> None:
    """P6: For any research_data dict passed to generate_questions, the LLM
    prompt always includes ``json.dumps(research_data, separators=(',',':'))``
    (compact, no whitespace). The uncompressed default JSON form (with spaces)
    is never passed to the LLM.

    **Validates: Requirements 1.2**
    """
    # Build expected compressed and uncompressed forms.
    compressed = json.dumps(research_data, separators=(",", ":"))
    spaced = json.dumps(research_data)

    # Build a valid 10-question response for the mock.
    distribution = (
        ["technical"] * 4
        + ["behavioral"] * 3
        + ["situational"] * 2
        + ["curveball"] * 1
    )

    def _make_q(i: int) -> dict:
        return {
            "id": f"llm-id-{i}",
            "category": distribution[i],
            "question": "Tell me about a challenging project you worked on recently?",
            "ideal_keywords": ["architecture", "trade-offs", "delivery"],
            "difficulty": i + 1,
            "follow_ups": [
                "Can you walk me through your approach step by step?",
                "What would you do differently next time?",
            ],
            "scoring_hint": "Look for evidence of ownership and technical depth.",
        }

    valid_questions = [_make_q(i) for i in range(TOTAL_QUESTIONS)]

    # Capture the prompt passed to _safe_llm_call via side_effect.
    captured_prompts: list[str] = []

    def capture_llm_call(prompt, system, model, max_tokens, agent_name):
        captured_prompts.append(prompt)
        return {"questions": valid_questions}

    with (
        patch("agents.question_generator._safe_llm_call", side_effect=capture_llm_call),
        patch("agents.question_generator.save_questions"),
        patch("agents.question_generator.time.sleep"),
    ):
        generate_questions(research_data, "session-id-test", "test-api-key")

    # At least one prompt must have been captured.
    assert captured_prompts, "Expected at least one _safe_llm_call invocation"
    prompt = captured_prompts[0]

    # Assert: the compressed form IS present in the prompt.
    assert compressed in prompt, (
        f"Expected compressed JSON to appear in the prompt.\n"
        f"Compressed: {compressed!r}\n"
        f"Prompt snippet: {prompt[:500]!r}"
    )

    # Assert: the uncompressed (spaced) form is NOT present — only when
    # the two serialized forms are actually different.
    if spaced != compressed:
        assert spaced not in prompt, (
            f"Prompt must NOT contain the uncompressed (spaced) JSON form.\n"
            f"Spaced: {spaced!r}\n"
            f"Prompt snippet: {prompt[:500]!r}"
        )


# ---------------------------------------------------------------------------
# Task 25: Property-based test — P9: Database Persistence Completeness
# ---------------------------------------------------------------------------
# Requirement: 7.1–7.3

import sqlite3

from hypothesis import given, settings
from hypothesis import strategies as st
from unittest.mock import patch, call

from agents.question_generator import generate_questions, QuestionGenerationError
from core.config import TOTAL_QUESTIONS


# Feature: question-generator-agent, Property 9: Database Persistence Completeness
@settings(max_examples=100)
@given(
    trigger_db_error=st.booleans(),
    exc_type=st.sampled_from([sqlite3.Error, ValueError, RuntimeError]),
)
def test_p9_database_persistence_completeness(
    trigger_db_error: bool,
    exc_type: type,
) -> None:
    """P9: When save_questions raises any exception, generate_questions wraps it
    in a QuestionGenerationError with "database write failed" in the message.
    When save_questions succeeds, it must be called once with all TOTAL_QUESTIONS questions.

    **Validates: Requirements 7.1, 7.2, 7.3**
    """
    valid_questions = _make_valid_10_questions()

    def mock_llm_call(prompt, system, model, max_tokens, agent_name):
        return {"questions": valid_questions}

    if trigger_db_error:
        # Failure path: save_questions raises the generated exception type
        with (
            patch("agents.question_generator._safe_llm_call", side_effect=mock_llm_call),
            patch(
                "agents.question_generator.save_questions",
                side_effect=exc_type("simulated db failure"),
            ),
            patch("agents.question_generator.time.sleep"),
        ):
            with pytest.raises(QuestionGenerationError) as exc_info:
                generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

            # Must NOT be the original exception type directly
            assert type(exc_info.value) is QuestionGenerationError
            # Message must contain "database write failed"
            assert "database write failed" in str(exc_info.value)
    else:
        # Success path: save_questions does not raise
        with (
            patch("agents.question_generator._safe_llm_call", side_effect=mock_llm_call),
            patch("agents.question_generator.save_questions") as mock_save,
            patch("agents.question_generator.time.sleep"),
        ):
            result = generate_questions(VALID_RESEARCH, VALID_SESSION_ID, VALID_API_KEY)

            # save_questions must be called exactly once
            mock_save.assert_called_once()

            # The call must include TOTAL_QUESTIONS questions
            call_args = mock_save.call_args
            saved_questions = call_args[0][1]  # second positional arg
            assert len(saved_questions) == TOTAL_QUESTIONS, (
                f"Expected save_questions to be called with {TOTAL_QUESTIONS} questions, "
                f"got {len(saved_questions)}"
            )


# ---------------------------------------------------------------------------
# Task 26: Property-based test — P10: Error Flag Isolation
# ---------------------------------------------------------------------------
# Requirement: 8.1–8.4

from hypothesis import given, settings
from hypothesis import strategies as st

from agents.question_generator import generate_questions
from core.config import TOTAL_QUESTIONS


# Feature: question-generator-agent, Property 10: Error Flag Isolation
@settings(max_examples=100)
@given(
    error_flag=st.booleans(),
    company_name=st.text(
        alphabet=st.characters(categories=("Lu",)),
        min_size=5,
    ),
)
def test_p10_error_flag_isolation(error_flag: bool, company_name: str) -> None:
    """P10: Error Flag Isolation.

    - When error_flag=True, the company name must NOT appear in the user_prompt
      sent to the LLM (isolation of company-specific data).
    - When error_flag=False (or absent), the company name IS in the user_prompt.
    - In both cases the result is a list of 10 dicts each with the standard
      7-key structure.

    **Validates: Requirements 8.1, 8.2, 8.3, 8.4**
    """
    # Prefix with a unique marker to avoid accidental substring matches with
    # boilerplate prompt text (numbers, common English words, etc.)
    unique_company = f"XYZCOMPANY_{company_name}_ENDXYZ"

    # Build research_data with all 8 required keys, overriding company and error_flag
    research_data = {
        "company": unique_company,
        "role": "Software Engineer",
        "interview_rounds": "3",
        "key_topics": "Python, system design",
        "difficulty": "medium",
        "culture_keywords": "innovation, teamwork",
        "known_question_types": "behavioural, technical",
        "red_flags_to_test": "ownership, communication",
        "error_flag": error_flag,
    }

    # Capture the prompt passed to _safe_llm_call
    captured_prompts: list[str] = []

    def capture_llm_call(prompt, system, model, max_tokens, agent_name):
        captured_prompts.append(prompt)
        return {"questions": _make_valid_10_questions()}

    with (
        patch("agents.question_generator._safe_llm_call", side_effect=capture_llm_call),
        patch("agents.question_generator.save_questions"),
        patch("time.sleep"),
    ):
        result = generate_questions(research_data, "session-id-test", "test-api-key")

    # At least one prompt must have been captured
    assert captured_prompts, "Expected at least one _safe_llm_call invocation"
    user_prompt = captured_prompts[0]

    # Assert: error_flag isolation of company name in prompt
    if error_flag:
        assert unique_company not in user_prompt, (
            f"When error_flag=True, company name {unique_company!r} must NOT "
            f"appear in the user_prompt."
        )
    else:
        assert unique_company in user_prompt, (
            f"When error_flag=False, company name {unique_company!r} must "
            f"appear in the user_prompt."
        )

    # Assert: result is always a list of 10 dicts with the standard 7-key structure
    expected_keys = {"id", "category", "question", "ideal_keywords",
                     "difficulty", "follow_ups", "scoring_hint"}
    assert isinstance(result, list)
    assert len(result) == TOTAL_QUESTIONS
    for q in result:
        assert isinstance(q, dict)
        assert set(q.keys()) == expected_keys, (
            f"Expected keys {expected_keys}, got {set(q.keys())}"
        )

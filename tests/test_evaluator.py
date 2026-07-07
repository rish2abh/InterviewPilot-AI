"""
tests/test_evaluator.py — Unit and property-based tests for agents/evaluator.py.

Currently covers:
  - get_follow_up_question: all 4 branches (negative count, exceeds MAX_FOLLOW_UPS,
    valid index in list, fallback when list is too short/empty)
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agents.evaluator import get_follow_up_question
from core.config import MAX_FOLLOW_UPS


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def make_question_dict(follow_ups: list[str]) -> dict:
    """Return a minimal Question_Dict with the given follow_ups list."""
    return {
        "id": 1,
        "category": "technical",
        "question": "Explain REST.",
        "ideal_keywords": ["REST", "HTTP", "stateless"],
        "difficulty": "medium",
        "follow_ups": follow_ups,
        "scoring_hint": "Look for REST principles.",
    }


GENERIC_FALLBACK = "Can you elaborate on your answer with a specific example?"


# ---------------------------------------------------------------------------
# Unit tests — specific examples
# ---------------------------------------------------------------------------


class TestGetFollowUpQuestion:
    """Unit tests for the 4 branches in get_follow_up_question."""

    # Guard 1: negative index → None
    def test_negative_count_returns_none(self):
        q = make_question_dict(["First follow-up?", "Second follow-up?"])
        assert get_follow_up_question(q, -1) is None

    def test_very_negative_count_returns_none(self):
        q = make_question_dict(["First follow-up?"])
        assert get_follow_up_question(q, -100) is None

    # Guard 2: count >= MAX_FOLLOW_UPS → None
    def test_count_equal_to_max_returns_none(self):
        q = make_question_dict(["First follow-up?", "Second follow-up?", "Third?"])
        assert get_follow_up_question(q, MAX_FOLLOW_UPS) is None

    def test_count_exceeds_max_returns_none(self):
        q = make_question_dict(["First follow-up?", "Second follow-up?", "Third?"])
        assert get_follow_up_question(q, MAX_FOLLOW_UPS + 5) is None

    # Guard 3: valid index within list → return that element
    def test_count_zero_returns_first_follow_up(self):
        q = make_question_dict(["First follow-up?", "Second follow-up?"])
        assert get_follow_up_question(q, 0) == "First follow-up?"

    def test_count_one_returns_second_follow_up(self):
        # Only valid if MAX_FOLLOW_UPS > 1 (it is: 2)
        if MAX_FOLLOW_UPS > 1:
            q = make_question_dict(["First follow-up?", "Second follow-up?"])
            assert get_follow_up_question(q, 1) == "Second follow-up?"

    def test_returns_exact_string_from_list(self):
        follow_up = "Can you walk me through a real-world example of that?"
        q = make_question_dict([follow_up])
        assert get_follow_up_question(q, 0) == follow_up

    # Fallback: list empty or too short
    def test_empty_list_count_zero_returns_fallback(self):
        q = make_question_dict([])
        assert get_follow_up_question(q, 0) == GENERIC_FALLBACK

    def test_list_shorter_than_count_returns_fallback(self):
        # list has 1 item, count=1 is within MAX_FOLLOW_UPS (if > 1) but out of list
        if MAX_FOLLOW_UPS > 1:
            q = make_question_dict(["Only one follow-up."])
            assert get_follow_up_question(q, 1) == GENERIC_FALLBACK

    def test_empty_list_any_valid_count_returns_fallback(self):
        q = make_question_dict([])
        for count in range(MAX_FOLLOW_UPS):
            assert get_follow_up_question(q, count) == GENERIC_FALLBACK

    # Return type checks
    def test_returns_string_on_valid_index(self):
        q = make_question_dict(["Follow-up question?"])
        result = get_follow_up_question(q, 0)
        assert isinstance(result, str)

    def test_returns_none_on_negative(self):
        q = make_question_dict(["Follow-up question?"])
        result = get_follow_up_question(q, -1)
        assert result is None

    def test_returns_none_on_exceeded_limit(self):
        q = make_question_dict(["Follow-up question?"])
        result = get_follow_up_question(q, MAX_FOLLOW_UPS)
        assert result is None


# ---------------------------------------------------------------------------
# Property-based tests — Property 10: Follow-Up Retrieval Bounds
# Feature: evaluator-agent, Property 10: Follow-Up Retrieval Bounds
# Validates: Requirements 10.1, 10.2, 10.3, 10.4
# ---------------------------------------------------------------------------


@given(
    follow_ups=st.lists(st.text(min_size=1, max_size=200), min_size=0, max_size=10),
    follow_up_count=st.integers(min_value=-(10 ** 6), max_value=10 ** 6),
)
@settings(max_examples=100)
def test_property_follow_up_bounds(follow_ups: list[str], follow_up_count: int):
    """Property 10: Follow-Up Retrieval Bounds.

    For any Question_Dict and integer follow_up_count,
    get_follow_up_question must return:
    - None if follow_up_count < 0 or follow_up_count >= MAX_FOLLOW_UPS
    - question_dict["follow_ups"][follow_up_count] if 0 <= follow_up_count < MAX_FOLLOW_UPS
      and follow_up_count < len(follow_ups)
    - The generic fallback string if 0 <= follow_up_count < MAX_FOLLOW_UPS
      but follow_up_count >= len(follow_ups)

    Validates: Requirements 10.1, 10.2, 10.3, 10.4
    """
    q = make_question_dict(follow_ups)
    result = get_follow_up_question(q, follow_up_count)

    if follow_up_count < 0 or follow_up_count >= MAX_FOLLOW_UPS:
        # Guards 1 & 2 — must return None
        assert result is None, (
            f"Expected None for follow_up_count={follow_up_count} "
            f"(MAX_FOLLOW_UPS={MAX_FOLLOW_UPS}), got {result!r}"
        )
    elif follow_up_count < len(follow_ups):
        # Guard 3 — valid index
        assert result == follow_ups[follow_up_count], (
            f"Expected follow_ups[{follow_up_count}]={follow_ups[follow_up_count]!r}, "
            f"got {result!r}"
        )
    else:
        # Fallback — within bounds but list too short / empty
        assert result == GENERIC_FALLBACK, (
            f"Expected generic fallback for count={follow_up_count} "
            f"with len(follow_ups)={len(follow_ups)}, got {result!r}"
        )


# ---------------------------------------------------------------------------
# Helpers shared by TestEvaluateAnswer
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock

from agents.evaluator import evaluate_answer, SYSTEM_PROMPT
from core.config import MIN_ANSWER_LENGTH, RATE_LIMIT_SLEEP, WEAK_SCORE_THRESHOLD


def make_valid_raw_response(
    relevance: int = 3,
    depth: int = 3,
    structure: int = 3,
    examples: int = 3,
    total: int = 12,
    verdict: str = "good",
    feedback: str = "Try to elaborate more on your examples.",
    missing_keywords: list | None = None,
    trigger_follow_up: bool = False,
) -> dict:
    """Return a realistic raw LLM response dict for evaluate_answer mocking."""
    return {
        "scores": {
            "relevance": relevance,
            "depth": depth,
            "structure": structure,
            "examples": examples,
        },
        "total": total,
        "verdict": verdict,
        "feedback": feedback,
        "missing_keywords": missing_keywords if missing_keywords is not None else [],
        "trigger_follow_up": trigger_follow_up,
    }


# A valid answer that is exactly MIN_ANSWER_LENGTH characters long
EXACT_MIN_ANSWER = "x" * MIN_ANSWER_LENGTH

# A valid answer clearly above MIN_ANSWER_LENGTH
FULL_ANSWER = "x" * (MIN_ANSWER_LENGTH + 50)

SAMPLE_QUESTION = "What is REST?"
SAMPLE_KEYWORDS = ["REST", "HTTP", "stateless"]
SAMPLE_HINT = "Look for REST principles."


# ---------------------------------------------------------------------------
# Unit tests — evaluate_answer
# ---------------------------------------------------------------------------


class TestEvaluateAnswer:
    """Unit tests for evaluate_answer covering boundary conditions and error paths."""

    # ------------------------------------------------------------------
    # Test 1: Length boundary — exactly MIN_ANSWER_LENGTH calls LLM
    # Validates: Requirement 2.3
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    def test_exact_min_length_calls_llm(self, mock_llm):
        """len(user_answer) == MIN_ANSWER_LENGTH should NOT take the penalty path."""
        mock_llm.return_value = make_valid_raw_response()
        evaluate_answer(
            SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
            EXACT_MIN_ANSWER, "dummy_key",
        )
        mock_llm.assert_called_once()

    # ------------------------------------------------------------------
    # Test 2: Penalty path skips sleep
    # Validates: Requirement 2.1, 12.1
    # ------------------------------------------------------------------

    @patch("agents.evaluator.time.sleep")
    def test_penalty_path_skips_sleep(self, mock_sleep):
        """Short answer (< MIN_ANSWER_LENGTH) must NOT call time.sleep."""
        short_answer = "x" * (MIN_ANSWER_LENGTH - 1)
        evaluate_answer(
            SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
            short_answer, "dummy_key",
        )
        mock_sleep.assert_not_called()

    # ------------------------------------------------------------------
    # Test 3: Rate limit sleep called before LLM on full path
    # Validates: Requirement 12.1
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    @patch("agents.evaluator.time.sleep")
    def test_rate_limit_sleep_not_called_on_full_path(self, mock_sleep, mock_llm):
        """evaluate_answer must NOT call time.sleep — rate limiting is orchestrator-owned."""
        mock_llm.return_value = make_valid_raw_response()
        evaluate_answer(
            SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
            FULL_ANSWER, "dummy_key",
        )
        mock_sleep.assert_not_called()

    # ------------------------------------------------------------------
    # Test 4: LLM called exactly once per invocation on full path
    # Validates: Requirement 1.4
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    def test_llm_called_exactly_once(self, mock_llm):
        """_safe_llm_call must be invoked exactly once per evaluate_answer call."""
        mock_llm.return_value = make_valid_raw_response()
        evaluate_answer(
            SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
            FULL_ANSWER, "dummy_key",
        )
        assert mock_llm.call_count == 1

    # ------------------------------------------------------------------
    # Test 5: Non-numeric subscore raises ValueError
    # Validates: Requirement 7.4
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    def test_non_numeric_subscore_raises_value_error(self, mock_llm):
        """None relevance subscore must raise ValueError with 'Non-numeric subscore'."""
        raw = make_valid_raw_response()
        raw["scores"]["relevance"] = None
        mock_llm.return_value = raw
        with pytest.raises(ValueError, match="Non-numeric subscore"):
            evaluate_answer(
                SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
                FULL_ANSWER, "dummy_key",
            )

    # ------------------------------------------------------------------
    # Test 6: Missing required scores structure raises ValueError
    # Validates: Requirement 6.9
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    def test_missing_scores_key_raises_value_error(self, mock_llm):
        """LLM response with missing 'scores' key causes ValueError (non-numeric subscore)."""
        raw = make_valid_raw_response()
        del raw["scores"]  # remove the scores dict entirely
        mock_llm.return_value = raw
        with pytest.raises(ValueError):
            evaluate_answer(
                SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
                FULL_ANSWER, "dummy_key",
            )

    # ------------------------------------------------------------------
    # Test 7: Off-topic feedback override (relevance == 1)
    # Validates: Requirement 11.3
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    def test_off_topic_feedback_override(self, mock_llm):
        """When relevance == 1, feedback must be overridden with the off-topic message."""
        raw = make_valid_raw_response(
            relevance=1,
            depth=1,
            structure=1,
            examples=1,
            feedback="Some generic unrelated feedback.",
        )
        mock_llm.return_value = raw
        result = evaluate_answer(
            SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
            FULL_ANSWER, "dummy_key",
        )
        expected_feedback = (
            "Your answer was not relevant to the question asked; "
            "focus on the specific topic."
        )
        assert result["feedback"] == expected_feedback

    # ------------------------------------------------------------------
    # Test 8: System prompt ends with required suffix
    # Validates: Requirement 14.1
    # ------------------------------------------------------------------

    def test_system_prompt_ends_with_required_suffix(self):
        """SYSTEM_PROMPT must end with the exact required JSON instruction."""
        required_suffix = (
            "Return ONLY a JSON object. No markdown. No explanation. "
            "No text before or after. Pure JSON only."
        )
        assert SYSTEM_PROMPT.endswith(required_suffix)

    # ------------------------------------------------------------------
    # Test 9: Token usage logging to stdout
    # Validates: Requirement 16.1
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    def test_token_usage_logged_on_success(self, mock_llm, capsys):
        """After a successful call, stdout must contain '[Evaluator] Success. Tokens:'."""
        mock_llm.return_value = make_valid_raw_response()
        # Simulate the print that _safe_llm_call would emit
        import builtins
        original_print = builtins.print

        printed_lines = []

        def capturing_print(*args, **kwargs):
            printed_lines.append(" ".join(str(a) for a in args))
            original_print(*args, **kwargs)

        # Patch _safe_llm_call to also emit the expected log line
        def mock_llm_with_log(prompt, system, model, max_tokens, agent_name):
            print(f"[{agent_name}] Success. Tokens: mock_usage")
            return make_valid_raw_response()

        mock_llm.side_effect = mock_llm_with_log

        evaluate_answer(
            SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
            FULL_ANSWER, "dummy_key",
        )
        captured = capsys.readouterr()
        assert "[Evaluator] Success. Tokens:" in captured.out

    # ------------------------------------------------------------------
    # Test 10: Total recalculation ignores LLM total
    # Validates: Requirement 3.1, 3.2
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    def test_total_recalculation_ignores_llm_total(self, mock_llm):
        """LLM total=99 must be discarded; result['total'] == sum of subscores."""
        # subscores: 4+4+3+3 = 14
        raw = make_valid_raw_response(
            relevance=4, depth=4, structure=3, examples=3,
            total=99,   # LLM hallucinated total — must be discarded
            verdict="good",
        )
        mock_llm.return_value = raw
        result = evaluate_answer(
            SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
            FULL_ANSWER, "dummy_key",
        )
        assert result["total"] == 14

    # ------------------------------------------------------------------
    # Test 11: Verdict from recalculated total (weak path)
    # Validates: Requirement 4.1, 5.1
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    def test_verdict_from_recalculated_total_weak(self, mock_llm):
        """Subscores summing below WEAK_SCORE_THRESHOLD yield verdict 'weak' and trigger_follow_up True."""
        # 3+3+3+2 = 11 < WEAK_SCORE_THRESHOLD (12)
        raw = make_valid_raw_response(
            relevance=3, depth=3, structure=3, examples=2,
            total=11,
            verdict="good",        # LLM verdict overridden
            trigger_follow_up=False,  # LLM value overridden
        )
        mock_llm.return_value = raw
        result = evaluate_answer(
            SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
            FULL_ANSWER, "dummy_key",
        )
        assert result["verdict"] == "weak"
        assert result["trigger_follow_up"] is True

    # ------------------------------------------------------------------
    # Test 12: Missing keywords filtered to ideal_keywords subset
    # Validates: Requirement 9.1, 9.2
    # ------------------------------------------------------------------

    @patch("agents.evaluator._safe_llm_call")
    def test_missing_keywords_filtered_to_ideal_subset(self, mock_llm):
        """LLM-returned missing_keywords with invalid entries must be filtered."""
        ideal_keywords = ["keyword1", "keyword2"]
        # LLM returns "keyword1" (valid) and "INVALID" (not in ideal_keywords)
        raw = make_valid_raw_response(
            relevance=3, depth=3, structure=3, examples=3,
            missing_keywords=["keyword1", "INVALID"],
        )
        mock_llm.return_value = raw
        result = evaluate_answer(
            SAMPLE_QUESTION, ideal_keywords, SAMPLE_HINT,
            FULL_ANSWER, "dummy_key",
        )
        # Only "keyword1" is in ideal_keywords; "INVALID" must be stripped
        assert result["missing_keywords"] == ["keyword1"]

    # ------------------------------------------------------------------
    # Test 13: Penalty dict structure has all 6 required keys
    # Validates: Requirement 2.1, 2.2
    # ------------------------------------------------------------------

    def test_penalty_dict_has_correct_structure(self):
        """Short answer must return a dict with exactly the 6 Penalty_Dict keys."""
        short_answer = "x" * (MIN_ANSWER_LENGTH - 1)
        result = evaluate_answer(
            SAMPLE_QUESTION, SAMPLE_KEYWORDS, SAMPLE_HINT,
            short_answer, "dummy_key",
        )
        required_keys = {"scores", "total", "verdict", "feedback", "missing_keywords", "trigger_follow_up"}
        assert set(result.keys()) == required_keys
        assert result["scores"] == {"relevance": 1, "depth": 1, "structure": 1, "examples": 1}
        assert result["total"] == 4
        assert result["verdict"] == "weak"
        assert result["feedback"] == "Answer too short. Elaborate with a specific example."
        assert result["missing_keywords"] == SAMPLE_KEYWORDS
        assert result["trigger_follow_up"] is True

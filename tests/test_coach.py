"""
tests/test_coach.py — Unit tests for agents/coach.py.

Covers boundary conditions, error paths, and integration behavior for the
Coach Agent's generate_report function and its private helpers.
"""

import inspect
import io
import json
import contextlib
from unittest.mock import patch, MagicMock, call

import pytest

from agents.coach import generate_report, SYSTEM_PROMPT, _safe_llm_call
from core.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    MAX_TOKENS_REPORT,
    RATE_LIMIT_SLEEP,
    ERROR_RETRY_SLEEP,
    HIRING_LOW_MAX,
    HIRING_HIGH_MIN,
    MAX_TOTAL_SCORE,
    TOTAL_QUESTIONS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_valid_answers(total_per_answer=15, count=TOTAL_QUESTIONS):
    """Build a list of valid Answer_Dict objects for testing."""
    return [
        {
            "question": f"Question {i+1}",
            "answer_text": f"Answer text for question {i+1}",
            "category": "technical" if i % 2 == 0 else "behavioral",
            "evaluation": {
                "total": total_per_answer,
                "missing_keywords": ["keyword1", "keyword2"],
                "feedback": f"Feedback for question {i+1}",
            },
        }
        for i in range(count)
    ]


VALID_LLM_RESPONSE = {
    "overall_score": 120,
    "hiring_probability": "Medium",
    "hiring_probability_percent": 60,
    "strongest_category": "technical",
    "weakest_category": "behavioral",
    "category_averages": {"technical": 15.5, "behavioral": 12.0},
    "top_3_strengths": ["Good depth", "Clear structure", "Real examples"],
    "top_3_improvements": [
        {"area": "keywords", "why": "shows knowledge", "how_to_fix": "study more", "free_resource": "https://leetcode.com"},
        {"area": "examples", "why": "concreteness", "how_to_fix": "practice stories", "free_resource": "https://pramp.com"},
        {"area": "depth", "why": "thoroughness", "how_to_fix": "go deeper", "free_resource": "https://neetcode.io"},
    ],
    "critical_moment": "Question 3 was the turning point",
    "overall_verdict": "Good candidate with room to grow",
    "next_interview_tip": "Practice system design questions",
}


# ---------------------------------------------------------------------------
# Test 1: Valid input succeeds
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_valid_input_succeeds(mock_sleep, mock_client, mock_llm):
    """Mock LLM returning valid 11-key JSON → returns Report_Dict with 11 keys."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    answers = make_valid_answers(total_per_answer=15)
    result = generate_report("session-123", answers)
    assert isinstance(result, dict)
    assert len(result) == 11
    expected_keys = {
        "overall_score", "hiring_probability", "hiring_probability_percent",
        "strongest_category", "weakest_category", "category_averages",
        "top_3_strengths", "top_3_improvements", "critical_moment",
        "overall_verdict", "next_interview_tip",
    }
    assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Test 2: Rate limit sleep called
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_rate_limit_sleep_called(mock_sleep, mock_client, mock_llm):
    """Assert time.sleep called with RATE_LIMIT_SLEEP before LLM."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    generate_report("session-123", make_valid_answers())
    mock_sleep.assert_called_once_with(RATE_LIMIT_SLEEP)


# ---------------------------------------------------------------------------
# Test 3: GEMINI_API_KEY used
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_gemini_api_key_used(mock_sleep, mock_client, mock_llm):
    """Assert genai.Client called with api_key=GEMINI_API_KEY."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    generate_report("session-123", make_valid_answers())
    mock_client.assert_called_once_with(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Test 4: GEMINI_MODEL used
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_gemini_model_used(mock_sleep, mock_client, mock_llm):
    """Assert GEMINI_MODEL is passed to _safe_llm_call via the client."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    generate_report("session-123", make_valid_answers())
    # Model name is now used inside _safe_llm_call; verify client was created
    mock_client.assert_called_once_with(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Test 5: MAX_TOKENS_REPORT passed
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_max_tokens_report_passed(mock_sleep, mock_client, mock_llm):
    """Assert _safe_llm_call is called with max_tokens == MAX_TOKENS_REPORT."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    generate_report("session-123", make_valid_answers())
    _, kwargs = mock_llm.call_args
    # _safe_llm_call(user_prompt, SYSTEM_PROMPT, model, MAX_TOKENS_REPORT, "Coach")
    args = mock_llm.call_args[0]
    assert args[3] == MAX_TOKENS_REPORT


# ---------------------------------------------------------------------------
# Test 6: Agent name is "Coach"
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_agent_name_is_coach(mock_sleep, mock_client, mock_llm):
    """Assert _safe_llm_call is called with agent_name == 'Coach'."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    generate_report("session-123", make_valid_answers())
    args = mock_llm.call_args[0]
    assert args[4] == "Coach"


# ---------------------------------------------------------------------------
# Test 7: System prompt suffix
# ---------------------------------------------------------------------------

def test_system_prompt_suffix():
    """Assert SYSTEM_PROMPT ends with exact required suffix."""
    required_suffix = (
        "Return ONLY a JSON object. No markdown. No explanation. "
        "No text before or after. Pure JSON only."
    )
    assert SYSTEM_PROMPT.endswith(required_suffix)


# ---------------------------------------------------------------------------
# Test 8: Invalid session_id empty raises
# ---------------------------------------------------------------------------

def test_invalid_session_id_empty_raises():
    """session_id='' → ValueError before any sleep."""
    with pytest.raises(ValueError, match="session_id"):
        generate_report("", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 9: Invalid session_id None raises
# ---------------------------------------------------------------------------

def test_invalid_session_id_none_raises():
    """session_id=None → ValueError."""
    with pytest.raises(ValueError, match="session_id"):
        generate_report(None, make_valid_answers())


# ---------------------------------------------------------------------------
# Test 10: Non-list answers raises
# ---------------------------------------------------------------------------

def test_non_list_answers_raises():
    """answers='not a list' → ValueError."""
    with pytest.raises(ValueError, match="must be a list"):
        generate_report("session-123", "not a list")


# ---------------------------------------------------------------------------
# Test 11: Empty answers raises
# ---------------------------------------------------------------------------

def test_empty_answers_raises():
    """answers=[] → ValueError."""
    with pytest.raises(ValueError, match="no answers"):
        generate_report("session-123", [])


# ---------------------------------------------------------------------------
# Test 12: Wrong count raises
# ---------------------------------------------------------------------------

def test_wrong_count_raises():
    """9 answers → ValueError with expected/actual counts."""
    answers = make_valid_answers(count=9)
    with pytest.raises(ValueError, match=r"expected.*10.*got.*9"):
        generate_report("session-123", answers)


# ---------------------------------------------------------------------------
# Test 13: Missing category raises
# ---------------------------------------------------------------------------

def test_missing_category_raises():
    """Answer_Dict without category → ValueError with index."""
    answers = make_valid_answers()
    del answers[2]["category"]
    with pytest.raises(ValueError, match="index 2"):
        generate_report("session-123", answers)


# ---------------------------------------------------------------------------
# Test 14: Missing evaluation raises
# ---------------------------------------------------------------------------

def test_missing_evaluation_raises():
    """Answer_Dict without evaluation → ValueError with index."""
    answers = make_valid_answers()
    del answers[5]["evaluation"]
    with pytest.raises(ValueError, match="index 5"):
        generate_report("session-123", answers)


# ---------------------------------------------------------------------------
# Test 15: Missing evaluation.total raises
# ---------------------------------------------------------------------------

def test_missing_evaluation_total_raises():
    """evaluation={"missing_keywords": []} → ValueError."""
    answers = make_valid_answers()
    answers[3]["evaluation"] = {"missing_keywords": []}
    with pytest.raises(ValueError, match="index 3"):
        generate_report("session-123", answers)


# ---------------------------------------------------------------------------
# Test 16: Missing evaluation.missing_keywords raises
# ---------------------------------------------------------------------------

def test_missing_evaluation_missing_keywords_raises():
    """evaluation={"total": 15} → ValueError."""
    answers = make_valid_answers()
    answers[7]["evaluation"] = {"total": 15}
    with pytest.raises(ValueError, match="index 7"):
        generate_report("session-123", answers)


# ---------------------------------------------------------------------------
# Test 17: LLM missing keys raises
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_llm_missing_keys_raises(mock_sleep, mock_client, mock_llm):
    """Mock LLM missing 'critical_moment' → ValueError listing missing keys."""
    response = VALID_LLM_RESPONSE.copy()
    del response["critical_moment"]
    mock_llm.return_value = response
    with pytest.raises(ValueError, match="critical_moment"):
        generate_report("session-123", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 18: Extra keys stripped
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_extra_keys_stripped(mock_sleep, mock_client, mock_llm):
    """Mock LLM returning 13 keys → output has exactly 11 keys."""
    response = VALID_LLM_RESPONSE.copy()
    response["extra_key_1"] = "should be stripped"
    response["extra_key_2"] = "should also be stripped"
    mock_llm.return_value = response
    result = generate_report("session-123", make_valid_answers())
    assert len(result) == 11
    assert "extra_key_1" not in result
    assert "extra_key_2" not in result


# ---------------------------------------------------------------------------
# Test 19: overall_score overridden
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_overall_score_overridden(mock_sleep, mock_client, mock_llm):
    """Mock LLM returning overall_score=999 → output uses sum of totals."""
    response = VALID_LLM_RESPONSE.copy()
    response["overall_score"] = 999
    mock_llm.return_value = response
    answers = make_valid_answers(total_per_answer=15)
    result = generate_report("session-123", answers)
    assert result["overall_score"] == 15 * TOTAL_QUESTIONS  # 150


# ---------------------------------------------------------------------------
# Test 20: hiring_probability overridden
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_hiring_probability_overridden(mock_sleep, mock_client, mock_llm):
    """Mock LLM returning 'Very High' → output uses band calculation."""
    response = VALID_LLM_RESPONSE.copy()
    response["hiring_probability"] = "Very High"
    mock_llm.return_value = response
    # total_per_answer=15 → sum=150 > HIRING_HIGH_MIN(140) → "High"
    answers = make_valid_answers(total_per_answer=15)
    result = generate_report("session-123", answers)
    assert result["hiring_probability"] == "High"


# ---------------------------------------------------------------------------
# Test 21: hiring_probability_percent overridden
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_hiring_probability_percent_overridden(mock_sleep, mock_client, mock_llm):
    """Mock LLM returning 99 → output uses formula."""
    response = VALID_LLM_RESPONSE.copy()
    response["hiring_probability_percent"] = 99
    mock_llm.return_value = response
    # total_per_answer=15 → sum=150 → round((150/200)*100) == 75
    answers = make_valid_answers(total_per_answer=15)
    result = generate_report("session-123", answers)
    assert result["hiring_probability_percent"] == 75


# ---------------------------------------------------------------------------
# Test 22: Low band score 79
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_low_band_score_79(mock_sleep, mock_client, mock_llm):
    """Mock answers summing to 79 → hiring_probability == 'Low'."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    # 79 total: first answer has 7, rest have 8 each → 7 + 9*8 = 79
    answers = make_valid_answers(total_per_answer=8)
    answers[0]["evaluation"]["total"] = 7  # 7 + 9*8 = 79
    result = generate_report("session-123", answers)
    assert result["overall_score"] == 79
    assert result["hiring_probability"] == "Low"


# ---------------------------------------------------------------------------
# Test 23: Medium band score 80
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_medium_band_score_80(mock_sleep, mock_client, mock_llm):
    """Mock answers summing to 80 → hiring_probability == 'Medium'."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    answers = make_valid_answers(total_per_answer=8)  # 8*10=80
    result = generate_report("session-123", answers)
    assert result["overall_score"] == 80
    assert result["hiring_probability"] == "Medium"


# ---------------------------------------------------------------------------
# Test 24: Medium band score 140
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_medium_band_score_140(mock_sleep, mock_client, mock_llm):
    """Mock answers summing to 140 → hiring_probability == 'Medium'."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    answers = make_valid_answers(total_per_answer=14)  # 14*10=140
    result = generate_report("session-123", answers)
    assert result["overall_score"] == 140
    assert result["hiring_probability"] == "Medium"


# ---------------------------------------------------------------------------
# Test 25: High band score 141
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_high_band_score_141(mock_sleep, mock_client, mock_llm):
    """Mock answers summing to 141 → hiring_probability == 'High'."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    # 141 total: first answer has 15, rest have 14 each → 15 + 9*14 = 141
    answers = make_valid_answers(total_per_answer=14)
    answers[0]["evaluation"]["total"] = 15  # 15 + 9*14 = 141
    result = generate_report("session-123", answers)
    assert result["overall_score"] == 141
    assert result["hiring_probability"] == "High"


# ---------------------------------------------------------------------------
# Test 26: hiring_probability_percent calculation
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_hiring_probability_percent_calculation(mock_sleep, mock_client, mock_llm):
    """score 150 → round((150/200)*100) == 75."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    answers = make_valid_answers(total_per_answer=15)  # 15*10=150
    result = generate_report("session-123", answers)
    assert result["hiring_probability_percent"] == round((150 / MAX_TOTAL_SCORE) * 100)
    assert result["hiring_probability_percent"] == 75


# ---------------------------------------------------------------------------
# Test 27: Invalid strongest_category raises
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_invalid_strongest_category_raises(mock_sleep, mock_client, mock_llm):
    """Empty string strongest_category → ValueError."""
    response = VALID_LLM_RESPONSE.copy()
    response["strongest_category"] = ""
    mock_llm.return_value = response
    with pytest.raises(ValueError, match="strongest_category"):
        generate_report("session-123", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 28: Invalid top_3_strengths count raises
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_invalid_top_3_strengths_count_raises(mock_sleep, mock_client, mock_llm):
    """2 items in top_3_strengths → ValueError."""
    response = VALID_LLM_RESPONSE.copy()
    response["top_3_strengths"] = ["Good depth", "Clear structure"]
    mock_llm.return_value = response
    with pytest.raises(ValueError, match="top_3_strengths"):
        generate_report("session-123", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 29: Invalid improvement entry missing key
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_invalid_improvement_entry_missing_key(mock_sleep, mock_client, mock_llm):
    """Entry without 'how_to_fix' → ValueError."""
    response = VALID_LLM_RESPONSE.copy()
    response["top_3_improvements"] = [
        {"area": "keywords", "why": "shows knowledge", "how_to_fix": "study more", "free_resource": "https://leetcode.com"},
        {"area": "examples", "why": "concreteness", "free_resource": "https://pramp.com"},  # missing how_to_fix
        {"area": "depth", "why": "thoroughness", "how_to_fix": "go deeper", "free_resource": "https://neetcode.io"},
    ]
    mock_llm.return_value = response
    with pytest.raises(ValueError, match="how_to_fix"):
        generate_report("session-123", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 30: Invalid free_resource URL
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_invalid_free_resource_url(mock_sleep, mock_client, mock_llm):
    """'not-a-url' → ValueError."""
    response = VALID_LLM_RESPONSE.copy()
    response["top_3_improvements"] = [
        {"area": "keywords", "why": "shows knowledge", "how_to_fix": "study more", "free_resource": "not-a-url"},
        {"area": "examples", "why": "concreteness", "how_to_fix": "practice stories", "free_resource": "https://pramp.com"},
        {"area": "depth", "why": "thoroughness", "how_to_fix": "go deeper", "free_resource": "https://neetcode.io"},
    ]
    mock_llm.return_value = response
    with pytest.raises(ValueError, match="free_resource"):
        generate_report("session-123", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 31: Empty free_resource raises
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_empty_free_resource_raises(mock_sleep, mock_client, mock_llm):
    """'' free_resource → ValueError."""
    response = VALID_LLM_RESPONSE.copy()
    response["top_3_improvements"] = [
        {"area": "keywords", "why": "shows knowledge", "how_to_fix": "study more", "free_resource": ""},
        {"area": "examples", "why": "concreteness", "how_to_fix": "practice stories", "free_resource": "https://pramp.com"},
        {"area": "depth", "why": "thoroughness", "how_to_fix": "go deeper", "free_resource": "https://neetcode.io"},
    ]
    mock_llm.return_value = response
    with pytest.raises(ValueError):
        generate_report("session-123", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 32: critical_moment no digit raises
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_critical_moment_no_digit_raises(mock_sleep, mock_client, mock_llm):
    """'The candidate performed well' → ValueError."""
    response = VALID_LLM_RESPONSE.copy()
    response["critical_moment"] = "The candidate performed well"
    mock_llm.return_value = response
    with pytest.raises(ValueError, match="critical_moment"):
        generate_report("session-123", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 33: critical_moment with digit passes
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_critical_moment_with_digit_passes(mock_sleep, mock_client, mock_llm):
    """'Question 3 was the turning point' → passes validation."""
    response = VALID_LLM_RESPONSE.copy()
    response["critical_moment"] = "Question 3 was the turning point"
    mock_llm.return_value = response
    result = generate_report("session-123", make_valid_answers())
    assert result["critical_moment"] == "Question 3 was the turning point"


# ---------------------------------------------------------------------------
# Test 34: Compression excludes answer_text
# ---------------------------------------------------------------------------

@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_compression_excludes_answer_text(mock_sleep, mock_client_cls):
    """Capture user prompt, assert no answer_text content present."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.text = json.dumps(VALID_LLM_RESPONSE)
    mock_response.usage_metadata = "mock_tokens"
    mock_client.models.generate_content.return_value = mock_response

    answers = make_valid_answers()
    result = generate_report("session-123", answers)

    # Get the user prompt passed to generate_content
    call_kwargs = mock_client.models.generate_content.call_args
    user_prompt = call_kwargs.kwargs.get("contents") or call_kwargs[1].get("contents")
    if user_prompt is None:
        # positional args
        user_prompt = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[0][0]

    # answer_text values should NOT appear in prompt
    for answer in answers:
        assert answer["answer_text"] not in user_prompt
        assert answer["question"] not in user_prompt


# ---------------------------------------------------------------------------
# Test 35: Compression includes question_index
# ---------------------------------------------------------------------------

@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_compression_includes_question_index(mock_sleep, mock_client_cls):
    """Each compressed entry has 1-based index."""
    mock_client = MagicMock()
    mock_client_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.text = json.dumps(VALID_LLM_RESPONSE)
    mock_response.usage_metadata = "mock_tokens"
    mock_client.models.generate_content.return_value = mock_response

    answers = make_valid_answers()
    generate_report("session-123", answers)

    # Parse the compressed JSON from the user prompt
    call_kwargs = mock_client.models.generate_content.call_args
    user_prompt = call_kwargs.kwargs.get("contents") or call_kwargs[1].get("contents")
    if user_prompt is None:
        user_prompt = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[0][0]

    # Extract the compressed data JSON from the prompt
    # The prompt has format: "...Compressed answer data:\n{json}"
    compressed_start = user_prompt.index("Compressed answer data:\n") + len("Compressed answer data:\n")
    compressed_json = user_prompt[compressed_start:]
    compressed = json.loads(compressed_json)

    assert len(compressed) == TOTAL_QUESTIONS
    for i, entry in enumerate(compressed):
        assert entry["question_index"] == i + 1


# ---------------------------------------------------------------------------
# Test 36: JSON retry behavior
# ---------------------------------------------------------------------------

def test_json_retry_behavior():
    """Mock client.models.generate_content returns invalid JSON then valid → retries."""
    mock_client = MagicMock()

    # First call returns invalid JSON, second returns valid
    response_bad = MagicMock()
    response_bad.text = "not json at all"
    response_good = MagicMock()
    response_good.text = json.dumps(VALID_LLM_RESPONSE)
    response_good.usage_metadata = "mock_tokens"

    mock_client.models.generate_content.side_effect = [response_bad, response_good]

    with patch("agents.coach.time.sleep"):
        result = _safe_llm_call("prompt", "system", mock_client, 1500, "Coach")

    assert mock_client.models.generate_content.call_count == 2
    assert result == VALID_LLM_RESPONSE


# ---------------------------------------------------------------------------
# Test 37: API error retry
# ---------------------------------------------------------------------------

def test_api_error_retry():
    """Mock client.models.generate_content raises then succeeds → ERROR_RETRY_SLEEP sleep, retry."""
    mock_client = MagicMock()

    response_good = MagicMock()
    response_good.text = json.dumps(VALID_LLM_RESPONSE)
    response_good.usage_metadata = "mock_tokens"

    mock_client.models.generate_content.side_effect = [
        RuntimeError("API error"),
        response_good,
    ]

    with patch("agents.coach.time.sleep") as mock_sleep:
        result = _safe_llm_call("prompt", "system", mock_client, 1500, "Coach")

    mock_sleep.assert_called_with(ERROR_RETRY_SLEEP)
    assert result == VALID_LLM_RESPONSE


# ---------------------------------------------------------------------------
# Test 38: ValueError propagation from _safe_llm_call
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_valueerror_propagation_from_safe_llm_call(mock_sleep, mock_client, mock_llm):
    """Mock raises ValueError → propagated to caller."""
    mock_llm.side_effect = ValueError("Coach failed after 2 attempts")
    with pytest.raises(ValueError, match="Coach failed after 2 attempts"):
        generate_report("session-123", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 39: Non-ValueError propagation
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_non_valueerror_propagation(mock_sleep, mock_client, mock_llm):
    """Mock raises RuntimeError → propagated unchanged."""
    mock_llm.side_effect = RuntimeError("API exploded")
    with pytest.raises(RuntimeError, match="API exploded"):
        generate_report("session-123", make_valid_answers())


# ---------------------------------------------------------------------------
# Test 40: No database operations
# ---------------------------------------------------------------------------

@patch("agents.coach._safe_llm_call")
@patch("agents.coach.genai.Client")
@patch("agents.coach.time.sleep")
def test_no_database_operations(mock_sleep, mock_client, mock_llm):
    """Mock core.database, assert no DB functions called."""
    mock_llm.return_value = VALID_LLM_RESPONSE.copy()
    with patch.dict("sys.modules", {"core.database": MagicMock()}) as mock_modules:
        import sys
        mock_db = sys.modules["core.database"]
        generate_report("session-123", make_valid_answers())
        # Verify no methods on the mock database module were called
        assert mock_db.method_calls == []
        assert mock_db.call_count == 0


# ---------------------------------------------------------------------------
# Test 41: Token usage logging
# ---------------------------------------------------------------------------

def test_token_usage_logging(capsys):
    """Capture stdout, assert '[Coach] Success. Tokens:' format."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps(VALID_LLM_RESPONSE)
    mock_response.usage_metadata = "prompt=100, completion=200"
    mock_client.models.generate_content.return_value = mock_response

    with patch("agents.coach.time.sleep"):
        _safe_llm_call("prompt", "system", mock_client, 1500, "Coach")

    captured = capsys.readouterr()
    assert "[Coach] Success. Tokens:" in captured.out


# ---------------------------------------------------------------------------
# Test 42: No public functions besides generate_report
# ---------------------------------------------------------------------------

def test_no_public_functions_besides_generate_report():
    """Inspect module, verify no other public names."""
    import agents.coach as coach_module

    public_names = [
        name for name in dir(coach_module)
        if not name.startswith("_")
        and callable(getattr(coach_module, name))
        and not inspect.ismodule(getattr(coach_module, name))
        and not inspect.isclass(getattr(coach_module, name))
    ]

    # Filter out imported modules/functions that aren't defined in coach.py
    defined_public_functions = [
        name for name in public_names
        if getattr(getattr(coach_module, name), "__module__", None) == "agents.coach"
    ]

    assert defined_public_functions == ["generate_report"], (
        f"Expected only 'generate_report' as public function, "
        f"found: {defined_public_functions}"
    )

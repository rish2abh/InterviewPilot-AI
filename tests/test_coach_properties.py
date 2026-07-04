"""
tests/test_coach_properties.py — Property-based tests for agents/coach.py.
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from agents.coach import _compress_answers, _validate_report, _calculate_hiring_probability, _calculate_hiring_percent, _validate_report
from core.config import HIRING_LOW_MAX, HIRING_HIGH_MIN, MAX_TOTAL_SCORE


# Feature: coach-agent, Property 1: Compression Correctness and Data Isolation
@settings(max_examples=100)
@given(
    scores=st.lists(st.integers(4, 20), min_size=10, max_size=10),
    categories=st.lists(
        st.sampled_from(["technical", "behavioral", "situational", "curveball"]),
        min_size=10, max_size=10
    ),
    missing_kws=st.lists(
        st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=5),
        min_size=10, max_size=10
    ),
    answer_texts=st.lists(st.text(min_size=1, max_size=100), min_size=10, max_size=10),
    questions=st.lists(st.text(min_size=1, max_size=100), min_size=10, max_size=10),
    feedbacks=st.lists(st.text(min_size=1, max_size=100), min_size=10, max_size=10),
)
def test_compression_correctness_and_data_isolation(
    scores, categories, missing_kws, answer_texts, questions, feedbacks
):
    """For any valid Answer_Dict list, compressed output has exactly 4 keys per entry,
    question_index equals 1-based position, and no answer_text/question/feedback leaks."""
    # Build Answer_Dict list
    answers = []
    for i in range(10):
        answers.append({
            "question": questions[i],
            "answer_text": answer_texts[i],
            "category": categories[i],
            "evaluation": {
                "total": scores[i],
                "missing_keywords": missing_kws[i],
                "feedback": feedbacks[i],
            },
        })

    compressed = _compress_answers(answers)

    # Assert correct number of entries
    assert len(compressed) == 10

    for i, entry in enumerate(compressed):
        # Each entry has exactly 4 keys
        assert set(entry.keys()) == {"question_index", "score", "category", "missing_keywords"}
        # question_index is 1-based
        assert entry["question_index"] == i + 1
        # score matches
        assert entry["score"] == scores[i]
        # category matches
        assert entry["category"] == categories[i]
        # missing_keywords matches
        assert entry["missing_keywords"] == missing_kws[i]




# Feature: coach-agent, Property 4: Output Contract Invariant
@settings(max_examples=100)
@given(
    extra_keys=st.dictionaries(
        st.text(min_size=1, max_size=10).filter(lambda x: x not in {
            "overall_score", "hiring_probability", "hiring_probability_percent",
            "strongest_category", "weakest_category", "category_averages",
            "top_3_strengths", "top_3_improvements", "critical_moment",
            "overall_verdict", "next_interview_tip",
        }),
        st.text(min_size=1, max_size=20),
        min_size=0, max_size=5,
    )
)
def test_output_contract_invariant(extra_keys):
    """Valid 11-key dicts with random extra keys always produce exactly 11 keys after validation."""
    valid_report = {
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
    # Add random extra keys
    report_with_extras = {**valid_report, **extra_keys}

    result = _validate_report(report_with_extras)

    # Must have exactly 11 keys
    assert len(result) == 11
    # Must have exactly the required keys
    expected_keys = {
        "overall_score", "hiring_probability", "hiring_probability_percent",
        "strongest_category", "weakest_category", "category_averages",
        "top_3_strengths", "top_3_improvements", "critical_moment",
        "overall_verdict", "next_interview_tip",
    }
    assert set(result.keys()) == expected_keys
    # No extra keys present
    for key in extra_keys:
        if key not in expected_keys:
            assert key not in result



# Feature: coach-agent, Property 3: Hiring Probability Band Classification
@settings(max_examples=100)
@given(overall_score=st.integers(40, 200))
def test_hiring_probability_band_classification(overall_score):
    """For any score in [40, 200], band classification is correct and percent is in [0, 100]."""
    result = _calculate_hiring_probability(overall_score)

    if overall_score < HIRING_LOW_MAX:
        assert result == "Low"
    elif overall_score <= HIRING_HIGH_MIN:
        assert result == "Medium"
    else:
        assert result == "High"

    # Verify percent is always an int in [0, 100]
    percent = _calculate_hiring_percent(overall_score)
    assert isinstance(percent, int)
    assert 0 <= percent <= 100
    # Verify percent matches formula
    expected = max(0, min(100, round((overall_score / MAX_TOTAL_SCORE) * 100)))
    assert percent == expected


# Feature: coach-agent, Property 6: Improvement Entry Structural Validation
@settings(max_examples=100)
@given(
    url_prefix=st.sampled_from(["https://", "http://", "ftp://", "", "not-a-url"]),
    has_area=st.booleans(),
    has_why=st.booleans(),
    has_how_to_fix=st.booleans(),
    has_free_resource=st.booleans(),
    area_value=st.text(min_size=1, max_size=30),
    why_value=st.text(min_size=1, max_size=30),
    how_to_fix_value=st.text(min_size=1, max_size=30),
)
def test_improvement_entry_structural_validation(
    url_prefix, has_area, has_why, has_how_to_fix, has_free_resource,
    area_value, why_value, how_to_fix_value,
):
    """Validation passes iff entry has all 4 keys as non-empty str and free_resource starts with http:// or https://."""
    # Build the test entry
    entry = {}
    if has_area:
        entry["area"] = area_value
    if has_why:
        entry["why"] = why_value
    if has_how_to_fix:
        entry["how_to_fix"] = how_to_fix_value
    if has_free_resource:
        entry["free_resource"] = url_prefix + "example.com/resource"

    # Build a full valid report except for the test entry at position 0
    valid_entries = [
        {"area": "keywords", "why": "shows knowledge", "how_to_fix": "study more", "free_resource": "https://leetcode.com"},
        {"area": "depth", "why": "thoroughness", "how_to_fix": "go deeper", "free_resource": "https://neetcode.io"},
    ]
    
    report = {
        "overall_score": 120,
        "hiring_probability": "Medium",
        "hiring_probability_percent": 60,
        "strongest_category": "technical",
        "weakest_category": "behavioral",
        "category_averages": {"technical": 15.5, "behavioral": 12.0},
        "top_3_strengths": ["Good depth", "Clear structure", "Real examples"],
        "top_3_improvements": [entry] + valid_entries,
        "critical_moment": "Question 3 was the turning point",
        "overall_verdict": "Good candidate with room to grow",
        "next_interview_tip": "Practice system design questions",
    }

    # Determine if this should be valid
    all_keys_present = has_area and has_why and has_how_to_fix and has_free_resource
    all_non_empty = (
        all_keys_present
        and bool(area_value.strip())
        and bool(why_value.strip())
        and bool(how_to_fix_value.strip())
        and bool((url_prefix + "example.com/resource").strip())
    )
    valid_url = url_prefix in ("https://", "http://")
    
    should_pass = all_keys_present and all_non_empty and valid_url

    if should_pass:
        result = _validate_report(report)
        assert result is not None
    else:
        with pytest.raises(ValueError) as exc_info:
            _validate_report(report)
        assert "Coach" in str(exc_info.value)



# Feature: coach-agent, Property 7: Critical Moment Digit Requirement
@settings(max_examples=100)
@given(critical_moment=st.text())
def test_critical_moment_digit_requirement(critical_moment):
    """Validation passes iff critical_moment is non-empty and contains at least one digit."""
    import re as _re
    
    report = {
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
        "critical_moment": critical_moment,
        "overall_verdict": "Good candidate with room to grow",
        "next_interview_tip": "Practice system design questions",
    }

    has_digit = bool(_re.search(r'\d', critical_moment))
    is_non_empty = bool(critical_moment.strip())
    should_pass = is_non_empty and has_digit

    if should_pass:
        result = _validate_report(report)
        assert result["critical_moment"] == critical_moment
    else:
        with pytest.raises(ValueError) as exc_info:
            _validate_report(report)
        assert "Coach" in str(exc_info.value)
        assert "critical_moment" in str(exc_info.value)



# Feature: coach-agent, Property 9: Exception propagation
@settings(max_examples=100)
@given(exc=st.sampled_from([ValueError("fail"), RuntimeError("api"), ConnectionError("net")]))
def test_exception_propagation(exc):
    """Exceptions from _safe_llm_call propagate through generate_report without being caught."""
    from agents.coach import generate_report
    from core.config import TOTAL_QUESTIONS

    # Build valid answers
    answers = []
    for i in range(TOTAL_QUESTIONS):
        answers.append({
            "question": f"Question {i+1}",
            "answer_text": f"Answer {i+1}",
            "category": "technical",
            "evaluation": {
                "total": 15,
                "missing_keywords": ["keyword1"],
                "feedback": "Good answer",
            },
        })

    with patch("agents.coach.time.sleep"), \
         patch("agents.coach.genai.Client"), \
         patch("agents.coach._safe_llm_call", side_effect=exc):
        with pytest.raises(type(exc)) as exc_info:
            generate_report("test-session-id", answers)
        assert str(exc_info.value) == str(exc)


# Feature: coach-agent, Property 8: Input Validation Completeness
@settings(max_examples=100)
@given(
    invalid_type=st.sampled_from([
        # Invalid session_id cases
        ("session_id", None, "valid_answers"),
        ("session_id", "", "valid_answers"),
        ("session_id", "   ", "valid_answers"),
        # Invalid answers type
        ("answers_type", "valid_session", "not a list"),
        ("answers_type", "valid_session", 42),
        # Empty answers
        ("answers_empty", "valid_session", []),
        # Wrong count
        ("answers_count", "valid_session", "wrong_count"),
        # Missing category
        ("missing_category", "valid_session", "missing_category"),
        # Missing evaluation
        ("missing_evaluation", "valid_session", "missing_evaluation"),
        # Missing evaluation.total
        ("missing_total", "valid_session", "missing_total"),
        # Missing evaluation.missing_keywords
        ("missing_keywords", "valid_session", "missing_keywords"),
    ])
)
def test_input_validation_completeness(invalid_type):
    """All invalid inputs raise ValueError before any sleep or LLM call."""
    from agents.coach import generate_report
    from core.config import TOTAL_QUESTIONS
    
    case_name, session_id_val, answers_val = invalid_type
    
    def make_valid_answer(idx):
        return {
            "question": f"Question {idx+1}",
            "answer_text": f"Answer {idx+1}",
            "category": "technical",
            "evaluation": {
                "total": 15,
                "missing_keywords": ["keyword1"],
                "feedback": "Good answer",
            },
        }
    
    # Build valid answers list as baseline
    valid_answers = [make_valid_answer(i) for i in range(TOTAL_QUESTIONS)]
    
    if case_name == "session_id":
        test_session = session_id_val
        test_answers = valid_answers
    elif case_name == "answers_type":
        test_session = "valid-session"
        test_answers = answers_val
    elif case_name == "answers_empty":
        test_session = "valid-session"
        test_answers = []
    elif case_name == "answers_count":
        test_session = "valid-session"
        test_answers = valid_answers[:9]  # Only 9 answers
    elif case_name == "missing_category":
        test_session = "valid-session"
        test_answers = valid_answers.copy()
        bad_answer = make_valid_answer(0)
        del bad_answer["category"]
        test_answers[0] = bad_answer
    elif case_name == "missing_evaluation":
        test_session = "valid-session"
        test_answers = valid_answers.copy()
        bad_answer = make_valid_answer(0)
        del bad_answer["evaluation"]
        test_answers[0] = bad_answer
    elif case_name == "missing_total":
        test_session = "valid-session"
        test_answers = valid_answers.copy()
        bad_answer = make_valid_answer(0)
        del bad_answer["evaluation"]["total"]
        test_answers[0] = bad_answer
    elif case_name == "missing_keywords":
        test_session = "valid-session"
        test_answers = valid_answers.copy()
        bad_answer = make_valid_answer(0)
        del bad_answer["evaluation"]["missing_keywords"]
        test_answers[0] = bad_answer
    else:
        return

    # Mock time.sleep and _safe_llm_call to verify they are NOT called
    with patch("agents.coach.time.sleep") as mock_sleep, \
         patch("agents.coach._safe_llm_call") as mock_llm:
        with pytest.raises(ValueError) as exc_info:
            generate_report(test_session, test_answers)
        # Verify no sleep or LLM call happened
        mock_sleep.assert_not_called()
        mock_llm.assert_not_called()
        # Error message should include "Coach"
        assert "Coach" in str(exc_info.value)


# Feature: coach-agent, Property 10: Rate Limit Compliance
@settings(max_examples=100)
@given(
    totals=st.lists(st.integers(4, 20), min_size=10, max_size=10),
)
def test_rate_limit_compliance(totals):
    """time.sleep(RATE_LIMIT_SLEEP) is called exactly once before _safe_llm_call."""
    from agents.coach import generate_report
    from core.config import TOTAL_QUESTIONS, RATE_LIMIT_SLEEP

    # Build valid answers
    answers = []
    for i in range(TOTAL_QUESTIONS):
        answers.append({
            "question": f"Question {i+1}",
            "answer_text": f"Answer {i+1}",
            "category": "technical",
            "evaluation": {
                "total": totals[i],
                "missing_keywords": ["keyword1"],
                "feedback": "Good answer",
            },
        })

    mock_llm_response = {
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

    call_order = []

    def mock_sleep(seconds):
        call_order.append(("sleep", seconds))

    def mock_llm_call(*args, **kwargs):
        call_order.append(("llm_call",))
        return mock_llm_response

    with patch("agents.coach.time.sleep", side_effect=mock_sleep), \
         patch("agents.coach.genai.Client"), \
         patch("agents.coach._safe_llm_call", side_effect=mock_llm_call):
        generate_report("test-session-id", answers)

    # Verify sleep called exactly once with RATE_LIMIT_SLEEP
    sleep_calls = [c for c in call_order if c[0] == "sleep"]
    assert len(sleep_calls) == 1
    assert sleep_calls[0][1] == RATE_LIMIT_SLEEP

    # Verify sleep happens before LLM call
    sleep_idx = call_order.index(("sleep", RATE_LIMIT_SLEEP))
    llm_idx = call_order.index(("llm_call",))
    assert sleep_idx < llm_idx


# Feature: coach-agent, Property 2: Deterministic Score Override
@settings(max_examples=100)
@given(
    totals=st.lists(st.integers(4, 20), min_size=10, max_size=10),
    llm_overall=st.integers(0, 300),
    llm_hiring=st.sampled_from(["Very High", "None", "Maybe", "Low", "Medium", "High"]),
    llm_percent=st.integers(0, 100),
)
def test_deterministic_score_override(totals, llm_overall, llm_hiring, llm_percent):
    """Output always uses locally calculated scores, never LLM-returned values."""
    from agents.coach import generate_report
    from core.config import TOTAL_QUESTIONS, MAX_TOTAL_SCORE, HIRING_LOW_MAX, HIRING_HIGH_MIN
    
    # Build valid answers with the given totals
    answers = []
    for i in range(TOTAL_QUESTIONS):
        answers.append({
            "question": f"Question {i+1}",
            "answer_text": f"Answer {i+1}",
            "category": "technical",
            "evaluation": {
                "total": totals[i],
                "missing_keywords": ["keyword1"],
                "feedback": "Good answer",
            },
        })

    # Mock LLM to return a valid 11-key dict with WRONG score values
    mock_llm_response = {
        "overall_score": llm_overall,  # Will be overridden
        "hiring_probability": llm_hiring,  # Will be overridden
        "hiring_probability_percent": llm_percent,  # Will be overridden
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

    with patch("agents.coach.time.sleep"), \
         patch("agents.coach.genai.Client"), \
         patch("agents.coach._safe_llm_call", return_value=mock_llm_response):
        result = generate_report("test-session-id", answers)

    # Verify deterministic overrides
    expected_score = sum(totals)
    assert result["overall_score"] == expected_score

    # Verify hiring probability band
    if expected_score < HIRING_LOW_MAX:
        assert result["hiring_probability"] == "Low"
    elif expected_score <= HIRING_HIGH_MIN:
        assert result["hiring_probability"] == "Medium"
    else:
        assert result["hiring_probability"] == "High"

    # Verify hiring percent
    expected_percent = max(0, min(100, round((expected_score / MAX_TOTAL_SCORE) * 100)))
    assert result["hiring_probability_percent"] == expected_percent


# Feature: coach-agent, Property 11: Single LLM Call Per Invocation
@settings(max_examples=100)
@given(
    totals=st.lists(st.integers(4, 20), min_size=10, max_size=10),
    categories=st.lists(
        st.sampled_from(["technical", "behavioral", "situational", "curveball"]),
        min_size=10, max_size=10
    ),
)
def test_single_llm_call_per_invocation(totals, categories):
    """_safe_llm_call is called exactly once per generate_report invocation."""
    from agents.coach import generate_report
    from core.config import TOTAL_QUESTIONS

    # Build valid answers with varied categories
    answers = []
    for i in range(TOTAL_QUESTIONS):
        answers.append({
            "question": f"Question {i+1}",
            "answer_text": f"Answer {i+1}",
            "category": categories[i],
            "evaluation": {
                "total": totals[i],
                "missing_keywords": ["keyword1"],
                "feedback": "Good answer",
            },
        })

    mock_llm_response = {
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

    with patch("agents.coach.time.sleep"), \
         patch("agents.coach.genai.Client"), \
         patch("agents.coach._safe_llm_call", return_value=mock_llm_response) as mock_llm:
        generate_report("test-session-id", answers)

    # Verify _safe_llm_call called exactly once
    assert mock_llm.call_count == 1

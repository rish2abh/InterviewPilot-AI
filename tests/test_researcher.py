"""
tests/test_researcher.py — Unit + property-based tests for the Researcher Agent.

Covers all 10 requirements and 6 correctness properties from the design doc.
Uses pytest + hypothesis for property-based testing and unittest.mock for
mocking the Gemini API.
"""

import json
import re
import pytest
from unittest.mock import patch, MagicMock, call
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from agents.researcher import (
    research_company,
    _sanitize_input,
    _safe_llm_call,
    _validate_research_dict,
    _build_default_dict,
    SYSTEM_PROMPT,
    _REQUIRED_KEYS,
    _VALID_DIFFICULTIES,
    _MAX_INPUT_LENGTH,
)
from core.config import (
    RATE_LIMIT_SLEEP,
    ERROR_RETRY_SLEEP,
    MAX_TOKENS_COMPLEX,
    GEMINI_MODEL,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_research_dict() -> dict:
    """A valid 8-key Research_Dict that passes all validation checks."""
    return {
        "company": "Google",
        "role": "Software Engineer",
        "interview_rounds": "5 rounds: phone screen, 2 coding, system design, behavioural",
        "key_topics": ["algorithms", "system design", "coding"],
        "difficulty": "hard",
        "culture_keywords": ["innovation", "impact"],
        "known_question_types": ["coding", "system design", "behavioural"],
        "red_flags_to_test": ["communication", "problem solving"],
    }


@pytest.fixture
def valid_research_data_input() -> dict:
    """Valid input parameters for research_company."""
    return {
        "company": "Google",
        "role": "Software Engineer",
        "level": "senior",
        "api_key": "test-api-key-12345",
    }


@pytest.fixture
def mock_model(valid_research_dict):
    """A mocked GenerativeModel that returns a valid JSON response."""
    model = MagicMock()
    response = MagicMock()
    response.text = json.dumps(valid_research_dict)
    response.usage_metadata = {"prompt_token_count": 100, "candidates_token_count": 200}
    model.generate_content.return_value = response
    return model


# ===========================================================================
# UNIT TESTS — Task 9.2: _sanitize_input
# ===========================================================================


class TestSanitizeInput:
    """Unit tests for _sanitize_input (Req 3.1–3.6)."""

    def test_empty_company_raises(self):
        with pytest.raises(ValueError, match="company"):
            _sanitize_input("", "company")

    def test_whitespace_only_company_raises(self):
        with pytest.raises(ValueError, match="company"):
            _sanitize_input("   ", "company")

    def test_all_special_chars_company_raises(self):
        with pytest.raises(ValueError, match="invalid after sanitization"):
            _sanitize_input("@#$%^&*()", "company")

    def test_special_chars_removed(self):
        assert _sanitize_input("Google!!", "company") == "Google"

    def test_valid_chars_unchanged(self):
        assert _sanitize_input("Meta-Platforms", "company") == "Meta-Platforms"

    def test_truncation_at_100_chars(self):
        long_input = "A" * 150
        result = _sanitize_input(long_input, "company")
        assert len(result) <= _MAX_INPUT_LENGTH

    def test_empty_role_raises(self):
        with pytest.raises(ValueError, match="role"):
            _sanitize_input("", "role")

    def test_role_special_chars_removed(self):
        assert _sanitize_input("Software Engineer!!!", "role") == "Software Engineer"

    def test_spaces_and_hyphens_preserved(self):
        assert _sanitize_input("full-stack dev", "role") == "full-stack dev"

    def test_digits_preserved(self):
        assert _sanitize_input("Web3 Developer", "role") == "Web3 Developer"


# ===========================================================================
# UNIT TESTS — Task 9.3: research_company input validation
# ===========================================================================


class TestResearchCompanyInputValidation:
    """Verify ValueError propagates from _sanitize_input (Req 5.7)."""

    def test_empty_company_propagates(self):
        with pytest.raises(ValueError, match="company"):
            research_company("", "Software Engineer", "senior", "fake-key")

    def test_whitespace_company_propagates(self):
        with pytest.raises(ValueError, match="company"):
            research_company("   ", "Software Engineer", "senior", "fake-key")

    def test_all_special_role_propagates(self):
        with pytest.raises(ValueError, match="role"):
            research_company("Google", "@#$", "senior", "fake-key")

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_valid_inputs_proceed(self, mock_sleep, mock_genai, valid_research_dict):
        """Valid inputs pass sanitization and reach the LLM call."""
        mock_model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_research_dict)
        response.usage_metadata = {}
        mock_model.generate_content.return_value = response
        mock_genai.GenerativeModel.return_value = mock_model

        result = research_company("Google", "SWE", "senior", "fake-key")
        assert "company" in result


# ===========================================================================
# UNIT TESTS — Task 10.1: _safe_llm_call JSON retry path
# ===========================================================================


class TestSafeLlmCallJsonRetry:
    """Tests for JSON retry logic (Req 2.7, 2.8, 5.1, 5.2, 8.1, 8.2)."""

    def test_json_retry_succeeds_on_second_attempt(self, valid_research_dict):
        """Invalid JSON on attempt 0, valid on attempt 1 → success."""
        model = MagicMock()
        bad_response = MagicMock()
        bad_response.text = "Not valid JSON at all"
        good_response = MagicMock()
        good_response.text = json.dumps(valid_research_dict)
        good_response.usage_metadata = {"total": 300}
        model.generate_content.side_effect = [bad_response, good_response]

        with patch("agents.researcher.time.sleep") as mock_sleep:
            result = _safe_llm_call("test", "sys", model, 1000, "Researcher")

        mock_sleep.assert_called_once_with(RATE_LIMIT_SLEEP)
        assert result == valid_research_dict

    def test_json_retry_both_fail_raises_valueerror(self):
        """Invalid JSON on both attempts → ValueError raised."""
        model = MagicMock()
        bad_response = MagicMock()
        bad_response.text = "Not JSON"
        model.generate_content.return_value = bad_response

        with patch("agents.researcher.time.sleep"):
            with pytest.raises(ValueError, match="Researcher failed after 2 attempts"):
                _safe_llm_call("test", "sys", model, 1000, "Researcher")

    def test_success_logs_tokens(self, valid_research_dict, capsys):
        """Successful call logs token usage."""
        model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_research_dict)
        response.usage_metadata = {"prompt": 50, "candidates": 100}
        model.generate_content.return_value = response

        _safe_llm_call("test", "sys", model, 1000, "Researcher")
        captured = capsys.readouterr()
        assert "[Researcher] Success. Tokens:" in captured.out

    def test_max_tokens_passed_to_model(self, valid_research_dict):
        """max_output_tokens uses MAX_TOKENS_COMPLEX."""
        model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_research_dict)
        response.usage_metadata = {}
        model.generate_content.return_value = response

        _safe_llm_call("test", "sys", model, MAX_TOKENS_COMPLEX, "Researcher")
        call_args = model.generate_content.call_args
        gen_config = call_args.kwargs.get("generation_config") or call_args[1].get("generation_config")
        assert gen_config["max_output_tokens"] == MAX_TOKENS_COMPLEX


# ===========================================================================
# UNIT TESTS — Task 10.2: _safe_llm_call API error retry path
# ===========================================================================


class TestSafeLlmCallApiRetry:
    """Tests for API error retry logic (Req 5.3, 5.4, 8.3, 8.4)."""

    def test_api_error_retry_succeeds(self, valid_research_dict):
        """API exception on attempt 0, success on attempt 1."""
        model = MagicMock()
        good_response = MagicMock()
        good_response.text = json.dumps(valid_research_dict)
        good_response.usage_metadata = {}
        model.generate_content.side_effect = [
            RuntimeError("Connection timeout"),
            good_response,
        ]

        with patch("agents.researcher.time.sleep") as mock_sleep:
            result = _safe_llm_call("test", "sys", model, 1000, "Researcher")

        mock_sleep.assert_called_once_with(ERROR_RETRY_SLEEP)
        assert result == valid_research_dict

    def test_api_error_both_fail_reraises(self):
        """API exception on both attempts → original re-raised."""
        model = MagicMock()
        model.generate_content.side_effect = RuntimeError("Server down")

        with patch("agents.researcher.time.sleep"):
            with pytest.raises(RuntimeError, match="Server down"):
                _safe_llm_call("test", "sys", model, 1000, "Researcher")

    def test_json_fail_log_format(self, capsys):
        """JSON failure logs correct format."""
        model = MagicMock()
        bad_response = MagicMock()
        bad_response.text = "invalid"
        model.generate_content.return_value = bad_response

        with patch("agents.researcher.time.sleep"):
            with pytest.raises(ValueError):
                _safe_llm_call("test", "sys", model, 1000, "Researcher")

        captured = capsys.readouterr()
        assert "[Researcher] JSON fail attempt 1:" in captured.out
        assert "[Researcher] JSON fail attempt 2:" in captured.out

    def test_api_error_log_format(self, capsys):
        """API error logs correct format."""
        model = MagicMock()
        model.generate_content.side_effect = RuntimeError("timeout")

        with patch("agents.researcher.time.sleep"):
            with pytest.raises(RuntimeError):
                _safe_llm_call("test", "sys", model, 1000, "Researcher")

        captured = capsys.readouterr()
        assert "[Researcher] API error attempt 1:" in captured.out
        assert "[Researcher] API error attempt 2:" in captured.out


# ===========================================================================
# UNIT TESTS — Task 11.1: _validate_research_dict missing/extra keys
# ===========================================================================


class TestValidateResearchDictKeys:
    """Tests for key presence and extra key stripping (Req 2.3, 2.4)."""

    def test_missing_single_key_raises(self, valid_research_dict):
        del valid_research_dict["key_topics"]
        with pytest.raises(ValueError, match="key_topics"):
            _validate_research_dict(valid_research_dict)

    def test_missing_multiple_keys_raises(self, valid_research_dict):
        del valid_research_dict["key_topics"]
        del valid_research_dict["difficulty"]
        with pytest.raises(ValueError, match="missing required keys"):
            _validate_research_dict(valid_research_dict)

    def test_extra_keys_stripped(self, valid_research_dict):
        valid_research_dict["extra1"] = "should be removed"
        valid_research_dict["extra2"] = 123
        valid_research_dict["extra3"] = []
        result = _validate_research_dict(valid_research_dict)
        assert set(result.keys()) == set(_REQUIRED_KEYS)
        assert "extra1" not in result


# ===========================================================================
# UNIT TESTS — Task 11.2: _validate_research_dict value types
# ===========================================================================


class TestValidateResearchDictValues:
    """Tests for value type and non-empty validation (Req 1.5, 2.1, 2.2)."""

    def test_empty_string_company_raises(self, valid_research_dict):
        valid_research_dict["company"] = ""
        with pytest.raises(ValueError, match="company"):
            _validate_research_dict(valid_research_dict)

    def test_whitespace_only_string_raises(self, valid_research_dict):
        valid_research_dict["company"] = "   "
        with pytest.raises(ValueError, match="company"):
            _validate_research_dict(valid_research_dict)

    def test_empty_list_raises(self, valid_research_dict):
        valid_research_dict["key_topics"] = []
        with pytest.raises(ValueError, match="key_topics"):
            _validate_research_dict(valid_research_dict)

    def test_list_with_empty_string_element_raises(self, valid_research_dict):
        valid_research_dict["key_topics"] = ["valid", ""]
        with pytest.raises(ValueError, match="key_topics"):
            _validate_research_dict(valid_research_dict)

    def test_wrong_type_for_list_key_raises(self, valid_research_dict):
        valid_research_dict["key_topics"] = "not a list"
        with pytest.raises(ValueError, match="key_topics"):
            _validate_research_dict(valid_research_dict)

    def test_invalid_difficulty_raises(self, valid_research_dict):
        valid_research_dict["difficulty"] = "impossible"
        with pytest.raises(ValueError, match="difficulty"):
            _validate_research_dict(valid_research_dict)

    def test_valid_dict_returns_8_keys(self, valid_research_dict):
        result = _validate_research_dict(valid_research_dict)
        assert len(result) == 8
        assert set(result.keys()) == set(_REQUIRED_KEYS)


# ===========================================================================
# UNIT TESTS — Task 12.1: _build_default_dict difficulty mapping
# ===========================================================================


class TestBuildDefaultDictDifficulty:
    """Tests for level-to-difficulty mapping (Req 6.4)."""

    def test_fresher_maps_to_easy(self):
        result = _build_default_dict("Co", "Role", "fresher")
        assert result["difficulty"] == "easy"

    def test_junior_maps_to_medium(self):
        result = _build_default_dict("Co", "Role", "junior")
        assert result["difficulty"] == "medium"

    def test_senior_maps_to_hard(self):
        result = _build_default_dict("Co", "Role", "senior")
        assert result["difficulty"] == "hard"

    def test_lead_maps_to_expert(self):
        result = _build_default_dict("Co", "Role", "lead")
        assert result["difficulty"] == "expert"

    def test_manager_maps_to_expert(self):
        result = _build_default_dict("Co", "Role", "manager")
        assert result["difficulty"] == "expert"

    def test_unknown_level_maps_to_medium(self):
        result = _build_default_dict("Co", "Role", "intern")
        assert result["difficulty"] == "medium"


# ===========================================================================
# UNIT TESTS — Task 12.2: _build_default_dict role-based key_topics
# ===========================================================================


class TestBuildDefaultDictTopics:
    """Tests for role-based key_topics selection (Req 6.5)."""

    def test_ml_role_topics(self):
        result = _build_default_dict("Co", "ML Engineer", "senior")
        assert "machine learning" in result["key_topics"]

    def test_data_analyst_topics(self):
        result = _build_default_dict("Co", "Data Analyst", "junior")
        assert "sql" in result["key_topics"]

    def test_product_manager_topics(self):
        result = _build_default_dict("Co", "Product Manager", "senior")
        assert "product strategy" in result["key_topics"]

    def test_devops_topics(self):
        result = _build_default_dict("Co", "DevOps Engineer", "senior")
        assert "ci/cd" in result["key_topics"]

    def test_frontend_topics(self):
        result = _build_default_dict("Co", "React Developer", "junior")
        assert "javascript" in result["key_topics"]

    def test_backend_topics(self):
        result = _build_default_dict("Co", "Backend Developer", "senior")
        assert "api design" in result["key_topics"]

    def test_generic_role_topics(self):
        result = _build_default_dict("Co", "Astronaut", "senior")
        assert "data structures" in result["key_topics"]


# ===========================================================================
# UNIT TESTS — Task 12.3: _build_default_dict structure
# ===========================================================================


class TestBuildDefaultDictStructure:
    """Tests for default dict fixed values (Req 2.10, 6.3, 6.6)."""

    def test_exactly_9_keys(self):
        result = _build_default_dict("Co", "Role", "junior")
        assert len(result) == 9

    def test_error_flag_true(self):
        result = _build_default_dict("Co", "Role", "junior")
        assert result["error_flag"] is True

    def test_interview_rounds_default(self):
        result = _build_default_dict("Co", "Role", "junior")
        assert result["interview_rounds"] == "3 rounds"

    def test_culture_keywords_default(self):
        result = _build_default_dict("Co", "Role", "junior")
        assert result["culture_keywords"] == ["collaboration", "ownership"]

    def test_known_question_types_default(self):
        result = _build_default_dict("Co", "Role", "junior")
        assert result["known_question_types"] == ["coding", "behavioural"]

    def test_red_flags_default(self):
        result = _build_default_dict("Co", "Role", "junior")
        assert result["red_flags_to_test"] == ["problem-solving approach", "communication clarity"]

    def test_company_uses_input_value(self):
        result = _build_default_dict("TestCo", "Role", "junior")
        assert result["company"] == "TestCo"

    def test_role_uses_input_value(self):
        result = _build_default_dict("Co", "Engineer", "junior")
        assert result["role"] == "Engineer"


# ===========================================================================
# UNIT TESTS — Task 13.1: research_company success path
# ===========================================================================


class TestResearchCompanySuccess:
    """End-to-end success path tests (Req 1.1, 1.2, 1.3, 9.4)."""

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_returns_8_keys_no_error_flag(self, mock_sleep, mock_genai, valid_research_dict):
        mock_model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_research_dict)
        response.usage_metadata = {}
        mock_model.generate_content.return_value = response
        mock_genai.GenerativeModel.return_value = mock_model

        result = research_company("Google", "SWE", "senior", "key")
        assert set(result.keys()) == set(_REQUIRED_KEYS)
        assert "error_flag" not in result

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_rate_limit_sleep_called(self, mock_sleep, mock_genai, valid_research_dict):
        mock_model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_research_dict)
        response.usage_metadata = {}
        mock_model.generate_content.return_value = response
        mock_genai.GenerativeModel.return_value = mock_model

        research_company("Google", "SWE", "senior", "key")
        mock_sleep.assert_called_with(RATE_LIMIT_SLEEP)

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_genai_configure_called_with_key(self, mock_sleep, mock_genai, valid_research_dict):
        mock_model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_research_dict)
        response.usage_metadata = {}
        mock_model.generate_content.return_value = response
        mock_genai.GenerativeModel.return_value = mock_model

        research_company("Google", "SWE", "senior", "test-api-key")
        mock_genai.configure.assert_called_once_with(api_key="test-api-key")

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_search_grounding_enabled(self, mock_sleep, mock_genai, valid_research_dict):
        mock_model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_research_dict)
        response.usage_metadata = {}
        mock_model.generate_content.return_value = response
        mock_genai.GenerativeModel.return_value = mock_model

        research_company("Google", "SWE", "senior", "key")
        mock_genai.GenerativeModel.assert_called_once_with(
            model_name=GEMINI_MODEL,
            tools="google_search_retrieval",
        )


# ===========================================================================
# UNIT TESTS — Task 13.2: research_company failure/default path
# ===========================================================================


class TestResearchCompanyFailure:
    """End-to-end failure path tests (Req 1.4, 5.5, 6.1, 6.2, 6.7, 7.3)."""

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_api_failure_returns_default_dict(self, mock_sleep, mock_genai):
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = RuntimeError("API down")
        mock_genai.GenerativeModel.return_value = mock_model

        result = research_company("Google", "SWE", "senior", "key")
        assert result["error_flag"] is True
        assert set(_REQUIRED_KEYS).issubset(set(result.keys()))

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_validation_failure_returns_default_dict(self, mock_sleep, mock_genai):
        mock_model = MagicMock()
        response = MagicMock()
        # Missing key_topics → validation fails
        response.text = json.dumps({"company": "G", "role": "R", "interview_rounds": "3",
                                     "difficulty": "hard", "culture_keywords": ["x"],
                                     "known_question_types": ["y"], "red_flags_to_test": ["z"]})
        response.usage_metadata = {}
        mock_model.generate_content.return_value = response
        mock_genai.GenerativeModel.return_value = mock_model

        result = research_company("Google", "SWE", "senior", "key")
        assert result["error_flag"] is True

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_warning_printed_on_failure(self, mock_sleep, mock_genai, capsys):
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = RuntimeError("fail")
        mock_genai.GenerativeModel.return_value = mock_model

        research_company("Google", "SWE", "senior", "key")
        captured = capsys.readouterr()
        assert "[Researcher] Unrecoverable error, returning default dict:" in captured.out

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_default_dict_has_nonempty_values(self, mock_sleep, mock_genai):
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = RuntimeError("fail")
        mock_genai.GenerativeModel.return_value = mock_model

        result = research_company("Google", "SWE", "senior", "key")
        for key in _REQUIRED_KEYS:
            val = result[key]
            if isinstance(val, str):
                assert len(val.strip()) > 0
            elif isinstance(val, list):
                assert len(val) > 0
                assert all(isinstance(x, str) and x.strip() for x in val)


# ===========================================================================
# UNIT TESTS — Task 14.1: System prompt compliance
# ===========================================================================


class TestSystemPromptCompliance:
    """Tests for system prompt content (Req 9.1, 9.2, 7.1)."""

    def test_ends_with_json_instruction(self):
        expected_ending = "Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."
        assert SYSTEM_PROMPT.strip().endswith(expected_ending)

    def test_contains_all_8_key_names(self):
        for key in _REQUIRED_KEYS:
            assert key in SYSTEM_PROMPT, f"SYSTEM_PROMPT missing key name: {key}"

    def test_contains_unknown_company_instruction(self):
        # The system prompt should instruct LLM to use defaults for unknown companies
        assert "industry" in SYSTEM_PROMPT.lower() or "defaults" in SYSTEM_PROMPT.lower()


# ===========================================================================
# UNIT TESTS — Task 14.2: No hardcoded values
# ===========================================================================


class TestNoHardcodedValues:
    """Tests verifying constants are used instead of literals (Req 10.1-10.3)."""

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_sleep_uses_rate_limit_constant(self, mock_sleep, mock_genai, valid_research_dict):
        mock_model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_research_dict)
        response.usage_metadata = {}
        mock_model.generate_content.return_value = response
        mock_genai.GenerativeModel.return_value = mock_model

        research_company("Google", "SWE", "senior", "key")
        # First sleep call should be RATE_LIMIT_SLEEP (before LLM call)
        mock_sleep.assert_any_call(RATE_LIMIT_SLEEP)

    @patch("agents.researcher.genai")
    @patch("agents.researcher.time.sleep")
    def test_max_tokens_passed_as_constant(self, mock_sleep, mock_genai, valid_research_dict):
        mock_model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_research_dict)
        response.usage_metadata = {}
        mock_model.generate_content.return_value = response
        mock_genai.GenerativeModel.return_value = mock_model

        research_company("Google", "SWE", "senior", "key")
        call_args = mock_model.generate_content.call_args
        gen_config = call_args.kwargs.get("generation_config") or call_args[1].get("generation_config")
        assert gen_config["max_output_tokens"] == MAX_TOKENS_COMPLEX


# ===========================================================================
# PROPERTY-BASED TESTS — Task 16.1–16.6
# ===========================================================================

# Valid input alphabet for hypothesis: ASCII letters, digits, ASCII space, hyphens
# Only these characters survive _sanitize_input's regex [a-zA-Z0-9 \-]
_VALID_ALPHABET = st.sampled_from(
    list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -")
)


# Feature: researcher-agent, Property 1: Output Structure Invariant
class TestPropertyOutputStructure:
    """For any valid invocation, the returned dict has exactly 8 keys (success)
    or exactly 9 keys (8 research + error_flag=True)."""

    @settings(max_examples=100)
    @given(
        company=st.text(min_size=1, max_size=50, alphabet=_VALID_ALPHABET),
        role=st.text(min_size=1, max_size=50, alphabet=_VALID_ALPHABET),
        level=st.sampled_from(["fresher", "junior", "senior", "lead", "manager"]),
        succeed=st.booleans(),
    )
    def test_output_structure_invariant(self, company, role, level, succeed):
        # Filter out inputs that would be empty after strip
        assume(company.strip())
        assume(role.strip())

        valid_dict = {
            "company": company.strip(),
            "role": role.strip(),
            "interview_rounds": "3 rounds",
            "key_topics": ["algorithms", "design"],
            "difficulty": "medium",
            "culture_keywords": ["teamwork"],
            "known_question_types": ["coding"],
            "red_flags_to_test": ["communication"],
        }

        with patch("agents.researcher.genai") as mock_genai, \
             patch("agents.researcher.time.sleep"):
            mock_model = MagicMock()
            if succeed:
                response = MagicMock()
                response.text = json.dumps(valid_dict)
                response.usage_metadata = {}
                mock_model.generate_content.return_value = response
            else:
                mock_model.generate_content.side_effect = RuntimeError("fail")
            mock_genai.GenerativeModel.return_value = mock_model

            result = research_company(company, role, level, "key")

        keys = set(result.keys())
        if "error_flag" in keys:
            assert keys == set(_REQUIRED_KEYS) | {"error_flag"}
            assert result["error_flag"] is True
        else:
            assert keys == set(_REQUIRED_KEYS)


# Feature: researcher-agent, Property 2: Failure Safety Invariant
class TestPropertyFailureSafety:
    """For any valid inputs where the LLM call fails, research_company always
    returns a complete dict with error_flag=True, never raises."""

    @settings(max_examples=100)
    @given(
        company=st.text(min_size=1, max_size=50, alphabet=_VALID_ALPHABET),
        role=st.text(min_size=1, max_size=50, alphabet=_VALID_ALPHABET),
        level=st.sampled_from(["fresher", "junior", "senior", "lead", "manager"]),
        exc_type=st.sampled_from([ValueError, RuntimeError, ConnectionError, TimeoutError]),
    )
    def test_failure_safety_invariant(self, company, role, level, exc_type):
        assume(company.strip())
        assume(role.strip())

        with patch("agents.researcher.genai") as mock_genai, \
             patch("agents.researcher.time.sleep"):
            mock_model = MagicMock()
            mock_model.generate_content.side_effect = exc_type("simulated failure")
            mock_genai.GenerativeModel.return_value = mock_model

            # Must never raise for valid sanitized inputs
            result = research_company(company, role, level, "key")

        assert "error_flag" in result
        assert result["error_flag"] is True
        for key in _REQUIRED_KEYS:
            assert key in result
            val = result[key]
            if isinstance(val, str):
                assert len(val.strip()) > 0
            elif isinstance(val, list):
                assert len(val) > 0


# Feature: researcher-agent, Property 3: Default Dict Role-Appropriate Completeness
class TestPropertyDefaultDictCompleteness:
    """For any combination of company, role, and level, _build_default_dict
    returns a correct 9-key dict with proper mappings."""

    @settings(max_examples=100)
    @given(
        company=st.text(min_size=1, max_size=50),
        role=st.text(min_size=1, max_size=50),
        level=st.sampled_from(["fresher", "junior", "senior", "lead", "manager", "intern", "CTO"]),
    )
    def test_default_dict_completeness(self, company, role, level):
        result = _build_default_dict(company, role, level)

        # Exactly 9 keys
        assert len(result) == 9
        assert "error_flag" in result
        assert result["error_flag"] is True

        # Difficulty mapping
        expected_map = {"fresher": "easy", "junior": "medium", "senior": "hard",
                        "lead": "expert", "manager": "expert"}
        expected_diff = expected_map.get(level.lower(), "medium")
        assert result["difficulty"] == expected_diff

        # key_topics has exactly 5 items
        assert len(result["key_topics"]) == 5
        assert all(isinstance(t, str) and t for t in result["key_topics"])

        # Fixed defaults
        assert result["interview_rounds"] == "3 rounds"
        assert result["culture_keywords"] == ["collaboration", "ownership"]
        assert result["known_question_types"] == ["coding", "behavioural"]
        assert result["red_flags_to_test"] == ["problem-solving approach", "communication clarity"]


# Feature: researcher-agent, Property 4: Input Sanitization Correctness
class TestPropertyInputSanitization:
    """For any input string, _sanitize_input satisfies the sanitization contract."""

    @settings(max_examples=100)
    @given(value=st.text(min_size=0, max_size=200))
    def test_sanitization_contract(self, value):
        try:
            result = _sanitize_input(value, "test_field")
            # If it succeeds:
            # Output length <= _MAX_INPUT_LENGTH
            assert len(result) <= _MAX_INPUT_LENGTH
            # Output contains only valid chars
            assert re.fullmatch(r"[a-zA-Z0-9 \-]+", result), f"Invalid chars in: {result!r}"
            # Output is non-empty
            assert len(result) > 0
        except ValueError:
            # ValueError is expected for: empty, whitespace-only, or all-special-chars
            stripped = value.strip()
            if not stripped:
                pass  # empty or whitespace → correct
            else:
                # Must be that all chars were special (non-alnum, non-space, non-hyphen)
                truncated = stripped[:_MAX_INPUT_LENGTH]
                sanitized = re.sub(r"[^a-zA-Z0-9 \-]", "", truncated).strip()
                assert sanitized == "", f"ValueError raised but sanitized is non-empty: {sanitized!r}"

    @settings(max_examples=100)
    @given(
        value=st.text(
            min_size=1,
            max_size=100,
            alphabet=st.sampled_from(
                list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -")
            ),
        )
    )
    def test_valid_inputs_pass_through(self, value):
        """Valid inputs (<=100 chars, only allowed chars) pass through unchanged after strip."""
        assume(value.strip())  # must not be empty after strip
        result = _sanitize_input(value, "test_field")
        assert result == value.strip()


# Feature: researcher-agent, Property 5: Markdown Stripping Round Trip
class TestPropertyMarkdownStripping:
    """For any valid JSON wrapped in markdown code fences, _safe_llm_call
    extracts and parses it correctly."""

    @settings(max_examples=100)
    @given(
        data=st.fixed_dictionaries({
            "company": st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",))),
            "role": st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L",))),
        }),
        wrapper=st.sampled_from(["json_fence", "generic_fence", "raw", "prose_around"]),
    )
    def test_markdown_stripping_round_trip(self, data, wrapper):
        json_str = json.dumps(data)

        if wrapper == "json_fence":
            wrapped = f"```json\n{json_str}\n```"
        elif wrapper == "generic_fence":
            wrapped = f"```\n{json_str}\n```"
        elif wrapper == "raw":
            wrapped = json_str
        else:  # prose_around
            wrapped = f"Here is the result:\n```json\n{json_str}\n```\nDone."

        model = MagicMock()
        response = MagicMock()
        response.text = wrapped
        response.usage_metadata = {}
        model.generate_content.return_value = response

        result = _safe_llm_call("test", "sys", model, 1000, "Test")
        assert result == data


# Feature: researcher-agent, Property 6: Retry Count and Rate Limit Invariant
class TestPropertyRetryCount:
    """For any invocation, generate_content is called at most 2 times, with
    correct sleep durations between attempts."""

    @settings(max_examples=100)
    @given(
        error_type=st.sampled_from(["json_error", "api_error"]),
        second_succeeds=st.booleans(),
    )
    def test_retry_count_invariant(self, error_type, second_succeeds):
        model = MagicMock()
        # Inline valid dict instead of using fixture
        valid_dict = {
            "company": "Google",
            "role": "Software Engineer",
            "interview_rounds": "5 rounds",
            "key_topics": ["algorithms", "system design", "coding"],
            "difficulty": "hard",
            "culture_keywords": ["innovation", "impact"],
            "known_question_types": ["coding", "system design"],
            "red_flags_to_test": ["communication", "problem solving"],
        }

        if error_type == "json_error":
            bad_response = MagicMock()
            bad_response.text = "NOT JSON"
            if second_succeeds:
                good_response = MagicMock()
                good_response.text = json.dumps(valid_dict)
                good_response.usage_metadata = {}
                model.generate_content.side_effect = [bad_response, good_response]
            else:
                model.generate_content.return_value = bad_response
        else:  # api_error
            if second_succeeds:
                good_response = MagicMock()
                good_response.text = json.dumps(valid_dict)
                good_response.usage_metadata = {}
                model.generate_content.side_effect = [
                    RuntimeError("timeout"),
                    good_response,
                ]
            else:
                model.generate_content.side_effect = RuntimeError("timeout")

        with patch("agents.researcher.time.sleep") as mock_sleep:
            try:
                _safe_llm_call("test", "sys", model, 1000, "Researcher")
            except (ValueError, RuntimeError):
                pass

        # At most 2 calls
        assert model.generate_content.call_count <= 2

        # Verify sleep durations
        if model.generate_content.call_count == 2:
            if error_type == "json_error":
                mock_sleep.assert_called_with(RATE_LIMIT_SLEEP)
            else:
                mock_sleep.assert_called_with(ERROR_RETRY_SLEEP)

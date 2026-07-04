"""
tests/test_orchestrator.py — Unit tests for the Orchestrator Agent.

Covers input validation, session creation, error handling, and state transitions.
Uses pytest fixtures and unittest.mock for mocking agent calls and DB functions.
"""

import uuid
import pytest
from unittest.mock import patch, MagicMock

from agents.orchestrator import (
    start_session,
    get_current_question,
    submit_answer,
    generate_final_report,
    get_current_state,
    QuestionGenerationError,
    MAX_INPUT_LENGTH,
)
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
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_research_dict() -> dict:
    """A valid 8-key Research_Dict that passes contract validation."""
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
def valid_questions_list() -> list:
    """A valid 10-item list of Question_Dicts that passes contract validation."""
    questions = []
    for i in range(TOTAL_QUESTIONS):
        questions.append({
            "id": str(uuid.uuid4()),
            "category": "system_design" if i % 2 == 0 else "behavioral",
            "question": f"Tell me about a time you dealt with challenge {i + 1}?",
            "ideal_keywords": ["teamwork", "leadership", "problem-solving"],
            "difficulty": (i % 5) + 1,
            "follow_ups": [
                f"Follow-up A for question {i + 1}",
                f"Follow-up B for question {i + 1}",
            ],
            "scoring_hint": f"Look for specific examples and structured thinking in Q{i + 1}.",
        })
    return questions


# ---------------------------------------------------------------------------
# Test 1: start_session happy path
# ---------------------------------------------------------------------------


@patch("agents.orchestrator.time.sleep")
@patch("agents.orchestrator.update_session_state")
@patch("agents.orchestrator.create_session")
@patch("agents.orchestrator.save_research")
@patch("agents.orchestrator.generate_questions")
@patch("agents.orchestrator.research_company")
@patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
def test_start_session_happy_path(
    mock_research,
    mock_generate,
    mock_save_research,
    mock_create_session,
    mock_update_state,
    mock_sleep,
    valid_research_dict,
    valid_questions_list,
):
    """Happy path: all agents succeed, returns UUID, transitions SETUP→RESEARCHING→GENERATING→READY."""
    mock_research.return_value = valid_research_dict
    mock_generate.return_value = valid_questions_list

    session_id = start_session("Google", "Software Engineer", "senior")

    # Returns a valid UUID string
    assert isinstance(session_id, str)
    uuid.UUID(session_id)  # Raises ValueError if not valid UUID

    # create_session was called with the right args
    mock_create_session.assert_called_once_with(
        session_id, "Google", "Software Engineer", "senior"
    )

    # Verify all state transitions happened in order
    transition_calls = mock_update_state.call_args_list
    states_transitioned_to = [call[0][1] for call in transition_calls]
    assert STATE_RESEARCHING in states_transitioned_to
    assert STATE_GENERATING in states_transitioned_to
    assert STATE_READY in states_transitioned_to

    # Verify order: RESEARCHING before GENERATING before READY
    idx_researching = states_transitioned_to.index(STATE_RESEARCHING)
    idx_generating = states_transitioned_to.index(STATE_GENERATING)
    idx_ready = states_transitioned_to.index(STATE_READY)
    assert idx_researching < idx_generating < idx_ready

    # Agents were called
    mock_research.assert_called_once()
    mock_generate.assert_called_once()
    mock_save_research.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2: Empty/whitespace/too-long company/role/level
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Tests for input validation on company, role, and level parameters."""

    @patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
    def test_empty_company_raises_valueerror(self):
        with pytest.raises(ValueError, match="company"):
            start_session("", "Software Engineer", "senior")

    @patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
    def test_whitespace_company_raises_valueerror(self):
        with pytest.raises(ValueError, match="company"):
            start_session("   ", "Software Engineer", "senior")

    @patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
    def test_too_long_company_raises_valueerror(self):
        with pytest.raises(ValueError) as exc_info:
            start_session("a" * 201, "Software Engineer", "senior")
        assert "company" in str(exc_info.value)
        assert "exceeds" in str(exc_info.value).lower() or "exceed" in str(exc_info.value).lower()

    @patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
    def test_empty_role_raises_valueerror(self):
        with pytest.raises(ValueError, match="role"):
            start_session("Google", "", "senior")

    @patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
    def test_whitespace_role_raises_valueerror(self):
        with pytest.raises(ValueError, match="role"):
            start_session("Google", "   ", "senior")

    @patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
    def test_too_long_role_raises_valueerror(self):
        with pytest.raises(ValueError) as exc_info:
            start_session("Google", "a" * 201, "senior")
        assert "role" in str(exc_info.value)
        assert "exceeds" in str(exc_info.value).lower() or "exceed" in str(exc_info.value).lower()

    @patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
    def test_empty_level_raises_valueerror(self):
        with pytest.raises(ValueError, match="level"):
            start_session("Google", "Software Engineer", "")

    @patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
    def test_whitespace_level_raises_valueerror(self):
        with pytest.raises(ValueError, match="level"):
            start_session("Google", "Software Engineer", "   ")

    @patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
    def test_too_long_level_raises_valueerror(self):
        with pytest.raises(ValueError) as exc_info:
            start_session("Google", "Software Engineer", "a" * 201)
        assert "level" in str(exc_info.value)
        assert "exceeds" in str(exc_info.value).lower() or "exceed" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test 3: Empty GEMINI_API_KEY raises ValueError
# ---------------------------------------------------------------------------


@patch("agents.orchestrator.GEMINI_API_KEY", "")
def test_empty_gemini_api_key_raises_valueerror():
    """When GEMINI_API_KEY is empty string, start_session raises ValueError."""
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        start_session("Google", "Software Engineer", "senior")


# ---------------------------------------------------------------------------
# Test 4: Researcher error_flag=True proceeds normally
# ---------------------------------------------------------------------------


@patch("agents.orchestrator.time.sleep")
@patch("agents.orchestrator.update_session_state")
@patch("agents.orchestrator.create_session")
@patch("agents.orchestrator.save_research")
@patch("agents.orchestrator.generate_questions")
@patch("agents.orchestrator.research_company")
@patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
def test_researcher_error_flag_proceeds_normally(
    mock_research,
    mock_generate,
    mock_save_research,
    mock_create_session,
    mock_update_state,
    mock_sleep,
    valid_research_dict,
    valid_questions_list,
):
    """When researcher returns error_flag=True (still has 8 required keys),
    start_session should complete successfully without transitioning to ERROR."""
    # Add error_flag to the research dict - still has all 8 required keys
    research_with_error_flag = dict(valid_research_dict)
    research_with_error_flag["error_flag"] = True

    mock_research.return_value = research_with_error_flag
    mock_generate.return_value = valid_questions_list

    session_id = start_session("Google", "Software Engineer", "senior")

    # Session completes successfully
    assert isinstance(session_id, str)
    uuid.UUID(session_id)  # Valid UUID

    # Transitions include READY (not ERROR)
    transition_calls = mock_update_state.call_args_list
    states_transitioned_to = [call[0][1] for call in transition_calls]
    assert STATE_READY in states_transitioned_to
    assert STATE_ERROR not in states_transitioned_to


# ---------------------------------------------------------------------------
# Test 5: QuestionGenerationError transitions to STATE_ERROR and re-raises
# ---------------------------------------------------------------------------


@patch("agents.orchestrator.time.sleep")
@patch("agents.orchestrator.update_session_state")
@patch("agents.orchestrator.create_session")
@patch("agents.orchestrator.save_research")
@patch("agents.orchestrator.generate_questions")
@patch("agents.orchestrator.research_company")
@patch("agents.orchestrator.GEMINI_API_KEY", "test-api-key-12345")
def test_question_generation_error_transitions_to_error_and_reraises(
    mock_research,
    mock_generate,
    mock_save_research,
    mock_create_session,
    mock_update_state,
    mock_sleep,
    valid_research_dict,
):
    """When generate_questions raises QuestionGenerationError, session transitions
    to STATE_ERROR and the exception is re-raised to the caller."""
    mock_research.return_value = valid_research_dict
    mock_generate.side_effect = QuestionGenerationError("test generation failure")

    with pytest.raises(QuestionGenerationError, match="test generation failure"):
        start_session("Google", "Software Engineer", "senior")

    # Verify the session was transitioned to ERROR state
    transition_calls = mock_update_state.call_args_list
    states_transitioned_to = [call[0][1] for call in transition_calls]
    assert STATE_ERROR in states_transitioned_to


# ---------------------------------------------------------------------------
# Tests for get_current_question
# ---------------------------------------------------------------------------


class TestGetCurrentQuestion:
    """Unit tests for get_current_question covering state transitions,
    idempotency, and error cases."""

    def _make_session(self, state: str) -> dict:
        """Helper to build a session dict for mocking get_session."""
        return {
            "session_id": "test-id",
            "company": "Google",
            "role": "Software Engineer",
            "level": "senior",
            "state": state,
            "created_at": "2024-01-01T00:00:00",
        }

    def _make_question(self, index: int = 0) -> dict:
        """Helper to build a 7-key question dict for mocking get_question."""
        return {
            "id": f"q-{index}",
            "category": "system_design",
            "question": f"Tell me about challenge {index + 1}?",
            "ideal_keywords": ["teamwork", "leadership"],
            "difficulty": (index % 5) + 1,
            "follow_ups": [f"Follow-up A for Q{index + 1}", f"Follow-up B for Q{index + 1}"],
            "scoring_hint": f"Look for structured thinking in Q{index + 1}.",
        }

    @patch("agents.orchestrator.get_question")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.get_session")
    def test_state_ready_transitions_to_asking_returns_first_question(
        self, mock_get_session, mock_update_state, mock_get_answers, mock_get_question
    ):
        """STATE_READY transitions to STATE_ASKING and returns the first question."""
        mock_get_session.return_value = self._make_session(STATE_READY)
        mock_get_answers.return_value = []
        question = self._make_question(0)
        mock_get_question.return_value = question

        result = get_current_question("test-id")

        # Transition to ASKING was called
        mock_update_state.assert_called_once_with("test-id", STATE_ASKING)
        # Returns a dict with exactly 7 keys
        assert isinstance(result, dict)
        assert len(result) == 7
        assert result == question

    @patch("agents.orchestrator.get_question")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.get_session")
    def test_state_next_q_transitions_to_asking_returns_next_question(
        self, mock_get_session, mock_update_state, mock_get_answers, mock_get_question
    ):
        """STATE_NEXT_Q transitions to STATE_ASKING and returns the next question (index 1)."""
        mock_get_session.return_value = self._make_session(STATE_NEXT_Q)
        # One answer already given → next question index = 1
        mock_get_answers.return_value = [{"answer": "some answer"}]
        question = self._make_question(1)
        mock_get_question.return_value = question

        result = get_current_question("test-id")

        # Transition happened
        mock_update_state.assert_called_once_with("test-id", STATE_ASKING)
        # get_question called with correct index
        mock_get_question.assert_called_once_with("test-id", 1)
        assert result == question

    @patch("agents.orchestrator.get_question")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.get_session")
    def test_state_asking_is_idempotent_no_transition(
        self, mock_get_session, mock_update_state, mock_get_answers, mock_get_question
    ):
        """STATE_ASKING is idempotent — returns question without triggering a transition."""
        mock_get_session.return_value = self._make_session(STATE_ASKING)
        mock_get_answers.return_value = []
        question = self._make_question(0)
        mock_get_question.return_value = question

        result = get_current_question("test-id")

        # NO transition should happen
        mock_update_state.assert_not_called()
        # Still returns the correct question
        assert isinstance(result, dict)
        assert len(result) == 7
        assert result == question

    @patch("agents.orchestrator.get_session")
    def test_nonexistent_session_raises_valueerror(self, mock_get_session):
        """Non-existent session_id raises ValueError with 'not found'."""
        mock_get_session.return_value = None

        with pytest.raises(ValueError, match="not found"):
            get_current_question("nonexistent-id")

    @patch("agents.orchestrator.get_session")
    def test_terminal_state_done_raises_valueerror(self, mock_get_session):
        """Terminal state (DONE) raises ValueError with 'terminal'."""
        mock_get_session.return_value = self._make_session(STATE_DONE)

        with pytest.raises(ValueError, match="terminal"):
            get_current_question("test-id")

    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.get_session")
    def test_all_questions_answered_raises_valueerror(
        self, mock_get_session, mock_get_answers
    ):
        """All questions answered raises ValueError with 'All' or 'answered'."""
        mock_get_session.return_value = self._make_session(STATE_ASKING)
        # 10 answers = all questions answered
        mock_get_answers.return_value = [{"answer": f"ans {i}"} for i in range(TOTAL_QUESTIONS)]

        with pytest.raises(ValueError, match="All.*answered"):
            get_current_question("test-id")


# ---------------------------------------------------------------------------
# Tests for generate_final_report
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_report_dict() -> dict:
    """A valid 11-key Report_Dict that passes contract validation."""
    return {
        "overall_score": 150,
        "hiring_probability": "High",
        "hiring_probability_percent": 75,
        "strongest_category": "technical",
        "weakest_category": "behavioral",
        "category_averages": {"technical": 4.2, "behavioral": 3.1},
        "top_3_strengths": ["a", "b", "c"],
        "top_3_improvements": ["d", "e", "f"],
        "critical_moment": "Q5 answer",
        "overall_verdict": "Hire",
        "next_interview_tip": "Practice behavioral",
    }


@pytest.fixture
def ten_answers() -> list:
    """A list of 10 answer dicts representing a completed session."""
    return [{"q_index": i, "answer": f"Answer {i}"} for i in range(TOTAL_QUESTIONS)]


class TestGenerateFinalReport:
    """Tests for generate_final_report function."""

    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.save_report")
    @patch("agents.orchestrator.generate_report")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.get_session")
    def test_report_generation_happy_path(
        self,
        mock_get_session,
        mock_get_answers,
        mock_generate_report,
        mock_save_report,
        mock_update_state,
        valid_report_dict,
        ten_answers,
    ):
        """Happy path: all 10 answers present, Coach returns valid 11-key dict,
        transitions to REPORT then DONE, save_report called."""
        mock_get_session.return_value = {
            "session_id": "test-id",
            "state": STATE_FOLLOW_UP,
        }
        mock_get_answers.return_value = ten_answers
        mock_generate_report.return_value = valid_report_dict

        result = generate_final_report("test-id")

        # Returns exactly the 11 required keys
        assert len(result) == 11
        assert result == valid_report_dict

        # save_report was called
        mock_save_report.assert_called_once_with("test-id", valid_report_dict)

        # State transitions: first to REPORT, then to DONE
        transition_calls = mock_update_state.call_args_list
        states = [call[0][1] for call in transition_calls]
        assert STATE_REPORT in states
        assert STATE_DONE in states
        idx_report = states.index(STATE_REPORT)
        idx_done = states.index(STATE_DONE)
        assert idx_report < idx_done

    @patch("agents.orchestrator.generate_report")
    @patch("agents.orchestrator.get_report")
    @patch("agents.orchestrator.get_session")
    def test_idempotent_return_when_state_done(
        self,
        mock_get_session,
        mock_get_report,
        mock_generate_report,
        valid_report_dict,
    ):
        """When session is already DONE with a saved report, returns it
        without calling generate_report (Coach agent)."""
        mock_get_session.return_value = {
            "session_id": "test-id",
            "state": STATE_DONE,
        }
        mock_get_report.return_value = valid_report_dict

        result = generate_final_report("test-id")

        assert result == valid_report_dict
        # Coach agent was NOT called
        mock_generate_report.assert_not_called()

    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.get_session")
    def test_incomplete_session_raises_valueerror_with_missing_count(
        self,
        mock_get_session,
        mock_get_answers,
    ):
        """When not all questions are answered, raises ValueError with count info."""
        mock_get_session.return_value = {
            "session_id": "test-id",
            "state": STATE_ASKING,
        }
        # Only 5 answers out of 10
        mock_get_answers.return_value = [{"q_index": i} for i in range(5)]

        with pytest.raises(ValueError) as exc_info:
            generate_final_report("test-id")

        error_msg = str(exc_info.value)
        # Should mention the count of answered (5) or unanswered (5)
        assert "5" in error_msg

    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.generate_report")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.get_session")
    def test_coach_agent_failure_transitions_to_state_error(
        self,
        mock_get_session,
        mock_get_answers,
        mock_generate_report,
        mock_update_state,
        ten_answers,
    ):
        """When Coach agent raises RuntimeError, session transitions to STATE_ERROR."""
        mock_get_session.return_value = {
            "session_id": "test-id",
            "state": STATE_FOLLOW_UP,
        }
        mock_get_answers.return_value = ten_answers
        mock_generate_report.side_effect = RuntimeError("Coach failed")

        with pytest.raises(RuntimeError, match="Coach failed"):
            generate_final_report("test-id")

        # update_session_state should have been called with STATE_ERROR
        all_calls = mock_update_state.call_args_list
        states = [call[0][1] for call in all_calls]
        assert STATE_ERROR in states

    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.save_report")
    @patch("agents.orchestrator.generate_report")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.get_session")
    def test_extra_report_keys_are_stripped(
        self,
        mock_get_session,
        mock_get_answers,
        mock_generate_report,
        mock_save_report,
        mock_update_state,
        valid_report_dict,
        ten_answers,
    ):
        """When Coach returns 11 required keys + 3 extra, extras are stripped."""
        mock_get_session.return_value = {
            "session_id": "test-id",
            "state": STATE_FOLLOW_UP,
        }
        mock_get_answers.return_value = ten_answers

        # Add 3 extra keys to the report
        report_with_extras = dict(valid_report_dict)
        report_with_extras["extra1"] = "should be removed"
        report_with_extras["extra2"] = "should be removed"
        report_with_extras["extra3"] = "should be removed"
        mock_generate_report.return_value = report_with_extras

        result = generate_final_report("test-id")

        # Result should have exactly 11 keys (no extras)
        assert len(result) == 11
        assert "extra1" not in result
        assert "extra2" not in result
        assert "extra3" not in result
        # All required keys are present
        for key in valid_report_dict:
            assert key in result


# ---------------------------------------------------------------------------
# Tests for get_current_state
# ---------------------------------------------------------------------------


class TestGetCurrentState:
    """Tests for get_current_state function."""

    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.get_session")
    def test_returns_state_string_without_side_effects(
        self,
        mock_get_session,
        mock_update_state,
    ):
        """get_current_state returns the state string and never calls
        update_session_state (no side effects)."""
        mock_get_session.return_value = {
            "session_id": "test-id",
            "state": STATE_ASKING,
        }

        result = get_current_state("test-id")

        assert result == "ASKING"
        mock_update_state.assert_not_called()

    def test_empty_session_id_raises_valueerror(self):
        """Passing empty string as session_id raises ValueError."""
        with pytest.raises(ValueError):
            get_current_state("")

    def test_none_session_id_raises_valueerror(self):
        """Passing None as session_id raises ValueError."""
        with pytest.raises(ValueError):
            get_current_state(None)


# --- Tests for submit_answer ---

from core.config import MAX_FOLLOW_UPS


class TestSubmitAnswer:
    """Unit tests for submit_answer covering evaluation, follow-up logic,
    state transitions, and error cases."""

    def _make_session(self, state: str) -> dict:
        """Helper to build a session dict for mocking get_session."""
        return {
            "session_id": "test-id",
            "company": "Google",
            "role": "Software Engineer",
            "level": "senior",
            "state": state,
            "created_at": "2024-01-01T00:00:00",
        }

    def _make_question(self, index: int = 0) -> dict:
        """Helper to build a 7-key question dict."""
        return {
            "id": f"q-{index}",
            "category": "system_design",
            "question": f"Tell me about challenge {index + 1}?",
            "ideal_keywords": ["teamwork", "leadership"],
            "difficulty": 3,
            "follow_ups": ["Follow-up A", "Follow-up B"],
            "scoring_hint": f"Look for structured thinking in Q{index + 1}.",
        }

    def _make_eval_dict(self, trigger_follow_up: bool = False) -> dict:
        """Helper to build a valid 6-key evaluation dict.

        When trigger_follow_up=True, uses total < 12 (weak score).
        When trigger_follow_up=False, uses total = 14 (good score).
        """
        if trigger_follow_up:
            return {
                "scores": {"relevance": 2, "depth": 2, "structure": 3, "examples": 2},
                "total": 9,
                "verdict": "weak",
                "feedback": "Needs improvement.",
                "missing_keywords": ["leadership"],
                "trigger_follow_up": True,
            }
        return {
            "scores": {"relevance": 4, "depth": 3, "structure": 4, "examples": 3},
            "total": 14,
            "verdict": "good",
            "feedback": "Good answer.",
            "missing_keywords": [],
            "trigger_follow_up": False,
        }

    @patch("agents.orchestrator.get_follow_up_count")
    @patch("agents.orchestrator.save_answer")
    @patch("agents.orchestrator.evaluate_answer")
    @patch("agents.orchestrator.get_question")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.get_session")
    def test_happy_path_evaluation_returned_transitions_to_next_q(
        self,
        mock_get_session,
        mock_update_state,
        mock_get_answers,
        mock_get_question,
        mock_evaluate_answer,
        mock_save_answer,
        mock_get_follow_up_count,
    ):
        """Happy path: evaluation returned, state transitions to NEXT_Q."""
        mock_get_session.return_value = self._make_session(STATE_ASKING)
        mock_get_answers.return_value = []  # first question, q_index=0
        mock_get_question.return_value = self._make_question(0)
        eval_dict = self._make_eval_dict(trigger_follow_up=False)
        mock_evaluate_answer.return_value = eval_dict
        mock_get_follow_up_count.return_value = 0

        result = submit_answer("test-id", "My detailed answer about the challenge")

        # Returns the evaluation dict
        assert result["scores"] == eval_dict["scores"]
        assert result["total"] == 14
        assert result["verdict"] == "good"
        assert result["trigger_follow_up"] is False

        # save_answer was called
        mock_save_answer.assert_called_once()

        # State transitions: ASKING → EVALUATING → NEXT_Q
        transition_calls = mock_update_state.call_args_list
        states = [call[0][1] for call in transition_calls]
        assert STATE_EVALUATING in states
        assert STATE_NEXT_Q in states

    @patch("agents.orchestrator.increment_follow_up_count")
    @patch("agents.orchestrator.get_follow_up_question")
    @patch("agents.orchestrator.get_follow_up_count")
    @patch("agents.orchestrator.save_answer")
    @patch("agents.orchestrator.evaluate_answer")
    @patch("agents.orchestrator.get_question")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.get_session")
    def test_follow_up_triggered_with_count_below_max(
        self,
        mock_get_session,
        mock_update_state,
        mock_get_answers,
        mock_get_question,
        mock_evaluate_answer,
        mock_save_answer,
        mock_get_follow_up_count,
        mock_get_follow_up_question,
        mock_increment_follow_up_count,
    ):
        """Follow-up triggered with count < MAX_FOLLOW_UPS returns follow_up_question."""
        mock_get_session.return_value = self._make_session(STATE_ASKING)
        mock_get_answers.return_value = []  # q_index=0
        mock_get_question.return_value = self._make_question(0)
        mock_evaluate_answer.return_value = self._make_eval_dict(trigger_follow_up=True)
        mock_get_follow_up_count.return_value = 0
        mock_get_follow_up_question.return_value = "Follow-up Q?"

        result = submit_answer("test-id", "A short but valid answer here")

        # Result contains follow_up_question key
        assert "follow_up_question" in result
        assert result["follow_up_question"] == "Follow-up Q?"

        # Transition to FOLLOW_UP
        transition_calls = mock_update_state.call_args_list
        states = [call[0][1] for call in transition_calls]
        assert STATE_FOLLOW_UP in states

        # increment_follow_up_count was called
        mock_increment_follow_up_count.assert_called_once()

    @patch("agents.orchestrator.get_follow_up_count")
    @patch("agents.orchestrator.save_answer")
    @patch("agents.orchestrator.evaluate_answer")
    @patch("agents.orchestrator.get_question")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.get_session")
    def test_follow_up_at_max_skips_follow_up_transitions_to_next_q(
        self,
        mock_get_session,
        mock_update_state,
        mock_get_answers,
        mock_get_question,
        mock_evaluate_answer,
        mock_save_answer,
        mock_get_follow_up_count,
    ):
        """Follow-up at MAX_FOLLOW_UPS skips follow-up, transitions to NEXT_Q."""
        mock_get_session.return_value = self._make_session(STATE_ASKING)
        mock_get_answers.return_value = []  # q_index=0
        mock_get_question.return_value = self._make_question(0)
        mock_evaluate_answer.return_value = self._make_eval_dict(trigger_follow_up=True)
        mock_get_follow_up_count.return_value = MAX_FOLLOW_UPS  # 2

        result = submit_answer("test-id", "My answer to the question")

        # No follow_up_question in result
        assert "follow_up_question" not in result

        # Transition to NEXT_Q (not FOLLOW_UP)
        transition_calls = mock_update_state.call_args_list
        states = [call[0][1] for call in transition_calls]
        assert STATE_NEXT_Q in states
        assert STATE_FOLLOW_UP not in states

    @patch("agents.orchestrator.increment_follow_up_count")
    @patch("agents.orchestrator.get_follow_up_question")
    @patch("agents.orchestrator.get_follow_up_count")
    @patch("agents.orchestrator.save_answer")
    @patch("agents.orchestrator.evaluate_answer")
    @patch("agents.orchestrator.get_question")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.get_session")
    def test_trigger_follow_up_on_last_question_enters_follow_up(
        self,
        mock_get_session,
        mock_update_state,
        mock_get_answers,
        mock_get_question,
        mock_evaluate_answer,
        mock_save_answer,
        mock_get_follow_up_count,
        mock_get_follow_up_question,
        mock_increment_follow_up_count,
    ):
        """trigger_follow_up=True on last question (q_index=9) enters FOLLOW_UP."""
        mock_get_session.return_value = self._make_session(STATE_ASKING)
        # 9 answers already → q_index=9 (last question)
        mock_get_answers.return_value = [{"answer": f"ans {i}"} for i in range(9)]
        mock_get_question.return_value = self._make_question(9)
        mock_evaluate_answer.return_value = self._make_eval_dict(trigger_follow_up=True)
        mock_get_follow_up_count.return_value = 0
        mock_get_follow_up_question.return_value = "Follow-up?"

        result = submit_answer("test-id", "Answer to the last question")

        # Transition to FOLLOW_UP (not REPORT)
        transition_calls = mock_update_state.call_args_list
        states = [call[0][1] for call in transition_calls]
        assert STATE_FOLLOW_UP in states
        assert STATE_REPORT not in states
        assert "follow_up_question" in result

    @patch("agents.orchestrator.get_follow_up_question")
    @patch("agents.orchestrator.get_follow_up_count")
    @patch("agents.orchestrator.save_answer")
    @patch("agents.orchestrator.evaluate_answer")
    @patch("agents.orchestrator.get_question")
    @patch("agents.orchestrator.get_answers")
    @patch("agents.orchestrator.update_session_state")
    @patch("agents.orchestrator.get_session")
    def test_follow_up_function_returning_none_falls_through_to_next_q(
        self,
        mock_get_session,
        mock_update_state,
        mock_get_answers,
        mock_get_question,
        mock_evaluate_answer,
        mock_save_answer,
        mock_get_follow_up_count,
        mock_get_follow_up_question,
    ):
        """get_follow_up_question returning None falls through to NEXT_Q."""
        mock_get_session.return_value = self._make_session(STATE_ASKING)
        mock_get_answers.return_value = []  # q_index=0
        mock_get_question.return_value = self._make_question(0)
        mock_evaluate_answer.return_value = self._make_eval_dict(trigger_follow_up=True)
        mock_get_follow_up_count.return_value = 0
        mock_get_follow_up_question.return_value = None

        result = submit_answer("test-id", "My answer to the question")

        # No follow_up_question in result
        assert "follow_up_question" not in result

        # Transition to NEXT_Q
        transition_calls = mock_update_state.call_args_list
        states = [call[0][1] for call in transition_calls]
        assert STATE_NEXT_Q in states
        assert STATE_FOLLOW_UP not in states

    def test_whitespace_only_answer_raises_valueerror(self):
        """Whitespace-only answer_text raises ValueError."""
        with pytest.raises(ValueError, match="non-empty"):
            submit_answer("test-id", "   ")

    @patch("agents.orchestrator.get_session")
    def test_wrong_state_ready_raises_valueerror(self, mock_get_session):
        """State READY (not ASKING or FOLLOW_UP) raises ValueError."""
        mock_get_session.return_value = self._make_session(STATE_READY)

        with pytest.raises(ValueError, match="Cannot submit"):
            submit_answer("test-id", "My answer")

    @patch("agents.orchestrator.get_session")
    def test_wrong_state_generating_raises_valueerror(self, mock_get_session):
        """State GENERATING raises ValueError."""
        mock_get_session.return_value = self._make_session(STATE_GENERATING)

        with pytest.raises(ValueError, match="Cannot submit"):
            submit_answer("test-id", "My answer")

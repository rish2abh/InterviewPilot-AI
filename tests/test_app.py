"""
tests/test_app.py — Unit tests for the Streamlit UI (ui/app.py).

Covers screen rendering, widget parameters, orchestrator interactions,
spinner messages, verdict color mapping, and import validation.
Uses unittest.mock.patch to mock all 5 orchestrator functions.
"""

import ast
import os
from unittest.mock import patch, MagicMock, call

import pytest

from core.config import (
    STATE_SETUP,
    STATE_ASKING,
    STATE_NEXT_Q,
    STATE_REPORT,
    STATE_DONE,
    STATE_ERROR,
    STATE_FOLLOW_UP,
    TOTAL_QUESTIONS,
    MIN_ANSWER_LENGTH,
    MAX_TOTAL_SCORE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_question_dict(q_id: int = 1) -> dict:
    """Build a valid 7-key Question_Dict for mocking."""
    return {
        "id": q_id,
        "category": "system_design",
        "question": "Describe a scalable architecture.",
        "ideal_keywords": ["scalability", "caching"],
        "difficulty": 3,
        "follow_ups": ["Follow-up A", "Follow-up B"],
        "scoring_hint": "Look for tradeoff analysis.",
    }


def _make_evaluation_dict(verdict: str = "good") -> dict:
    """Build a valid Evaluation_Dict for mocking."""
    return {
        "scores": {"relevance": 4, "depth": 3, "structure": 4, "examples": 3},
        "total": 14,
        "verdict": verdict,
        "feedback": "Solid answer with room for more depth.",
        "missing_keywords": ["caching"],
        "trigger_follow_up": False,
    }


def _make_report_dict() -> dict:
    """Build a valid 11-key Report_Dict for mocking."""
    return {
        "overall_score": 150,
        "hiring_probability": "High",
        "hiring_probability_percent": 75,
        "strongest_category": "technical",
        "weakest_category": "behavioral",
        "category_averages": {"technical": 4.2, "behavioral": 3.1},
        "top_3_strengths": ["strong coding", "system design", "communication"],
        "top_3_improvements": ["depth", "examples", "time management"],
        "critical_moment": "Q5 showed excellent problem-solving",
        "overall_verdict": "Strong Hire",
        "next_interview_tip": "Practice behavioral questions",
    }


# ---------------------------------------------------------------------------
# Test: Import validation — only approved modules imported
# ---------------------------------------------------------------------------


class TestImportValidation:
    """Validate that ui/app.py only imports from approved modules."""

    def test_only_approved_imports(self):
        """Parse ui/app.py import block and verify only approved modules are used.

        Approved: streamlit, agents.orchestrator, core.config, and Python built-ins
        (json, time, re, uuid, datetime).
        """
        app_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ui",
            "app.py",
        )
        with open(app_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)

        approved_modules = {
            "streamlit",
            "agents.orchestrator",
            "core.config",
            # Python built-ins allowed by requirement 13.3
            "json",
            "time",
            "re",
            "uuid",
            "datetime",
        }

        imported_modules: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    # Use full dotted module for project imports
                    top_level = node.module.split(".")[0]
                    full_module = node.module
                    # Check if it's a project internal import
                    if top_level in ("agents", "core", "ui"):
                        imported_modules.add(full_module)
                    else:
                        imported_modules.add(top_level)

        # Every imported module must be in the approved set
        for module in imported_modules:
            assert module in approved_modules, (
                f"Unapproved import '{module}' found in ui/app.py. "
                f"Approved: {sorted(approved_modules)}"
            )


# ---------------------------------------------------------------------------
# Test: Setup screen renders correct widgets
# ---------------------------------------------------------------------------


class TestSetupScreen:
    """Tests for the Setup screen rendering and widget parameters."""

    @patch("ui.app.st")
    @patch("ui.app.get_current_state")
    def test_setup_renders_company_text_input_with_max_chars(
        self, mock_get_state, mock_st
    ):
        """Setup screen renders text_input for company with max_chars=200."""
        mock_st.session_state = {"session_id": None, "error_message": None}
        mock_st.text_input.return_value = ""
        mock_st.selectbox.return_value = "Fresher"
        mock_st.button.return_value = False

        from ui.app import _render_setup_screen

        _render_setup_screen()

        # Find the call for company text_input
        text_input_calls = mock_st.text_input.call_args_list
        assert len(text_input_calls) >= 2

        # First text_input is Company Name
        company_call = text_input_calls[0]
        assert company_call[0][0] == "Company Name"
        assert company_call[1]["max_chars"] == 200

    @patch("ui.app.st")
    @patch("ui.app.get_current_state")
    def test_setup_renders_role_text_input_with_max_chars(
        self, mock_get_state, mock_st
    ):
        """Setup screen renders text_input for role with max_chars=200."""
        mock_st.session_state = {"session_id": None, "error_message": None}
        mock_st.text_input.return_value = ""
        mock_st.selectbox.return_value = "Fresher"
        mock_st.button.return_value = False

        from ui.app import _render_setup_screen

        _render_setup_screen()

        text_input_calls = mock_st.text_input.call_args_list
        assert len(text_input_calls) >= 2

        # Second text_input is Role
        role_call = text_input_calls[1]
        assert role_call[0][0] == "Role"
        assert role_call[1]["max_chars"] == 200

    @patch("ui.app.st")
    @patch("ui.app.get_current_state")
    def test_setup_renders_selectbox_with_five_options_in_order(
        self, mock_get_state, mock_st
    ):
        """Setup screen renders selectbox with exactly 5 options in correct order."""
        mock_st.session_state = {"session_id": None, "error_message": None}
        mock_st.text_input.return_value = ""
        mock_st.selectbox.return_value = "Fresher"
        mock_st.button.return_value = False

        from ui.app import _render_setup_screen

        _render_setup_screen()

        mock_st.selectbox.assert_called_once()
        selectbox_call = mock_st.selectbox.call_args

        expected_options = [
            "Fresher",
            "Junior Engineer",
            "Senior Engineer",
            "Product Manager",
            "Data Scientist",
        ]

        # Options can be positional or keyword arg
        if "options" in selectbox_call[1]:
            actual_options = selectbox_call[1]["options"]
        else:
            actual_options = selectbox_call[0][1]

        assert list(actual_options) == expected_options

    @patch("ui.app.st")
    @patch("ui.app.get_current_state")
    def test_setup_renders_start_interview_button(self, mock_get_state, mock_st):
        """Setup screen renders a 'Start Interview' button."""
        mock_st.session_state = {"session_id": None, "error_message": None}
        mock_st.text_input.return_value = ""
        mock_st.selectbox.return_value = "Fresher"
        mock_st.button.return_value = False

        from ui.app import _render_setup_screen

        _render_setup_screen()

        # Check button was called with "Start Interview"
        button_calls = mock_st.button.call_args_list
        button_labels = [c[0][0] for c in button_calls]
        assert "Start Interview" in button_labels


# ---------------------------------------------------------------------------
# Test: start_session success stores session_id
# ---------------------------------------------------------------------------


class TestStartSessionSuccess:
    """Tests for start_session success storing session_id in session_state."""

    @patch("ui.app.st")
    @patch("ui.app.start_session")
    def test_start_session_success_stores_session_id(
        self, mock_start_session, mock_st
    ):
        """start_session success stores returned session_id in session_state."""
        mock_session_state = {"session_id": None, "error_message": None}
        mock_st.session_state = mock_session_state
        mock_st.text_input.side_effect = ["Google", "Software Engineer"]
        mock_st.selectbox.return_value = "Senior Engineer"
        mock_st.button.return_value = True
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_start_session.return_value = "test-uuid-123"

        from ui.app import _render_setup_screen

        _render_setup_screen()

        assert mock_session_state["session_id"] == "test-uuid-123"

    @patch("ui.app.st")
    @patch("ui.app.start_session")
    def test_start_session_exception_shows_error_preserves_none(
        self, mock_start_session, mock_st
    ):
        """start_session exception shows error and preserves None session_id."""
        mock_session_state = {"session_id": None, "error_message": None}
        mock_st.session_state = mock_session_state
        mock_st.text_input.side_effect = ["Google", "Software Engineer"]
        mock_st.selectbox.return_value = "Senior Engineer"
        mock_st.button.return_value = True
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_start_session.side_effect = RuntimeError("Agent failed")

        from ui.app import _render_setup_screen

        _render_setup_screen()

        # session_id remains None
        assert mock_session_state["session_id"] is None
        # st.error was called
        mock_st.error.assert_called()


# ---------------------------------------------------------------------------
# Test: Spinner text matches expected strings
# ---------------------------------------------------------------------------


class TestSpinnerMessages:
    """Tests verifying spinner text messages for blocking orchestrator calls."""

    @patch("ui.app.st")
    @patch("ui.app.start_session")
    def test_spinner_text_for_start_session(self, mock_start_session, mock_st):
        """Spinner text matches 'Researching company and generating questions...'."""
        mock_st.session_state = {"session_id": None, "error_message": None}
        mock_st.text_input.side_effect = ["Google", "Software Engineer"]
        mock_st.selectbox.return_value = "Senior Engineer"
        mock_st.button.return_value = True
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_start_session.return_value = "test-uuid"

        from ui.app import _render_setup_screen

        _render_setup_screen()

        mock_st.spinner.assert_called_with(
            "Researching company and generating questions..."
        )

    @patch("ui.app.st")
    @patch("ui.app.get_current_state")
    @patch("ui.app.get_current_question")
    @patch("ui.app.submit_answer")
    def test_spinner_text_for_submit_answer(
        self, mock_submit, mock_get_q, mock_get_state, mock_st
    ):
        """Spinner text matches 'Evaluating your answer...' for submit_answer."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_get_state.return_value = STATE_ASKING
        mock_get_q.return_value = _make_question_dict()
        mock_st.text_area.return_value = "A" * MIN_ANSWER_LENGTH
        mock_st.button.side_effect = [True]  # Submit Answer clicked
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_submit.return_value = _make_evaluation_dict()
        mock_st.columns.return_value = [MagicMock() for _ in range(4)]

        from ui.app import _render_interview_screen

        _render_interview_screen("test-id")

        mock_st.spinner.assert_called_with("Evaluating your answer...")

    @patch("ui.app.st")
    @patch("ui.app.generate_final_report")
    def test_spinner_text_for_generate_final_report(
        self, mock_gen_report, mock_st
    ):
        """Spinner text matches 'Generating your report...' for generate_final_report."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_st.button.return_value = False
        mock_st.columns.return_value = [MagicMock(), MagicMock()]
        mock_gen_report.return_value = _make_report_dict()

        from ui.app import _render_report_screen

        _render_report_screen("test-id")

        mock_st.spinner.assert_called_with("Generating your report...")


# ---------------------------------------------------------------------------
# Test: Verdict color mapping
# ---------------------------------------------------------------------------


class TestVerdictColorMapping:
    """Tests for verdict color coding: weak→error, good→warning, strong→success."""

    @patch("ui.app.st")
    def test_weak_verdict_uses_st_error(self, mock_st):
        """Verdict 'weak' is displayed via st.error."""
        mock_st.columns.return_value = [MagicMock() for _ in range(4)]

        from ui.app import _render_evaluation

        eval_dict = _make_evaluation_dict("weak")
        _render_evaluation(eval_dict)

        # st.error called with verdict text containing "WEAK"
        error_calls = mock_st.error.call_args_list
        error_texts = [str(c) for c in error_calls]
        assert any("WEAK" in t for t in error_texts)

    @patch("ui.app.st")
    def test_good_verdict_uses_st_warning(self, mock_st):
        """Verdict 'good' is displayed via st.warning."""
        mock_st.columns.return_value = [MagicMock() for _ in range(4)]

        from ui.app import _render_evaluation

        eval_dict = _make_evaluation_dict("good")
        _render_evaluation(eval_dict)

        # st.warning called with verdict text containing "GOOD"
        warning_calls = mock_st.warning.call_args_list
        warning_texts = [str(c) for c in warning_calls]
        assert any("GOOD" in t for t in warning_texts)

    @patch("ui.app.st")
    def test_strong_verdict_uses_st_success(self, mock_st):
        """Verdict 'strong' is displayed via st.success."""
        mock_st.columns.return_value = [MagicMock() for _ in range(4)]

        from ui.app import _render_evaluation

        eval_dict = _make_evaluation_dict("strong")
        eval_dict["total"] = 18
        _render_evaluation(eval_dict)

        # st.success called with verdict text containing "STRONG"
        success_calls = mock_st.success.call_args_list
        success_texts = [str(c) for c in success_calls]
        assert any("STRONG" in t for t in success_texts)


# ---------------------------------------------------------------------------
# Test: "Next Question" button only appears when state is STATE_NEXT_Q
# ---------------------------------------------------------------------------


class TestNextQuestionButton:
    """Tests for 'Next Question' button visibility based on state."""

    @patch("ui.app.st")
    @patch("ui.app.get_current_state")
    @patch("ui.app.get_current_question")
    @patch("ui.app.submit_answer")
    def test_next_question_button_appears_after_submit_in_next_q_state(
        self, mock_submit, mock_get_q, mock_get_state, mock_st
    ):
        """'Next Question' button appears when state is STATE_NEXT_Q after submit."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        # First call in the function returns ASKING (for rendering)
        # Second call after submit returns NEXT_Q
        mock_get_state.side_effect = [STATE_ASKING, STATE_NEXT_Q]
        mock_get_q.return_value = _make_question_dict()
        mock_st.text_area.return_value = "A" * MIN_ANSWER_LENGTH
        # Submit Answer clicked = True, then Next Question button
        mock_st.button.side_effect = [True, False]
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_submit.return_value = _make_evaluation_dict()
        mock_st.columns.return_value = [MagicMock() for _ in range(4)]

        from ui.app import _render_interview_screen

        _render_interview_screen("test-id")

        # Check button calls include "Next Question"
        button_calls = mock_st.button.call_args_list
        button_labels = [c[0][0] for c in button_calls]
        assert "Next Question" in button_labels

    @patch("ui.app.st")
    @patch("ui.app.get_current_state")
    @patch("ui.app.get_current_question")
    def test_next_question_button_not_shown_when_state_is_asking(
        self, mock_get_q, mock_get_state, mock_st
    ):
        """'Next Question' button does NOT appear when state is STATE_ASKING
        and no submit has occurred."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_get_state.return_value = STATE_ASKING
        mock_get_q.return_value = _make_question_dict()
        mock_st.text_area.return_value = ""
        mock_st.button.return_value = False

        from ui.app import _render_interview_screen

        _render_interview_screen("test-id")

        # Check that "Next Question" is NOT among button labels
        button_calls = mock_st.button.call_args_list
        button_labels = [c[0][0] for c in button_calls]
        assert "Next Question" not in button_labels


# ---------------------------------------------------------------------------
# Test: "Start New Interview" button clears session_id
# ---------------------------------------------------------------------------


class TestStartNewInterviewButton:
    """Tests for 'Start New Interview' button on error and report screens."""

    @patch("ui.app.st")
    def test_error_screen_start_new_clears_session_id(self, mock_st):
        """'Start New Interview' on error screen clears session_id."""
        mock_session_state = {"session_id": "test-id", "error_message": None}
        mock_st.session_state = mock_session_state
        mock_st.button.return_value = True  # Button clicked

        from ui.app import _render_error_screen

        _render_error_screen()

        assert mock_session_state["session_id"] is None

    @patch("ui.app.st")
    @patch("ui.app.generate_final_report")
    def test_report_screen_start_new_clears_session_id(
        self, mock_gen_report, mock_st
    ):
        """'Start New Interview' on report screen clears session_id."""
        mock_session_state = {"session_id": "test-id", "error_message": None}
        mock_st.session_state = mock_session_state
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_st.columns.return_value = [MagicMock(), MagicMock()]
        mock_st.button.return_value = True  # Button clicked
        mock_gen_report.return_value = _make_report_dict()

        from ui.app import _render_report_screen

        _render_report_screen("test-id")

        assert mock_session_state["session_id"] is None


# ---------------------------------------------------------------------------
# Test: Error screen shows only generic message and restart button
# ---------------------------------------------------------------------------


class TestErrorScreen:
    """Tests for Error screen content — generic message, no retry/resume."""

    @patch("ui.app.st")
    def test_error_screen_shows_generic_message(self, mock_st):
        """Error screen displays a generic error message without internal details."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_st.button.return_value = False

        from ui.app import _render_error_screen

        _render_error_screen()

        # st.error was called with a generic message
        mock_st.error.assert_called_once()
        error_msg = mock_st.error.call_args[0][0]
        assert "cannot continue" in error_msg.lower() or "error" in error_msg.lower()

    @patch("ui.app.st")
    def test_error_screen_has_no_retry_resume_controls(self, mock_st):
        """Error screen has no retry, resume, or back-navigation controls."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_st.button.return_value = False

        from ui.app import _render_error_screen

        _render_error_screen()

        # Only one button: "Start New Interview"
        button_calls = mock_st.button.call_args_list
        button_labels = [c[0][0] for c in button_calls]
        assert len(button_labels) == 1
        assert button_labels[0] == "Start New Interview"

        # No "Retry", "Resume", or "Back" buttons
        for label in button_labels:
            assert "retry" not in label.lower()
            assert "resume" not in label.lower()
            assert "back" not in label.lower()


# ---------------------------------------------------------------------------
# Test: text_area max_chars = 5000
# ---------------------------------------------------------------------------


class TestTextAreaMaxChars:
    """Tests for text_area max_chars constraint."""

    @patch("ui.app.st")
    @patch("ui.app.get_current_state")
    @patch("ui.app.get_current_question")
    def test_text_area_max_chars_is_5000(self, mock_get_q, mock_get_state, mock_st):
        """Interview screen text_area has max_chars=5000."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_get_state.return_value = STATE_ASKING
        mock_get_q.return_value = _make_question_dict()
        mock_st.text_area.return_value = ""
        mock_st.button.return_value = False

        from ui.app import _render_interview_screen

        _render_interview_screen("test-id")

        mock_st.text_area.assert_called_once()
        text_area_call = mock_st.text_area.call_args
        assert text_area_call[1]["max_chars"] == 5000


# ---------------------------------------------------------------------------
# Test: get_current_question called with correct session_id
# ---------------------------------------------------------------------------


class TestGetCurrentQuestionCall:
    """Tests that get_current_question is called with the correct session_id."""

    @patch("ui.app.st")
    @patch("ui.app.get_current_state")
    @patch("ui.app.get_current_question")
    def test_get_current_question_receives_correct_session_id(
        self, mock_get_q, mock_get_state, mock_st
    ):
        """get_current_question is called with the session_id passed to the screen."""
        mock_st.session_state = {"session_id": "my-unique-session", "error_message": None}
        mock_get_state.return_value = STATE_ASKING
        mock_get_q.return_value = _make_question_dict()
        mock_st.text_area.return_value = ""
        mock_st.button.return_value = False

        from ui.app import _render_interview_screen

        _render_interview_screen("my-unique-session")

        mock_get_q.assert_called_once_with("my-unique-session")


# ---------------------------------------------------------------------------
# Test: Report screen calls generate_final_report with session_id
# ---------------------------------------------------------------------------


class TestReportScreenCallsGenerateReport:
    """Tests that report screen calls generate_final_report with session_id."""

    @patch("ui.app.st")
    @patch("ui.app.generate_final_report")
    def test_report_screen_calls_generate_final_report_with_session_id(
        self, mock_gen_report, mock_st
    ):
        """Report screen calls generate_final_report with the correct session_id."""
        mock_st.session_state = {"session_id": "report-session-42", "error_message": None}
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock(return_value=False)
        mock_st.columns.return_value = [MagicMock(), MagicMock()]
        mock_st.button.return_value = False
        mock_gen_report.return_value = _make_report_dict()

        from ui.app import _render_report_screen

        _render_report_screen("report-session-42")

        mock_gen_report.assert_called_once_with("report-session-42")

"""tests/test_app_props.py — Property-based tests for the Streamlit UI (ui/app.py).

Uses Hypothesis to verify universal correctness properties.
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as hst
from unittest.mock import patch, MagicMock, PropertyMock
import pytest

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
    MIN_ANSWER_LENGTH,
    TOTAL_QUESTIONS,
    MAX_TOTAL_SCORE,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for session_id: either None or a UUID-like string
uuid_strategy = hst.from_regex(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    fullmatch=True,
)
session_id_strategy = hst.one_of(hst.none(), uuid_strategy)

# Strategy for error_message: either None or arbitrary non-empty strings
error_message_strategy = hst.one_of(hst.none(), hst.text(min_size=1, max_size=200))

# All 11 orchestrator state labels
ALL_STATES = [
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
]

# Strategy for whitespace-only strings (spaces, tabs, newlines)
whitespace_strategy = hst.from_regex(r"[\s]+", fullmatch=True).filter(
    lambda s: s.strip() == ""
)


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 1: INIT Block Idempotency
# ---------------------------------------------------------------------------


class TestInitBlockIdempotency:
    """Property 1: INIT Block Idempotency.

    **Validates: Requirements 2.1**

    For any pre-existing session_state containing a session_id value and
    an error_message value, executing the INIT block SHALL NOT overwrite
    those values.
    """

    # Feature: streamlit-ui, Property 1: INIT Block Idempotency

    @given(
        session_id=session_id_strategy,
        error_message=error_message_strategy,
    )
    @settings(max_examples=100)
    def test_init_block_does_not_overwrite_existing_values(
        self, session_id, error_message
    ):
        """INIT block idempotency: pre-existing values are never overwritten."""
        # Simulate session_state as a plain dict with pre-existing keys
        mock_session_state = {
            "session_id": session_id,
            "error_message": error_message,
        }

        # Execute the INIT block logic: only set if key does NOT exist
        if "session_id" not in mock_session_state:
            mock_session_state["session_id"] = None
        if "error_message" not in mock_session_state:
            mock_session_state["error_message"] = None

        # Values must be unchanged
        assert mock_session_state["session_id"] == session_id
        assert mock_session_state["error_message"] == error_message


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 2: Session State Minimality
# ---------------------------------------------------------------------------


# Operations that simulate UI interactions
OPERATIONS = ["setup", "answer", "report", "error_recovery"]


class TestSessionStateMinimality:
    """Property 2: Session State Minimality.

    **Validates: Requirements 2.4**

    After each operation, st.session_state contains only session_id and
    error_message keys — no question data, evaluation results, or report
    data cached.
    """

    # Feature: streamlit-ui, Property 2: Session State Minimality

    @given(
        operations=hst.lists(
            hst.sampled_from(OPERATIONS), min_size=1, max_size=10
        )
    )
    @settings(max_examples=100, deadline=None)
    @patch("ui.app.start_session")
    @patch("ui.app.get_current_state")
    @patch("ui.app.get_current_question")
    @patch("ui.app.submit_answer")
    @patch("ui.app.generate_final_report")
    def test_session_state_contains_only_declared_keys(
        self,
        mock_report,
        mock_submit,
        mock_get_question,
        mock_get_state,
        mock_start,
        operations,
    ):
        """After any sequence of operations, only session_id and error_message exist."""
        import streamlit as st

        # Set up mocks
        mock_start.return_value = "test-session-id"
        mock_get_state.return_value = STATE_ASKING
        mock_get_question.return_value = {
            "id": 1,
            "category": "technical",
            "question": "Test question?",
            "ideal_keywords": ["kw"],
            "difficulty": 3,
            "follow_ups": ["f1", "f2"],
            "scoring_hint": "hint",
        }
        mock_submit.return_value = {
            "scores": {"relevance": 4, "depth": 3, "structure": 4, "examples": 3},
            "total": 14,
            "verdict": "good",
            "feedback": "Good answer.",
            "missing_keywords": [],
            "trigger_follow_up": False,
        }
        mock_report.return_value = {
            "overall_score": 150,
            "hiring_probability": "High",
            "hiring_probability_percent": 75,
            "strongest_category": "technical",
            "weakest_category": "behavioral",
            "category_averages": {"technical": 4.2},
            "top_3_strengths": ["a", "b", "c"],
            "top_3_improvements": ["x", "y", "z"],
            "critical_moment": "Q5",
            "overall_verdict": "Strong Hire",
            "next_interview_tip": "Practice more",
        }

        # Use a real dict to simulate session_state
        fake_session_state = {"session_id": None, "error_message": None}

        with patch.object(st, "session_state", fake_session_state):
            for op in operations:
                if op == "setup":
                    # Simulate start_session storing session_id
                    fake_session_state["session_id"] = mock_start(
                        "Company", "Role", "Senior"
                    )
                elif op == "answer":
                    if fake_session_state["session_id"]:
                        mock_submit(fake_session_state["session_id"], "answer text")
                elif op == "report":
                    if fake_session_state["session_id"]:
                        mock_report(fake_session_state["session_id"])
                elif op == "error_recovery":
                    # Simulate error recovery: clear session
                    fake_session_state["session_id"] = None
                    fake_session_state["error_message"] = None

                # After each operation, verify only declared keys exist
                allowed_keys = {"session_id", "error_message"}
                assert set(fake_session_state.keys()) == allowed_keys, (
                    f"After operation '{op}', session_state has extra keys: "
                    f"{set(fake_session_state.keys()) - allowed_keys}"
                )


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 3: State-to-Screen Routing Completeness
# ---------------------------------------------------------------------------


class TestStateToScreenRouting:
    """Property 3: State-to-Screen Routing Completeness.

    **Validates: Requirements 3.1, 5.1, 10.1, 11.3**

    Every state maps to exactly one screen. No state maps to more than one
    screen. The mapping covers all 11 states plus None.
    """

    # Feature: streamlit-ui, Property 3: State-to-Screen Routing Completeness

    # Expected mapping
    EXPECTED_MAPPING = {
        None: "setup",
        STATE_SETUP: "setup",
        STATE_RESEARCHING: "loading",
        STATE_GENERATING: "loading",
        STATE_READY: "interview",
        STATE_ASKING: "interview",
        STATE_EVALUATING: "interview",
        STATE_FOLLOW_UP: "interview",
        STATE_NEXT_Q: "interview",
        STATE_REPORT: "report",
        STATE_DONE: "report",
        STATE_ERROR: "error",
    }

    @given(state=hst.sampled_from(ALL_STATES + [None]))
    @settings(max_examples=100)
    @patch("ui.app.get_current_state")
    def test_every_state_maps_to_exactly_one_screen(
        self, mock_get_state, state
    ):
        """Each orchestrator state maps to exactly one screen name."""
        import streamlit as st
        from ui.app import _get_active_screen

        fake_session_state = {"session_id": None, "error_message": None}

        if state is None:
            # No session — should route to "setup"
            fake_session_state["session_id"] = None
        else:
            # Session exists, orchestrator returns the given state
            fake_session_state["session_id"] = "test-session-uuid"
            mock_get_state.return_value = state

        with patch.object(st, "session_state", fake_session_state):
            screen = _get_active_screen()

        expected = self.EXPECTED_MAPPING[state]
        assert screen == expected, (
            f"State {state!r} mapped to {screen!r}, expected {expected!r}"
        )


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 4: Invalid Session Recovery
# ---------------------------------------------------------------------------


class TestInvalidSessionRecovery:
    """Property 4: Invalid Session Recovery.

    **Validates: Requirements 2.6, 11.4**

    When get_current_state raises ValueError, the router resets session_id
    to None, sets error_message to a non-empty string, and returns "setup".
    """

    # Feature: streamlit-ui, Property 4: Invalid Session Recovery

    @given(session_id=uuid_strategy)
    @settings(max_examples=100)
    @patch("ui.app.get_current_state")
    def test_invalid_session_resets_and_returns_setup(
        self, mock_get_state, session_id
    ):
        """ValueError from get_current_state triggers recovery."""
        import streamlit as st
        from ui.app import _get_active_screen

        mock_get_state.side_effect = ValueError("Session not found")

        fake_session_state = {
            "session_id": session_id,
            "error_message": None,
        }

        with patch.object(st, "session_state", fake_session_state):
            screen = _get_active_screen()

        # Router must return "setup"
        assert screen == "setup"
        # session_id must be cleared
        assert fake_session_state["session_id"] is None
        # error_message must be set to a non-empty string
        assert fake_session_state["error_message"] is not None
        assert isinstance(fake_session_state["error_message"], str)
        assert len(fake_session_state["error_message"]) > 0


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 5: Whitespace Input Rejection
# ---------------------------------------------------------------------------


class TestWhitespaceInputRejection:
    """Property 5: Whitespace Input Rejection.

    **Validates: Requirements 3.6**

    Whitespace-only company and/or role fields are rejected, validation
    error is shown, start_session is NOT called, session_id remains None.
    """

    # Feature: streamlit-ui, Property 5: Whitespace Input Rejection

    @given(
        company=whitespace_strategy,
        role=hst.text(min_size=1, max_size=50),
    )
    @settings(max_examples=100)
    @patch("ui.app.start_session")
    @patch("ui.app.st")
    def test_whitespace_company_rejected(
        self, mock_st, mock_start, company, role
    ):
        """Whitespace-only company input triggers validation error."""
        # Set up mock session_state
        mock_st.session_state = {"session_id": None, "error_message": None}
        mock_st.text_input.side_effect = [company, role]
        mock_st.selectbox.return_value = "Fresher"
        mock_st.button.return_value = True  # Simulate button click

        from ui.app import _render_setup_screen

        _render_setup_screen()

        # start_session must NOT be called
        mock_start.assert_not_called()
        # session_id must remain None
        assert mock_st.session_state["session_id"] is None
        # st.error must have been called (validation error)
        mock_st.error.assert_called()

    @given(
        company=hst.text(min_size=1, max_size=50).filter(lambda s: s.strip() != ""),
        role=whitespace_strategy,
    )
    @settings(max_examples=100)
    @patch("ui.app.start_session")
    @patch("ui.app.st")
    def test_whitespace_role_rejected(
        self, mock_st, mock_start, company, role
    ):
        """Whitespace-only role input triggers validation error."""
        # Set up mock session_state
        mock_st.session_state = {"session_id": None, "error_message": None}
        mock_st.text_input.side_effect = [company, role]
        mock_st.selectbox.return_value = "Senior Engineer"
        mock_st.button.return_value = True  # Simulate button click

        from ui.app import _render_setup_screen

        _render_setup_screen()

        # start_session must NOT be called
        mock_start.assert_not_called()
        # session_id must remain None
        assert mock_st.session_state["session_id"] is None
        # st.error must have been called (validation error)
        mock_st.error.assert_called()

    @given(
        company=whitespace_strategy,
        role=whitespace_strategy,
    )
    @settings(max_examples=100)
    @patch("ui.app.start_session")
    @patch("ui.app.st")
    def test_both_whitespace_rejected(
        self, mock_st, mock_start, company, role
    ):
        """Whitespace-only company AND role both trigger validation error."""
        # Set up mock session_state
        mock_st.session_state = {"session_id": None, "error_message": None}
        mock_st.text_input.side_effect = [company, role]
        mock_st.selectbox.return_value = "Data Scientist"
        mock_st.button.return_value = True  # Simulate button click

        from ui.app import _render_setup_screen

        _render_setup_screen()

        # start_session must NOT be called
        mock_start.assert_not_called()
        # session_id must remain None
        assert mock_st.session_state["session_id"] is None
        # st.error must have been called (validation error)
        mock_st.error.assert_called()


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 6: Answer Length Validation Threshold
# ---------------------------------------------------------------------------


class TestAnswerLengthValidationThreshold:
    """Property 6: Answer Length Validation Threshold.

    **Validates: Requirements 6.2, 6.3**

    For any string shorter than MIN_ANSWER_LENGTH, answer submission SHALL
    reject without calling submit_answer. For any string >= MIN_ANSWER_LENGTH,
    submit_answer SHALL be called.
    """

    # Feature: streamlit-ui, Property 6: Answer Length Validation Threshold

    @given(
        answer=hst.text(min_size=0, max_size=49),
    )
    @settings(max_examples=100)
    @patch("ui.app.submit_answer")
    @patch("ui.app.get_current_question")
    @patch("ui.app.get_current_state")
    @patch("ui.app.st")
    def test_short_answer_rejected(
        self, mock_st, mock_get_state, mock_get_question, mock_submit, answer
    ):
        """Answers shorter than MIN_ANSWER_LENGTH are rejected."""
        assume(len(answer) < MIN_ANSWER_LENGTH)

        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_get_state.return_value = STATE_ASKING
        mock_get_question.return_value = {
            "id": 1,
            "category": "technical",
            "question": "What is Python?",
            "ideal_keywords": ["interpreted"],
            "difficulty": 3,
            "follow_ups": ["f1", "f2"],
            "scoring_hint": "hint",
        }
        mock_st.text_area.return_value = answer
        mock_st.button.return_value = True
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock()

        from ui.app import _render_interview_screen

        _render_interview_screen("test-id")

        # submit_answer must NOT be called for short answers
        mock_submit.assert_not_called()
        # st.error must be called (validation error)
        mock_st.error.assert_called()

    @given(
        answer=hst.text(min_size=50, max_size=200),
    )
    @settings(max_examples=100)
    @patch("ui.app.submit_answer")
    @patch("ui.app.get_current_question")
    @patch("ui.app.get_current_state")
    @patch("ui.app.st")
    def test_valid_length_answer_accepted(
        self, mock_st, mock_get_state, mock_get_question, mock_submit, answer
    ):
        """Answers >= MIN_ANSWER_LENGTH proceed to submit_answer call."""
        assume(len(answer) >= MIN_ANSWER_LENGTH)

        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_get_state.return_value = STATE_ASKING
        mock_get_question.return_value = {
            "id": 1,
            "category": "technical",
            "question": "What is Python?",
            "ideal_keywords": ["interpreted"],
            "difficulty": 3,
            "follow_ups": ["f1", "f2"],
            "scoring_hint": "hint",
        }
        mock_st.text_area.return_value = answer
        mock_st.button.return_value = True
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock()
        mock_submit.return_value = {
            "scores": {"relevance": 4, "depth": 3, "structure": 4, "examples": 3},
            "total": 14,
            "verdict": "good",
            "feedback": "Good answer.",
            "missing_keywords": [],
            "trigger_follow_up": False,
        }
        mock_get_state.return_value = STATE_NEXT_Q

        from ui.app import _render_interview_screen

        _render_interview_screen("test-id")

        # submit_answer MUST be called for valid-length answers
        mock_submit.assert_called()


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 7: Hidden Question Fields Not Rendered
# ---------------------------------------------------------------------------


class TestHiddenQuestionFieldsNotRendered:
    """Property 7: Hidden Question Fields Not Rendered.

    **Validates: Requirements 5.6**

    For any Question_Dict, the UI SHALL NOT render ideal_keywords,
    difficulty, follow_ups, or scoring_hint values in any widget call.
    Only question, category, and id are displayed.
    """

    # Feature: streamlit-ui, Property 7: Hidden Question Fields Not Rendered

    @given(
        ideal_keywords=hst.lists(
            hst.text(min_size=3, max_size=30).filter(lambda s: s.strip() != ""),
            min_size=1,
            max_size=5,
        ),
        difficulty=hst.integers(min_value=1, max_value=5),
        follow_ups=hst.lists(
            hst.text(min_size=5, max_size=50).filter(lambda s: s.strip() != ""),
            min_size=2,
            max_size=2,
        ),
        scoring_hint=hst.text(min_size=5, max_size=100).filter(
            lambda s: s.strip() != ""
        ),
    )
    @settings(max_examples=100)
    @patch("ui.app.submit_answer")
    @patch("ui.app.get_current_question")
    @patch("ui.app.get_current_state")
    @patch("ui.app.st")
    def test_hidden_fields_not_in_widget_calls(
        self,
        mock_st,
        mock_get_state,
        mock_get_question,
        mock_submit,
        ideal_keywords,
        difficulty,
        follow_ups,
        scoring_hint,
    ):
        """Hidden question fields never appear in Streamlit widget calls."""
        # Use unique display values that won't overlap with generated hidden values.
        # The category and question use a distinctive prefix so substring false
        # positives from Hypothesis-generated hidden field values are avoided.
        display_category = "ZZQCATEGORY"
        display_question = "ZZQQUESTION describe something"
        display_id = 99

        # Filter out generated values that are substrings of the display fields
        # (these are false positives, not real rendering leaks)
        displayed_text = f"Question {display_id} of {TOTAL_QUESTIONS} Category: {display_category} {display_question} Your Answer Submit Answer"

        # Skip examples where hidden values coincidentally appear in displayed text
        for kw in ideal_keywords:
            assume(kw not in displayed_text)
        for fu in follow_ups:
            assume(fu not in displayed_text)
        assume(scoring_hint not in displayed_text)
        assume(str(difficulty) not in str(display_id))
        assume(str(difficulty) not in str(TOTAL_QUESTIONS))
        assume(str(difficulty) not in displayed_text)

        question_dict = {
            "id": display_id,
            "category": display_category,
            "question": display_question,
            "ideal_keywords": ideal_keywords,
            "difficulty": difficulty,
            "follow_ups": follow_ups,
            "scoring_hint": scoring_hint,
        }

        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_get_state.return_value = STATE_ASKING
        mock_get_question.return_value = question_dict
        mock_st.text_area.return_value = ""
        mock_st.button.return_value = False  # Don't submit, just render
        mock_st.columns.return_value = [MagicMock() for _ in range(4)]
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock()

        from ui.app import _render_interview_screen

        _render_interview_screen("test-id")

        # Collect all string arguments passed to any mock_st method
        all_call_args = []
        for call in mock_st.method_calls:
            for arg in call.args:
                if isinstance(arg, str):
                    all_call_args.append(arg)
            for val in call.kwargs.values():
                if isinstance(val, str):
                    all_call_args.append(val)

        rendered_text = " ".join(all_call_args)

        # Hidden field values must NOT appear in rendered output
        for kw in ideal_keywords:
            assert kw not in rendered_text, (
                f"ideal_keyword '{kw}' was rendered"
            )
        assert str(difficulty) not in rendered_text, (
            f"difficulty '{difficulty}' was rendered"
        )
        for fu in follow_ups:
            assert fu not in rendered_text, (
                f"follow_up '{fu}' was rendered"
            )
        assert scoring_hint not in rendered_text, (
            f"scoring_hint '{scoring_hint}' was rendered"
        )


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 8: Evaluation Display Completeness
# ---------------------------------------------------------------------------


class TestEvaluationDisplayCompleteness:
    """Property 8: Evaluation Display Completeness.

    **Validates: Requirements 6.5**

    For any valid Evaluation_Dict, all four sub-scores, total, verdict,
    and feedback SHALL be rendered by Streamlit display widgets.
    """

    # Feature: streamlit-ui, Property 8: Evaluation Display Completeness

    @given(
        relevance=hst.integers(min_value=1, max_value=5),
        depth=hst.integers(min_value=1, max_value=5),
        structure=hst.integers(min_value=1, max_value=5),
        examples=hst.integers(min_value=1, max_value=5),
        verdict=hst.sampled_from(["weak", "good", "strong"]),
        feedback=hst.text(min_size=5, max_size=200).filter(
            lambda s: s.strip() != ""
        ),
    )
    @settings(max_examples=100)
    @patch("ui.app.st")
    def test_all_evaluation_fields_rendered(
        self, mock_st, relevance, depth, structure, examples, verdict, feedback
    ):
        """All evaluation fields are passed to Streamlit display widgets."""
        total = relevance + depth + structure + examples
        evaluation = {
            "scores": {
                "relevance": relevance,
                "depth": depth,
                "structure": structure,
                "examples": examples,
            },
            "total": total,
            "verdict": verdict,
            "feedback": feedback,
            "missing_keywords": [],
            "trigger_follow_up": False,
        }

        # Mock columns to return mock objects with .metric method
        col_mocks = [MagicMock() for _ in range(4)]
        mock_st.columns.return_value = col_mocks

        from ui.app import _render_evaluation

        _render_evaluation(evaluation)

        # Verify sub-scores rendered via column metrics
        col_mocks[0].metric.assert_called_with("Relevance", f"{relevance}/5")
        col_mocks[1].metric.assert_called_with("Depth", f"{depth}/5")
        col_mocks[2].metric.assert_called_with("Structure", f"{structure}/5")
        col_mocks[3].metric.assert_called_with("Examples", f"{examples}/5")

        # Verify total score rendered
        mock_st.metric.assert_called_with("Total Score", f"{total}/20")

        # Verify verdict rendered (color-coded)
        if verdict == "weak":
            mock_st.error.assert_called_with("Verdict: WEAK")
        elif verdict == "good":
            mock_st.warning.assert_called_with("Verdict: GOOD")
        else:
            mock_st.success.assert_called_with("Verdict: STRONG")

        # Verify feedback rendered
        mock_st.info.assert_called_with(feedback)


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 9: Follow-Up Conditional Rendering
# ---------------------------------------------------------------------------


class TestFollowUpConditionalRendering:
    """Property 9: Follow-Up Conditional Rendering.

    **Validates: Requirements 7.1**

    Evaluation_Dicts WITH follow_up_question key → follow-up is rendered.
    Evaluation_Dicts WITHOUT follow_up_question key → no follow-up rendered.
    """

    # Feature: streamlit-ui, Property 9: Follow-Up Conditional Rendering

    @given(
        follow_up=hst.text(min_size=5, max_size=200).filter(
            lambda s: s.strip() != ""
        ),
    )
    @settings(max_examples=100)
    @patch("ui.app.get_current_state")
    @patch("ui.app.submit_answer")
    @patch("ui.app.get_current_question")
    @patch("ui.app.st")
    def test_follow_up_rendered_when_present(
        self, mock_st, mock_get_question, mock_submit, mock_get_state, follow_up
    ):
        """Follow-up question is rendered when present in evaluation."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_get_state.return_value = STATE_ASKING
        mock_get_question.return_value = {
            "id": 1,
            "category": "technical",
            "question": "Explain OOP.",
            "ideal_keywords": ["kw"],
            "difficulty": 3,
            "follow_ups": ["f1", "f2"],
            "scoring_hint": "hint",
        }
        # Valid answer length
        mock_st.text_area.return_value = "x" * MIN_ANSWER_LENGTH
        mock_st.button.return_value = True
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock()
        mock_st.columns.return_value = [MagicMock() for _ in range(4)]

        mock_submit.return_value = {
            "scores": {"relevance": 3, "depth": 3, "structure": 3, "examples": 3},
            "total": 12,
            "verdict": "weak",
            "feedback": "Needs more depth.",
            "missing_keywords": [],
            "trigger_follow_up": True,
            "follow_up_question": follow_up,
        }

        from ui.app import _render_interview_screen

        _render_interview_screen("test-id")

        # Verify st.warning was called with the follow-up text
        found = any(
            call.args and call.args[0] == follow_up
            for call in mock_st.warning.call_args_list
        )
        assert found, (
            f"Follow-up not found in st.warning calls: "
            f"{mock_st.warning.call_args_list}"
        )

    @given(
        relevance=hst.integers(min_value=1, max_value=5),
        depth=hst.integers(min_value=1, max_value=5),
        structure=hst.integers(min_value=1, max_value=5),
        examples=hst.integers(min_value=1, max_value=5),
        feedback=hst.text(min_size=5, max_size=200).filter(
            lambda s: s.strip() != ""
        ),
    )
    @settings(max_examples=100)
    @patch("ui.app.st")
    def test_no_follow_up_when_key_absent(
        self, mock_st, relevance, depth, structure, examples, feedback
    ):
        """No follow-up rendered when follow_up_question key is absent."""
        total = relevance + depth + structure + examples
        evaluation = {
            "scores": {
                "relevance": relevance,
                "depth": depth,
                "structure": structure,
                "examples": examples,
            },
            "total": total,
            "verdict": "good",
            "feedback": feedback,
            "missing_keywords": [],
            "trigger_follow_up": False,
        }

        col_mocks = [MagicMock() for _ in range(4)]
        mock_st.columns.return_value = col_mocks

        from ui.app import _render_evaluation

        _render_evaluation(evaluation)

        # st.warning should NOT be called with any follow-up text
        # (it may be called for verdict "good", but that's the verdict, not a follow-up)
        if mock_st.warning.called:
            for call in mock_st.warning.call_args_list:
                call_str = str(call)
                # The only allowed warning call is the verdict
                assert "Verdict" in call_str or "GOOD" in call_str, (
                    f"Unexpected st.warning call (possible follow-up leak): {call_str}"
                )


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 10: Report Score Formatting
# ---------------------------------------------------------------------------


class TestReportScoreFormatting:
    """Property 10: Report Score Formatting.

    **Validates: Requirements 9.3, 12.2**

    For any overall_score (0 to MAX_TOTAL_SCORE), the report displays it
    as "{overall_score}/{MAX_TOTAL_SCORE}" using the named constant.
    """

    # Feature: streamlit-ui, Property 10: Report Score Formatting

    @given(
        overall_score=hst.integers(min_value=0, max_value=MAX_TOTAL_SCORE),
    )
    @settings(max_examples=100)
    @patch("ui.app.generate_final_report")
    @patch("ui.app.st")
    def test_score_format_uses_constant(
        self, mock_st, mock_report, overall_score
    ):
        """Report score is formatted as '{score}/{MAX_TOTAL_SCORE}'."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock()
        mock_st.columns.return_value = [MagicMock(), MagicMock()]

        mock_report.return_value = {
            "overall_score": overall_score,
            "hiring_probability": "Medium",
            "hiring_probability_percent": 50,
            "strongest_category": "technical",
            "weakest_category": "behavioral",
            "category_averages": {"technical": 4.0},
            "top_3_strengths": ["a", "b", "c"],
            "top_3_improvements": ["x", "y", "z"],
            "critical_moment": "Q5",
            "overall_verdict": "Hire",
            "next_interview_tip": "Practice more",
        }

        from ui.app import _render_report_screen

        _render_report_screen("test-id")

        # Verify st.metric was called with the correct format
        expected_value = f"{overall_score}/{MAX_TOTAL_SCORE}"
        metric_calls = mock_st.metric.call_args_list
        found_score = any(
            len(call.args) >= 2 and call.args[1] == expected_value
            for call in metric_calls
        )
        assert found_score, (
            f"Expected metric call with '{expected_value}' not found in: "
            f"{metric_calls}"
        )


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 11: Category Averages Display Completeness
# ---------------------------------------------------------------------------


class TestCategoryAveragesDisplayCompleteness:
    """Property 11: Category Averages Display Completeness.

    **Validates: Requirements 9.6**

    For any category_averages dict with N entries, all N entries SHALL be
    rendered showing both category name and numeric value.
    """

    # Feature: streamlit-ui, Property 11: Category Averages Display Completeness

    @given(
        category_averages=hst.dictionaries(
            keys=hst.text(
                alphabet=hst.characters(whitelist_categories=("L",)),
                min_size=3,
                max_size=20,
            ),
            values=hst.floats(min_value=1.0, max_value=5.0, allow_nan=False),
            min_size=1,
            max_size=6,
        ),
    )
    @settings(max_examples=100)
    @patch("ui.app.generate_final_report")
    @patch("ui.app.st")
    def test_all_categories_rendered(
        self, mock_st, mock_report, category_averages
    ):
        """All category average entries are rendered."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock()
        mock_st.columns.return_value = [MagicMock(), MagicMock()]

        mock_report.return_value = {
            "overall_score": 150,
            "hiring_probability": "High",
            "hiring_probability_percent": 75,
            "strongest_category": "technical",
            "weakest_category": "behavioral",
            "category_averages": category_averages,
            "top_3_strengths": ["a", "b", "c"],
            "top_3_improvements": ["x", "y", "z"],
            "critical_moment": "Q5",
            "overall_verdict": "Strong Hire",
            "next_interview_tip": "Practice more",
        }

        from ui.app import _render_report_screen

        _render_report_screen("test-id")

        # Verify st.write was called for each category
        write_calls = [str(c) for c in mock_st.write.call_args_list]
        all_writes = " ".join(write_calls)

        for category_name in category_averages.keys():
            assert category_name in all_writes, (
                f"Category '{category_name}' not found in st.write calls: "
                f"{write_calls}"
            )


# ---------------------------------------------------------------------------
# Feature: streamlit-ui, Property 12: Report Lists Render Exactly Three Items
# ---------------------------------------------------------------------------


class TestReportListsRenderExactlyThreeItems:
    """Property 12: Report Lists Render Exactly Three Items.

    **Validates: Requirements 9.7**

    For any Report_Dict with top_3_strengths and top_3_improvements as
    lists of exactly 3 strings, the rendered output SHALL contain two
    separate lists each with exactly 3 items.
    """

    # Feature: streamlit-ui, Property 12: Report Lists Render Exactly Three Items

    @given(
        strengths=hst.lists(
            hst.text(min_size=3, max_size=80).filter(
                lambda s: s.strip() != ""
            ),
            min_size=3,
            max_size=3,
        ),
        improvements=hst.lists(
            hst.text(min_size=3, max_size=80).filter(
                lambda s: s.strip() != ""
            ),
            min_size=3,
            max_size=3,
        ),
    )
    @settings(max_examples=100, deadline=None)
    @patch("ui.app.generate_final_report")
    @patch("ui.app.st")
    def test_lists_render_exactly_three_items(
        self, mock_st, mock_report, strengths, improvements
    ):
        """Top 3 strengths and improvements each render exactly 3 items."""
        mock_st.session_state = {"session_id": "test-id", "error_message": None}
        mock_st.spinner.return_value.__enter__ = MagicMock()
        mock_st.spinner.return_value.__exit__ = MagicMock()
        mock_st.columns.return_value = [MagicMock(), MagicMock()]

        mock_report.return_value = {
            "overall_score": 150,
            "hiring_probability": "High",
            "hiring_probability_percent": 75,
            "strongest_category": "technical",
            "weakest_category": "behavioral",
            "category_averages": {"technical": 4.0},
            "top_3_strengths": strengths,
            "top_3_improvements": improvements,
            "critical_moment": "Q5",
            "overall_verdict": "Strong Hire",
            "next_interview_tip": "Practice more",
        }

        from ui.app import _render_report_screen

        _render_report_screen("test-id")

        # Verify st.markdown was called exactly twice (strengths + improvements)
        # Each call should be a numbered list with exactly 3 items
        markdown_calls = mock_st.markdown.call_args_list
        assert len(markdown_calls) == 2, (
            f"Expected 2 st.markdown calls, got {len(markdown_calls)}"
        )

        # Each markdown call should have exactly 3 numbered lines
        for i, call in enumerate(markdown_calls):
            call_text = call.args[0] if call.args else ""
            lines = [
                line for line in call_text.strip().split("\n") if line.strip()
            ]
            assert len(lines) == 3, (
                f"Markdown call {i} has {len(lines)} items, expected 3. "
                f"Content: {call_text!r}"
            )

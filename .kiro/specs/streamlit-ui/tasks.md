# Implementation Plan: Streamlit UI

## Overview

Implement the complete Streamlit UI (`ui/app.py`) for the Mock Interview Stress Tester. The UI renders five screens (Setup, Loading, Interview, Report, Error) driven by the orchestrator's state machine. It imports ONLY from `agents.orchestrator` and `core.config`, stores only `session_id` and `error_message` in `st.session_state`, and uses named constants for all thresholds. Tests are split into unit tests (`tests/test_app.py`) and property-based tests (`tests/test_app_props.py`).

## Tasks

- [x] 1. Create ui/app.py with imports, INIT block, and screen router
  - [x] 1.1 Create `ui/app.py` with import block, INIT block, and `_get_active_screen()` function
    - Create `ui/app.py` with the module docstring
    - Add `import streamlit as st`
    - Add imports from `agents.orchestrator`: `start_session`, `get_current_question`, `submit_answer`, `generate_final_report`, `get_current_state`
    - Add imports from `core.config`: `TOTAL_QUESTIONS`, `MIN_ANSWER_LENGTH`, `WEAK_SCORE_THRESHOLD`, `STRONG_SCORE_THRESHOLD`, `MAX_FOLLOW_UPS`, `HIRING_LOW_MAX`, `HIRING_HIGH_MIN`, `MAX_TOTAL_SCORE`, and all 11 `STATE_*` constants
    - Implement the INIT block with idempotent guard pattern for `session_id` (str | None, default None) and `error_message` (str | None, default None), each with an inline comment documenting type and purpose
    - Define module-level constant sets: `_LOADING_STATES`, `_INTERVIEW_STATES`, `_REPORT_STATES`
    - Implement `_get_active_screen() -> str` that reads `session_id` from session_state, calls `get_current_state` if non-None, handles ValueError by clearing session_id and setting error_message, and returns one of "setup", "loading", "interview", "report", "error"
    - Implement `_reset_session() -> None` helper that sets both keys to None
    - All functions must have type hints on parameters and return types
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 11.1, 11.2, 11.3, 11.4, 12.1_

- [x] 2. Implement Setup and Loading screens
  - [x] 2.1 Implement `_render_setup_screen()` with form inputs, validation, and start_session call
    - Add `_render_setup_screen() -> None` function
    - Display title "Mock Interview Stress Tester" and description
    - Show transient error_message from session_state (if any) via `st.error`, then clear it
    - Add `st.text_input("Company Name", max_chars=200)` for company
    - Add `st.text_input("Role", max_chars=200)` for role
    - Add `st.selectbox("Experience Level", options=["Fresher", "Junior Engineer", "Senior Engineer", "Product Manager", "Data Scientist"])`
    - Add `st.button("Start Interview")` submit trigger
    - On submit: validate `company.strip()` and `role.strip()` are non-empty; show `st.error` with specific field name if invalid; return without calling orchestrator
    - On valid submit: wrap `start_session(company, role, level)` in `st.spinner("Researching company and generating questions...")`, store returned session_id in session_state, call `st.rerun()`
    - On exception from `start_session`: display `st.error("Session creation failed. Please try again.")`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 14.1, 14.4_

  - [x] 2.2 Implement loading screen handling in the main routing for interrupted sessions
    - In the `main()` function, when screen is "loading", display a title, info message about session preparation, and a "Start New Interview" button that calls `_reset_session()` + `st.rerun()`
    - This handles the edge case where a page refresh occurs during start_session (RESEARCHING/GENERATING states)
    - _Requirements: 4.1, 11.3_

- [x] 3. Implement Interview screen
  - [x] 3.1 Implement `_render_interview_screen(session_id: str)` with question display and answer submission
    - Add `_render_interview_screen(session_id: str) -> None` function
    - Call `get_current_state(session_id)` to determine sub-state
    - Call `get_current_question(session_id)` wrapped in try/except ValueError; on error show `st.error` and return
    - Display question number as `st.caption(f"Question {n} of {TOTAL_QUESTIONS}")` using the config constant
    - Display category as `st.caption(f"Category: {question_dict['category']}")`
    - Display question text via `st.subheader(question_dict["question"])`
    - Do NOT render `ideal_keywords`, `difficulty`, `follow_ups`, or `scoring_hint`
    - If state is `STATE_FOLLOW_UP`, show `st.warning("Follow-up question — expand on your previous answer.")`
    - Add `st.text_area("Your Answer", max_chars=5000)` for answer input
    - Add "Submit Answer" button
    - On submit: validate `len(answer) < MIN_ANSWER_LENGTH` → show `st.error` with character count; return without calling orchestrator
    - On valid submit: wrap `submit_answer(session_id, answer)` in `st.spinner("Evaluating your answer...")`, catch exceptions and show error preserving typed text
    - On success: call `_render_evaluation(evaluation)` to display scores
    - After evaluation: if `"follow_up_question"` in evaluation dict, display it via `st.warning` and `st.rerun()`
    - After evaluation: check new state — if STATE_REPORT then `st.rerun()`, if STATE_NEXT_Q show "Next Question" button that triggers `st.rerun()`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 6.1, 6.2, 6.3, 6.4, 6.5, 6.7, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4, 14.2, 14.4_

  - [x] 3.2 Implement `_render_evaluation(evaluation: dict)` helper for score display with color-coded verdict
    - Add `_render_evaluation(evaluation: dict) -> None` function
    - Display 4 sub-scores (relevance, depth, structure, examples each as "{n}/5") in `st.columns(4)` using `st.metric`
    - Display total score as `st.metric("Total Score", f"{evaluation['total']}/20")`
    - Color-coded verdict: "weak" → `st.error(f"Verdict: WEAK")`, "good" → `st.warning(f"Verdict: GOOD")`, "strong" → `st.success(f"Verdict: STRONG")`
    - Display feedback via `st.info(evaluation["feedback"])`
    - _Requirements: 6.5, 6.6_

- [x] 4. Implement Report and Error screens
  - [x] 4.1 Implement `_render_report_screen(session_id: str)` with full report display
    - Add `_render_report_screen(session_id: str) -> None` function
    - Wrap `generate_final_report(session_id)` in `st.spinner("Generating your report...")`, catch exceptions and show `st.error`
    - Display `st.metric("Overall Score", f"{report['overall_score']}/{MAX_TOTAL_SCORE}")` using the config constant
    - Display `st.metric("Hiring Probability", f"{report['hiring_probability']} ({report['hiring_probability_percent']}%)")`
    - Display strongest_category and weakest_category in two columns via `st.metric`
    - Display category_averages breakdown: iterate `report["category_averages"].items()` showing each category name and numeric average
    - Display `top_3_strengths` as a numbered markdown list (exactly 3 items)
    - Display `top_3_improvements` as a separate numbered markdown list (exactly 3 items)
    - Display `critical_moment` via `st.info`
    - Display `overall_verdict` via `st.write`
    - Display `next_interview_tip` via `st.success`
    - Add `st.button("Start New Interview")` that calls `_reset_session()` + `st.rerun()`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 9.10, 9.11, 14.3, 14.4_

  - [x] 4.2 Implement `_render_error_screen()` with generic error message and restart button
    - Add `_render_error_screen() -> None` function
    - Display title "Session Error"
    - Display `st.error(...)` with a generic message ("This interview session encountered an error and cannot continue. Please start a new interview.") — no internal details or stack traces
    - No retry/resume/back-navigation controls
    - Add `st.button("Start New Interview")` that calls `_reset_session()` + `st.rerun()`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 5. Implement main entry point and wire all screens together
  - [x] 5.1 Implement `main()` function with `st.set_page_config` and screen routing
    - Add `main() -> None` function
    - Call `st.set_page_config(page_title="Mock Interview Stress Tester", page_icon="🎯", layout="centered")`
    - Call `_get_active_screen()` to determine which screen to render
    - Route to `_render_setup_screen()`, loading handler, `_render_interview_screen(session_id)`, `_render_report_screen(session_id)`, or `_render_error_screen()` based on returned screen name
    - Add `if __name__ == "__main__": main()` guard
    - _Requirements: 11.1, 11.2, 11.3, 11.5, 13.1, 13.2_

- [x] 6. Checkpoint — Verify ui/app.py structure
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: only `session_id` and `error_message` in session_state, no magic numbers, all functions have type hints, import block matches design exactly

- [x] 7. Create unit tests
  - [x] 7.1 Create `tests/test_app.py` with unit tests covering screen rendering and orchestrator interactions
    - Create `tests/test_app.py` file
    - Use `unittest.mock.patch` to mock all 5 orchestrator functions
    - Test: Setup screen renders text_input for company (max_chars=200), text_input for role (max_chars=200), selectbox with exactly 5 options in order (Fresher, Junior Engineer, Senior Engineer, Product Manager, Data Scientist), and "Start Interview" button
    - Test: `start_session` success stores session_id in session_state
    - Test: `start_session` exception shows error and preserves None session_id
    - Test: Spinner text matches "Researching company and generating questions..." for start_session
    - Test: Spinner text matches "Evaluating your answer..." for submit_answer
    - Test: Spinner text matches "Generating your report..." for generate_final_report
    - Test: Verdict color mapping — "weak" → `st.error`, "good" → `st.warning`, "strong" → `st.success`
    - Test: "Next Question" button only appears when state is STATE_NEXT_Q
    - Test: "Start New Interview" button on error/report screen clears session_id
    - Test: Error screen shows only generic message and restart button (no retry/resume)
    - Test: text_area max_chars = 5000
    - Test: Import validation — only approved modules imported (parse the import block of ui/app.py)
    - Test: `get_current_question` called with correct session_id
    - Test: Report screen calls `generate_final_report` with session_id
    - _Requirements: 3.4, 3.5, 3.7, 4.2, 5.6, 6.1, 6.6, 8.1, 9.10, 10.2, 10.3, 13.3, 14.1, 14.2, 14.3_

- [x] 8. Create property-based tests
  - [x] 8.1 Write property test for INIT block idempotency
    - **Property 1: INIT Block Idempotency**
    - **Validates: Requirements 2.1**
    - Generate random session_id (None or UUID strings) and error_message (None or arbitrary strings) using Hypothesis strategies
    - Set session_state with those values, execute the INIT block logic, verify values are unchanged after execution

  - [x] 8.2 Write property test for session state minimality
    - **Property 2: Session State Minimality**
    - **Validates: Requirements 2.4**
    - Generate arbitrary operation sequences (setup, answer, report, error recovery)
    - After each operation, verify `st.session_state` contains only `session_id` and `error_message` keys (no question data, evaluation results, or report data cached)

  - [x] 8.3 Write property test for state-to-screen routing completeness
    - **Property 3: State-to-Screen Routing Completeness**
    - **Validates: Requirements 3.1, 5.1, 10.1, 11.3**
    - Generate all 11 state labels plus None using `st.sampled_from`
    - Verify each maps to exactly one screen: None/STATE_SETUP → "setup", RESEARCHING/GENERATING → "loading", READY/ASKING/EVALUATING/FOLLOW_UP/NEXT_Q → "interview", REPORT/DONE → "report", ERROR → "error"

  - [x] 8.4 Write property test for invalid session recovery
    - **Property 4: Invalid Session Recovery**
    - **Validates: Requirements 2.6, 11.4**
    - Generate random session_id strings, mock `get_current_state` to raise ValueError
    - Verify router sets session_id to None, sets error_message to a non-empty string, and returns "setup"

  - [x] 8.5 Write property test for whitespace input rejection
    - **Property 5: Whitespace Input Rejection**
    - **Validates: Requirements 3.6**
    - Generate whitespace-only strings (spaces, tabs, newlines) for company and/or role fields
    - Verify setup submission logic rejects the input, shows validation error, does NOT call `start_session`, and session_id remains None

  - [x] 8.6 Write property test for answer length validation threshold
    - **Property 6: Answer Length Validation Threshold**
    - **Validates: Requirements 6.2, 6.3**
    - Generate strings shorter than MIN_ANSWER_LENGTH (50) → verify rejection without calling `submit_answer`
    - Generate strings of length >= MIN_ANSWER_LENGTH → verify `submit_answer` IS called (mocked)

  - [x] 8.7 Write property test for hidden question fields not rendered
    - **Property 7: Hidden Question Fields Not Rendered**
    - **Validates: Requirements 5.6**
    - Generate random Question_Dicts with all 7 keys (including random values for ideal_keywords, difficulty, follow_ups, scoring_hint)
    - Verify that only `question`, `category`, and `id` values appear in Streamlit widget calls; the 4 hidden fields do NOT appear

  - [x] 8.8 Write property test for evaluation display completeness
    - **Property 8: Evaluation Display Completeness**
    - **Validates: Requirements 6.5**
    - Generate valid Evaluation_Dicts with random scores (1-5), total (4-20), verdict, and feedback
    - Verify all four sub-scores, total, verdict, and feedback are passed to Streamlit display widgets

  - [x] 8.9 Write property test for follow-up conditional rendering
    - **Property 9: Follow-Up Conditional Rendering**
    - **Validates: Requirements 7.1**
    - Generate Evaluation_Dicts WITH a "follow_up_question" key (non-empty string) → verify it's rendered
    - Generate Evaluation_Dicts WITHOUT "follow_up_question" key → verify no follow-up prompt is rendered

  - [x] 8.10 Write property test for report score formatting
    - **Property 10: Report Score Formatting**
    - **Validates: Requirements 9.3, 12.2**
    - Generate overall_score integers (0 to MAX_TOTAL_SCORE) and verify display format is `"{overall_score}/{MAX_TOTAL_SCORE}"` using the named constant, never a hardcoded "200"

  - [x] 8.11 Write property test for category averages display completeness
    - **Property 11: Category Averages Display Completeness**
    - **Validates: Requirements 9.6**
    - Generate category_averages dicts with N key-value pairs (random category names → random floats)
    - Verify all N entries are rendered showing both category name and numeric value

  - [x] 8.12 Write property test for report lists render exactly three items
    - **Property 12: Report Lists Render Exactly Three Items**
    - **Validates: Requirements 9.7**
    - Generate Report_Dicts with top_3_strengths and top_3_improvements as lists of exactly 3 random strings
    - Verify two separate rendered lists each contain exactly 3 items

- [x] 9. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: no magic numbers in ui/app.py, all session_state keys documented, type hints on all functions, only approved imports

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All orchestrator functions must be mocked in tests — never call real agents
- The design uses Python (Streamlit 1.40.0 + Python 3.10+), so all code examples use Python
- Only two keys in session_state: `session_id` and `error_message`
- Use Hypothesis library for property-based tests (already used elsewhere in project per .hypothesis/ directory)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2"] },
    { "id": 2, "tasks": ["3.1", "3.2"] },
    { "id": 3, "tasks": ["4.1", "4.2"] },
    { "id": 4, "tasks": ["5.1"] },
    { "id": 5, "tasks": ["7.1"] },
    { "id": 6, "tasks": ["8.1", "8.2", "8.3", "8.4", "8.5", "8.6", "8.7", "8.8", "8.9", "8.10", "8.11", "8.12"] }
  ]
}
```

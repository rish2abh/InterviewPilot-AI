# Requirements Document

## Introduction

This document defines the requirements for the Streamlit front-end (`ui/app.py`) of the Mock Interview Stress Tester. The UI provides four screens (Setup, Loading, Interview, Report) plus an Error screen, all driven by the orchestrator's state machine. The UI enforces the MVC boundary rule: it may ONLY call functions from `agents/orchestrator.py` and import constants from `core/config.py`. It must never import from any other agent or core module directly.

## Glossary

- **App**: The Streamlit application defined in `ui/app.py`
- **Orchestrator**: The public API exposed by `agents/orchestrator.py` (start_session, get_current_question, submit_answer, generate_final_report, get_current_state)
- **Session_State**: Streamlit's `st.session_state` dictionary that persists data across reruns
- **Session_ID**: A UUID string returned by `start_session()` identifying an interview session
- **Question_Dict**: A dict with 7 keys (id, category, question, ideal_keywords, difficulty, follow_ups, scoring_hint)
- **Evaluation_Dict**: A dict with 6 keys (scores, total, verdict, feedback, missing_keywords, trigger_follow_up) plus optional "follow_up_question"
- **Report_Dict**: A dict with 11 keys (overall_score, hiring_probability, hiring_probability_percent, strongest_category, weakest_category, category_averages, top_3_strengths, top_3_improvements, critical_moment, overall_verdict, next_interview_tip)
- **State_Label**: One of the 11 state machine constants from config.py (STATE_SETUP, STATE_RESEARCHING, STATE_GENERATING, STATE_READY, STATE_ASKING, STATE_EVALUATING, STATE_FOLLOW_UP, STATE_NEXT_Q, STATE_REPORT, STATE_DONE, STATE_ERROR)
- **INIT_Block**: The top section of app.py where all Session_State keys are initialized with default values and documented with comments
- **Setup_Screen**: The initial form where users provide company, role, and level
- **Loading_Screen**: A spinner/progress display shown during RESEARCHING and GENERATING states
- **Interview_Screen**: The main screen displaying questions and accepting answers
- **Report_Screen**: The final screen displaying the complete performance report
- **Error_Screen**: A screen displayed when the orchestrator state is STATE_ERROR

## Requirements

### Requirement 1: MVC Boundary Enforcement

**User Story:** As a maintainer, I want the UI to only communicate through the orchestrator, so that the architecture remains decoupled and testable.

#### Acceptance Criteria

1. THE App SHALL import only from `agents.orchestrator` and `core.config` as project-internal module-level imports; standard library modules and third-party packages (e.g., `streamlit`, `json`, `time`) are not subject to this restriction
2. THE App SHALL call only the 5 public orchestrator functions (`start_session`, `get_current_question`, `submit_answer`, `generate_final_report`, `get_current_state`) for all interactions with the backend agents and database
3. THE App SHALL NOT import directly or indirectly from `agents.researcher`, `agents.question_generator`, `agents.evaluator`, `agents.coach`, `core.database`, or `agents.__init__` re-exports of those modules
4. THE App SHALL NOT use dynamic import mechanisms (`importlib`, `__import__`, or `getattr` on imported modules) to access any project-internal module other than `agents.orchestrator` and `core.config`

### Requirement 2: Session State Initialization

**User Story:** As a developer, I want all session state keys initialized in a single INIT block at the top of app.py, so that no uninitialized key access occurs during reruns.

#### Acceptance Criteria

1. THE App SHALL initialize all Session_State keys in a single INIT_Block that executes before any Streamlit widget rendering or screen routing logic, using an idempotent guard pattern (only setting a key if it does not already exist) so that values are not reset on subsequent reruns
2. THE App SHALL initialize exactly one persistent key ("session_id") with a default value of None, and all other Session_State keys used by the UI (such as current screen identifier, error message, and any transient display flags) SHALL also be declared in this INIT_Block with documented default values
3. THE App SHALL document each Session_State key with an inline comment stating the key's data type and role within the application
4. THE App SHALL store only the Session_ID in Session_State for cross-rerun persistence; no orchestrator state, question data, evaluation results, or report data SHALL be cached in Session_State
5. WHEN a Streamlit rerun occurs and a valid Session_ID exists in Session_State, THE App SHALL call the Orchestrator's get_current_state function to retrieve the session's current state and derive all screen data from the Orchestrator and database rather than from Session_State
6. IF the Orchestrator's get_current_state call raises a ValueError (session not found or invalid), THEN THE App SHALL clear the Session_ID from Session_State, reset to the setup screen, and display an error message indicating the session is no longer available

### Requirement 3: Setup Screen

**User Story:** As a user, I want to enter a company name, role, and experience level, so that the system can generate a tailored mock interview.

#### Acceptance Criteria

1. WHILE the Orchestrator state is STATE_SETUP or no Session_ID exists in Session_State, THE App SHALL display the Setup_Screen with input fields for company, role, and level
2. THE App SHALL provide a text input field for company name that accepts between 1 and 200 characters
3. THE App SHALL provide a text input field for role that accepts between 1 and 200 characters
4. THE App SHALL provide a selection input for experience level with exactly these options: Fresher, Junior Engineer, Senior Engineer, Product Manager, Data Scientist
5. WHEN the user submits the setup form, THE App SHALL display a loading indicator, call `start_session(company, role, level)`, and store the returned Session_ID in Session_State
6. IF any input field is empty or contains only whitespace at submission time, THEN THE App SHALL display a validation error message indicating which field is invalid, without calling start_session
7. IF `start_session` raises an exception, THEN THE App SHALL hide the loading indicator and display an error message indicating that session creation failed

### Requirement 4: Loading Screen

**User Story:** As a user, I want visual feedback while the system researches and generates questions, so that I know the application is working.

#### Acceptance Criteria

1. WHILE the start_session call is executing (blocking), THE App SHALL display a spinner context (st.spinner) wrapping the call, visible to the user for the entire duration of the SETUP→RESEARCHING→GENERATING→READY flow
2. WHILE the spinner is displayed, THE App SHALL show a status message that reads "Researching company and generating questions..." to indicate the current operation
3. WHEN the start_session call returns successfully with state STATE_READY, THE App SHALL proceed to the Interview_Screen on the next Streamlit rerun without requiring additional user action
4. IF the start_session call raises an exception during the loading phase, THEN THE App SHALL hide the spinner and display an error message indicating that session initialization failed, and SHALL remain on the current screen

### Requirement 5: Interview Screen — Question Display

**User Story:** As a user, I want to see the current interview question clearly, so that I can formulate my answer.

#### Acceptance Criteria

1. WHILE the Orchestrator state is STATE_ASKING, STATE_FOLLOW_UP, or STATE_NEXT_Q, THE App SHALL display the Interview_Screen
2. WHEN the state transitions to STATE_READY or STATE_NEXT_Q, THE App SHALL call `get_current_question(session_id)` to retrieve the current Question_Dict
3. WHILE the Interview_Screen is displayed, THE App SHALL display the question text from the Question_Dict using a visually distinct heading element that is larger than surrounding body text
4. WHILE the Interview_Screen is displayed, THE App SHALL display the question category from the Question_Dict as a secondary label adjacent to the question text
5. WHILE the Interview_Screen is displayed, THE App SHALL display the current question number in the format "{current_number} of {TOTAL_QUESTIONS}" where current_number is 1-indexed and TOTAL_QUESTIONS is read from config.py
6. WHILE the Interview_Screen is displayed, THE App SHALL NOT render the ideal_keywords, difficulty, follow_ups, or scoring_hint fields from the Question_Dict in any user-visible element
7. IF `get_current_question(session_id)` raises a ValueError, THEN THE App SHALL display an error message indicating the question could not be loaded and SHALL NOT display stale question data from a previous call

### Requirement 6: Interview Screen — Answer Submission

**User Story:** As a user, I want to type and submit my answer, so that it can be evaluated by the system.

#### Acceptance Criteria

1. THE App SHALL provide a multi-line text area input with a maximum capacity of 5000 characters for the user to type their answer
2. WHEN the user submits an answer, THE App SHALL validate that the answer length is at least MIN_ANSWER_LENGTH characters (50 characters, from config.py)
3. IF the submitted answer is shorter than MIN_ANSWER_LENGTH characters, THEN THE App SHALL display an error message indicating the minimum length requirement without calling submit_answer
4. WHEN the answer passes length validation, THE App SHALL call `submit_answer(session_id, answer_text)` and display the returned Evaluation_Dict
5. WHEN the Evaluation_Dict is returned, THE App SHALL display the evaluation scores (relevance, depth, structure, examples each shown as integer 1–5), total score (integer 4–20), verdict ("weak", "good", or "strong"), and feedback text from the Evaluation_Dict
6. WHEN the Evaluation_Dict is displayed, THE App SHALL apply color coding to the verdict: red for "weak", yellow for "good", and green for "strong"
7. IF the call to `submit_answer` raises a ValueError or any exception, THEN THE App SHALL display an error message indicating that evaluation failed and allow the user to re-submit the same answer without losing the typed text

### Requirement 7: Interview Screen — Follow-Up Questions

**User Story:** As a user, I want to see and respond to follow-up questions inline, so that I can improve my score on weak answers.

#### Acceptance Criteria

1. WHEN the Evaluation_Dict returned by `submit_answer` contains a "follow_up_question" key, THE App SHALL display the follow-up question text below the evaluation feedback within the Interview_Screen chat flow
2. WHILE the Orchestrator state is STATE_FOLLOW_UP, THE App SHALL display the text input for the follow-up answer and disable the submit control until the user has entered at least MIN_ANSWER_LENGTH (50) characters
3. WHEN the user submits a follow-up answer, THE App SHALL call `submit_answer(session_id, answer_text)` with the follow-up response and display the returned evaluation feedback
4. IF the response from `submit_answer` after a follow-up contains another "follow_up_question" key, THEN THE App SHALL display the subsequent follow-up question below the latest evaluation feedback, up to a maximum of MAX_FOLLOW_UPS (2) follow-ups per topic
5. IF the response from `submit_answer` after a follow-up does not contain a "follow_up_question" key, THEN THE App SHALL advance to the next question or the report screen based on the resulting Orchestrator state (STATE_NEXT_Q or STATE_REPORT)

### Requirement 8: Interview Screen — Question Progression

**User Story:** As a user, I want to proceed to the next question after evaluation, so that I can complete the full interview.

#### Acceptance Criteria

1. WHEN the Orchestrator state is STATE_NEXT_Q after an answer evaluation, THE App SHALL display a "Next Question" button as the sole mechanism to advance to the next question
2. WHEN the user clicks the "Next Question" button, THE App SHALL call `get_current_question(session_id)` and display the returned question text along with the current question number in the format "Question N of 10" where N is the next question's ordinal position (2 through 10)
3. IF `get_current_question(session_id)` raises a ValueError or any exception, THEN THE App SHALL display an error message indicating the question could not be loaded and keep the user on the current screen without advancing
4. WHEN the Orchestrator state transitions to STATE_REPORT after the last question (question 10) is evaluated, THE App SHALL navigate to the Report_Screen without displaying the "Next Question" button

### Requirement 9: Report Screen

**User Story:** As a user, I want to see a comprehensive performance report, so that I can understand my strengths and areas for improvement.

#### Acceptance Criteria

1. WHEN the Orchestrator state is STATE_REPORT or STATE_DONE, THE App SHALL call `generate_final_report(session_id)` and display the Report_Screen
2. WHILE `generate_final_report(session_id)` is executing, THE App SHALL display a loading indicator on the Report_Screen
3. THE App SHALL display the overall_score from the Report_Dict as a numeric value out of MAX_TOTAL_SCORE (200)
4. THE App SHALL display the hiring_probability and hiring_probability_percent from the Report_Dict
5. THE App SHALL display the strongest_category and weakest_category from the Report_Dict
6. THE App SHALL display the category_averages from the Report_Dict as a labeled breakdown showing each category name and its corresponding numeric average
7. THE App SHALL display the top_3_strengths and top_3_improvements from the Report_Dict as two separate lists of exactly 3 items each
8. THE App SHALL display the critical_moment from the Report_Dict
9. THE App SHALL display the overall_verdict and next_interview_tip from the Report_Dict
10. THE App SHALL display a button labeled for starting a new session on the Report_Screen that, WHEN clicked, resets the session state and navigates the user to the Setup_Screen
11. IF `generate_final_report(session_id)` raises an exception, THEN THE App SHALL display an error message indicating report generation failed and preserve the current session state

### Requirement 10: Error Screen

**User Story:** As a user, I want to see a clear error message when something goes wrong, so that I know the interview cannot continue and can start over.

#### Acceptance Criteria

1. WHEN the Orchestrator state is STATE_ERROR, THE App SHALL display the Error_Screen and SHALL NOT display any other screen content or navigation controls
2. WHILE the Error_Screen is displayed, THE App SHALL show a text message indicating the session cannot continue, without exposing internal error details or stack traces to the user
3. WHILE the Error_Screen is displayed, THE App SHALL NOT provide any retry, resume, or back-navigation controls
4. WHEN the user clicks the "Start New Interview" button on the Error_Screen, THE App SHALL clear the session_id from Session_State and redirect the user to the Setup_Screen

### Requirement 11: State Polling and Screen Routing

**User Story:** As a user, I want the UI to always show the correct screen based on the current session state, so that a page refresh does not lose my progress.

#### Acceptance Criteria

1. IF no session_id key exists in st.session_state, THEN THE App SHALL display the Setup_Screen without calling `get_current_state`
2. WHEN a session_id key exists in st.session_state, THE App SHALL call `get_current_state(session_id)` once at the start of each Streamlit rerun to determine the current State_Label
3. WHEN `get_current_state` returns a State_Label, THE App SHALL route to the corresponding screen: Loading_Screen for RESEARCHING or GENERATING, Interview_Screen for READY, ASKING, EVALUATING, FOLLOW_UP, or NEXT_Q, Report_Screen for REPORT or DONE, Error_Screen for ERROR
4. IF `get_current_state` raises a ValueError (session not found), THEN THE App SHALL remove the session_id key from st.session_state and display the Setup_Screen
5. WHEN a new session is created via `start_session`, THE App SHALL store the returned session_id in st.session_state so that subsequent reruns and page refreshes resume from the persisted state

### Requirement 12: Constants from Config

**User Story:** As a maintainer, I want all display thresholds and limits sourced from config.py, so that no magic numbers exist in the UI code.

#### Acceptance Criteria

1. THE App SHALL import TOTAL_QUESTIONS, MIN_ANSWER_LENGTH, WEAK_SCORE_THRESHOLD, STRONG_SCORE_THRESHOLD, MAX_FOLLOW_UPS, HIRING_LOW_MAX, HIRING_HIGH_MIN, MAX_TOTAL_SCORE, and all STATE_* constants from `core.config` at the top of `ui/app.py`
2. WHEN the App performs threshold comparisons, progress calculations, or conditional rendering based on scores, question counts, answer lengths, or hiring probability bands, THE App SHALL reference the corresponding named constant from `core.config` rather than a hardcoded numeric or string literal
3. THE App SHALL contain no integer, float, or string literal in `ui/app.py` that duplicates the value of any constant defined in `core.config`, with the sole exception of UI-only values that have no corresponding config constant (e.g., layout column counts, Streamlit widget labels)

### Requirement 13: Technology Constraints

**User Story:** As a maintainer, I want the UI to use only approved libraries, so that the project remains lightweight and consistent.

#### Acceptance Criteria

1. THE App SHALL use only Streamlit 1.40.0 for all UI rendering in ui/app.py, with no other UI framework imported
2. THE App SHALL use Python 3.10+ with type hints (parameter types and return types) on all module-level and class-level function signatures
3. THE App SHALL NOT import any module in ui/app.py outside the approved list: streamlit, agents.orchestrator, core.config, and Python built-ins limited to json, time, re, uuid, and datetime
4. IF a static analysis check or code review detects an import not present in the approved list within ui/app.py, THEN THE App SHALL fail the review and the unapproved import SHALL be removed before merge

### Requirement 14: Blocking Call Handling

**User Story:** As a user, I want the UI to remain responsive during long orchestrator calls, so that I am not confused by a frozen screen.

#### Acceptance Criteria

1. WHEN `start_session()` is called, THE App SHALL display a spinner with a progress message indicating that the interview session is being prepared (e.g., indicating research and question generation are in progress), and the spinner SHALL remain visible until `start_session()` returns or raises an exception
2. WHEN `submit_answer()` is called, THE App SHALL display a spinner with a progress message indicating that the answer is being evaluated, and the spinner SHALL remain visible until `submit_answer()` returns or raises an exception
3. WHEN `generate_final_report()` is called, THE App SHALL display a spinner with a progress message indicating that the report is being generated, and the spinner SHALL remain visible until `generate_final_report()` returns or raises an exception
4. WHILE any blocking orchestrator call (`start_session`, `submit_answer`, or `generate_final_report`) is in progress, THE App SHALL prevent the user from triggering additional orchestrator calls by disabling or hiding the relevant input controls

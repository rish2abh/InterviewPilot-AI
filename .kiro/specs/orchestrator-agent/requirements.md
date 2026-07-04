# Requirements Document

## Introduction

The Orchestrator Agent is the central state machine controller for the Mock Interview Stress Tester. Implemented as `agents/orchestrator.py`, it drives one interview session end-to-end by sequencing calls to four existing agents (Researcher, QuestionGenerator, Evaluator, Coach) and persisting every state transition to SQLite via `core/database.py`. The orchestrator owns no business logic of its own — no scoring, no question generation, no prompt construction — it only sequences agent calls, validates handoff contracts, manages state transitions, and handles errors. All state is re-derived from the database on each call; no module-level caching is permitted.

## Glossary

- **Orchestrator**: The Python module `agents/orchestrator.py` containing all public API functions that drive a single interview session through its state machine
- **Session**: A single interview run identified by a UUID `session_id`, stored in the `sessions` table with its current state label
- **State_Machine**: The ordered sequence of valid states a session transitions through: SETUP → RESEARCHING → GENERATING → READY → ASKING → EVALUATING → FOLLOW_UP → NEXT_Q → REPORT → DONE, plus ERROR reachable from any state
- **STATE_SETUP**: The initial state assigned when a session is created via `create_session`
- **STATE_RESEARCHING**: The state during which the Researcher agent is executing
- **STATE_GENERATING**: The state during which the QuestionGenerator agent is executing
- **STATE_READY**: The state indicating all questions are generated and the session is ready to begin asking
- **STATE_ASKING**: The state indicating the current question has been presented to the user
- **STATE_EVALUATING**: The state during which the Evaluator agent is scoring an answer
- **STATE_FOLLOW_UP**: The state indicating a follow-up question is being presented
- **STATE_NEXT_Q**: The transitional state indicating the session is advancing to the next question
- **STATE_REPORT**: The state during which the Coach agent is generating the final report
- **STATE_DONE**: The terminal state indicating the session is complete with a final report generated
- **STATE_ERROR**: The terminal error state reachable from any other state, storing a reason string
- **Researcher_Agent**: The function `research_company(company, role, level, api_key)` in `agents/researcher.py` that returns a Research_Dict
- **QuestionGenerator_Agent**: The function `generate_questions(research_data, session_id, api_key)` in `agents/question_generator.py` that returns a list of 10 Question_Dict objects
- **Evaluator_Agent**: The function `evaluate_answer(question, ideal_keywords, scoring_hint, user_answer, api_key)` in `agents/evaluator.py` that returns an Evaluation_Dict
- **Follow_Up_Function**: The function `get_follow_up_question(question_dict, follow_up_count)` in `agents/evaluator.py` that returns a follow-up question string or None
- **Coach_Agent**: The function `generate_report(session_id, answers)` in `agents/coach.py` (stubbed) that returns a Report_Dict with 11 keys
- **Research_Dict**: A validated dict with 8 keys: company, role, interview_rounds, key_topics, difficulty, culture_keywords, known_question_types, red_flags_to_test (plus optional error_flag)
- **Question_Dict**: A validated dict with 7 keys: id, category, question, ideal_keywords, difficulty, follow_ups, scoring_hint
- **Evaluation_Dict**: A validated dict with 6 keys: scores, total, verdict, feedback, missing_keywords, trigger_follow_up
- **Report_Dict**: A validated dict with 11 keys: overall_score, hiring_probability, hiring_probability_percent, strongest_category, weakest_category, category_averages, top_3_strengths, top_3_improvements, critical_moment, overall_verdict, next_interview_tip
- **TOTAL_QUESTIONS**: The constant value 10 from `core/config.py` defining the exact number of interview questions per session
- **MAX_FOLLOW_UPS**: The constant value 2 from `core/config.py` defining the maximum follow-up questions allowed per topic
- **WEAK_SCORE_THRESHOLD**: The constant value 12 from `core/config.py` below which a verdict is "weak" and trigger_follow_up is True
- **RATE_LIMIT_SLEEP**: The constant value 4 from `core/config.py` — seconds between consecutive LLM calls
- **ERROR_RETRY_SLEEP**: The constant value 8 from `core/config.py` — seconds to sleep before retrying after an API error
- **GEMINI_API_KEY**: The API key loaded from the environment via `core/config.py`
- **MIN_ANSWER_LENGTH**: The constant value 50 from `core/config.py` — minimum character count for a user answer before LLM evaluation

## Requirements

### Requirement 1: Start Session — Setup, Research, and Question Generation

**User Story:** As a job seeker, I want to start a mock interview by providing a company, role, and experience level, so that the system prepares a tailored set of interview questions for me.

#### Acceptance Criteria

1. WHEN start_session receives a company (str), role (str), and level (str), THE Orchestrator SHALL generate a UUID session_id, call create_session to persist it with STATE_SETUP, and return the session_id to the caller
2. WHEN the session is created, THE Orchestrator SHALL transition the session state to STATE_RESEARCHING, call Researcher_Agent with the company, role, level, and GEMINI_API_KEY, and persist the returned Research_Dict via save_research
3. WHEN research is complete, THE Orchestrator SHALL transition the session state to STATE_GENERATING, call QuestionGenerator_Agent with the Research_Dict, session_id, and GEMINI_API_KEY, and transition to STATE_READY upon successful return
4. IF the company string is empty, contains only whitespace, or exceeds 200 characters after stripping, THEN THE Orchestrator SHALL raise a ValueError with a descriptive message without creating a session
5. IF the role string is empty, contains only whitespace, or exceeds 200 characters after stripping, THEN THE Orchestrator SHALL raise a ValueError with a descriptive message without creating a session
6. IF the level string is empty, contains only whitespace, or exceeds 200 characters after stripping, THEN THE Orchestrator SHALL raise a ValueError with a descriptive message without creating a session
7. WHEN Researcher_Agent returns a Research_Dict containing error_flag set to True, THE Orchestrator SHALL proceed normally with the generic research data (no special error handling needed since the researcher already provides safe defaults)
8. IF QuestionGenerator_Agent raises a QuestionGenerationError during question generation, THEN THE Orchestrator SHALL transition the session state to STATE_ERROR and re-raise the exception to the caller without leaving the session in an intermediate state
9. IF GEMINI_API_KEY is empty or not configured at the time start_session is called, THEN THE Orchestrator SHALL raise a ValueError with a descriptive message without creating a session

### Requirement 2: Get Current Question

**User Story:** As a job seeker, I want to retrieve the current question I need to answer, so that the UI can display it and I can respond.

#### Acceptance Criteria

1. WHEN get_current_question receives a session_id that exists in the database, THE Orchestrator SHALL determine the current question index from the number of answers already submitted (count of rows in answers table for that session_id), retrieve the corresponding Question_Dict from the questions table, and return it
2. WHEN the session is in STATE_READY and get_current_question is called, THE Orchestrator SHALL transition the session to STATE_ASKING and return the first question (q_index 0)
3. WHEN the session is in STATE_NEXT_Q and get_current_question is called, THE Orchestrator SHALL transition the session to STATE_ASKING and return the next unanswered question based on the current answer count
4. WHEN the session is already in STATE_ASKING and get_current_question is called again, THE Orchestrator SHALL return the current question without performing another state transition (idempotent read)
5. IF get_current_question is called with a session_id that does not exist in the database, THEN THE Orchestrator SHALL raise a ValueError with the message indicating session not found
6. IF get_current_question is called while the session is in STATE_DONE or STATE_ERROR, THEN THE Orchestrator SHALL raise a ValueError with a message indicating the session is no longer active
7. IF get_current_question is called when all TOTAL_QUESTIONS have been answered, THEN THE Orchestrator SHALL raise a ValueError indicating no more questions are available
8. THE Orchestrator SHALL return a dict containing exactly the 7 Question_Dict keys: question (str), ideal_keywords (list), scoring_hint (str), category (str), difficulty (int), follow_ups (list), and id (str)

### Requirement 3: Submit Answer — Evaluation and Follow-Up Logic

**User Story:** As a job seeker, I want to submit my answer and receive immediate evaluation with possible follow-up questions, so that I get adaptive feedback during the interview.

#### Acceptance Criteria

1. WHEN submit_answer receives a valid session_id and answer_text (non-empty, non-whitespace-only string), THE Orchestrator SHALL identify the current question by counting existing answers for the session, call Evaluator_Agent with the question text, ideal_keywords, scoring_hint, answer_text, and GEMINI_API_KEY, save the answer and evaluation via save_answer, and transition to STATE_EVALUATING
2. WHEN the Evaluation_Dict has trigger_follow_up set to True and the current follow-up count for this question is less than MAX_FOLLOW_UPS, THE Orchestrator SHALL call Follow_Up_Function with the Question_Dict and follow_up_count, transition to STATE_FOLLOW_UP, and include the follow-up question string in the returned dict
3. WHEN the Evaluation_Dict has trigger_follow_up set to True but the current follow-up count has reached MAX_FOLLOW_UPS, THE Orchestrator SHALL skip the follow-up and transition to STATE_NEXT_Q (or STATE_REPORT if the last question was answered)
4. WHEN the Evaluation_Dict has trigger_follow_up set to False, THE Orchestrator SHALL transition directly to STATE_NEXT_Q (or STATE_REPORT if the last question has been answered)
5. WHEN trigger_follow_up is True on the last question (q_index equals TOTAL_QUESTIONS minus 1) and follow-up count is less than MAX_FOLLOW_UPS, THE Orchestrator SHALL still transition to STATE_FOLLOW_UP before eventually transitioning to STATE_REPORT
6. WHEN Follow_Up_Function returns None despite trigger_follow_up being True, THE Orchestrator SHALL fall through to STATE_NEXT_Q (or STATE_REPORT if last question)
7. IF submit_answer is called with a session_id that does not exist, THEN THE Orchestrator SHALL raise a ValueError indicating session not found
8. IF submit_answer is called while the session is in STATE_DONE or STATE_ERROR, THEN THE Orchestrator SHALL raise a ValueError indicating the session is no longer active
9. IF submit_answer is called for a q_index that already has a saved answer (duplicate submission), THEN THE Orchestrator SHALL raise a ValueError indicating duplicate answer submission
10. IF submit_answer is called when the session is not in STATE_ASKING or STATE_FOLLOW_UP, THEN THE Orchestrator SHALL raise a ValueError indicating the session is not expecting an answer
11. THE Orchestrator SHALL return a dict containing the Evaluation_Dict keys plus optionally a "follow_up_question" key (str) when a follow-up is triggered and available

### Requirement 4: Generate Final Report

**User Story:** As a job seeker, I want a comprehensive performance report after completing all questions, so that I understand my hiring probability and areas for improvement.

#### Acceptance Criteria

1. WHEN generate_final_report receives a session_id that exists in the database and all TOTAL_QUESTIONS answers have been saved for that session, THE Orchestrator SHALL transition to STATE_REPORT, retrieve all answers via get_answers, call Coach_Agent with the session_id and answers, validate the Report_Dict contains exactly 11 required keys with correct types, save it via save_report, transition to STATE_DONE, and return the Report_Dict
2. IF generate_final_report is called before all TOTAL_QUESTIONS answers have been saved for the session, THEN THE Orchestrator SHALL raise a ValueError with a message indicating the session is incomplete and how many answers are missing
3. IF generate_final_report is called when the session is already in STATE_DONE and a report already exists in the reports table, THEN THE Orchestrator SHALL return the previously saved report without calling Coach_Agent again (idempotent behavior)
4. IF Coach_Agent raises an exception or returns a Report_Dict missing any of the 11 required keys or containing keys with incorrect types, THEN THE Orchestrator SHALL transition the session to STATE_ERROR and store the failure reason as a string in the session state update
5. IF generate_final_report is called with a session_id that does not exist in the database, THEN THE Orchestrator SHALL raise a ValueError indicating session not found
6. THE Report_Dict returned SHALL contain exactly 11 keys: overall_score (int), hiring_probability (str, one of "Low", "Medium", "High"), hiring_probability_percent (int, range 0 to 100), strongest_category (str), weakest_category (str), category_averages (dict mapping category name strings to numeric averages), top_3_strengths (list of exactly 3 strings), top_3_improvements (list of exactly 3 strings), critical_moment (str), overall_verdict (str), next_interview_tip (str)
7. IF the Report_Dict returned by Coach_Agent contains extra keys beyond the 11 required keys, THEN THE Orchestrator SHALL strip the extra keys before saving and returning the report

### Requirement 5: Get Current State

**User Story:** As the UI layer, I want to query the current state of any session, so that I can render the appropriate screen.

#### Acceptance Criteria

1. WHEN get_current_state receives a session_id that exists in the database, THE Orchestrator SHALL read the session from the database and return the current state label as a string matching one of the 11 valid state constants from core/config.py
2. IF get_current_state is called with a session_id that does not exist in the database, THEN THE Orchestrator SHALL raise a ValueError indicating session not found
3. THE Orchestrator SHALL return only the state string value without modifying the session state (pure read operation with no side effects)
4. IF get_current_state is called with a session_id that is None or empty string, THEN THE Orchestrator SHALL raise a ValueError indicating invalid session_id

### Requirement 6: State Machine Transition Enforcement

**User Story:** As a developer, I want the orchestrator to enforce valid state transitions, so that sessions never reach an inconsistent or undefined state.

#### Acceptance Criteria

1. THE Orchestrator SHALL only permit transitions that follow the defined forward order: SETUP → RESEARCHING → GENERATING → READY → ASKING → EVALUATING → FOLLOW_UP → NEXT_Q → REPORT → DONE, with the following exceptions: NEXT_Q may transition back to ASKING (to cycle through all 10 questions), EVALUATING may transition directly to NEXT_Q (when no follow-up is triggered), and ERROR is reachable from any state
2. WHEN a state transition passes validation, THE Orchestrator SHALL log it to the console in the exact format: `[Orchestrator] {old_state} → {new_state}` before any other side effects of the new state execute
3. IF the Orchestrator receives a transition request that does not match any permitted transition (excluding transitions to STATE_ERROR), THEN THE Orchestrator SHALL raise a ValueError whose message contains both the current state name and the requested target state name, and SHALL NOT modify the session state in the database
4. WHEN a state transition passes validation, THE Orchestrator SHALL update the session's state field in the database synchronously within the same function call, before the transition method returns control to the caller
5. WHILE a session is in STATE_ERROR or STATE_DONE, THE Orchestrator SHALL raise a ValueError indicating the session is in a terminal state for any transition request, while still permitting read-only access to the current state via get_current_state

### Requirement 7: Agent Output Contract Validation

**User Story:** As a developer, I want all agent outputs validated before the orchestrator acts on them, so that corrupted or hallucinated data never persists to the database.

#### Acceptance Criteria

1. WHEN Researcher_Agent returns a value, THE Orchestrator SHALL verify that the value is a dict containing all 8 required keys (company, role, interview_rounds, key_topics, difficulty, culture_keywords, known_question_types, red_flags_to_test) before calling save_research
2. WHEN QuestionGenerator_Agent returns a value, THE Orchestrator SHALL verify that the value is a list containing exactly TOTAL_QUESTIONS items, where each item is a dict containing all 7 required keys (id, category, question, ideal_keywords, difficulty, follow_ups, scoring_hint), before proceeding
3. WHEN Evaluator_Agent returns a value, THE Orchestrator SHALL verify that the value is a dict containing all 6 required keys (scores, total, verdict, feedback, missing_keywords, trigger_follow_up), that scores is a dict with exactly 4 integer-valued keys (relevance, depth, structure, examples) each in range 1 to 5, that total is an integer in range 4 to 20, that verdict is one of "weak", "good", or "strong", that missing_keywords is a list, and that trigger_follow_up is a boolean, before acting on it
4. WHEN Coach_Agent returns a value, THE Orchestrator SHALL verify that the value is a dict containing all 11 required keys (overall_score, hiring_probability, hiring_probability_percent, strongest_category, weakest_category, category_averages, top_3_strengths, top_3_improvements, critical_moment, overall_verdict, next_interview_tip) before calling save_report
5. IF any agent returns a value that is not the expected type (dict or list) or that fails contract validation due to missing keys or invalid value types, THEN THE Orchestrator SHALL transition the session to STATE_ERROR with a reason string that includes the agent name and a description of which keys were missing or which values had invalid types
6. THE Orchestrator SHALL complete all contract validation checks for an agent's output before invoking any database persistence function (save_research, save_questions, save_report) for that output

### Requirement 8: Error Handling and STATE_ERROR Transitions

**User Story:** As a developer, I want all agent failures caught and stored in a terminal error state, so that sessions fail gracefully and the reason is always diagnosable.

#### Acceptance Criteria

1. IF any agent (Researcher, QuestionGenerator, Evaluator, Coach) raises an exception during execution, THEN THE Orchestrator SHALL catch the exception, transition the session to STATE_ERROR from whatever state it is currently in, and store the error reason as a string of at most 500 characters (truncating if necessary)
2. IF an agent returns output that fails JSON contract validation (missing required keys or incorrect value types as defined per agent contract), THEN THE Orchestrator SHALL transition the session to STATE_ERROR with a reason string that identifies the agent name and the specific validation failure
3. WHEN a session transitions to STATE_ERROR, THE Orchestrator SHALL persist the error reason to the session record so that callers can retrieve it via get_current_state
4. WHILE a session is in STATE_ERROR, THE Orchestrator SHALL refuse all API calls except get_current_state, raising a ValueError with a message that includes the stored error reason string
5. IF Researcher_Agent falls back to the default dict (error_flag=True), THEN THE Orchestrator SHALL NOT transition to STATE_ERROR; it SHALL proceed to the next state (GENERATING) using the default research data as valid input
6. IF persisting the error reason to the database fails (e.g., database write error), THEN THE Orchestrator SHALL log the persistence failure to stdout and ensure the session is still treated as errored in the current call flow

### Requirement 9: Input Validation for All Public Functions

**User Story:** As a developer, I want all inputs validated at the orchestrator boundary, so that invalid data never reaches agents or the database.

#### Acceptance Criteria

1. WHEN start_session receives company, role, or level that is empty or contains only whitespace after stripping, THE Orchestrator SHALL raise a ValueError with a message identifying which parameter is invalid
2. WHEN start_session receives company or role that exceeds 200 characters after stripping, THE Orchestrator SHALL raise a ValueError indicating which parameter is too long and the 200-character maximum
3. WHEN submit_answer receives answer_text that is empty or contains only whitespace after stripping, THE Orchestrator SHALL raise a ValueError indicating the answer text is invalid (the Evaluator handles short-but-nonempty answers below MIN_ANSWER_LENGTH characters via the penalty path)
4. WHEN any public function (get_current_question, submit_answer, generate_final_report, get_current_state) receives a session_id that does not correspond to an existing session in the database, THE Orchestrator SHALL raise a ValueError indicating session not found
5. THE Orchestrator SHALL perform all input validation checks before making any state transitions, agent calls, or database writes, ensuring the session state remains unchanged when invalid inputs are rejected

### Requirement 10: Rate Limiting Between LLM Calls

**User Story:** As a developer, I want the orchestrator to respect Gemini API rate limits, so that the system avoids 429 throttling errors.

#### Acceptance Criteria

1. THE Orchestrator SHALL ensure that at least RATE_LIMIT_SLEEP seconds (as defined in `core/config.py`) elapse between the completion of one LLM-adjacent agent call and the start of the next LLM-adjacent agent call within the same session flow
2. WHEN a Gemini 429 rate-limit error propagates up from an agent call, THE Orchestrator SHALL wait ERROR_RETRY_SLEEP seconds (as defined in `core/config.py`) and then retry the same agent call a maximum of 2 times before transitioning to STATE_ERROR
3. IF the Orchestrator exhausts all 2 retry attempts for a 429 error without success, THEN THE Orchestrator SHALL transition to STATE_ERROR and cease further agent calls for that session
4. THE Orchestrator SHALL use only RATE_LIMIT_SLEEP and ERROR_RETRY_SLEEP from `core/config.py` for all timing values, with no hardcoded numeric sleep durations anywhere in the orchestrator module

### Requirement 11: Concurrency and Statelessness

**User Story:** As a developer, I want the orchestrator to support multiple concurrent sessions without data leakage, so that the system is safe for multi-user deployment.

#### Acceptance Criteria

1. THE Orchestrator SHALL maintain no module-level mutable state (no global variables, no caches, no session dictionaries); immutable module-level constants (as defined in config.py) and function definitions are permitted
2. WHEN any public function is called, THE Orchestrator SHALL accept session_id as a required parameter and read the current session row from the database before executing any business logic, ensuring it operates on the latest persisted state
3. IF a public function is called with a session_id that does not exist in the database, THEN THE Orchestrator SHALL raise a ValueError indicating the session was not found, without modifying any stored data
4. THE Orchestrator SHALL not store any inter-call state between function invocations; each call SHALL derive its complete execution context solely from the session_id parameter and corresponding database lookups, making every call independently re-entrant
5. WHEN two or more sessions execute concurrently, THE Orchestrator SHALL scope all database reads and writes to the provided session_id such that no function call returns, modifies, or overwrites data belonging to a different session_id

### Requirement 12: Configuration and Constants Usage

**User Story:** As a developer, I want the orchestrator to use only named constants from config.py, so that no hardcoded literals exist in the coordination logic.

#### Acceptance Criteria

1. THE Orchestrator SHALL import and use STATE_SETUP, STATE_RESEARCHING, STATE_GENERATING, STATE_READY, STATE_ASKING, STATE_EVALUATING, STATE_FOLLOW_UP, STATE_NEXT_Q, STATE_REPORT, STATE_DONE, and STATE_ERROR from `core/config.py` for every state comparison, state assignment, and state transition log within the module
2. THE Orchestrator SHALL import and use TOTAL_QUESTIONS, MAX_FOLLOW_UPS, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, and GEMINI_API_KEY from `core/config.py` for all numeric thresholds, sleep durations, and configuration values
3. THE Orchestrator SHALL contain no hardcoded numeric literals for question counts, follow-up limits, sleep durations, or input length limits, with the sole exception of the input max-length boundary (200 characters) which SHALL be defined as a module-level constant named in UPPER_SNAKE_CASE (e.g., MAX_INPUT_LENGTH) at the top of the orchestrator module
4. IF a constant required by the orchestrator does not exist in `core/config.py`, THEN THE Orchestrator SHALL define it as a module-level UPPER_SNAKE_CASE constant at the top of its own module rather than embedding a literal inline

### Requirement 13: MVC Separation Compliance

**User Story:** As a developer, I want clear separation between UI, orchestrator, and agents, so that the architecture remains maintainable and testable.

#### Acceptance Criteria

1. THE Orchestrator SHALL import and call functions exclusively from `agents/researcher.py`, `agents/question_generator.py`, `agents/evaluator.py`, and `agents/coach.py` for all agent-related operations, and SHALL NOT define any LLM call logic or prompt construction within its own module
2. THE Orchestrator SHALL import and call functions exclusively from `core/database.py` for all persistence operations, using only the public API exposed by that module (init_db, create_session, get_session, save_research, save_questions, save_answer, get_answers, save_report)
3. THE Orchestrator SHALL NOT import from `ui/` or any Streamlit-related module (including `streamlit`, `st`, or any `streamlit.*` subpackage)
4. THE Orchestrator SHALL NOT perform any direct SQLite operations — specifically no `import sqlite3`, no raw SQL strings, and no direct `sqlite3.Connection` or `sqlite3.Cursor` usage — all database access SHALL go through `core/database.py` functions
5. THE Orchestrator SHALL be permitted to import from `core/config.py` for constants and configuration values, and from Python standard library modules (uuid, json, time, datetime), without violating the separation constraints

### Requirement 14: Duplicate and Out-of-Order Submission Prevention

**User Story:** As a developer, I want the orchestrator to reject duplicate or out-of-order answer submissions, so that evaluation integrity is preserved.

#### Acceptance Criteria

1. WHEN submit_answer is called for a q_index that already has a persisted answer in the answers table for that session_id, THE Orchestrator SHALL raise a ValueError whose message includes the duplicate q_index value
2. IF submit_answer is called with a q_index that does not equal the number of answers already persisted for that session_id, THEN THE Orchestrator SHALL raise a ValueError whose message includes both the submitted q_index and the expected next index
3. THE Orchestrator SHALL determine the expected next question index as the count of rows in the answers table for the given session_id, queried at the time submit_answer is invoked
4. IF submit_answer is called with a q_index less than 0 or greater than or equal to TOTAL_QUESTIONS, THEN THE Orchestrator SHALL raise a ValueError indicating the q_index is outside the valid range of 0 to TOTAL_QUESTIONS minus 1

### Requirement 15: Follow-Up Question Tracking

**User Story:** As a developer, I want follow-up counts tracked per question, so that the MAX_FOLLOW_UPS limit is enforced correctly across multiple follow-up rounds.

#### Acceptance Criteria

1. THE Orchestrator SHALL maintain a per-question follow-up counter initialized to 0, incrementing the counter by 1 immediately after each follow-up question is presented to the user
2. WHEN the follow-up counter for the current question equals MAX_FOLLOW_UPS (2), THE Orchestrator SHALL skip follow-up presentation and transition to STATE_NEXT_Q (or STATE_REPORT if the current question index equals TOTAL_QUESTIONS minus 1) regardless of the trigger_follow_up value returned by the Evaluator
3. WHEN the session advances to the next question (STATE_NEXT_Q → STATE_ASKING), THE Orchestrator SHALL reset the follow-up counter to 0 for the new question
4. WHEN the Evaluator returns trigger_follow_up as True and the follow-up counter is less than MAX_FOLLOW_UPS, THE Orchestrator SHALL pass the current follow-up counter value as the zero-based index argument to get_follow_up_question to retrieve the corresponding entry from the Question_Dict's follow_ups list
5. WHEN the session first enters STATE_ASKING for question index 0, THE Orchestrator SHALL initialize the follow-up counter to 0

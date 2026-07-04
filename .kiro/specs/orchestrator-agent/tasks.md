# Implementation Plan: Orchestrator Agent

## Overview

Implement `agents/orchestrator.py` as the central state machine controller that sequences calls to existing agents (Researcher, QuestionGenerator, Evaluator, Coach), enforces state transitions, validates agent output contracts, handles errors, and persists all state to SQLite via `core/database.py`. The implementation also extends `core/database.py` with three new functions and a new table required by the orchestrator.

## Tasks

- [x] 1. Extend database layer with orchestrator-required functions and schema
  - [x] 1.1 Add `update_session_state`, `get_question`, `get_report` functions to `core/database.py`
    - Add `update_session_state(session_id: str, new_state: str) -> None` that executes `UPDATE sessions SET state = ? WHERE session_id = ?` and raises ValueError if rowcount is 0
    - Add `get_question(session_id: str, q_index: int) -> dict | None` that retrieves and JSON-deserializes a single question by session_id and q_index
    - Add `get_report(session_id: str) -> dict | None` that retrieves and JSON-deserializes the saved report for a session
    - _Requirements: 6.4, 2.1, 4.3_

  - [x] 1.2 Add `follow_up_tracking` table and helper functions to `core/database.py`
    - Add `CREATE TABLE IF NOT EXISTS follow_up_tracking (session_id TEXT NOT NULL, q_index INTEGER NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (session_id, q_index))` to `init_db()`
    - Add `get_follow_up_count(session_id: str, q_index: int) -> int` that returns the current follow-up count (0 if no row)
    - Add `increment_follow_up_count(session_id: str, q_index: int) -> None` that inserts or increments the count
    - Add `reset_follow_up_count(session_id: str, q_index: int) -> None` that sets count to 0 (or is a no-op for new questions)
    - _Requirements: 15.1, 15.3, 15.4, 15.5_

- [x] 2. Implement orchestrator module constants, imports, and private helpers
  - [x] 2.1 Create `agents/orchestrator.py` with module constants, imports, and transition map
    - Create file with imports from `core/config.py` (all STATE_* constants, TOTAL_QUESTIONS, MAX_FOLLOW_UPS, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, GEMINI_API_KEY)
    - Import from `core/database.py` (create_session, get_session, save_research, save_questions, save_answer, get_answers, save_report, update_session_state, get_question, get_report, get_follow_up_count, increment_follow_up_count)
    - Import from agent modules (research_company, generate_questions, QuestionGenerationError, evaluate_answer, get_follow_up_question, generate_report)
    - Import stdlib: uuid, time, json
    - Define module-level constants: MAX_INPUT_LENGTH = 200, MAX_ERROR_REASON_LENGTH = 500, MAX_RETRIES = 2
    - Define `_VALID_TRANSITIONS` dict mapping each state to its set of permitted target states
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 13.1, 13.2, 13.4, 13.5_

  - [x] 2.2 Implement `_validate_session_exists`, `_validate_not_terminal`, and `_transition` helpers
    - `_validate_session_exists(session_id: str) -> dict`: raise ValueError if session_id is empty/None or session not found in DB
    - `_validate_not_terminal(session: dict) -> None`: raise ValueError if state is STATE_DONE or STATE_ERROR
    - `_transition(session_id: str, current_state: str, new_state: str) -> None`: check _VALID_TRANSITIONS, raise ValueError with both state names if invalid, print log in format `[Orchestrator] {current_state} → {new_state}`, call update_session_state
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 9.4, 11.3_

  - [x] 2.3 Implement `_handle_error` and `_call_with_retry` helpers
    - `_handle_error(session_id: str, reason: str) -> None`: truncate reason to MAX_ERROR_REASON_LENGTH, call update_session_state to STATE_ERROR, catch DB exceptions and print to stdout
    - `_call_with_retry(agent_fn, args, session_id: str) -> Any`: try up to MAX_RETRIES+1 times, catch exceptions with "429" in str(e) and sleep ERROR_RETRY_SLEEP between retries, re-raise on final failure
    - _Requirements: 8.1, 8.3, 8.6, 10.2, 10.3, 10.4_

  - [x] 2.4 Implement contract validator functions
    - `_validate_research_dict(data)`: check dict type, check 8 required keys present
    - `_validate_questions_list(data)`: check list type, check length == TOTAL_QUESTIONS, check each item is dict with 7 required keys
    - `_validate_evaluation_dict(data)`: check dict type, 6 required keys, scores is dict with 4 int keys (1-5 each), total is int 4-20, verdict in {"weak","good","strong"}, missing_keywords is list, trigger_follow_up is bool
    - `_validate_report_dict(data)`: check dict type, 11 required keys present
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [x] 3. Implement public API functions
  - [x] 3.1 Implement `start_session(company: str, role: str, level: str) -> str`
    - Validate GEMINI_API_KEY is non-empty (raise ValueError if not)
    - Validate company, role, level: strip → must be non-empty and ≤ MAX_INPUT_LENGTH (raise ValueError identifying which param is invalid)
    - Generate session_id via uuid.uuid4(), call create_session
    - Transition SETUP → RESEARCHING, call research_company with retry, validate, save_research
    - Sleep RATE_LIMIT_SLEEP
    - Transition RESEARCHING → GENERATING, call generate_questions with retry, validate, save_questions
    - Transition GENERATING → READY, return session_id
    - Wrap agent calls in try/except: on failure call _handle_error and re-raise
    - Handle QuestionGenerationError specifically: transition to ERROR and re-raise
    - Researcher error_flag=True proceeds normally (no special handling)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 9.1, 9.2, 9.5, 10.1_

  - [x] 3.2 Implement `get_current_question(session_id: str) -> dict`
    - Call _validate_session_exists and _validate_not_terminal
    - Validate state is in (STATE_READY, STATE_ASKING, STATE_NEXT_Q), else raise ValueError
    - Determine q_index from len(get_answers(session_id))
    - If q_index >= TOTAL_QUESTIONS: raise ValueError "no more questions"
    - If state is STATE_READY or STATE_NEXT_Q: transition to STATE_ASKING
    - If already STATE_ASKING: no transition (idempotent)
    - Retrieve Question_Dict via get_question(session_id, q_index)
    - Return dict with exactly 7 Question_Dict keys
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 3.3 Implement `submit_answer(session_id: str, answer_text: str) -> dict`
    - Validate answer_text: strip → must be non-empty (raise ValueError if whitespace-only)
    - Call _validate_session_exists and _validate_not_terminal
    - Validate state is in (STATE_ASKING, STATE_FOLLOW_UP), else raise ValueError "not expecting answer"
    - Determine q_index from answer count, check for duplicate submission
    - Transition to STATE_EVALUATING
    - Retrieve current Question_Dict, call evaluate_answer with retry, validate evaluation
    - Call save_answer with the evaluation
    - Determine next state based on trigger_follow_up, follow_up_count (from DB), and question position
    - If trigger=True and count < MAX_FOLLOW_UPS: call get_follow_up_question, if non-None transition to FOLLOW_UP and increment_follow_up_count
    - If follow-up is None or count >= MAX: transition to NEXT_Q (or REPORT if last Q)
    - If trigger=False: transition to NEXT_Q (or REPORT if last Q)
    - Return evaluation dict with optional "follow_up_question" key
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 14.1, 14.2, 14.3, 14.4, 15.1, 15.2, 15.4_

  - [x] 3.4 Implement `generate_final_report(session_id: str) -> dict`
    - Call _validate_session_exists
    - If STATE_DONE and report exists via get_report: return cached (idempotent)
    - Call _validate_not_terminal
    - Verify len(get_answers) == TOTAL_QUESTIONS, else raise ValueError with missing count
    - Transition to STATE_REPORT
    - Call generate_report with retry, validate with _validate_report_dict
    - Strip extra keys: keep only 11 required keys
    - Call save_report, transition to STATE_DONE, return report
    - On failure: _handle_error and raise
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 3.5 Implement `get_current_state(session_id: str) -> str`
    - Validate session_id is non-None and non-empty (raise ValueError if invalid)
    - Call _validate_session_exists
    - Return session["state"] without any side effects
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Unit tests for orchestrator
  - [x] 5.1 Write unit tests for input validation and session creation in `tests/test_orchestrator.py`
    - Test start_session happy path with mocked agents (end-to-end flow returns session_id)
    - Test empty/whitespace/too-long company/role/level raises ValueError
    - Test empty GEMINI_API_KEY raises ValueError
    - Test Researcher error_flag=True proceeds normally
    - Test QuestionGenerationError transitions to STATE_ERROR and re-raises
    - Mock all agent calls and database functions
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9_

  - [x] 5.2 Write unit tests for get_current_question in `tests/test_orchestrator.py`
    - Test STATE_READY transitions to STATE_ASKING and returns first question
    - Test STATE_NEXT_Q transitions to STATE_ASKING and returns next question
    - Test STATE_ASKING is idempotent (no transition, same question returned)
    - Test non-existent session_id raises ValueError
    - Test terminal state (DONE/ERROR) raises ValueError
    - Test all questions answered raises ValueError
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [x] 5.3 Write unit tests for submit_answer in `tests/test_orchestrator.py`
    - Test happy path: evaluation returned, state transitions correctly
    - Test follow-up triggered with count < MAX_FOLLOW_UPS returns follow_up_question
    - Test follow-up at MAX_FOLLOW_UPS skips follow-up, transitions to NEXT_Q
    - Test trigger_follow_up=True on last question enters FOLLOW_UP
    - Test Follow_Up_Function returning None falls through to NEXT_Q
    - Test whitespace-only answer_text raises ValueError
    - Test duplicate submission raises ValueError
    - Test wrong state raises ValueError
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.9, 3.10, 3.11, 14.1, 14.2_

  - [x] 5.4 Write unit tests for generate_final_report and get_current_state in `tests/test_orchestrator.py`
    - Test report generation happy path
    - Test idempotent return when STATE_DONE
    - Test incomplete session raises ValueError with missing count
    - Test Coach_Agent failure transitions to STATE_ERROR
    - Test extra report keys are stripped
    - Test get_current_state returns state string without side effects
    - Test get_current_state with None/empty session_id raises ValueError
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 5.1, 5.2, 5.3, 5.4_

- [ ] 6. Property-based tests with Hypothesis
  - [ ]* 6.1 Write property test: Input validation rejects invalid strings without side effects
    - **Property 1: Input validation rejects invalid strings without side effects**
    - Generate random strings that are empty, whitespace-only, or exceed MAX_INPUT_LENGTH after stripping
    - Verify ValueError raised and no session created in DB
    - **Validates: Requirements 1.4, 1.5, 1.6, 9.1, 9.2, 9.5**

  - [ ]* 6.2 Write property test: Non-existent session_id raises ValueError
    - **Property 2: Non-existent session_id raises ValueError across all public functions**
    - Generate random UUID strings not in DB
    - Verify all four session-scoped functions raise ValueError with no DB modifications
    - **Validates: Requirements 2.5, 3.7, 4.5, 5.2, 9.4, 11.3**

  - [ ]* 6.3 Write property test: State transition validity
    - **Property 3: State transition validity is determined exclusively by the transitions map**
    - Generate all (current_state, target_state) pairs
    - Verify _transition succeeds iff target is in valid set; invalid raises ValueError with both state names
    - **Validates: Requirements 6.1, 6.3, 6.4, 6.5**

  - [ ]* 6.4 Write property test: Agent output contract validation catches missing keys
    - **Property 4: Agent output contract validation catches all missing keys**
    - Generate dicts with random subsets of required keys (missing at least one)
    - Verify validation function raises ValueError with agent name and missing keys info
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 8.2**

  - [ ]* 6.5 Write property test: Evaluation outcome determines correct next state
    - **Property 5: Evaluation outcome determines correct next state**
    - Generate (trigger_follow_up, follow_up_count, q_index) tuples
    - Verify the orchestrator transitions to the correct state per the branching logic
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.6, 15.2**

  - [ ]* 6.6 Write property test: Duplicate and out-of-order submissions rejected
    - **Property 6: Duplicate and out-of-order submissions are rejected**
    - Generate (answer_count N, submitted q_index != N) pairs
    - Verify ValueError raised with both indices in message, no DB write
    - **Validates: Requirements 3.9, 14.1, 14.2, 14.4**

  - [ ]* 6.7 Write property test: Agent exceptions transition to STATE_ERROR with truncated reason
    - **Property 7: Agent exceptions transition to STATE_ERROR with truncated reason**
    - Generate random exception messages of varying lengths
    - Verify session transitions to STATE_ERROR with reason ≤ 500 chars stored in DB
    - **Validates: Requirements 8.1, 8.3**

  - [ ]* 6.8 Write property test: get_current_state is a pure read operation
    - **Property 8: get_current_state is a pure read operation**
    - Generate sessions in all 11 valid states
    - Verify get_current_state returns correct label and state in DB is unchanged after call
    - **Validates: Requirements 5.1, 5.3**

  - [ ]* 6.9 Write property test: get_current_question is idempotent in STATE_ASKING
    - **Property 9: get_current_question is idempotent in STATE_ASKING**
    - Generate sessions in STATE_ASKING with N answers (0 ≤ N < TOTAL_QUESTIONS)
    - Call get_current_question multiple times, verify same dict returned and state unchanged
    - **Validates: Requirements 2.4, 2.8**

  - [ ]* 6.10 Write property test: Follow-up counter resets on question advance
    - **Property 10: Follow-up counter resets on question advance**
    - Generate sequences where follow-ups are exhausted then question advances
    - Verify counter is 0 for new question
    - **Validates: Requirements 15.1, 15.3, 15.4**

  - [ ]* 6.11 Write property test: Report generation is idempotent once STATE_DONE
    - **Property 11: Report generation is idempotent once STATE_DONE**
    - Generate sessions in STATE_DONE with saved report
    - Call generate_final_report twice, verify same report returned without Coach_Agent call
    - **Validates: Requirements 4.3**

  - [ ]* 6.12 Write property test: Extra report keys are stripped
    - **Property 12: Extra report keys are stripped**
    - Generate Report_Dicts with 11 required keys plus random extra keys
    - Verify returned dict has exactly 11 keys with no extras
    - **Validates: Requirements 4.7**

  - [ ]* 6.13 Write property test: Rate limiting between LLM calls
    - **Property 13: Rate limiting between LLM calls**
    - Mock time.sleep, run start_session with mocked agents
    - Verify time.sleep(RATE_LIMIT_SLEEP) called between consecutive agent calls
    - **Validates: Requirements 10.1, 10.4**

  - [ ]* 6.14 Write property test: Whitespace-only answer text is rejected
    - **Property 14: Whitespace-only answer text is rejected**
    - Generate strings composed entirely of whitespace characters (spaces, tabs, newlines)
    - Verify submit_answer raises ValueError and no answer persisted
    - **Validates: Requirements 9.3**

  - [ ]* 6.15 Write property test: Session isolation under concurrent access
    - **Property 15: Session isolation under concurrent access**
    - Generate pairs of distinct session_ids with separate data
    - Verify operations on one session never read/write data from the other
    - **Validates: Requirements 11.5**

  - [ ]* 6.16 Write property test: Incomplete sessions reject report generation
    - **Property 16: Incomplete sessions reject report generation**
    - Generate answer counts 0-9 (less than TOTAL_QUESTIONS)
    - Verify generate_final_report raises ValueError indicating missing count
    - **Validates: Requirements 4.2**

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific example scenarios and edge cases
- All agent calls are mocked in tests — no real Gemini API calls during testing
- The `agents/coach.py` module is assumed to exist (stubbed) with `generate_report` function
- Database extensions (task 1) must be completed before orchestrator implementation (tasks 2-3)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["3.1", "3.5"] },
    { "id": 4, "tasks": ["3.2", "3.4"] },
    { "id": 5, "tasks": ["3.3"] },
    { "id": 6, "tasks": ["5.1", "5.2", "5.4"] },
    { "id": 7, "tasks": ["5.3"] },
    { "id": 8, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.7", "6.8", "6.13", "6.14", "6.16"] },
    { "id": 9, "tasks": ["6.5", "6.6", "6.9", "6.10", "6.11", "6.12", "6.15"] }
  ]
}
```

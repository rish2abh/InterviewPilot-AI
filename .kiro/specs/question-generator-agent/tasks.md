# Implementation Plan

## Overview

Implementation tasks for `agents/question_generator.py`. The implementation already exists — these tasks drive the test suite creation and verification that the code satisfies every requirement and correctness property documented in `design.md`.

Tasks are grouped into three phases:
1. **Implementation verification** — confirm the existing code satisfies all requirements
2. **Unit tests** — specific boundary and error-path tests in `tests/test_question_generator.py`
3. **Property-based tests** — Hypothesis tests for the 10 correctness properties

---

## Tasks

- [x] 1. Verify core module structure and exception definition
  - Confirm `QuestionGenerationError` is defined in `agents/question_generator.py` as a subclass of `Exception`
  - Confirm it has a `message: str` attribute set via `__init__`
  - Confirm `str(exc)` returns the same text as `exc.message`
  - Confirm all imports are from the approved library list only: `json`, `re`, `time`, `uuid`, `google.generativeai`, and `core.config` / `core.database`
  - Confirm no hardcoded numeric literals exist — all values reference named constants from `core.config`
  - **Requirement**: 9.4, 10.5

- [x] 2. Verify `_safe_llm_call` follows the canonical template
  - Confirm 2-attempt loop structure
  - Confirm `JSONDecodeError` at attempt 0 → sleep `RATE_LIMIT_SLEEP` → append corrective instruction → retry
  - Confirm `JSONDecodeError` at attempt 1 → raise `QuestionGenerationError` with "JSON parse failure" in message
  - Confirm non-JSON `Exception` at attempt 0 → sleep `ERROR_RETRY_SLEEP` → retry
  - Confirm non-JSON `Exception` at attempt 1 → raise `QuestionGenerationError` with original error text
  - Confirm stdout log format: `[QuestionGenerator] Success. Tokens: {usage_metadata}`
  - Confirm markdown stripping via `re.sub(r'```json\s*', '', text)` and `re.sub(r'```\s*', '', text)`
  - **Requirement**: 9.1, 9.5, 10.3

- [x] 3. Verify `validate_questions` covers all 11 checks
  - Confirm check order matches design: count → dict type → keys → id → category → question length → ideal_keywords → difficulty → follow_ups type → scoring_hint → distribution
  - Confirm returns `(False, reason)` for each failing check with a descriptive reason string
  - Confirm returns `(True, "")` when all checks pass
  - Confirm category check is exact case-sensitive match against `{"technical", "behavioral", "situational", "curveball"}`
  - Confirm distribution check uses `_REQUIRED_DISTRIBUTION = {technical:4, behavioral:3, situational:2, curveball:1}`
  - **Requirement**: 2.3, 2.5, 4.1–4.3, 9.2, 9.3

- [x] 4. Verify `generate_questions` pipeline steps 1–4
  - Confirm Step 1 raises `QuestionGenerationError` for each missing required research key
  - Confirm Step 1 raises `QuestionGenerationError` for empty or whitespace-only `api_key`
  - Confirm Step 2 calls `time.sleep(RATE_LIMIT_SLEEP)` unconditionally before any LLM call
  - Confirm Step 3 compresses via `json.dumps(research_data, separators=(',',':'))`
  - Confirm Step 4 uses `genai.GenerativeModel(model_name=GEMINI_MODEL)` with no search grounding tools
  - Confirm `SYSTEM_PROMPT.format(total=TOTAL_QUESTIONS)` is used as the system instruction
  - Confirm `error_flag=True` produces a `user_prompt` that does NOT contain `research_data["company"]`
  - **Requirement**: 1.2, 1.4, 1.6, 8.2, 10.1, 10.6

- [x] 5. Verify `generate_questions` pipeline steps 5–6 (retry loop)
  - Confirm the outer loop runs at most 2 times (`for attempt in range(2)`)
  - Confirm `time.sleep(RATE_LIMIT_SLEEP)` is called at the start of attempt 1 (retry)
  - Confirm missing `"questions"` key triggers retry at attempt 0 with corrective prompt appended
  - Confirm wrong question count triggers retry at attempt 0 with count-correction prompt appended
  - Confirm `validate_questions` failure triggers retry at attempt 0 with validation-correction prompt appended
  - Confirm all three failure types at attempt 1 raise `QuestionGenerationError`
  - **Requirement**: 4.4, 4.5, 4.6, 6.1–6.4, 2.2, 2.4

- [x] 6. Verify `_assign_ids_and_difficulties` post-processing
  - Confirm every `id` is overwritten with `str(uuid.uuid4())` regardless of LLM-returned value
  - Confirm `difficulty` for question at index `i` (0-based) is set to `i + 1`
  - Confirm the list is mutated in-place and returned
  - **Requirement**: 1.5, 3.2, 3.4

- [x] 7. Verify `_normalize_follow_ups` normalization logic
  - Confirm non-list `follow_ups` is replaced entirely with fallback items
  - Confirm invalid items (non-string or empty string) are replaced with category-appropriate fallbacks
  - Confirm lists shorter than `FOLLOW_UP_COUNT` are padded to exactly `FOLLOW_UP_COUNT`
  - Confirm lists longer than `FOLLOW_UP_COUNT` are trimmed to exactly `FOLLOW_UP_COUNT` (first entries kept)
  - Confirm fallback lookup uses `_FALLBACK_FOLLOW_UPS[category]` with `"technical"` as default for unknown categories
  - Confirm normalization is applied after `validate_questions` passes and before `save_questions`
  - **Requirement**: 5.1–5.5

- [x] 8. Verify database persistence step
  - Confirm `save_questions(session_id, questions)` is called with all `TOTAL_QUESTIONS` validated questions
  - Confirm it is called before the function returns
  - Confirm any exception from `save_questions` is caught and re-raised as `QuestionGenerationError` with "database write failed" in message
  - **Requirement**: 7.1–7.3, 7.5

- [x] 9. Write unit tests — `QuestionGenerationError` and input validation
  - File: `tests/test_question_generator.py`
  - Test: `QuestionGenerationError` is a subclass of `Exception`
  - Test: `exc.message` equals `str(exc)` for any message string
  - Test: missing each of the 8 required research keys individually raises `QuestionGenerationError`
  - Test: `api_key=""` raises `QuestionGenerationError` before `time.sleep` is called
  - Test: `api_key="   "` (whitespace-only) raises `QuestionGenerationError`
  - Test: valid inputs do not raise during input validation phase (requires mock for LLM + db)
  - **Requirement**: 1.6, 9.4

- [ ] 10. Write unit tests — `_safe_llm_call` retry behaviour
  - Test: invalid JSON on attempt 0 → `time.sleep(RATE_LIMIT_SLEEP)` → corrective text appended to prompt → retry succeeds
  - Test: invalid JSON on both attempts → `QuestionGenerationError` raised with "JSON parse failure"
  - Test: API exception on attempt 0 → `time.sleep(ERROR_RETRY_SLEEP)` → retry succeeds
  - Test: API exception on both attempts → `QuestionGenerationError` raised with original error text
  - Test: successful call logs `"[QuestionGenerator] Success. Tokens:"` to stdout (capture with `capsys`)
  - Test: `max_output_tokens` is passed as `MAX_TOKENS_COMPLEX` (assert via `generate_content` mock call args)
  - **Requirement**: 1.3, 9.1, 9.5, 10.3

- [-] 11. Write unit tests — `validate_questions` boundary cases
  - Test: list of 9 questions → `(False, "Expected 10 questions, got 9")`
  - Test: list of 11 questions → `(False, ...)`
  - Test: question with `category="Technical"` (wrong case) → `(False, ...)`
  - Test: question with `question="short"` (4 chars < `MIN_QUESTION_LENGTH`) → `(False, ...)`
  - Test: question with `ideal_keywords=[]` → `(False, ...)`
  - Test: question with `difficulty=0` → `(False, ...)`
  - Test: question with `difficulty=11` → `(False, ...)`
  - Test: question with `scoring_hint=""` → `(False, ...)`
  - Test: valid 10-question list with correct distribution → `(True, "")`
  - Test: valid 10-question list with wrong distribution (e.g., 5 technical, 3 behavioral, 2 situational, 0 curveball) → `(False, ...)`
  - **Requirement**: 2.3, 2.5, 4.1–4.3

- [x] 12. Write unit tests — retry loop in `generate_questions`
  - Test: LLM returns 9 questions on attempt 0, 10 questions on attempt 1 → returns list of 10
  - Test: LLM always returns 9 questions → `QuestionGenerationError` raised
  - Test: LLM returns invalid category on attempt 0, valid on attempt 1 → returns list of 10
  - Test: LLM always returns invalid distribution → `QuestionGenerationError` raised
  - Test: `time.sleep(RATE_LIMIT_SLEEP)` is called twice when retry is triggered (once before attempt 0, once before attempt 1)
  - Test: corrective prompt text is appended when retrying wrong count
  - **Requirement**: 2.2, 2.4, 6.1–6.3

- [-] 13. Write unit tests — `_normalize_follow_ups`
  - Test: `follow_ups=[]` → padded to `["<technical fallback 0>", "<technical fallback 1>"]` for `category="technical"`
  - Test: `follow_ups=["valid follow-up question here"]` → padded with one fallback
  - Test: `follow_ups=["q1", "q2", "q3", "q4", "q5"]` → trimmed to `["q1", "q2"]`
  - Test: `follow_ups=[None, "valid follow-up question here"]` → invalid item replaced with fallback, valid kept
  - Test: `follow_ups=["", "valid follow-up question here"]` → empty string replaced with fallback
  - Test: `follow_ups` not a list (e.g., `"string"`) → entire value replaced
  - Test: category `"behavioral"` uses behavioral fallback strings
  - Test: category `"situational"` uses situational fallback strings
  - Test: category `"curveball"` uses curveball fallback strings
  - Test: unrecognised category falls back to `"technical"` fallbacks
  - **Requirement**: 5.1–5.4

- [-] 14. Write unit tests — `_assign_ids_and_difficulties`
  - Test: LLM-returned `id="abc"` and `difficulty=7` → both overwritten; `id` is valid UUID4, `difficulty=1` for Q1
  - Test: all 10 questions get unique UUIDs (no duplicates)
  - Test: difficulties are exactly `[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]`
  - **Requirement**: 1.5, 3.2, 3.4

- [-] 15. Write unit tests — `error_flag` and database
  - Test: `error_flag=True` → company name NOT present anywhere in the prompt passed to `_safe_llm_call`
  - Test: `error_flag=False` → company name IS present in the prompt
  - Test: `error_flag` key absent → treated as False (no error raised)
  - Test: `save_questions` called exactly once with all 10 validated questions
  - Test: `save_questions` raises `sqlite3.Error` → `QuestionGenerationError` raised with "database write failed"
  - Test: `save_questions` called with correct `session_id`
  - **Requirement**: 7.1–7.3, 8.1–8.4

- [ ] 16. Write unit tests — system prompt and rate limit compliance
  - Test: `SYSTEM_PROMPT` ends with exact required suffix: `"Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."`
  - Test: `SYSTEM_PROMPT` contains `"questions"` key instruction
  - Test: `SYSTEM_PROMPT` contains the exact distribution: `"4 questions with category \"technical\""`, `"3 questions with category \"behavioral\""`, `"2 questions with category \"situational\""`, `"1 question with category \"curveball\""`
  - Test: `time.sleep` called with `RATE_LIMIT_SLEEP` as first call in `generate_questions` (before LLM)
  - Test: compressed research uses `separators=(',',':')` — assert no spaces in serialised output
  - **Requirement**: 1.2, 1.4, 10.1, 10.4, 10.6

- [~] 17. Write property-based test — P1: Output Count Invariant
  - Use `@given(st.integers(min_value=0, max_value=20))` for LLM-returned list length
  - Mock `_safe_llm_call` to return a questions list of the generated length with valid-except-count structure
  - Assert: result is either a list of exactly `TOTAL_QUESTIONS` dicts or `QuestionGenerationError` is raised
  - Assert: no other length is ever returned
  - Tag: `# Feature: question-generator-agent, Property 1: Output Count Invariant`
  - **Requirement**: 1.1, 6.1, 6.3

- [~] 18. Write property-based test — P2: Category Distribution Invariant
  - Use `st.lists(st.sampled_from(["technical", "behavioral", "situational", "curveball", "invalid"]))` for category lists
  - Mock `_safe_llm_call` to always return questions with the generated category mix
  - Assert: if a list is returned, its distribution exactly equals `_REQUIRED_DISTRIBUTION`
  - Assert: any non-conforming distribution results in `QuestionGenerationError` after retry
  - Tag: `# Feature: question-generator-agent, Property 2: Category Distribution Invariant`
  - **Requirement**: 2.1–2.4

- [~] 19. Write property-based test — P3: Difficulty Sequence Invariant
  - Use `st.lists(st.integers(min_value=-5, max_value=15), min_size=10, max_size=10)` for LLM-returned difficulties
  - Build a valid 10-question list with LLM-returned difficulty values, mock `_safe_llm_call`
  - Call `_assign_ids_and_difficulties` directly on the list
  - Assert: `questions[i]["difficulty"] == i + 1` for all `i` in `0..9`
  - Tag: `# Feature: question-generator-agent, Property 3: Difficulty Sequence Invariant`
  - **Requirement**: 3.2, 3.4

- [~] 20. Write property-based test — P4: Follow-Up Count Invariant
  - Use `st.lists(st.one_of(st.text(), st.none(), st.integers()), min_size=0, max_size=6)` for follow_ups
  - Use `st.sampled_from(["technical", "behavioral", "situational", "curveball"])` for category
  - Call `_normalize_follow_ups` directly on a question dict with generated follow_ups
  - Assert: `len(question["follow_ups"]) == FOLLOW_UP_COUNT`
  - Assert: all items in `follow_ups` are non-empty strings
  - Tag: `# Feature: question-generator-agent, Property 4: Follow-Up Count Invariant`
  - **Requirement**: 5.1–5.4

- [~] 21. Write property-based test — P5: UUID Identity Invariant
  - Use `st.text()` for LLM-returned id values (including empty, non-UUID, valid UUID strings)
  - Build a valid 10-question list with generated id values, call `_assign_ids_and_difficulties`
  - Assert: every `id` in the result matches UUID4 format (`re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', id)`)
  - Assert: no returned id matches any LLM-supplied id value
  - Tag: `# Feature: question-generator-agent, Property 5: UUID Identity Invariant`
  - **Requirement**: 1.5

- [~] 22. Write property-based test — P6: Compression Token Efficiency
  - Use `st.fixed_dictionaries({k: st.text() for k in REQUIRED_RESEARCH_KEYS})` for research_data
  - Capture the prompt passed to `_safe_llm_call` via mock side effect
  - Assert: prompt contains `json.dumps(research_data, separators=(',',':'))`
  - Assert: prompt does NOT contain `json.dumps(research_data)` (default with spaces)
  - Tag: `# Feature: question-generator-agent, Property 6: Compression Token Efficiency`
  - **Requirement**: 1.2

- [~] 23. Write property-based test — P7: Rate Limit Compliance
  - Use `st.booleans()` for whether retry is triggered (mock LLM to succeed or fail on first attempt)
  - Mock `time.sleep` and capture all calls
  - Assert: `time.sleep(RATE_LIMIT_SLEEP)` is always the first `time.sleep` call in any invocation
  - Assert: when retry is triggered, a second `time.sleep(RATE_LIMIT_SLEEP)` call is made
  - Tag: `# Feature: question-generator-agent, Property 7: Rate Limit Compliance`
  - **Requirement**: 1.4, 6.2

- [~] 24. Write property-based test — P8: Input Validation Completeness
  - Use `st.frozensets(st.sampled_from(list(REQUIRED_RESEARCH_KEYS)), min_size=1)` for key subsets to remove
  - For each non-empty subset of required keys: remove those keys from a valid research_data dict
  - Assert: `QuestionGenerationError` is raised before any `time.sleep` or LLM call
  - Use `st.text()` for api_key including empty and whitespace-only strings
  - Assert: empty / whitespace api_key also raises `QuestionGenerationError` before sleep
  - Tag: `# Feature: question-generator-agent, Property 8: Input Validation Completeness`
  - **Requirement**: 1.6, 9.1

- [~] 25. Write property-based test — P9: Database Persistence Completeness
  - Use `st.sampled_from([sqlite3.Error, ValueError, RuntimeError])` for exception type
  - Mock `save_questions` to raise the generated exception
  - Assert: `QuestionGenerationError` is raised (not the original exception type directly)
  - Assert: `"database write failed"` appears in the error message
  - Also assert the success path: mock `save_questions` to succeed, assert it was called with all 10 questions
  - Tag: `# Feature: question-generator-agent, Property 9: Database Persistence Completeness`
  - **Requirement**: 7.1–7.3

- [~] 26. Write property-based test — P10: Error Flag Isolation
  - Use `st.booleans()` for `error_flag`
  - Use `st.text(min_size=1)` for company name
  - Capture prompt via mock side effect on `_safe_llm_call`
  - Assert: when `error_flag=True`, company name is NOT a substring of the captured user_prompt
  - Assert: when `error_flag=False` (or absent), the output list has the same 7-key structure regardless
  - Tag: `# Feature: question-generator-agent, Property 10: Error Flag Isolation`
  - **Requirement**: 8.1–8.4

- [~] 27. Run the full test suite and confirm all tests pass
  - Run `pytest tests/test_question_generator.py -v` from the project root
  - Confirm 0 failures and 0 errors
  - Confirm all property tests complete `max_examples=100` without shrinking to a failure
  - If any test fails: fix the implementation in `agents/question_generator.py` to satisfy the failing assertion, then re-run
  - **Requirement**: all

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2", "3", "4", "5", "6", "7", "8"] },
    { "id": 1, "tasks": ["9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26"] },
    { "id": 2, "tasks": ["27"] }
  ]
}
```

Wave 0 — Implementation Verification (Tasks 1–8): all independent, run in any order.
Wave 1 — Unit Tests (Tasks 9–16) and Property-Based Tests (Tasks 17–26): depend on Wave 0 completion, can run in parallel with each other.
Wave 2 — Full Test Suite Run (Task 27): depends on all tasks in Waves 0 and 1.

---

## Notes

- All tasks target `agents/question_generator.py`. Do not modify any other agent file when working on these tasks.
- The implementation in `agents/question_generator.py` is assumed to already exist. Tasks 1–8 are read-only verification steps — no code changes are expected unless a discrepancy is found.
- All tests belong in `tests/test_question_generator.py`. Create the file during task 9 if it does not already exist.
- Property-based tests must use the **Hypothesis** library with `@settings(max_examples=100)` and be tagged with the comment format `# Feature: question-generator-agent, Property {N}: {property_text}`.
- All constants (`TOTAL_QUESTIONS`, `RATE_LIMIT_SLEEP`, `ERROR_RETRY_SLEEP`, `MAX_TOKENS_COMPLEX`, `MIN_QUESTION_LENGTH`, `FOLLOW_UP_COUNT`, `GEMINI_MODEL`) must be imported from `core.config` — never hardcoded in tests.
- Only libraries from the approved list in `tech.md` may be used. `unittest.mock` (stdlib) is permitted for mocking in tests.
- Task 27 is the integration gate: all 26 prior tasks must be complete before running the full suite.

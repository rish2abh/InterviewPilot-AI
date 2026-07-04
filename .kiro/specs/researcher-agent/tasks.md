# Implementation Plan: Researcher Agent

## Overview

Implementation tasks for `agents/researcher.py`. The implementation already exists — these tasks drive the test suite creation and verification that the code satisfies every requirement and correctness property documented in `design.md`.

Tasks are grouped into three phases:
1. **Implementation verification** — confirm the existing code satisfies all requirements
2. **Unit tests** — specific boundary and error-path tests in `tests/test_researcher.py`
3. **Property-based tests** — Hypothesis tests for the 6 correctness properties

---

## Tasks

- [x] 1. Verify core module structure and imports
  - Confirm `agents/researcher.py` imports only from the approved library list: `json`, `re`, `time`, `google.generativeai`, and `core.config`
  - Confirm it imports exactly `GEMINI_MODEL`, `MAX_TOKENS_COMPLEX`, `RATE_LIMIT_SLEEP`, `ERROR_RETRY_SLEEP` from `core.config`
  - Confirm no hardcoded numeric literals exist for token limits, sleep durations, or input length caps — all values reference named constants
  - Confirm module-level constants `_REQUIRED_KEYS`, `_LIST_KEYS`, `_STR_KEYS`, `_MAX_INPUT_LENGTH` are defined
  - Confirm search grounding is enabled via `tools="google_search_retrieval"` on the `GenerativeModel` constructor
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 9.4_

- [x] 2. Verify `_sanitize_input` logic
  - Confirm steps in order: strip → empty check (raise ValueError) → truncate to `_MAX_INPUT_LENGTH` → regex remove non-`[a-zA-Z0-9 \-]` → strip → empty check (raise ValueError)
  - Confirm the ValueError messages include the field name ("company" or "role") and the reason
  - Confirm the function returns the sanitized string on success
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [x] 3. Verify `_safe_llm_call` follows the canonical template
  - Confirm 2-attempt loop structure (`for attempt in range(2)`)
  - Confirm `JSONDecodeError` at attempt 0 → sleep `RATE_LIMIT_SLEEP` → append `"\n\nRETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."` → retry
  - Confirm `JSONDecodeError` at attempt 1 → raise `ValueError` with message `"Researcher failed after 2 attempts"`
  - Confirm non-JSON `Exception` at attempt 0 → sleep `ERROR_RETRY_SLEEP` → retry without prompt modification
  - Confirm non-JSON `Exception` at attempt 1 → re-raise original exception
  - Confirm stdout log format: `[Researcher] Success. Tokens: {response.usage_metadata}` on success
  - Confirm markdown stripping via `re.sub(r'```json\s*', '', text)` then `re.sub(r'```\s*', '', text)` then `.strip()`
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6, 8.1, 8.2, 8.3, 8.4, 4.1, 4.2, 4.3, 4.4_

- [x] 4. Verify `_validate_research_dict` validation checks
  - Confirm all 8 required keys checked for presence (raises ValueError listing missing keys)
  - Confirm string keys (`company`, `role`, `interview_rounds`, `difficulty`) validated as non-empty `str` after strip
  - Confirm list keys (`key_topics`, `culture_keywords`, `known_question_types`, `red_flags_to_test`) validated as non-empty `list` with every element being a non-empty `str`
  - Confirm `difficulty` must be one of: `"easy"`, `"medium"`, `"hard"`, `"expert"` (if not in current impl, flag as required fix)
  - Confirm extra keys are stripped — only the 8 required keys returned
  - _Requirements: 1.5, 2.1, 2.2, 2.3, 2.4, 2.6, 9.5_

- [x] 5. Verify `_build_default_dict` fallback logic
  - Confirm difficulty mapping: fresher→"easy", junior→"medium", senior→"hard", lead→"expert", manager→"expert", unknown→"medium"
  - Confirm key_topics uses 7 role-category branches (ML/AI, data, PM, DevOps, frontend, backend, generic fallback)
  - Confirm each branch provides exactly 5 topics
  - Confirm fixed defaults: `interview_rounds="3 rounds"`, `culture_keywords=["collaboration", "ownership"]`, `known_question_types=["coding", "behavioural"]`, `red_flags_to_test=["problem-solving approach", "communication clarity"]`
  - Confirm `error_flag=True` is always present in the returned dict
  - Confirm the total key count is 9 (8 research keys + error_flag)
  - _Requirements: 2.10, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

- [x] 6. Verify `research_company` end-to-end pipeline
  - Confirm Step 1: `_sanitize_input` called for both company and role; ValueError propagates (not caught)
  - Confirm Step 2: `time.sleep(RATE_LIMIT_SLEEP)` called unconditionally before LLM call
  - Confirm Step 3: `genai.configure(api_key=api_key)` followed by `GenerativeModel(model_name=GEMINI_MODEL, tools="google_search_retrieval")`
  - Confirm Step 4: prompt contains `"{company} {role} interview questions experience {level} 2024 2025"` search query
  - Confirm Step 5: `_safe_llm_call` invoked with `MAX_TOKENS_COMPLEX` and agent_name `"Researcher"`
  - Confirm Step 6: `_validate_research_dict` called on the raw result
  - Confirm Step 7: validated dict returned on success (no error_flag key)
  - Confirm Step 8: top-level try/except catches any exception from steps 5–6 and returns `_build_default_dict`
  - Confirm warning printed: `[Researcher] Unrecoverable error, returning default dict: {e}`
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 5.5, 5.7, 6.7, 7.1_

- [x] 7. Verify system prompt compliance
  - Confirm `SYSTEM_PROMPT` ends with exact text: `"Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."`
  - Confirm `SYSTEM_PROMPT` contains all 8 key names as literal strings: "company", "role", "interview_rounds", "key_topics", "difficulty", "culture_keywords", "known_question_types", "red_flags_to_test"
  - Confirm `SYSTEM_PROMPT` contains instruction to use industry defaults when company data is unavailable
  - _Requirements: 9.1, 9.2, 7.1_

- [x] 8. Checkpoint — Verify all implementation requirements are met
  - Ensure all verification tasks (1–7) pass, ask the user if questions arise.
  - If any requirement is not met by the current implementation, fix the code in `agents/researcher.py` before proceeding to tests.

- [x] 9. Write unit tests — input validation and sanitization
  - [x] 9.1 Create `tests/test_researcher.py` with imports and test fixtures
    - Import `pytest`, `unittest.mock`, `hypothesis`
    - Import `research_company`, `_sanitize_input`, `_safe_llm_call`, `_validate_research_dict`, `_build_default_dict`, `SYSTEM_PROMPT`, `_REQUIRED_KEYS` from `agents.researcher`
    - Import config constants: `RATE_LIMIT_SLEEP`, `ERROR_RETRY_SLEEP`, `MAX_TOKENS_COMPLEX`, `GEMINI_MODEL` from `core.config`
    - Create fixture for a valid 8-key research dict
    - _Requirements: 10.1, 10.2_

  - [x] 9.2 Write unit tests for `_sanitize_input`
    - Test: `company=""` → `ValueError` with "company" in message
    - Test: `company="   "` (whitespace-only) → `ValueError`
    - Test: `company="@#$%"` (all special chars) → `ValueError` with "invalid after sanitization" in message
    - Test: `company="Google!!"` → returns `"Google"`
    - Test: `company="Meta-Platforms"` → returns `"Meta-Platforms"` (valid chars unchanged)
    - Test: 150-char input → output length ≤ 100
    - Test: `role=""` → `ValueError` with "role" in message
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 9.3 Write unit tests for `research_company` input validation
    - Test: `company=""` raises `ValueError` that propagates (not caught by top-level handler)
    - Test: `company="   "` raises `ValueError` that propagates
    - Test: `role="@#$"` raises `ValueError` that propagates
    - Test: valid inputs proceed past sanitization (mock LLM to succeed)
    - _Requirements: 5.7_

- [x] 10. Write unit tests — `_safe_llm_call` retry behaviour
  - [x] 10.1 Write tests for JSON retry path
    - Test: invalid JSON on attempt 0 → `time.sleep(RATE_LIMIT_SLEEP)` called → corrective text appended → retry succeeds
    - Test: invalid JSON on both attempts → `ValueError` raised with "Researcher failed after 2 attempts"
    - Test: successful call logs `"[Researcher] Success. Tokens:"` to stdout (capture with `capsys`)
    - Test: `max_output_tokens` is passed as `MAX_TOKENS_COMPLEX` (assert via mock call args)
    - _Requirements: 2.7, 2.8, 5.1, 5.2, 8.1, 8.2_

  - [x] 10.2 Write tests for API error retry path
    - Test: API exception on attempt 0 → `time.sleep(ERROR_RETRY_SLEEP)` called → retry succeeds
    - Test: API exception on both attempts → original exception re-raised
    - Test: JSON fail logs format `"[Researcher] JSON fail attempt {N}: {error}"` to stdout
    - Test: API error logs format `"[Researcher] API error attempt {N}: {error}"` to stdout
    - _Requirements: 5.3, 5.4, 8.3, 8.4_

- [x] 11. Write unit tests — `_validate_research_dict`
  - [x] 11.1 Write tests for missing and extra keys
    - Test: dict missing `key_topics` → `ValueError` with "missing required keys" and "key_topics" in message
    - Test: dict missing multiple keys → `ValueError` listing all missing keys
    - Test: dict with 8 required + 3 extra keys → returns only 8 required keys
    - _Requirements: 2.3, 2.4_

  - [x] 11.2 Write tests for value type validation
    - Test: `company=""` (empty string) → `ValueError`
    - Test: `company="  "` (whitespace-only after strip) → `ValueError`
    - Test: `key_topics=[]` (empty list) → `ValueError`
    - Test: `key_topics=["valid", ""]` (list with empty string element) → `ValueError`
    - Test: `key_topics="not a list"` (wrong type) → `ValueError`
    - Test: `difficulty="impossible"` → `ValueError` (if difficulty validation implemented)
    - Test: valid dict with all correct types → returns dict with exactly 8 keys
    - _Requirements: 1.5, 2.1, 2.2_

- [x] 12. Write unit tests — `_build_default_dict` and fallback behaviour
  - [x] 12.1 Write tests for difficulty mapping
    - Test: `level="fresher"` → `difficulty="easy"`
    - Test: `level="junior"` → `difficulty="medium"`
    - Test: `level="senior"` → `difficulty="hard"`
    - Test: `level="lead"` → `difficulty="expert"`
    - Test: `level="manager"` → `difficulty="expert"`
    - Test: `level="intern"` (unknown) → `difficulty="medium"`
    - _Requirements: 6.4_

  - [x] 12.2 Write tests for role-based key_topics selection
    - Test: `role="ML Engineer"` → key_topics includes "machine learning"
    - Test: `role="Data Analyst"` → key_topics includes "sql"
    - Test: `role="Product Manager"` → key_topics includes "product strategy"
    - Test: `role="DevOps Engineer"` → key_topics includes "ci/cd"
    - Test: `role="React Developer"` → key_topics includes "javascript"
    - Test: `role="Backend Developer"` → key_topics includes "api design"
    - Test: `role="Astronaut"` (generic) → key_topics includes "data structures"
    - _Requirements: 6.5_

  - [x] 12.3 Write tests for default dict structure
    - Test: returned dict has exactly 9 keys (8 research + error_flag)
    - Test: `error_flag` is `True`
    - Test: `interview_rounds` is `"3 rounds"`
    - Test: `culture_keywords` is `["collaboration", "ownership"]`
    - Test: `known_question_types` is `["coding", "behavioural"]`
    - Test: `red_flags_to_test` is `["problem-solving approach", "communication clarity"]`
    - _Requirements: 2.10, 6.3, 6.6_

- [x] 13. Write unit tests — `research_company` end-to-end paths
  - [x] 13.1 Write tests for the success path
    - Test: mock LLM returning valid 8-key JSON → returns dict with 8 keys, no `error_flag`
    - Test: `time.sleep(RATE_LIMIT_SLEEP)` called before the LLM call
    - Test: `genai.configure` called with the provided `api_key`
    - Test: `GenerativeModel` called with `tools="google_search_retrieval"`
    - Test: prompt contains the search query format `"{company} {role} interview questions experience {level} 2024 2025"`
    - _Requirements: 1.1, 1.2, 1.3, 9.4_

  - [x] 13.2 Write tests for the failure/default path
    - Test: LLM raises `RuntimeError` after retries → returns Default_Dict with `error_flag=True`
    - Test: `_validate_research_dict` raises `ValueError` → returns Default_Dict with `error_flag=True`
    - Test: warning printed: `"[Researcher] Unrecoverable error, returning default dict:"` (capture with `capsys`)
    - Test: Default_Dict returned still has all 8 research keys with non-empty values
    - _Requirements: 1.4, 5.5, 6.1, 6.2, 6.7, 7.3_

- [x] 14. Write unit tests — system prompt and configuration compliance
  - [x] 14.1 Write tests for system prompt content
    - Test: `SYSTEM_PROMPT` ends with `"Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."`
    - Test: `SYSTEM_PROMPT` contains all 8 key names as literal strings
    - Test: `SYSTEM_PROMPT` contains instruction about "industry defaults" for unknown companies
    - _Requirements: 9.1, 9.2, 7.1_

  - [x] 14.2 Write tests for no hardcoded values
    - Test: all `time.sleep` calls in `research_company` use `RATE_LIMIT_SLEEP` constant (mock and assert)
    - Test: `MAX_TOKENS_COMPLEX` is passed to `generation_config` (not a literal `1000`)
    - _Requirements: 10.1, 10.2, 10.3_

- [x] 15. Checkpoint — Ensure all unit tests pass
  - Run `pytest tests/test_researcher.py -v --tb=short` from the project root
  - Ensure all tests pass, ask the user if questions arise.

- [x] 16. Write property-based tests
  - [x]* 16.1 Write property test for Output Structure Invariant
    - **Property 1: Output Structure Invariant**
    - **Validates: Requirements 1.1, 2.1, 2.2, 2.3, 2.6**
    - Use `@given(st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('L','N','Zs'), whitelist_characters='-')))` for company/role
    - Use `st.sampled_from(["fresher", "junior", "senior", "lead", "manager"])` for level
    - Mock LLM to return valid/invalid dicts using `st.fixed_dictionaries` strategy
    - Assert: returned dict either has exactly 8 keys matching `_REQUIRED_KEYS` (no `error_flag`) OR has exactly 9 keys (8 research + `error_flag=True`)
    - Assert: no other key set is ever returned
    - Tag: `# Feature: researcher-agent, Property 1: Output Structure Invariant`

  - [x]* 16.2 Write property test for Failure Safety Invariant
    - **Property 2: Failure Safety Invariant**
    - **Validates: Requirements 1.4, 2.5, 2.9, 5.5, 6.1, 6.2, 7.3**
    - Use `st.sampled_from([ValueError, RuntimeError, ConnectionError, TimeoutError])` for exception types
    - Use `st.text(min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=('L','N','Zs'), whitelist_characters='-'))` for company/role
    - Mock `_safe_llm_call` to raise the sampled exception
    - Assert: `research_company` never raises (for valid sanitized inputs)
    - Assert: returned dict contains all 8 required keys with non-empty values + `error_flag=True`
    - Tag: `# Feature: researcher-agent, Property 2: Failure Safety Invariant`

  - [x]* 16.3 Write property test for Default Dict Role-Appropriate Completeness
    - **Property 3: Default Dict Role-Appropriate Completeness**
    - **Validates: Requirements 2.10, 6.3, 6.4, 6.5, 6.6**
    - Use `st.text(min_size=1, max_size=50)` for company/role
    - Use `st.sampled_from(["fresher", "junior", "senior", "lead", "manager", "intern", "unknown", "CTO"])` for level
    - Call `_build_default_dict` directly
    - Assert: returned dict has exactly 9 keys
    - Assert: difficulty correctly mapped from level
    - Assert: key_topics has exactly 5 items matching the role category
    - Assert: fixed defaults match spec values
    - Tag: `# Feature: researcher-agent, Property 3: Default Dict Role-Appropriate Completeness`

  - [x]* 16.4 Write property test for Input Sanitization Correctness
    - **Property 4: Input Sanitization Correctness**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.7**
    - Use `st.text(min_size=0, max_size=200)` for arbitrary input strings
    - Use `st.text(min_size=1, max_size=100, alphabet=st.characters(whitelist_categories=('L','N','Zs'), whitelist_characters='-'))` for valid inputs
    - Assert: empty/whitespace → `ValueError`
    - Assert: output length ≤ 100 for any input
    - Assert: output contains only `[a-zA-Z0-9 \-]`
    - Assert: valid inputs (≤100 chars, only allowed chars) → output equals stripped input
    - Assert: all-special-char inputs → `ValueError`
    - Tag: `# Feature: researcher-agent, Property 4: Input Sanitization Correctness`

  - [x]* 16.5 Write property test for Markdown Stripping Round Trip
    - **Property 5: Markdown Stripping Round Trip**
    - **Validates: Requirements 4.1, 4.2, 4.5**
    - Use `st.dictionaries(st.text(min_size=1, alphabet=st.characters(whitelist_categories=('L','N'))), st.text(min_size=1, alphabet=st.characters(whitelist_categories=('L','N'))), min_size=1, max_size=5)` for JSON content
    - Wrap JSON in various markdown formats: ` ```json ... ``` `, ` ``` ... ``` `, raw JSON, with surrounding prose
    - Mock model to return the wrapped text
    - Assert: `_safe_llm_call` extracts and parses the JSON correctly, producing the same dict
    - Tag: `# Feature: researcher-agent, Property 5: Markdown Stripping Round Trip`

  - [x]* 16.6 Write property test for Retry Count and Rate Limit Invariant
    - **Property 6: Retry Count and Rate Limit Invariant**
    - **Validates: Requirements 1.2, 1.3, 5.1, 5.3, 5.6**
    - Use `st.integers(min_value=0, max_value=1)` for which attempt fails
    - Use `st.sampled_from(["json_error", "api_error", "success"])` for attempt outcomes
    - Mock model's `generate_content` to track call count
    - Assert: `generate_content` called at most 2 times
    - Assert: on JSON failure at attempt 0, `time.sleep(RATE_LIMIT_SLEEP)` called before retry
    - Assert: on API error at attempt 0, `time.sleep(ERROR_RETRY_SLEEP)` called before retry
    - Assert: no sleep after the final (2nd) attempt failure
    - Tag: `# Feature: researcher-agent, Property 6: Retry Count and Rate Limit Invariant`

- [x] 17. Final checkpoint — Ensure all tests pass
  - Run `pytest tests/test_researcher.py -v --tb=short` from the project root
  - Confirm 0 failures and 0 errors
  - Confirm all property tests complete `max_examples=100` without shrinking to a failure
  - If any test fails: fix the implementation in `agents/researcher.py` to satisfy the failing assertion, then re-run
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- All tasks target `agents/researcher.py`. Do not modify any other agent file when working on these tasks.
- The implementation in `agents/researcher.py` is assumed to already exist. Tasks 1–7 are read-only verification steps — no code changes are expected unless a discrepancy is found (e.g., missing difficulty validation in `_validate_research_dict`).
- All tests belong in `tests/test_researcher.py`. Create the file during task 9.1.
- Tasks marked with `*` are optional and can be skipped for faster MVP.
- Property-based tests must use the **Hypothesis** library with `@settings(max_examples=100)` and be tagged with the comment format `# Feature: researcher-agent, Property {N}: {property_text}`.
- All constants (`RATE_LIMIT_SLEEP`, `ERROR_RETRY_SLEEP`, `MAX_TOKENS_COMPLEX`, `GEMINI_MODEL`) must be imported from `core.config` — never hardcoded in tests.
- Only libraries from the approved list in `tech.md` may be used. `unittest.mock` (stdlib) is permitted for mocking in tests.
- Each task references specific requirements for traceability.
- Checkpoints ensure incremental validation.
- Property tests validate universal correctness properties from the design document.
- Unit tests validate specific examples and edge cases.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2", "3", "4", "5", "6", "7"] },
    { "id": 1, "tasks": ["9.1"] },
    { "id": 2, "tasks": ["9.2", "9.3", "10.1", "10.2", "11.1", "11.2", "12.1", "12.2", "12.3", "13.1", "13.2", "14.1", "14.2"] },
    { "id": 3, "tasks": ["16.1", "16.2", "16.3", "16.4", "16.5", "16.6"] },
    { "id": 4, "tasks": ["17"] }
  ]
}
```

Wave 0 — Implementation Verification (Tasks 1–7): all independent, run in any order.
Wave 1 — Test file setup (Task 9.1): creates the test file with imports and fixtures.
Wave 2 — Unit Tests (Tasks 9.2–14.2): depend on test file setup, can run in parallel with each other.
Wave 3 — Property-Based Tests (Tasks 16.1–16.6): depend on unit tests being complete to avoid conflicts in the same file.
Wave 4 — Final Test Suite Run (Task 17): depends on all prior tasks.

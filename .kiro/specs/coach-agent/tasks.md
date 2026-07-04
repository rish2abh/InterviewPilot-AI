# Implementation Plan: Coach Agent

## Overview

Implement `agents/coach.py` as a single-file Python module containing:
- `_safe_llm_call` — private helper following the exact steering template
- `_compress_answers` — private helper that extracts only LLM-relevant fields from Answer_Dicts
- `_calculate_hiring_probability` — private helper for deterministic band classification
- `_calculate_hiring_percent` — private helper for percentage calculation
- `_validate_report` — private helper for 11-key output contract validation
- `generate_report` — public function that produces the final performance report via a 9-step processing pipeline

All constants are imported from `core/config.py`. No hardcoded numeric literals for thresholds, limits, or sleep durations. The file uses only libraries from the approved stack (google-generativeai, json, re, time).

---

## Tasks

- [x] 1. Verify `core/config.py` constants for Coach Agent
  - Open `core/config.py` and confirm all constants required by the Coach Agent exist:
    `MAX_TOKENS_REPORT = 1500`, `RATE_LIMIT_SLEEP = 4`, `ERROR_RETRY_SLEEP = 8`,
    `HIRING_LOW_MAX = 80`, `HIRING_HIGH_MIN = 140`, `MAX_TOTAL_SCORE = 200`,
    `TOTAL_QUESTIONS = 10`, `GEMINI_API_KEY`, `GEMINI_MODEL`
  - Confirm `agents/__init__.py` exists (create empty file if missing)
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 2. Implement `_safe_llm_call` in `agents/coach.py`
  - [x] 2.1 Create `agents/coach.py` with module-level imports and `_safe_llm_call`
    - Add imports: `import json`, `import re`, `import time`, `import google.generativeai as genai`
    - Import constants from `core.config`: `GEMINI_API_KEY`, `GEMINI_MODEL`, `MAX_TOKENS_REPORT`, `RATE_LIMIT_SLEEP`, `ERROR_RETRY_SLEEP`, `HIRING_LOW_MAX`, `HIRING_HIGH_MIN`, `MAX_TOTAL_SCORE`, `TOTAL_QUESTIONS`
    - Implement `_safe_llm_call(prompt: str, system: str, model, max_tokens: int, agent_name: str) -> dict` using the exact template from `agents.md`:
      - `for attempt in range(2)` loop
      - `model.generate_content([system, prompt], generation_config={"max_output_tokens": max_tokens})`
      - Strip `response.text`, remove ` ```json ` and ` ``` ` markdown blocks with `re.sub`
      - `json.loads(text)` → print `[{agent_name}] Success. Tokens: {response.usage_metadata}` → return
      - `json.JSONDecodeError` on attempt 0: print, sleep `RATE_LIMIT_SLEEP`, append corrective prompt; on attempt 1: raise `ValueError("Coach failed after 2 attempts")`
      - Any other `Exception` on attempt 0: print, sleep `ERROR_RETRY_SLEEP`; on attempt 1: re-raise
    - _Requirements: 2.1, 2.6, 3.2, 9.1, 9.2, 10.5_

  - [x] 2.2 Write property test for exception propagation (P9)
    - **Property 9: Exception propagation**
    - Mock `_safe_llm_call` to raise varied exceptions; assert `generate_report` propagates without returning a partial dict
    - Use `@given(st.sampled_from([ValueError("fail"), RuntimeError("api"), ConnectionError("net")]))`
    - Tag: `# Feature: coach-agent, Property 9: Exception propagation`
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4**

- [x] 3. Implement `_compress_answers` and `SYSTEM_PROMPT`
  - [x] 3.1 Add `SYSTEM_PROMPT` constant and `_compress_answers` helper
    - Add `SYSTEM_PROMPT` string constant at module level matching the design document exactly
    - Must end with: `"Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."`
    - Implement `_compress_answers(answers: list[dict]) -> list[dict]`:
      - For each answer at index `i`, extract: `{"question_index": i+1, "score": answer["evaluation"]["total"], "category": answer["category"], "missing_keywords": answer["evaluation"]["missing_keywords"]}`
      - Never include `answer_text`, `question`, or `feedback`
    - _Requirements: 1.1, 1.2, 1.3, 2.4, 2.5_

  - [x] 3.2 Write property test for compression correctness (P1)
    - **Property 1: Compression Correctness and Data Isolation**
    - Generate valid Answer_Dict lists with varied categories, scores, and missing_keywords
    - Assert each compressed entry has exactly 4 keys: `question_index`, `score`, `category`, `missing_keywords`
    - Assert `question_index` equals 1-based position
    - Assert the JSON-serialized compressed data contains no `answer_text`, `question`, or `feedback` strings
    - Tag: `# Feature: coach-agent, Property 1: Compression Correctness and Data Isolation`
    - **Validates: Requirements 1.1, 1.2, 1.3**

- [x] 4. Implement `_calculate_hiring_probability` and `_calculate_hiring_percent`
  - [x] 4.1 Add both deterministic calculation helpers
    - Implement `_calculate_hiring_probability(overall_score: int) -> str`:
      - `if overall_score < HIRING_LOW_MAX: return "Low"`
      - `elif overall_score <= HIRING_HIGH_MIN: return "Medium"`
      - `else: return "High"`
    - Implement `_calculate_hiring_percent(overall_score: int) -> int`:
      - `return max(0, min(100, round((overall_score / MAX_TOTAL_SCORE) * 100)))`
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 4.2 Write property test for hiring probability bands (P3)
    - **Property 3: Hiring Probability Band Classification**
    - `@given(st.integers(40, 200))` for overall_score
    - Assert: `score < HIRING_LOW_MAX` → `"Low"`; `HIRING_LOW_MAX <= score <= HIRING_HIGH_MIN` → `"Medium"`; `score > HIRING_HIGH_MIN` → `"High"`
    - Assert `_calculate_hiring_percent` always returns int in `[0, 100]`
    - Tag: `# Feature: coach-agent, Property 3: Hiring Probability Band Classification`
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.5**

- [x] 5. Implement `_validate_report`
  - [x] 5.1 Implement the 11-key output contract validator
    - Implement `_validate_report(report: dict) -> dict`:
      - Check all 11 required keys exist; raise `ValueError` with missing key names if not
      - Strip extra keys beyond the 11 required
      - Validate `strongest_category`, `weakest_category`, `overall_verdict`, `next_interview_tip`: non-empty str
      - Validate `category_averages`: dict with str keys and numeric (int/float) values
      - Validate `top_3_strengths`: list of exactly 3 non-empty strings
      - Validate `top_3_improvements`: list of exactly 3 dicts, each with keys `area`, `why`, `how_to_fix`, `free_resource` (all non-empty str), and `free_resource` starts with `"http://"` or `"https://"`
      - Validate `critical_moment`: non-empty str containing at least one digit (`re.search(r'\d', value)`)
      - Raise `ValueError` with `"Coach"` prefix on any failure
    - _Requirements: 5.1, 5.2, 5.6, 5.7, 5.8, 5.9, 5.10, 6.1, 6.2, 6.3, 6.5, 7.2, 7.3_

  - [x] 5.2 Write property test for output contract invariant (P4)
    - **Property 4: Output Contract Invariant (11-Key Enforcement)**
    - Mock `_safe_llm_call` to return valid 11-key dicts with random extra keys
    - Assert output always has exactly 11 keys; extra keys are stripped
    - Assert all type checks pass for valid inputs
    - Tag: `# Feature: coach-agent, Property 4: Output Contract Invariant`
    - **Validates: Requirements 5.1, 5.6, 5.7, 5.8, 5.9, 5.10, 11.2**

  - [x] 5.3 Write property test for missing keys detection (P5)
    - **Property 5: Missing Keys Detection**
    - `@given(st.sets(st.sampled_from(REQUIRED_KEYS), min_size=1, max_size=10))` for keys to remove from LLM response
    - Mock `_safe_llm_call` to return dict with those keys removed
    - Assert `ValueError` raised identifying the missing keys
    - Tag: `# Feature: coach-agent, Property 5: Missing Keys Detection`
    - **Validates: Requirements 5.1, 5.2**

  - [x] 5.4 Write property test for improvement entry validation (P6)
    - **Property 6: Improvement Entry Structural Validation**
    - Generate random dicts for improvement entries (varied keys, values, URL formats)
    - Assert validation passes iff entry has all 4 keys as non-empty str and `free_resource` starts with `http://` or `https://`
    - Tag: `# Feature: coach-agent, Property 6: Improvement Entry Structural Validation`
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.5**

  - [x] 5.5 Write property test for critical moment digit requirement (P7)
    - **Property 7: Critical Moment Digit Requirement**
    - `@given(st.text())` for critical_moment values
    - Assert validation passes iff string is non-empty and contains at least one digit
    - Tag: `# Feature: coach-agent, Property 7: Critical Moment Digit Requirement`
    - **Validates: Requirements 7.2, 7.3**

- [x] 6. Checkpoint — Helpers complete
  - Ensure all tests pass, ask the user if questions arise.
  - All private helpers (`_safe_llm_call`, `_compress_answers`, `_calculate_hiring_probability`, `_calculate_hiring_percent`, `_validate_report`) must be implemented

- [x] 7. Implement `generate_report` — Steps 1–3 (input validation, compress, calculate score)
  - [x] 7.1 Implement Steps 1–3 of the processing pipeline
    - Signature: `def generate_report(session_id: str, answers: list[dict]) -> dict:`
    - Step 1: Input validation (all checks from design document):
      - `session_id` is None, empty, or whitespace → `ValueError`
      - `answers` not a list → `ValueError`
      - `answers` empty → `ValueError`
      - `len(answers) != TOTAL_QUESTIONS` → `ValueError` with expected/actual
      - Each Answer_Dict: validate `category` (non-empty str), `evaluation` (dict), `evaluation["total"]` (int), `evaluation["missing_keywords"]` (list)
    - Step 2: `compressed = _compress_answers(answers)`
    - Step 3: `overall_score = sum(answer["evaluation"]["total"] for answer in answers)`
    - _Requirements: 1.4, 4.1, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_

  - [x] 7.2 Write property test for input validation completeness (P8)
    - **Property 8: Input Validation Completeness**
    - Generate invalid inputs: None/empty/whitespace session_id, non-list answers, wrong count, malformed Answer_Dicts
    - Assert `ValueError` raised before any sleep or LLM call (mock `time.sleep` and `_safe_llm_call`, verify not called)
    - Tag: `# Feature: coach-agent, Property 8: Input Validation Completeness`
    - **Validates: Requirements 1.4, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6**

- [x] 8. Implement `generate_report` — Steps 4–9 (sleep, configure, LLM call, validate, override, return)
  - [x] 8.1 Implement Steps 4–9 of the processing pipeline
    - Step 4: `time.sleep(RATE_LIMIT_SLEEP)`
    - Step 5: `genai.configure(api_key=GEMINI_API_KEY)`, `model = genai.GenerativeModel(GEMINI_MODEL)`, build user_prompt with compressed JSON
    - Step 6: `raw = _safe_llm_call(user_prompt, SYSTEM_PROMPT, model, MAX_TOKENS_REPORT, "Coach")`
    - Step 7: `raw = _validate_report(raw)` — validates 11-key contract
    - Step 8: Deterministic overrides:
      - `raw["overall_score"] = overall_score`
      - `raw["hiring_probability"] = _calculate_hiring_probability(overall_score)`
      - `raw["hiring_probability_percent"] = _calculate_hiring_percent(overall_score)`
    - Step 9: `return raw`
    - _Requirements: 2.1, 2.2, 2.3, 2.5, 3.1, 3.3, 5.3, 5.4, 5.5, 10.3, 10.4, 11.1_

  - [x] 8.2 Write property test for deterministic score override (P2)
    - **Property 2: Deterministic Score Override**
    - `@given(st.integers(4, 20))` × 10 for evaluation.total values; mock LLM to return arbitrary `overall_score`, `hiring_probability`, `hiring_probability_percent`
    - Assert output `overall_score == sum(totals)`, `hiring_probability` derived from local score, `hiring_probability_percent == round((sum/MAX_TOTAL_SCORE)*100)`
    - Tag: `# Feature: coach-agent, Property 2: Deterministic Score Override`
    - **Validates: Requirements 4.1, 5.3, 5.4, 5.5**

  - [x] 8.3 Write property test for rate limit compliance (P10)
    - **Property 10: Rate Limit Compliance**
    - Mock `time.sleep` and `_safe_llm_call`; provide valid inputs
    - Assert `time.sleep` called exactly once with `RATE_LIMIT_SLEEP` before `_safe_llm_call`
    - Tag: `# Feature: coach-agent, Property 10: Rate Limit Compliance`
    - **Validates: Requirements 3.1, 3.3**

  - [x] 8.4 Write property test for single LLM call (P11)
    - **Property 11: Single LLM Call Per Invocation**
    - Mock `_safe_llm_call`; provide varied valid inputs
    - Assert `_safe_llm_call` called exactly once per `generate_report` invocation
    - Tag: `# Feature: coach-agent, Property 11: Single LLM Call Per Invocation`
    - **Validates: Requirements 2.1**

- [x] 9. Checkpoint — Full pipeline complete
  - Ensure all tests pass, ask the user if questions arise.
  - All 9 pipeline steps must be implemented and reachable
  - `generate_report` must be importable from `agents.coach`

- [x] 10. Write unit tests in `tests/test_coach.py`
  - [x] 10.1 Create `tests/test_coach.py` with unit test cases for boundary conditions and error paths
    - **Valid input succeeds**: Mock LLM returning valid 11-key JSON → returns Report_Dict with 11 keys
    - **Rate limit sleep called**: Mock `time.sleep`, assert called with `RATE_LIMIT_SLEEP` before LLM
    - **GEMINI_API_KEY used**: Mock `genai.configure`, assert called with `GEMINI_API_KEY`
    - **GEMINI_MODEL used**: Mock `genai.GenerativeModel`, assert called with `GEMINI_MODEL`
    - **MAX_TOKENS_REPORT passed**: Mock `_safe_llm_call`, assert `max_tokens == MAX_TOKENS_REPORT`
    - **Agent name is "Coach"**: Mock `_safe_llm_call`, assert `agent_name == "Coach"`
    - **System prompt suffix**: Assert `SYSTEM_PROMPT` ends with exact required suffix string
    - **Invalid session_id raises**: `session_id=""` → `ValueError` before any sleep
    - **None session_id raises**: `session_id=None` → `ValueError`
    - **Non-list answers raises**: `answers="not a list"` → `ValueError`
    - **Empty answers raises**: `answers=[]` → `ValueError`
    - **Wrong count raises**: 9 answers → `ValueError` with expected/actual counts
    - **Missing category raises**: Answer_Dict without `category` → `ValueError` with index
    - **Missing evaluation raises**: Answer_Dict without `evaluation` → `ValueError` with index
    - **Missing evaluation.total raises**: `evaluation={"missing_keywords": []}` → `ValueError` with index
    - **Missing evaluation.missing_keywords raises**: `evaluation={"total": 15}` → `ValueError` with index
    - **LLM missing keys raises**: Mock LLM missing `"critical_moment"` → `ValueError` listing missing keys
    - **Extra keys stripped**: Mock LLM returning 13 keys → output has exactly 11 keys
    - **overall_score overridden**: Mock LLM returning `overall_score=999` → output uses sum of totals
    - **hiring_probability overridden**: Mock LLM returning `"Very High"` → output uses band calculation
    - **hiring_probability_percent overridden**: Mock LLM returning `99` → output uses formula
    - **Low band (score 79)**: Mock answers summing to 79 → `hiring_probability == "Low"`
    - **Medium band (score 80)**: Mock answers summing to 80 → `hiring_probability == "Medium"`
    - **Medium band (score 140)**: Mock answers summing to 140 → `hiring_probability == "Medium"`
    - **High band (score 141)**: Mock answers summing to 141 → `hiring_probability == "High"`
    - **hiring_probability_percent calculation**: score 150 → `round((150/200)*100) == 75`
    - **Invalid strongest_category raises**: Empty string → `ValueError`
    - **Invalid top_3_strengths count raises**: 2 items → `ValueError`
    - **Invalid improvement entry missing key**: Entry without `"how_to_fix"` → `ValueError`
    - **Invalid free_resource URL**: `"not-a-url"` → `ValueError`
    - **Empty free_resource raises**: `""` → `ValueError`
    - **critical_moment no digit raises**: `"The candidate performed well"` → `ValueError`
    - **critical_moment with digit passes**: `"Question 3 was the turning point"` → passes
    - **Compression excludes answer_text**: Capture user prompt, assert no answer_text content present
    - **Compression includes question_index**: Each compressed entry has 1-based index
    - **JSON retry behavior**: Mock `model.generate_content` returns invalid JSON then valid → retries
    - **API error retry**: Mock `model.generate_content` raises then succeeds → 8s sleep, retry
    - **ValueError propagation from _safe_llm_call**: Mock raises ValueError → propagated to caller
    - **Non-ValueError propagation**: Mock raises RuntimeError → propagated unchanged
    - **No database operations**: Mock `core.database`, assert no DB functions called
    - **Token usage logging**: Capture stdout, assert `"[Coach] Success. Tokens:"` format
    - **No public functions besides generate_report**: Inspect module, verify no other public names
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 2.6, 3.1, 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 6.1, 6.2, 6.3, 6.5, 7.2, 7.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 9.1, 9.2, 9.3, 9.4, 10.1, 10.2, 10.3, 10.4, 10.5, 11.1, 11.2, 11.3, 11.4_

- [x] 11. Final checkpoint — All tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Run `pytest tests/test_coach.py -v` to confirm green
  - Verify `agents/coach.py` has no hardcoded numeric literals for thresholds or sleeps
  - Verify all 11 Report_Dict keys are present and validated
  - Verify no public functions besides `generate_report` exist in the module

---

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use the **Hypothesis** library (`hypothesis` must be in dev dependencies); configure each with `@settings(max_examples=100)`
- Each property test MUST include the tag comment: `# Feature: coach-agent, Property {N}: {property_text}`
- The `_safe_llm_call` retry sleep values (4s for JSON via `RATE_LIMIT_SLEEP`, 8s for API errors via `ERROR_RETRY_SLEEP`) reference named constants; all other numbers use config constants as well
- The processing pipeline order (Steps 1–9) is critical and must not be reordered
- `generate_report` is stateless — all context passed as parameters; no module-level mutable state
- The Coach Agent never performs database operations — the orchestrator handles persistence

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1", "3.1"] },
    { "id": 1, "tasks": ["4.1", "5.1"] },
    { "id": 2, "tasks": ["3.2", "4.2", "5.2", "5.3", "5.4", "5.5"] },
    { "id": 3, "tasks": ["7.1", "2.2"] },
    { "id": 4, "tasks": ["8.1", "7.2"] },
    { "id": 5, "tasks": ["8.2", "8.3", "8.4"] },
    { "id": 6, "tasks": ["10.1"] }
  ]
}
```

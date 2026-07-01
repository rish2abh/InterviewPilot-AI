# Implementation Plan: Evaluator Agent

## Overview

Implement `agents/evaluator.py` as a single-file Python module containing:
- `_safe_llm_call` — private helper following the exact steering template
- `evaluate_answer` — public function that scores interview answers via a 12-step post-processing pipeline
- `get_follow_up_question` — pure helper that retrieves follow-up questions with bounds checking

All constants are imported from `core/config.py`. No hardcoded numeric literals for thresholds, limits, or sleep durations. The file uses only libraries from the approved stack (google-generativeai, json, re, time).

---

## Tasks

- [x] 1. Verify and populate `core/config.py` constants
  - Open `core/config.py` and confirm or add the six constants required by the evaluator:
    `MIN_ANSWER_LENGTH = 50`, `MAX_TOKENS_SIMPLE = 500`, `RATE_LIMIT_SLEEP = 4`,
    `WEAK_SCORE_THRESHOLD = 12`, `STRONG_SCORE_THRESHOLD = 16`, `MAX_FOLLOW_UPS = 2`
  - Confirm `core/__init__.py` exists (create empty file if missing)
  - Confirm `agents/__init__.py` exists (create empty file if missing)
  - _Requirements: 13.1, 13.2, 13.3, 13.4_

- [x] 2. Implement `_safe_llm_call` in `agents/evaluator.py`
  - [x] 2.1 Create `agents/evaluator.py` with module-level imports and `_safe_llm_call`
    - Add imports: `import json`, `import re`, `import time`, `import google.generativeai as genai`
    - Import constants from `core.config`: `MIN_ANSWER_LENGTH`, `MAX_TOKENS_SIMPLE`, `RATE_LIMIT_SLEEP`, `WEAK_SCORE_THRESHOLD`, `STRONG_SCORE_THRESHOLD`, `MAX_FOLLOW_UPS`
    - Implement `_safe_llm_call(prompt, system, model, max_tokens, agent_name) -> dict` using the exact template from `agents.md`:
      - `for attempt in range(2)` loop
      - `model.generate_content([system, prompt], generation_config={"max_output_tokens": max_tokens})`
      - Strip `response.text`, remove ` ```json ` and ` ``` ` markdown blocks with `re.sub`
      - `json.loads(text)` → print `[{agent_name}] Success. Tokens: {response.usage_metadata}` → return
      - `json.JSONDecodeError` on attempt 0: print `[{agent_name}] JSON fail attempt 1: {e}`, sleep 4s (hardcoded per template), append corrective prompt; on attempt 1: raise `ValueError("{agent_name} failed after 2 attempts")`
      - Any other `Exception` on attempt 0: print `[{agent_name}] API error attempt 1: {e}`, sleep 8s (hardcoded per template); on attempt 1: re-raise
    - _Requirements: 1.4, 15.1, 15.2, 15.3, 15.4, 15.5, 16.1, 16.2, 16.3_

  - [ ]* 2.2 Write property test for exception propagation (P9)
    - **Property 9: Exception propagation from safe_llm_call**
    - Mock `_safe_llm_call` to raise varied exceptions; assert `evaluate_answer` propagates without returning a partial dict
    - Use `@given(st.sampled_from([ValueError("fail"), RuntimeError("api"), ConnectionError("net")]))`
    - Tag: `# Feature: evaluator-agent, Property 9: Exception propagation from safe_llm_call`
    - **Validates: Requirements 1.5, 15.3, 15.5**

- [x] 3. Define module-level constants: `SYSTEM_PROMPT` and `Penalty_Dict` factory
  - Add `SYSTEM_PROMPT` string constant at module level in `agents/evaluator.py`
    - Must include 20 level descriptions (5 levels × 4 dimensions)
    - Must list exact JSON response schema with all 6 keys and their types
    - Must end with exactly: `"Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."`
  - Add `_build_penalty_dict(ideal_keywords: list[str]) -> dict` private helper that returns the fixed `Penalty_Dict` shape
  - _Requirements: 2.2, 14.1, 14.2, 14.3, 14.4_

- [x] 4. Implement `get_follow_up_question`
  - [x] 4.1 Write `get_follow_up_question(question_dict: dict, follow_up_count: int) -> str | None`
    - Guard 1: `if follow_up_count < 0: return None`
    - Guard 2: `if follow_up_count >= MAX_FOLLOW_UPS: return None`
    - Guard 3: `if follow_up_count < len(question_dict["follow_ups"]): return question_dict["follow_ups"][follow_up_count]`
    - Fallback: `return "Can you elaborate on your answer with a specific example?"`
    - Uses `MAX_FOLLOW_UPS` from `core.config` — no hardcoded number
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 13.4_

  - [ ]* 4.2 Write property test for follow-up bounds (P10)
    - **Property 10: get_follow_up_question bounds**
    - `@given(st.integers(), st.lists(st.text()))` — vary count and follow_ups list length
    - Assert: `count < 0` → `None`; `count >= MAX_FOLLOW_UPS` → `None`; `0 <= count < MAX_FOLLOW_UPS and count < len(list)` → list element; otherwise → fallback string
    - Tag: `# Feature: evaluator-agent, Property 10: get_follow_up_question bounds`
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4**

- [x] 5. Implement `evaluate_answer` — Steps 1–3 (entry, penalty path, LLM call)
  - [x] 5.1 Implement the function signature, Step 1 (length check), Step 2 (rate limit sleep), and Step 3 (LLM call)
    - Signature: `def evaluate_answer(question: str, ideal_keywords: list[str], scoring_hint: str, user_answer: str, api_key: str) -> dict:`
    - Step 1: `if len(user_answer) < MIN_ANSWER_LENGTH: return _build_penalty_dict(ideal_keywords)`
    - Step 2: `time.sleep(RATE_LIMIT_SLEEP)` — must use constant, no `time.sleep(4)`
    - Step 3: `model = genai.GenerativeModel("gemini-2.0-flash-exp")`, build `user_prompt` f-string with exactly the 4 fields, call `_safe_llm_call(user_prompt, SYSTEM_PROMPT, model, MAX_TOKENS_SIMPLE, "Evaluator")`
    - _Requirements: 1.1, 1.3, 2.1, 2.3, 2.4, 12.1, 12.2, 12.3, 12.4_

  - [ ]* 5.2 Write property test for short-answer penalty path (P1)
    - **Property 1: Short-answer penalty path**
    - `@given(st.text(max_size=49), st.lists(st.text()))` for `(user_answer, ideal_keywords)`
    - Assert returned dict equals `_build_penalty_dict(ideal_keywords)` exactly (all 6 keys, fixed values)
    - Assert `_safe_llm_call` is NOT called (mock it and verify call count == 0)
    - Tag: `# Feature: evaluator-agent, Property 1: Short-answer penalty path`
    - **Validates: Requirements 2.1, 2.2, 2.4**

- [x] 6. Implement `evaluate_answer` — Steps 4–5 (subscore clamping and total recalculation)
  - [x] 6.1 Implement Step 4 (subscore clamping) and Step 5 (total recalculation)
    - Step 4: for each dim in `["relevance", "depth", "structure", "examples"]`:
      - If `not isinstance(raw["scores"][dim], (int, float))`: raise `ValueError(f"Non-numeric subscore: {dim}")`
      - `score = max(1, min(5, round(raw["scores"][dim])))`
      - Assign back to `raw["scores"][dim]`
    - Step 5: `total = sum(raw["scores"].values())` — verify `4 <= total <= 20`, else raise `ValueError(f"Total out of range after clamping: {total}")`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 7.1, 7.2, 7.3, 7.4_

  - [ ]* 6.2 Write property test for subscore clamping (P2)
    - **Property 2: Subscore clamping**
    - `@given(st.floats(allow_nan=False, allow_infinity=False))` for each of the 4 subscores
    - Mock LLM to return given float values; assert each clamped subscore == `max(1, min(5, round(x)))`
    - Assert no subscore in output is outside `[1, 5]`
    - Tag: `# Feature: evaluator-agent, Property 2: Subscore clamping`
    - **Validates: Requirements 7.1, 7.2, 7.3**

  - [ ]* 6.3 Write property test for total recalculation invariant (P3)
    - **Property 3: Total recalculation invariant**
    - `@given(st.integers(1,5), st.integers(1,5), st.integers(1,5), st.integers(1,5), st.integers(-100,100))` for subscores + arbitrary LLM total
    - Mock LLM to return given values; assert `result["total"] == sum of 4 clamped subscores` regardless of LLM-returned total
    - Tag: `# Feature: evaluator-agent, Property 3: Total recalculation invariant`
    - **Validates: Requirements 3.1, 3.2**

- [x] 7. Implement `evaluate_answer` — Steps 6–7 (verdict derivation and off-topic correction)
  - [x] 7.1 Implement Step 6 (verdict derivation) and Step 7 (off-topic correction flag)
    - Step 6:
      ```
      if total < WEAK_SCORE_THRESHOLD:   verdict = "weak"
      elif total <= STRONG_SCORE_THRESHOLD: verdict = "good"
      else:                               verdict = "strong"
      ```
    - Step 7: if `raw["scores"]["relevance"] == 1`, set `missing_keywords_override = list(ideal_keywords)` and `feedback_override = "Your answer was not relevant to the question asked; focus on the specific topic."` (store for use in Steps 8–9)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 11.1, 11.2, 11.3_

  - [ ]* 7.2 Write property test for verdict classification (P4)
    - **Property 4: Verdict classification from total**
    - `@given(st.integers(4, 20))` for total; mock pipeline to produce that total
    - Assert: `total < WEAK_SCORE_THRESHOLD` → `verdict == "weak"`; `WEAK_SCORE_THRESHOLD <= total <= STRONG_SCORE_THRESHOLD` → `verdict == "good"`; `total > STRONG_SCORE_THRESHOLD` → `verdict == "strong"`
    - Assert LLM-returned verdict is always discarded
    - Tag: `# Feature: evaluator-agent, Property 4: Verdict classification from total`
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4**

- [x] 8. Implement `evaluate_answer` — Steps 8–9 (feedback enforcement and missing keywords filtering)
  - [x] 8.1 Implement Step 8 (feedback enforcement)
    - `feedback = raw.get("feedback", "").strip()`
    - If empty: `feedback = "Review the ideal keywords and try incorporating them into your answer."`
    - Else: find first sentence boundary with `re.search(r'[.!?](?=\s+[A-Z])', feedback)` → truncate at `m.start() + 1`
    - If `len(feedback) > 200`: truncate to 200, append `"."` if last char not in `".!?"`
    - Apply `feedback_override` if `relevance == 1`
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 11.3_

  - [x] 8.2 Implement Step 9 (missing keywords filtering)
    - `ideal_set = set(ideal_keywords)`
    - If `relevance == 1`: `missing = list(ideal_keywords)` (full list, order preserved)
    - Else: iterate `raw.get("missing_keywords", [])`, keep only items in `ideal_set`, deduplicate preserving first-seen order
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 11.1_

  - [ ]* 8.3 Write property test for feedback single-sentence enforcement (P6)
    - **Property 6: Feedback single-sentence enforcement**
    - `@given(st.text())` for LLM-returned feedback string (including empty, multi-sentence, very long)
    - Mock LLM to return given feedback; assert output `feedback` has no sentence boundary pattern `[.!?]\s+[A-Z]` (i.e., exactly one sentence)
    - Assert `len(feedback) <= 200` and `len(feedback) >= 10` (after fallback)
    - Tag: `# Feature: evaluator-agent, Property 6: Feedback single-sentence enforcement`
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4**

  - [ ]* 8.4 Write property test for missing keywords filtering (P7)
    - **Property 7: Missing keywords is a filtered subset**
    - `@given(st.lists(st.text()), st.lists(st.text()))` for `(ideal_keywords, llm_missing_keywords)`
    - Mock LLM to return `llm_missing_keywords`; assert every element of output `missing_keywords` is in `ideal_keywords` (case-sensitive exact match)
    - Assert no duplicates in output `missing_keywords`
    - Tag: `# Feature: evaluator-agent, Property 7: Missing keywords is a filtered subset`
    - **Validates: Requirements 9.1, 9.2, 9.4**

  - [ ]* 8.5 Write property test for off-topic override (P8)
    - **Property 8: Off-topic override when relevance is 1**
    - `@given(st.lists(st.text(min_size=1)))` for `ideal_keywords`; fix `relevance=1` in mocked LLM response
    - Assert output `missing_keywords == ideal_keywords` (full list)
    - Assert output `feedback` contains off-topic override message
    - Tag: `# Feature: evaluator-agent, Property 8: Off-topic override when relevance is 1`
    - **Validates: Requirements 9.3, 11.1, 11.3**

- [x] 9. Implement `evaluate_answer` — Steps 10–12 (trigger_follow_up, validation, return)
  - [x] 9.1 Implement Step 10 (trigger_follow_up), Step 11 (final validation), and Step 12 (return)
    - Step 10: `trigger_follow_up = (verdict == "weak")`
    - Step 11: assemble `result` dict with exactly 6 keys; run validation checks:
      - `scores`: dict with 4 keys, each `int` in `[1, 5]`
      - `total`: `int` in `[4, 20]`
      - `verdict`: one of `"weak"`, `"good"`, `"strong"`
      - `feedback`: non-empty `str`, `10 <= len <= 200`
      - `missing_keywords`: `list` where every element is in `ideal_keywords`
      - `trigger_follow_up`: `bool`
      - Raise `ValueError(f"Validation failed for field '{field}': {value}")` on any failure
    - Step 12: `return result`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

  - [ ]* 9.2 Write property test for trigger_follow_up consistency (P5)
    - **Property 5: trigger_follow_up consistency with verdict**
    - `@given(st.integers(4, 20))` for total; mock pipeline to produce that total
    - Assert `trigger_follow_up == True` iff `verdict == "weak"` (i.e., `total < WEAK_SCORE_THRESHOLD`)
    - Assert `trigger_follow_up == False` for `verdict in ("good", "strong")`
    - Tag: `# Feature: evaluator-agent, Property 5: trigger_follow_up consistency with verdict`
    - **Validates: Requirements 5.1, 5.2, 5.3**

- [x] 10. Checkpoint — Core pipeline complete
  - Ensure all tests pass, ask the user if questions arise.
  - All 12 pipeline steps must be implemented and reachable
  - `evaluate_answer` and `get_follow_up_question` must be importable from `agents.evaluator`

- [x] 11. Write unit tests in `tests/test_evaluator.py`
  - [x] 11.1 Create `tests/test_evaluator.py` with unit test cases for boundary conditions and error paths
    - **Length boundary:** `len(user_answer) == MIN_ANSWER_LENGTH` → LLM is called (not penalty path)
    - **Penalty path skips sleep:** Mock `time.sleep`; assert NOT called when `len(user_answer) < MIN_ANSWER_LENGTH`
    - **Rate limit sleep called:** Mock `time.sleep`; assert called with `RATE_LIMIT_SLEEP` before LLM on full path
    - **LLM call count:** Mock `_safe_llm_call`; assert called exactly once per `evaluate_answer` invocation on full path
    - **Non-numeric subscore:** Pass `None`, `"five"`, missing key → assert `ValueError` raised with subscore name
    - **Missing required key:** Mock LLM response that omits `"feedback"` → assert `ValueError` raised naming the missing key
    - **JSON retry behavior:** Mock `model.generate_content` to return invalid JSON on attempt 1, valid JSON on attempt 2; assert retry occurred and final result is valid
    - **API error retry:** Mock `model.generate_content` to raise `Exception` on attempt 1, succeed on attempt 2; assert 8s sleep and valid result returned
    - **Off-topic feedback override:** `relevance=1` with generic LLM feedback → assert `feedback` equals override message
    - **System prompt suffix:** Assert `SYSTEM_PROMPT.endswith("Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only.")`
    - **`get_follow_up_question` empty list:** `follow_ups=[]`, `count=0` → generic fallback returned
    - **`get_follow_up_question` negative count:** `count=-1` → `None` returned
    - **Token usage logging:** Capture stdout; verify output contains `[Evaluator] Success. Tokens:` format
    - _Requirements: 1.4, 2.1, 2.3, 6.9, 7.4, 12.1, 14.1, 15.2, 15.4, 16.1_

  - [ ]* 11.2 Write property test for `_safe_llm_call` JSON retry (part of P9 test file)
    - Additional Hypothesis test: `@given(st.text())` for malformed JSON strings; assert `_safe_llm_call` either returns a dict or raises `ValueError`/re-raises `Exception`, never silently returns `None`
    - Tag: `# Feature: evaluator-agent, Property 9: Exception propagation from safe_llm_call`
    - **Validates: Requirements 15.3, 15.5**

- [x] 12. Final checkpoint — All tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Run `pytest tests/test_evaluator.py -v` to confirm green
  - Verify `agents/evaluator.py` has no hardcoded numeric literals for thresholds or sleeps
  - Verify all 6 Evaluation_Dict keys are present and validated in Step 11

---

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use the **Hypothesis** library (`hypothesis` must be added to dev dependencies); configure each with `@settings(max_examples=100)`
- Each property test MUST include the tag comment: `# Feature: evaluator-agent, Property {N}: {text}`
- The `_safe_llm_call` retry sleep values (4s for JSON, 8s for API errors) are hardcoded in the template from `agents.md` — these are the only permitted hardcoded numeric literals in `evaluator.py`; all other numbers use config constants
- The processing pipeline order (Steps 1–12) is critical and must not be reordered
- `evaluate_answer` is stateless — all context passed as parameters; no module-level mutable state

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "3.1"] },
    { "id": 2, "tasks": ["4.1", "5.1"] },
    { "id": 3, "tasks": ["6.1", "2.2", "4.2", "5.2"] },
    { "id": 4, "tasks": ["7.1", "6.2", "6.3"] },
    { "id": 5, "tasks": ["8.1", "8.2", "7.2"] },
    { "id": 6, "tasks": ["9.1", "8.3", "8.4", "8.5"] },
    { "id": 7, "tasks": ["9.2", "11.1"] },
    { "id": 8, "tasks": ["11.2"] }
  ]
}
```

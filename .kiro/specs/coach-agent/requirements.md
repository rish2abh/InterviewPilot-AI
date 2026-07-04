# Requirements Document

## Introduction

The Coach Agent is the final-report generation component of the Mock Interview Stress Tester. Implemented as `agents/coach.py`, it exposes a single public function `generate_report(session_id, answers)` that compresses answer data, makes exactly one LLM call to Gemini, and returns a validated 11-key report dict. The Coach Agent owns the logic for answer compression, hiring probability calculation, and output contract validation. It never persists data directly — the orchestrator handles database writes. All numeric constants are imported from `core/config.py`.

## Glossary

- **Coach_Agent**: The Python module `agents/coach.py` containing the public function `generate_report` and supporting private helpers
- **generate_report**: The single public function with signature `generate_report(session_id: str, answers: list[dict]) -> dict` that produces the final performance report
- **Answer_Dict**: A dict as returned by `database.get_answers()` containing keys: question, answer_text, evaluation (a nested dict with scores, total, verdict, feedback, missing_keywords, trigger_follow_up), category, and other metadata
- **Compressed_Answer**: A dict containing only score (int), category (str), and missing_keywords (list[str]) extracted from an Answer_Dict — never contains raw answer text
- **Report_Dict**: The validated 11-key output dict: overall_score, hiring_probability, hiring_probability_percent, strongest_category, weakest_category, category_averages, top_3_strengths, top_3_improvements, critical_moment, overall_verdict, next_interview_tip
- **Improvement_Entry**: A dict within top_3_improvements containing exactly four keys: area (str), why (str), how_to_fix (str), free_resource (str URL)
- **_safe_llm_call**: The private helper function (matching the pattern from `agents/evaluator.py`) that handles LLM invocation with retry logic, JSON stripping, and error handling
- **GEMINI_API_KEY**: The API key loaded from the environment via `core/config.py`, used to configure the google-generativeai client
- **GEMINI_MODEL**: The model identifier string from `core/config.py` (value: "gemini-2.0-flash-exp")
- **MAX_TOKENS_REPORT**: The maximum output token budget for the Coach LLM call, value 1500 from `core/config.py`
- **RATE_LIMIT_SLEEP**: Seconds to sleep before the LLM call to respect Gemini rate limits, value 4 from `core/config.py`
- **ERROR_RETRY_SLEEP**: Seconds to sleep before retrying after a non-JSON API error, value 8 from `core/config.py`
- **MAX_TOTAL_SCORE**: The maximum possible aggregate score across all questions (value 200 from `core/config.py`), used for hiring_probability_percent calculation
- **HIRING_LOW_MAX**: The threshold below which overall_score maps to hiring probability "Low" (value 80 from `core/config.py`)
- **HIRING_HIGH_MIN**: The threshold above which overall_score maps to hiring probability "High" (value 140 from `core/config.py`)
- **TOTAL_QUESTIONS**: The constant value 10 from `core/config.py` defining the exact number of interview questions per session
- **overall_score**: An integer representing the sum of all individual answer scores (evaluation totals) across the session

## Requirements

### Requirement 1: Answer Compression Before LLM Call

**User Story:** As a developer, I want the Coach Agent to compress answer data before passing it to the LLM, so that token usage is minimized and raw answer text never leaks into the prompt.

#### Acceptance Criteria

1. WHEN generate_report receives a list of Answer_Dict objects, THE Coach_Agent SHALL extract only the score (evaluation.total), category, and missing_keywords (evaluation.missing_keywords) from each Answer_Dict to produce a list of Compressed_Answer dicts
2. THE Coach_Agent SHALL never include the raw answer_text field, the full evaluation.feedback field, or the original question text in the data passed to the LLM prompt
3. WHEN constructing Compressed_Answer dicts, THE Coach_Agent SHALL include the question index (1-based position in the answers list) in each compressed entry so the LLM can reference specific question numbers
4. IF an Answer_Dict is missing the evaluation key or the evaluation dict is missing the total or missing_keywords keys, THEN THE Coach_Agent SHALL raise a ValueError identifying the malformed answer and its index

### Requirement 2: LLM Call and Prompt Construction

**User Story:** As a developer, I want the Coach Agent to make exactly one LLM call using the established safe-call pattern, so that report generation is reliable and follows project conventions.

#### Acceptance Criteria

1. THE Coach_Agent SHALL make exactly one LLM call per invocation of generate_report, using the _safe_llm_call pattern (retry logic, JSON stripping, markdown removal) as implemented in `agents/evaluator.py`
2. WHEN invoking the LLM, THE Coach_Agent SHALL configure the google-generativeai client with GEMINI_API_KEY from `core/config.py` and instantiate the model using GEMINI_MODEL from `core/config.py`
3. WHEN invoking the LLM, THE Coach_Agent SHALL pass MAX_TOKENS_REPORT from `core/config.py` as the max_output_tokens generation config parameter
4. THE Coach_Agent SHALL construct a system prompt that ends with the exact string: "Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."
5. WHEN constructing the user prompt, THE Coach_Agent SHALL include the compressed answers list (as JSON), the session_id for reference, and the total number of questions answered
6. THE Coach_Agent SHALL pass "Coach" as the agent_name parameter to _safe_llm_call for logging purposes

### Requirement 3: Rate Limiting

**User Story:** As a developer, I want the Coach Agent to respect Gemini API rate limits, so that the system avoids 429 throttling errors.

#### Acceptance Criteria

1. WHEN generate_report is called, THE Coach_Agent SHALL execute time.sleep(RATE_LIMIT_SLEEP) before making the LLM call, using the RATE_LIMIT_SLEEP constant from `core/config.py`
2. THE Coach_Agent SHALL use ERROR_RETRY_SLEEP from `core/config.py` as the wait duration when retrying after a non-JSON API error (handled within _safe_llm_call)
3. THE Coach_Agent SHALL contain no hardcoded numeric sleep durations; all timing values SHALL reference named constants from `core/config.py`

### Requirement 4: Hiring Probability Calculation

**User Story:** As a job seeker, I want an accurate hiring probability derived from my aggregate score using defined thresholds, so that I understand my competitive positioning.

#### Acceptance Criteria

1. WHEN the Report_Dict is assembled, THE Coach_Agent SHALL calculate overall_score as the sum of evaluation.total values from all Answer_Dict objects in the answers list
2. WHEN overall_score is strictly less than HIRING_LOW_MAX (80), THE Coach_Agent SHALL set hiring_probability to the string "Low"
3. WHEN overall_score is greater than or equal to HIRING_LOW_MAX (80) and less than or equal to HIRING_HIGH_MIN (140), THE Coach_Agent SHALL set hiring_probability to the string "Medium"
4. WHEN overall_score is strictly greater than HIRING_HIGH_MIN (140), THE Coach_Agent SHALL set hiring_probability to the string "High"
5. THE Coach_Agent SHALL calculate hiring_probability_percent as round((overall_score / MAX_TOTAL_SCORE) * 100), producing an integer in the range 0 to 100
6. THE Coach_Agent SHALL use HIRING_LOW_MAX, HIRING_HIGH_MIN, and MAX_TOTAL_SCORE from `core/config.py` for all threshold comparisons and percentage calculations, with no hardcoded numeric literals

### Requirement 5: Output Contract Validation (11-Key Report_Dict)

**User Story:** As a developer, I want the Coach Agent to validate its output against the exact 11-key contract before returning, so that corrupted or hallucinated data never reaches the orchestrator.

#### Acceptance Criteria

1. WHEN _safe_llm_call returns a dict, THE Coach_Agent SHALL verify that the dict contains all 11 required keys: overall_score, hiring_probability, hiring_probability_percent, strongest_category, weakest_category, category_averages, top_3_strengths, top_3_improvements, critical_moment, overall_verdict, next_interview_tip
2. IF the LLM response dict is missing any of the 11 required keys, THEN THE Coach_Agent SHALL raise a ValueError whose message identifies the missing keys
3. THE Coach_Agent SHALL override the LLM-returned overall_score with the locally calculated sum of evaluation.total values (deterministic recalculation, not trusting the LLM)
4. THE Coach_Agent SHALL override the LLM-returned hiring_probability with the locally calculated value derived from the deterministically calculated overall_score using config.py bands
5. THE Coach_Agent SHALL override the LLM-returned hiring_probability_percent with the locally calculated value: round((overall_score / MAX_TOTAL_SCORE) * 100)
6. IF the LLM response dict contains extra keys beyond the 11 required keys, THEN THE Coach_Agent SHALL strip the extra keys before returning
7. THE Coach_Agent SHALL validate that strongest_category (str), weakest_category (str), overall_verdict (str), next_interview_tip (str), and critical_moment (str) are non-empty strings
8. THE Coach_Agent SHALL validate that category_averages is a dict with string keys and numeric values
9. THE Coach_Agent SHALL validate that top_3_strengths is a list containing exactly 3 string entries
10. THE Coach_Agent SHALL validate that top_3_improvements is a list containing exactly 3 Improvement_Entry dicts

### Requirement 6: top_3_improvements Structure and Resource URLs

**User Story:** As a job seeker, I want each improvement suggestion to include a specific explanation and a real learning resource URL, so that I have actionable next steps.

#### Acceptance Criteria

1. THE Coach_Agent SHALL validate that each entry in top_3_improvements is a dict containing exactly four keys: area (str), why (str), how_to_fix (str), and free_resource (str)
2. THE Coach_Agent SHALL validate that each free_resource value starts with "http://" or "https://" (a syntactically valid URL)
3. IF any entry in top_3_improvements is missing a required key (area, why, how_to_fix, free_resource) or contains a non-string value for any key, THEN THE Coach_Agent SHALL raise a ValueError identifying the invalid entry and the specific field that failed validation
4. THE Coach_Agent system prompt SHALL instruct the LLM to provide real, well-known free resource URLs (such as neetcode.io, pramp.com, leetcode.com, freecodecamp.org, developer.mozilla.org) and to never return placeholder URLs or generic advice without a URL
5. IF a free_resource value is an empty string, THEN THE Coach_Agent SHALL raise a ValueError indicating the resource URL is missing for that improvement entry

### Requirement 7: critical_moment Specificity

**User Story:** As a job seeker, I want the critical moment to reference a specific question from my session, so that I can pinpoint exactly where my performance shifted.

#### Acceptance Criteria

1. THE Coach_Agent system prompt SHALL instruct the LLM to reference a specific question number (1-based) from the session in the critical_moment field
2. THE Coach_Agent SHALL validate that the critical_moment string is non-empty and contains at least one numeric digit referencing a question number
3. IF critical_moment does not contain any digit character, THEN THE Coach_Agent SHALL raise a ValueError indicating the critical moment must reference a specific question number

### Requirement 8: Input Validation

**User Story:** As a developer, I want all inputs validated at the Coach Agent boundary, so that invalid data is caught early with clear error messages.

#### Acceptance Criteria

1. WHEN generate_report receives a session_id that is None, empty, or contains only whitespace, THE Coach_Agent SHALL raise a ValueError indicating the session_id is invalid
2. WHEN generate_report receives an answers parameter that is not a list, THE Coach_Agent SHALL raise a ValueError indicating answers must be a list
3. WHEN generate_report receives an empty answers list, THE Coach_Agent SHALL raise a ValueError indicating no answers were provided
4. WHEN generate_report receives an answers list with a length not equal to TOTAL_QUESTIONS (10), THE Coach_Agent SHALL raise a ValueError indicating the expected count and actual count
5. WHEN generate_report receives an Answer_Dict where evaluation is not a dict or is missing the total key (int) or missing_keywords key (list), THE Coach_Agent SHALL raise a ValueError identifying the malformed entry by index
6. WHEN generate_report receives an Answer_Dict where the category key is missing or is not a non-empty string, THE Coach_Agent SHALL raise a ValueError identifying the malformed entry by index

### Requirement 9: Error Handling

**User Story:** As a developer, I want the Coach Agent to handle LLM failures gracefully with clear error propagation, so that the orchestrator can transition to STATE_ERROR with a meaningful reason.

#### Acceptance Criteria

1. IF _safe_llm_call raises a ValueError after exhausting retry attempts (JSON parse failure on both attempts), THEN THE Coach_Agent SHALL propagate the ValueError to the caller without catching or transforming it
2. IF _safe_llm_call raises a non-ValueError exception after exhausting retry attempts (API error on both attempts), THEN THE Coach_Agent SHALL propagate the exception to the caller without catching or transforming it
3. IF output contract validation fails (missing keys, invalid types, or structural violations), THEN THE Coach_Agent SHALL raise a ValueError with a message that includes "Coach" and describes the specific validation failure
4. THE Coach_Agent SHALL not catch or suppress any exception raised during input validation — all ValueErrors from input checks SHALL propagate directly to the caller

### Requirement 10: Constants and Configuration Usage

**User Story:** As a developer, I want the Coach Agent to use only named constants from config.py with no magic numbers, so that the module remains maintainable and consistent with the rest of the codebase.

#### Acceptance Criteria

1. THE Coach_Agent SHALL import and use GEMINI_API_KEY, GEMINI_MODEL, MAX_TOKENS_REPORT, RATE_LIMIT_SLEEP, ERROR_RETRY_SLEEP, HIRING_LOW_MAX, HIRING_HIGH_MIN, MAX_TOTAL_SCORE, and TOTAL_QUESTIONS from `core/config.py`
2. THE Coach_Agent SHALL contain no hardcoded numeric literals for score thresholds, token limits, sleep durations, question counts, or score maximums
3. WHEN configuring the google-generativeai client, THE Coach_Agent SHALL use GEMINI_API_KEY from `core/config.py` as the api_key parameter passed to genai.configure
4. WHEN instantiating the GenerativeModel, THE Coach_Agent SHALL use GEMINI_MODEL from `core/config.py` as the model name string
5. THE Coach_Agent SHALL import only from approved libraries: google.generativeai, json, re, time, and core.config — no other external dependencies

### Requirement 11: Function Signature and Return Contract

**User Story:** As a developer, I want a stable public API contract for the Coach Agent, so that the orchestrator and tests can depend on a predictable interface.

#### Acceptance Criteria

1. THE Coach_Agent SHALL expose exactly one public function: generate_report(session_id: str, answers: list[dict]) -> dict
2. THE Coach_Agent SHALL return a dict containing exactly 11 keys with the following types: overall_score (int), hiring_probability (str, one of "Low", "Medium", "High"), hiring_probability_percent (int, range 0 to 100), strongest_category (str), weakest_category (str), category_averages (dict with str keys and numeric values), top_3_strengths (list of exactly 3 str), top_3_improvements (list of exactly 3 Improvement_Entry dicts), critical_moment (str containing at least one digit), overall_verdict (str), next_interview_tip (str)
3. THE Coach_Agent SHALL not expose any other public functions or classes; all helpers SHALL be prefixed with an underscore to indicate private scope
4. THE Coach_Agent SHALL not perform any database operations — all persistence is delegated to the orchestrator calling `core/database.py` functions after receiving the Report_Dict

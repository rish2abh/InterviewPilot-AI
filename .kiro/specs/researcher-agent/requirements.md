# Requirements Document

## Introduction

The Researcher Agent is a Python function (`research_company`) in `agents/researcher.py` that takes a company name, role, and experience level as input, then uses Gemini 2.0 Flash with search grounding to discover company-specific interview patterns. It returns a validated JSON dict with exactly 8 keys representing the research findings. The agent follows the `safe_llm_call` template pattern with 2 retry attempts, handles edge cases gracefully, and returns a safe default dict when the API fails.

## Glossary

- **Researcher_Agent**: The Python function `research_company` in `agents/researcher.py` that performs company interview research via Gemini Search Grounding
- **Search_Grounding**: A Gemini API feature that enables the LLM to search the web for current information before generating a response
- **Safe_LLM_Call**: A wrapper function following the steering template that handles retries, markdown stripping, JSON parsing, and error logging for all LLM calls
- **Research_Dict**: The validated Python dictionary with exactly 8 keys returned by the Researcher_Agent on a successful call
- **Default_Dict**: A fallback dictionary with role-appropriate generic values and `error_flag=True`, returned when any unrecoverable error occurs after input validation passes
- **Rate_Limit_Sleep**: A mandatory 4-second pause (`RATE_LIMIT_SLEEP` from `core.config`) between consecutive LLM calls to avoid API rate limiting
- **MAX_TOKENS_COMPLEX**: The constant value 1000 from `core/config.py` used as the maximum output token limit for researcher and question generator agents
- **Input_Sanitization**: The process of removing special characters from company names and role strings before building the search query

## Requirements

### Requirement 1: Research Company Interview Patterns

**User Story:** As a job seeker, I want the system to research my target company's interview patterns, so that I receive company-specific mock interview questions.

#### Acceptance Criteria

1. WHEN the Researcher_Agent receives a company name (1–100 characters, non-empty string), a role (1–100 characters, non-empty string), and an experience level (one of: fresher, junior, senior, lead, or manager), THE Researcher_Agent SHALL call Gemini 2.0 Flash with Search_Grounding enabled and return a validated dict containing exactly the keys: company, role, interview_rounds, key_topics, difficulty, culture_keywords, known_question_types, and red_flags_to_test
2. THE Researcher_Agent SHALL make exactly one LLM call per attempt (up to a maximum of 2 attempts via the `safe_llm_call` retry pattern) per invocation, using `MAX_TOKENS_COMPLEX` as the token limit for every call
3. THE Researcher_Agent SHALL unconditionally call `time.sleep(RATE_LIMIT_SLEEP)` from `core.config` before making the LLM call, because the researcher always follows the SETUP state in the orchestrator and a prior LLM call will always have preceded it
4. IF the LLM call fails after 2 attempts or returns a response that cannot be validated into the required dict structure, THEN THE Researcher_Agent SHALL catch the resulting exception and return a Default_Dict containing exactly 9 keys: the 8 required Research_Dict keys populated with role-appropriate generic values, plus `error_flag` set to True
5. WHEN the Researcher_Agent successfully parses the LLM response, THE Researcher_Agent SHALL verify that all 8 required keys are present, that each string-typed key (`company`, `role`, `interview_rounds`, `difficulty`) has a non-empty string value after stripping whitespace, that each list-typed key (`key_topics`, `culture_keywords`, `known_question_types`, `red_flags_to_test`) has a non-empty list where every element is a non-empty string, and that `difficulty` is one of: "easy", "medium", "hard", or "expert"; THE Researcher_Agent SHALL strip any extra keys beyond the required 8 before returning

### Requirement 2: Return Validated Research Dictionary

**User Story:** As the question generator agent, I want a structured research dictionary from the researcher, so that I can generate targeted interview questions.

#### Acceptance Criteria

1. THE Researcher_Agent SHALL return a Research_Dict containing exactly these 8 keys with the following types: `company` (str), `role` (str), `interview_rounds` (str), `key_topics` (list of str), `difficulty` (str), `culture_keywords` (list of str), `known_question_types` (list of str), `red_flags_to_test` (list of str)
2. THE Researcher_Agent SHALL validate that all 8 keys are present and that each value is of the correct type and is non-empty (strings have length >= 1 after stripping whitespace, lists have at least 1 non-empty-string element) before returning
3. IF the LLM response contains extra keys beyond the required 8, THEN THE Researcher_Agent SHALL strip the extra keys from the result, retaining only the 8 required keys
4. IF the LLM response is missing any of the 8 required keys or any value fails type or non-empty validation, THEN THE `_validate_research_dict` function SHALL raise a ValueError indicating which key failed validation
5. IF `_validate_research_dict` raises a ValueError, THEN THE `research_company` function SHALL catch that ValueError and return a Default_Dict rather than propagating it to the caller
6. WHEN the LLM response passes all validation checks, THE Researcher_Agent SHALL return a Research_Dict containing exactly the 8 required keys with no `error_flag` key present; the `error_flag` key is absent on every successful return path
7. IF the LLM response cannot be parsed as valid JSON on the first attempt, THEN THE Researcher_Agent SHALL retry exactly once after appending a JSON-only instruction to the prompt, waiting `RATE_LIMIT_SLEEP` (4 seconds) before the retry
8. IF the retry in criterion 7 also fails to produce valid JSON, THEN THE `_safe_llm_call` function SHALL raise a ValueError indicating JSON parsing failure after 2 attempts
9. IF `_safe_llm_call` raises a ValueError per criterion 8, THEN THE `research_company` function SHALL catch that ValueError and return a Default_Dict
10. THE Default_Dict returned by the fallback paths in criteria 5 and 9 SHALL contain exactly these 9 keys: `company` (the sanitized input value), `role` (the sanitized input value), `interview_rounds` set to "3 rounds", `key_topics` (list of role-appropriate topics), `difficulty` (level-appropriate value), `culture_keywords` set to `["collaboration", "ownership"]`, `known_question_types` set to `["coding", "behavioural"]`, `red_flags_to_test` set to `["problem-solving approach", "communication clarity"]`, and `error_flag` set to `True`

### Requirement 3: Input Validation and Sanitization

**User Story:** As a developer, I want the researcher agent to validate and sanitize inputs, so that malformed data does not corrupt the LLM query.

#### Acceptance Criteria

1. IF the company name or role parameter is an empty string or contains only whitespace characters, THEN THE Researcher_Agent SHALL raise a ValueError with a message indicating which parameter failed validation and the reason for rejection; this ValueError is NOT caught by the top-level exception handler and propagates to the caller
2. IF the company name contains special characters (non-alphanumeric, non-space, non-hyphen), THEN THE Researcher_Agent SHALL remove those characters before building the search query
3. IF the company name or role parameter contains only special characters such that sanitization would result in an empty string, THEN THE Researcher_Agent SHALL raise a ValueError with a message indicating the input is invalid after sanitization; this ValueError propagates to the caller
4. THE Researcher_Agent SHALL accept company names and role strings containing only letters, digits, spaces, and hyphens as valid without modification
5. IF the role parameter contains special characters (non-alphanumeric, non-space, non-hyphen), THEN THE Researcher_Agent SHALL remove those characters before building the search query
6. IF the company name or role parameter exceeds 100 characters in length, THEN THE Researcher_Agent SHALL truncate the input to 100 characters as the first step of sanitization, before special character removal, so that the 100-character cap applies to the pre-sanitized string

### Requirement 4: Markdown Stripping from LLM Response

**User Story:** As a developer, I want markdown formatting removed from LLM responses, so that JSON parsing succeeds reliably.

#### Acceptance Criteria

1. WHEN the LLM returns a response containing a markdown code block with json language identifier (` ```json ... ``` `), THE Safe_LLM_Call SHALL remove the opening ` ```json ` delimiter and the closing ` ``` ` delimiter, extracting only the content between them, before JSON parsing
2. WHEN the LLM returns a response containing a generic markdown code block (` ``` ... ``` `) without a language identifier, THE Safe_LLM_Call SHALL remove the opening ` ``` ` delimiter and the closing ` ``` ` delimiter, extracting only the content between them, before JSON parsing
3. THE Safe_LLM_Call SHALL apply stripping in this order: first remove ` ```json ` delimiters, then remove generic ` ``` ` delimiters, then trim whitespace
4. THE Safe_LLM_Call SHALL trim all leading and trailing whitespace characters (spaces, tabs, newlines) from the response text after stripping markdown delimiters
5. IF the response text contains prose before or after the first occurring code block delimiters, THEN THE Safe_LLM_Call SHALL discard all text outside the first occurring code block delimiters and parse only the content within
6. WHEN the LLM returns a response that contains no markdown code block delimiters, THE Safe_LLM_Call SHALL attempt JSON parsing directly on the whitespace-trimmed response text without modification
7. IF the response text is empty or contains only whitespace after all stripping steps, THEN THE Safe_LLM_Call SHALL raise a json.JSONDecodeError (or equivalent parse failure) rather than attempting to parse an empty string

### Requirement 5: Retry Logic and Error Handling

**User Story:** As a user, I want the system to retry failed API calls, so that transient errors do not prevent me from starting my mock interview.

#### Acceptance Criteria

1. WHEN the LLM response fails JSON parsing on the first attempt, THE Safe_LLM_Call SHALL wait `RATE_LIMIT_SLEEP` seconds, append the corrective instruction "RETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER." to the prompt, and retry the call exactly once
2. IF the LLM response fails JSON parsing on both attempts, THEN THE Safe_LLM_Call SHALL raise a ValueError with a message containing the agent name and indicating that the agent failed after 2 attempts
3. WHEN a non-JSON exception (including network timeout, API connectivity error, or server error) occurs on the first attempt, THE Safe_LLM_Call SHALL wait `ERROR_RETRY_SLEEP` seconds from `core.config` and retry the call exactly once without modifying the prompt
4. IF a non-JSON exception occurs on both attempts, THEN THE Safe_LLM_Call SHALL re-raise the original exception to the calling agent
5. IF the `research_company` function receives any unrecoverable exception from `_safe_llm_call` or `_validate_research_dict` — specifically: (a) a re-raised API/network exception per criterion 4, (b) a ValueError from `_safe_llm_call` after 2 failed JSON parse attempts, or (c) a ValueError from `_validate_research_dict` for missing or invalid keys — THEN THE `research_company` function SHALL catch the exception in its top-level try/except block and return a Default_Dict with role-appropriate values and `error_flag=True`; the `key_topics` list SHALL be selected based on role category keywords (ML/AI keywords → machine learning topics; data keywords → SQL/ETL topics; PM keywords → product strategy topics; DevOps/infrastructure keywords → CI/CD topics; frontend keywords → JavaScript topics; backend/API keywords → API design topics; all others → data structures/algorithms topics) and the `difficulty` value SHALL be mapped as: fresher→"easy", junior→"medium", senior→"hard", lead/manager→"expert", any unrecognized level→"medium"
6. THE Safe_LLM_Call SHALL limit retry attempts to a maximum of 2 total attempts (1 initial + 1 retry) per invocation, regardless of error type
7. IF the `research_company` function receives a ValueError raised by `_sanitize_input` due to an empty, whitespace-only, or all-special-character input for `company` or `role`, THEN THE `research_company` function SHALL NOT catch that ValueError; it SHALL propagate directly to the caller as a programming error that must be corrected at the call site

### Requirement 6: Safe Default for API Failures

**User Story:** As a user, I want the system to continue working even when the API fails, so that I still get a functional (if generic) interview experience.

#### Acceptance Criteria

1. IF the `research_company` function catches an unrecoverable API/network exception after `_safe_llm_call` exhausts its 2 retry attempts, THEN THE Researcher_Agent SHALL return a Default_Dict with role-appropriate generic values
2. IF `_validate_research_dict` raises a ValueError for a missing key or invalid value in the LLM response, THEN THE Researcher_Agent SHALL return a Default_Dict with role-appropriate generic values
3. THE Default_Dict SHALL contain exactly these 9 keys: `company` (str), `role` (str), `interview_rounds` (str), `key_topics` (list of str), `difficulty` (str), `culture_keywords` (list of str), `known_question_types` (list of str), `red_flags_to_test` (list of str), and `error_flag` (bool set to True)
4. THE Default_Dict SHALL set `difficulty` to "easy" for fresher, "medium" for junior, "hard" for senior, and "expert" for lead or manager experience levels; IF the provided level does not match any of these five values (case-insensitive), THEN THE Default_Dict SHALL set `difficulty` to "medium" as a safe fallback
5. THE Default_Dict SHALL populate `key_topics` with at least 3 and at most 5 generic topics: for ML/AI roles → `["machine learning", "statistics", "python", "model evaluation", "data pipelines"]`; for data engineering/analyst roles → `["sql", "data modeling", "etl pipelines", "data warehousing", "python"]`; for PM roles → `["product strategy", "user research", "metrics", "prioritization", "stakeholder management"]`; for DevOps/SRE/infrastructure roles → `["ci/cd", "containerization", "cloud infrastructure", "monitoring", "incident response"]`; for frontend roles → `["javascript", "html/css", "browser rendering", "state management", "performance optimization"]`; for backend/API roles → `["api design", "databases", "system design", "concurrency", "caching"]`; for all other roles → `["data structures", "algorithms", "system design", "object-oriented design", "debugging"]`
6. THE Default_Dict SHALL set `interview_rounds` to "3 rounds"
7. WHEN the Default_Dict is returned, THE Researcher_Agent SHALL print a warning to the console in the format `[Researcher] Unrecoverable error, returning default dict: {error_message}` where `{error_message}` is the string representation of the caught exception

### Requirement 7: Handle Unknown Companies

**User Story:** As a job seeker targeting a less-known company, I want the system to still provide useful interview preparation, so that I can practice even when company-specific data is unavailable.

#### Acceptance Criteria

1. THE Researcher_Agent system prompt SHALL contain an explicit instruction directing the LLM to use role-appropriate and level-appropriate industry defaults for all 8 Research_Dict keys when it cannot find company-specific data via Search_Grounding, so that unknown companies do not produce empty or null values in the response
2. IF fewer than 5 of the 8 returned Research_Dict fields contain company-specific content (i.e., 5 or more fields contain only generic/default values), THEN the LLM-populated response will be treated identically to a fully valid response since the system prompt handles this case; the `error_flag` key will only be set to True if validation fails and the Default_Dict path is triggered
3. IF `error_flag` is True in the returned dict, THEN THE Researcher_Agent SHALL have returned a complete dict containing all 8 required keys with non-empty values, ensuring that downstream agents can proceed without interruption

### Requirement 8: Token Usage Logging

**User Story:** As a developer, I want token usage logged to console after each LLM call, so that I can monitor API costs and optimize prompts.

#### Acceptance Criteria

1. WHEN the LLM call succeeds, THE Safe_LLM_Call SHALL print token usage metadata to the console in the format `[{agent_name}] Success. Tokens: {usage_metadata}`, where `{agent_name}` is the name of the calling agent (e.g., Researcher, QuestionGenerator, Evaluator, Coach) and `{usage_metadata}` is the `response.usage_metadata` object returned by the google-generativeai SDK
2. WHEN the LLM call fails with a JSON parse error on attempt 1, THE Safe_LLM_Call SHALL print to the console in the format `[{agent_name}] JSON fail attempt 1: {error_message}`, where `{error_message}` is the exception message from the JSONDecodeError, and then wait `RATE_LIMIT_SLEEP` seconds before retrying
3. WHEN the LLM call fails with an API or network error on attempt 1, THE Safe_LLM_Call SHALL print to the console in the format `[{agent_name}] API error attempt 1: {error_message}`, where `{error_message}` is the exception message, and then wait `ERROR_RETRY_SLEEP` seconds before retrying
4. IF the LLM call fails on the final attempt (attempt 2), THEN THE Safe_LLM_Call SHALL print the failure log for attempt 2 using the same format patterns as criteria 2 and 3, and then raise a ValueError (for JSON parse failures) or re-raise the original exception (for API errors) without any additional sleep

### Requirement 9: System Prompt Compliance

**User Story:** As a developer, I want the researcher agent to follow the system prompt convention, so that LLM responses are consistently formatted as raw JSON.

#### Acceptance Criteria

1. THE Researcher_Agent system prompt SHALL end with the exact text: "Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."
2. THE Researcher_Agent system prompt text SHALL contain all 8 of the following key names as literal strings: "company", "role", "interview_rounds", "key_topics", "difficulty", "culture_keywords", "known_question_types", "red_flags_to_test", so that the LLM is aware of the exact keys to populate
3. IF the LLM response cannot be parsed as valid JSON after 2 attempts, THEN THE `_safe_llm_call` function SHALL raise a ValueError with a message containing both the agent name ("Researcher") and a description indicating JSON parse failure after 2 attempts
4. THE Researcher_Agent SHALL invoke the LLM with search grounding enabled using the `google_search_retrieval` tool name and a maximum output token limit set to `MAX_TOKENS_COMPLEX` from `core.config`
5. WHEN the Researcher_Agent successfully receives and validates the LLM response, THE returned dict SHALL contain exactly the 8 required keys with non-null, non-empty values of the correct types: `company` (str), `role` (str), `interview_rounds` (str), `key_topics` (list of str, min 1 element), `difficulty` (str, one of: "easy", "medium", "hard", "expert"), `culture_keywords` (list of str, min 1 element), `known_question_types` (list of str, min 1 element), `red_flags_to_test` (list of str, min 1 element)

### Requirement 10: Configuration and Constants Usage

**User Story:** As a developer, I want all magic numbers replaced with named constants from config, so that the codebase remains maintainable and consistent.

#### Acceptance Criteria

1. THE Researcher_Agent SHALL import `MAX_TOKENS_COMPLEX` from `core.config` and use it as the sole value for the `max_output_tokens` generation config parameter in all LLM calls, including both the initial attempt and the retry attempt within `_safe_llm_call`
2. THE Researcher_Agent SHALL import `RATE_LIMIT_SLEEP` from `core.config` and use it as the duration for all `time.sleep()` calls that enforce rate limiting between consecutive LLM calls; error-retry backoff sleeps SHALL use the separate named constant `ERROR_RETRY_SLEEP` from `core.config` and never a hardcoded numeric literal
3. THE Researcher_Agent SHALL contain no hardcoded numeric literals for token limits, sleep durations, retry attempt counts, input length limits, or score thresholds; each such value SHALL reference a named constant imported from `core.config` or defined as a module-level named constant within `researcher.py`
4. IF a required constant (specifically `MAX_TOKENS_COMPLEX`, `RATE_LIMIT_SLEEP`, `ERROR_RETRY_SLEEP`, or `GEMINI_MODEL`) is not defined in `core.config` at import time, THEN the `from core.config import (...)` statement SHALL raise an `ImportError` preventing the module from loading, with the missing constant name identifiable from the import error message

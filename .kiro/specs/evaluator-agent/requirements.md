# Requirements Document

## Introduction

The Evaluator Agent is a Python function (`evaluate_answer`) in `agents/evaluator.py` that scores user interview answers on four dimensions (relevance, depth, structure, examples) each rated 1–5 for a maximum total of 20. It short-circuits with a penalty response for answers under `MIN_ANSWER_LENGTH` (50 characters) without making an LLM call. The agent always recalculates the total from subscores (never trusting the LLM's total), determines a verdict (weak/good/strong), and returns a validated dict with exactly 6 keys. A companion function `get_follow_up_question` retrieves follow-up questions with bounds checking. Both functions are part of the Mock Interview Stress Tester multi-agent system and follow the `safe_llm_call` pattern with Gemini 2.0 Flash.

## Glossary

- **Evaluator_Agent**: The Python function `evaluate_answer` in `agents/evaluator.py` that scores user answers against ideal criteria using Gemini 2.0 Flash
- **Evaluation_Dict**: The validated Python dictionary returned by the Evaluator_Agent containing exactly 6 keys: `scores`, `total`, `verdict`, `feedback`, `missing_keywords`, `trigger_follow_up`
- **Scores_Dict**: A nested dictionary within Evaluation_Dict containing exactly 4 integer keys: `relevance`, `depth`, `structure`, `examples`, each valued 1–5
- **Penalty_Dict**: A pre-built Evaluation_Dict returned immediately (without LLM call) when the user answer is shorter than MIN_ANSWER_LENGTH
- **Safe_LLM_Call**: A wrapper function following the steering template that handles retries, markdown stripping, JSON parsing, and error logging for all LLM calls
- **MIN_ANSWER_LENGTH**: The constant value 50 from `core/config.py` representing the minimum character count required before LLM evaluation is triggered
- **MAX_TOKENS_SIMPLE**: The constant value 500 from `core/config.py` used as the maximum output token limit for the evaluator agent LLM calls
- **WEAK_SCORE_THRESHOLD**: The constant value 12 from `core/config.py` below which a verdict is classified as "weak" and a follow-up is triggered
- **STRONG_SCORE_THRESHOLD**: The constant value 16 from `core/config.py` above which a verdict is classified as "strong"
- **MAX_FOLLOW_UPS**: The constant value 2 from `core/config.py` representing the maximum number of follow-up questions allowed per topic
- **RATE_LIMIT_SLEEP**: The constant value 4 from `core/config.py` representing seconds to wait between consecutive LLM calls
- **Follow_Up_Function**: The Python function `get_follow_up_question` in `agents/evaluator.py` that retrieves the next follow-up question for a given topic
- **Question_Dict**: A dictionary representing a single interview question, containing at minimum the keys `question`, `ideal_keywords`, `follow_ups`, and `scoring_hint`

## Requirements

### Requirement 1: Evaluate User Answer with LLM Scoring

**User Story:** As a job seeker, I want my interview answers scored on multiple dimensions, so that I understand my strengths and weaknesses across different evaluation criteria.

#### Acceptance Criteria

1. WHEN the Evaluator_Agent receives a question (str), ideal_keywords (list of str), scoring_hint (str), user_answer (str with length >= MIN_ANSWER_LENGTH), and api_key (str), THE Evaluator_Agent SHALL call Gemini 2.0 Flash via Safe_LLM_Call with MAX_TOKENS_SIMPLE (500) as the token limit, apply subscore clamping and total recalculation to the LLM response, and return a validated Evaluation_Dict containing exactly 6 keys: scores, total, verdict, feedback, missing_keywords, and trigger_follow_up
2. THE Evaluator_Agent SHALL score the user_answer on exactly 4 dimensions: relevance, depth, structure, and examples, each rated as an integer from 1 to 5 inclusive, where 1 represents the lowest quality and 5 represents the highest quality for that dimension
3. THE Evaluator_Agent SHALL pass ONLY the question, ideal_keywords, scoring_hint, and user_answer to the LLM prompt, excluding all other context such as full research data, other questions, or session metadata
4. THE Evaluator_Agent SHALL make exactly one logical LLM evaluation per invocation, delegating the call to Safe_LLM_Call which may internally retry up to once on parse failure, but no additional LLM calls shall be made outside of Safe_LLM_Call
5. IF Safe_LLM_Call raises a ValueError or other exception after exhausting its retry attempts, THEN THE Evaluator_Agent SHALL propagate the exception to the caller without returning a partial Evaluation_Dict

### Requirement 2: Short Answer Penalty Without LLM Call

**User Story:** As a system operator, I want answers below the minimum length rejected immediately without consuming API tokens, so that costs are minimized and response time is instant.

#### Acceptance Criteria

1. WHEN the user_answer has fewer than MIN_ANSWER_LENGTH characters (measured by `len(user_answer)`), THE Evaluator_Agent SHALL return a Penalty_Dict without making any LLM call and without invoking any rate-limiting sleep
2. THE Penalty_Dict SHALL contain exactly 6 keys matching the Evaluation_Dict schema: scores set to `{"relevance": 1, "depth": 1, "structure": 1, "examples": 1}`, total set to 4, verdict set to "weak", feedback set to "Answer too short. Elaborate with a specific example.", missing_keywords set to the full ideal_keywords list passed as input, and trigger_follow_up set to True
3. WHEN the user_answer length equals exactly MIN_ANSWER_LENGTH characters, THE Evaluator_Agent SHALL proceed with LLM evaluation (penalty applies only when length is strictly less than MIN_ANSWER_LENGTH)
4. WHEN the user_answer is an empty string or contains only whitespace characters, THE Evaluator_Agent SHALL apply the penalty path (since `len(user_answer)` is less than MIN_ANSWER_LENGTH)

### Requirement 3: Total Recalculation from Subscores

**User Story:** As a developer, I want the total always computed from subscores, so that LLM hallucinated totals never corrupt the scoring data.

#### Acceptance Criteria

1. THE Evaluator_Agent SHALL calculate the total as the arithmetic sum of relevance + depth + structure + examples from the Scores_Dict after all subscores have been clamped to the range 1–5, regardless of any total value returned by the LLM
2. IF the LLM returns a total value that differs from the sum of the 4 clamped subscores, THEN THE Evaluator_Agent SHALL discard the LLM total and use the recalculated sum
3. THE Evaluator_Agent SHALL verify that the recalculated total falls within the range 4 to 20 inclusive (4 subscores each 1–5)
4. IF the recalculated total falls outside the range 4 to 20 inclusive after clamping, THEN THE Evaluator_Agent SHALL raise a ValueError indicating that the total validation failed

### Requirement 4: Verdict Classification

**User Story:** As a job seeker, I want a clear verdict on my answer quality, so that I immediately know whether I need to improve.

#### Acceptance Criteria

1. WHEN the recalculated total is less than WEAK_SCORE_THRESHOLD (12), THE Evaluator_Agent SHALL set verdict to "weak"
2. WHEN the recalculated total is greater than or equal to WEAK_SCORE_THRESHOLD (12) and less than or equal to STRONG_SCORE_THRESHOLD (16), THE Evaluator_Agent SHALL set verdict to "good"
3. WHEN the recalculated total is greater than STRONG_SCORE_THRESHOLD (16), THE Evaluator_Agent SHALL set verdict to "strong"
4. THE Evaluator_Agent SHALL always derive the verdict from the recalculated total, discarding any verdict value returned by the LLM

### Requirement 5: Follow-Up Triggering Based on Verdict

**User Story:** As a job seeker, I want the system to ask follow-up questions when my answer is weak, so that I get a chance to improve and demonstrate deeper knowledge.

#### Acceptance Criteria

1. WHEN the verdict is determined as "weak" (total less than WEAK_SCORE_THRESHOLD), THE Evaluator_Agent SHALL set trigger_follow_up to boolean True in the Evaluation_Dict
2. WHEN the verdict is determined as "good" or "strong" (total greater than or equal to WEAK_SCORE_THRESHOLD), THE Evaluator_Agent SHALL set trigger_follow_up to boolean False in the Evaluation_Dict
3. THE Evaluator_Agent SHALL set trigger_follow_up only after the verdict has been determined from the recalculated total, ensuring the boolean value is always consistent with the verdict field in the same Evaluation_Dict
4. IF the verdict field contains a value other than "weak", "good", or "strong" at the time trigger_follow_up is to be set, THEN THE Evaluator_Agent SHALL raise a ValueError indicating an invalid verdict was produced

### Requirement 6: Evaluation Dict Validation

**User Story:** As a developer, I want strict output validation on the evaluator response, so that downstream agents always receive a predictable data structure.

#### Acceptance Criteria

1. THE Evaluator_Agent SHALL return an Evaluation_Dict containing exactly 6 top-level keys: `scores`, `total`, `verdict`, `feedback`, `missing_keywords`, `trigger_follow_up`, and SHALL strip any extra keys not in this set before validation
2. THE Evaluator_Agent SHALL validate that `scores` is a dict with exactly 4 keys (`relevance`, `depth`, `structure`, `examples`), each an integer between 1 and 5 inclusive
3. THE Evaluator_Agent SHALL validate that `total` is an integer between 4 and 20 inclusive
4. THE Evaluator_Agent SHALL validate that `verdict` is one of exactly three string values: "weak", "good", or "strong"
5. THE Evaluator_Agent SHALL validate that `feedback` is a non-empty string between 10 and 500 characters containing exactly one sentence (no period-separated multi-sentence text)
6. THE Evaluator_Agent SHALL validate that `missing_keywords` is a list (which may be empty) where every element is a string present in the original ideal_keywords input
7. THE Evaluator_Agent SHALL validate that `trigger_follow_up` is a boolean value
8. IF any validation check fails after all corrections are applied (subscore clamping, total recalculation, verdict classification, feedback truncation, and missing_keywords filtering), THEN THE Evaluator_Agent SHALL raise a ValueError indicating which field failed validation and the invalid value encountered
9. IF any required key from the 6 top-level keys is missing from the LLM response, THEN THE Evaluator_Agent SHALL raise a ValueError indicating which key is absent

### Requirement 7: Subscore Clamping

**User Story:** As a developer, I want out-of-range scores corrected automatically, so that LLM hallucinated extreme values do not break the scoring system.

#### Acceptance Criteria

1. IF any subscore returned by the LLM is less than 1, THEN THE Evaluator_Agent SHALL clamp that subscore to 1
2. IF any subscore returned by the LLM is greater than 5, THEN THE Evaluator_Agent SHALL clamp that subscore to 5
3. IF any subscore returned by the LLM is not an integer, THEN THE Evaluator_Agent SHALL round it to the nearest integer using half-up rounding (values at .5 round toward positive infinity, e.g., 2.5 becomes 3) and then clamp the result to the range 1 to 5
4. IF any subscore returned by the LLM is not a numeric value (e.g., null, string, or missing key), THEN THE Evaluator_Agent SHALL raise a ValueError indicating which subscore field contains the non-numeric value

### Requirement 8: Feedback Format Enforcement

**User Story:** As a job seeker, I want concise, actionable feedback on each answer, so that I know exactly what to improve without reading lengthy paragraphs.

#### Acceptance Criteria

1. THE Evaluator_Agent SHALL ensure the feedback field contains exactly one sentence with a maximum length of 200 characters that provides a suggestion related to the user_answer content
2. IF the LLM returns feedback containing more than one sentence (detected by the regex pattern matching any of the sentence-ending punctuation marks ".", "!", or "?" followed by a space and an uppercase letter [A-Z]), THEN THE Evaluator_Agent SHALL truncate the feedback to the first sentence only (up to and including the first sentence-ending punctuation mark)
3. IF the LLM returns feedback that is empty or contains only whitespace characters, THEN THE Evaluator_Agent SHALL set feedback to the fallback value: "Review the ideal keywords and try incorporating them into your answer."
4. IF the truncated or LLM-returned feedback exceeds 200 characters, THEN THE Evaluator_Agent SHALL truncate it to the first 200 characters and append a period if the truncated text does not already end with a sentence-ending punctuation mark

### Requirement 9: Missing Keywords Filtering

**User Story:** As a job seeker, I want to know which key terms I missed in my answer, so that I can include them in follow-up responses or future interviews.

#### Acceptance Criteria

1. THE Evaluator_Agent SHALL populate missing_keywords with only strings that exist in the ideal_keywords input list, using case-sensitive exact string matching for comparison
2. IF the LLM returns missing_keywords containing items not present in the ideal_keywords input list, THEN THE Evaluator_Agent SHALL filter out those invalid entries and retain only entries that exactly match a string in ideal_keywords
3. IF the relevance score is 1, THEN THE Evaluator_Agent SHALL set missing_keywords to the full ideal_keywords list regardless of what the LLM returned (an off-topic answer misses all keywords)
4. IF the LLM returns missing_keywords containing duplicate entries, THEN THE Evaluator_Agent SHALL remove duplicates so that each keyword appears at most once in the final missing_keywords list

### Requirement 10: Get Follow-Up Question Function

**User Story:** As the orchestrator, I want to retrieve the next follow-up question for a topic, so that weak answers receive targeted follow-up probing.

#### Acceptance Criteria

1. WHEN the Follow_Up_Function receives a Question_Dict and a follow_up_count greater than or equal to MAX_FOLLOW_UPS, THE Follow_Up_Function SHALL return None without inspecting the `follow_ups` list
2. WHEN the Follow_Up_Function receives a Question_Dict and a follow_up_count that is a non-negative integer less than MAX_FOLLOW_UPS and less than the length of the `follow_ups` list, THE Follow_Up_Function SHALL return the string at index `follow_up_count` from the `follow_ups` list in the Question_Dict
3. IF the follow_up_count is a non-negative integer less than MAX_FOLLOW_UPS but greater than or equal to the length of the `follow_ups` list (including when the list is empty), THEN THE Follow_Up_Function SHALL return the generic text: "Can you elaborate on your answer with a specific example?"
4. IF the follow_up_count is a negative integer, THEN THE Follow_Up_Function SHALL return None
5. THE Follow_Up_Function SHALL accept exactly two parameters (question_dict: dict, follow_up_count: int) and return either a string or None

### Requirement 11: Off-Topic Answer Handling

**User Story:** As a job seeker, I want the system to detect when my answer is completely off-topic, so that I receive clear feedback to stay focused.

#### Acceptance Criteria

1. WHEN the LLM scores the relevance dimension as 1, THE Evaluator_Agent SHALL set missing_keywords to the full ideal_keywords list, regardless of what the LLM returned for missing_keywords
2. WHEN the relevance score is 1, THE Evaluator_Agent SHALL set trigger_follow_up to True (the recalculated total with relevance of 1 will produce a verdict of "weak" per Requirement 4, which triggers follow-up per Requirement 5)
3. WHEN the relevance score is 1 and the LLM-returned feedback does not reference the answer being off-topic or unrelated, THE Evaluator_Agent SHALL override feedback with a message indicating the answer was not relevant to the question and suggesting the user focus on the topic asked

### Requirement 12: Rate Limiting Compliance

**User Story:** As a developer, I want the evaluator to respect API rate limits, so that the system avoids being throttled by the Gemini API.

#### Acceptance Criteria

1. WHEN the Evaluator_Agent is about to make an LLM call via Safe_LLM_Call, THE Evaluator_Agent SHALL call `time.sleep(RATE_LIMIT_SLEEP)` before the call, since the evaluator is never the first LLM-calling agent in the orchestrator flow (researcher and question_generator always precede it)
2. THE Evaluator_Agent SHALL use RATE_LIMIT_SLEEP from `core.config` as the sole value for pre-call rate limit delays, with no hardcoded numeric literals for sleep duration
3. WHEN the Evaluator_Agent is invoked multiple times in sequence (e.g., evaluating successive user answers or follow-up answers), THE Evaluator_Agent SHALL apply the `time.sleep(RATE_LIMIT_SLEEP)` delay before each LLM call independently
4. THE Evaluator_Agent pre-call sleep SHALL be independent of and in addition to any retry-related waits defined in the Safe_LLM_Call retry logic (Requirement 15); the pre-call sleep applies only once before the first attempt of each invocation

### Requirement 13: Configuration and Constants Usage

**User Story:** As a developer, I want all magic numbers replaced with named constants from config, so that the codebase remains maintainable and consistent.

#### Acceptance Criteria

1. THE Evaluator_Agent SHALL import `MIN_ANSWER_LENGTH`, `MAX_TOKENS_SIMPLE`, `WEAK_SCORE_THRESHOLD`, `STRONG_SCORE_THRESHOLD`, `MAX_FOLLOW_UPS`, and `RATE_LIMIT_SLEEP` from `core.config` and use these as the sole values for answer-length checking, LLM token limits, verdict classification boundaries, follow-up count bounds, and pre-call sleep durations respectively
2. THE Evaluator_Agent SHALL contain no hardcoded numeric literals for answer length thresholds, token limits, score thresholds, follow-up limits, or sleep durations, with the exception of fixed domain constants: subscore clamping bounds (1 and 5), penalty subscore values (1), penalty total (4), and retry-related counts
3. THE Evaluator_Agent SHALL reference `STRONG_SCORE_THRESHOLD` from `core.config` as the boundary above which a verdict is classified as "strong", and `WEAK_SCORE_THRESHOLD` as the boundary below which a verdict is classified as "weak"
4. THE Follow_Up_Function SHALL use `MAX_FOLLOW_UPS` from `core.config` as the sole value for determining whether additional follow-up questions are permitted

### Requirement 14: System Prompt Compliance

**User Story:** As a developer, I want the evaluator agent to follow the system prompt convention, so that LLM responses are consistently formatted as raw JSON.

#### Acceptance Criteria

1. THE Evaluator_Agent system prompt SHALL end with the exact text: "Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only." with no additional characters, whitespace, or text following this suffix
2. THE Evaluator_Agent system prompt SHALL explicitly list the expected JSON response structure containing exactly these keys with their types: "scores" (object with keys: relevance (int 1-5), depth (int 1-5), structure (int 1-5), examples (int 1-5)), "total" (int), "verdict" (string: weak/good/strong), "feedback" (string, one sentence), "missing_keywords" (list of strings), "trigger_follow_up" (boolean)
3. THE Evaluator_Agent system prompt SHALL include a scoring rubric that provides a distinct textual description for each of the 5 score levels (1 through 5) for each of the 4 dimensions (relevance, depth, structure, examples), totaling 20 individual level definitions
4. THE Evaluator_Agent system prompt SHALL contain placeholder references for the 4 dynamic inputs (question, ideal_keywords, scoring_hint, user_answer) that are substituted at call time, ensuring the LLM evaluates only the provided answer context

### Requirement 15: Retry Logic and Error Handling

**User Story:** As a user, I want the system to retry failed evaluator calls, so that transient errors do not interrupt my interview session.

#### Acceptance Criteria

1. WHEN the LLM response text is received, THE Safe_LLM_Call SHALL strip markdown code block delimiters (```json and ```) and leading/trailing whitespace before attempting JSON parsing
2. WHEN the stripped LLM response fails JSON parsing on the first attempt, THE Safe_LLM_Call SHALL wait RATE_LIMIT_SLEEP seconds, append the corrective instruction "RETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER." to the prompt, and retry the call exactly once
3. IF the LLM response fails JSON parsing on both attempts, THEN THE Safe_LLM_Call SHALL raise a ValueError with a message containing the agent name and indicating failure after 2 attempts
4. WHEN an exception other than json.JSONDecodeError occurs on the first attempt, THE Safe_LLM_Call SHALL wait 8 seconds and retry the call exactly once without modifying the prompt
5. IF an exception other than json.JSONDecodeError occurs on both attempts, THEN THE Safe_LLM_Call SHALL re-raise the original exception to the calling agent

### Requirement 16: Token Usage Logging

**User Story:** As a developer, I want token usage logged for every evaluator call, so that I can monitor the most frequently called agent's API costs.

#### Acceptance Criteria

1. WHEN the LLM call succeeds, THE Safe_LLM_Call SHALL print token usage to the console in the exact format `[Evaluator] Success. Tokens: {usage_metadata}` where `{usage_metadata}` is the value of `response.usage_metadata` from the google-generativeai library
2. WHEN a JSON parse error occurs, THE Safe_LLM_Call SHALL print to the console in the exact format `[Evaluator] JSON fail attempt {N}: {error_message}` where N is the 1-based attempt number and error_message is the string representation of the JSONDecodeError
3. WHEN a non-JSON API error occurs, THE Safe_LLM_Call SHALL print to the console in the exact format `[Evaluator] API error attempt {N}: {error_message}` where N is the 1-based attempt number and error_message is the string representation of the exception

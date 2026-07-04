# Design Document: Coach Agent

## Overview

The Coach Agent (`agents/coach.py`) occupies the REPORT state in the orchestrator's state machine. It is the final agent invoked in the interview flow, responsible for producing a comprehensive performance report after all 10 questions have been answered and evaluated.

The module exposes one public function:

- **`generate_report`** — the single entry point. Takes `session_id` and `answers` (a list of 10 Answer_Dict objects), compresses answer data, makes exactly one Gemini 2.0 Flash LLM call, validates the 11-key output contract, deterministically calculates hiring probability metrics, and returns a validated `Report_Dict`.

One private helper is defined:

- **`_safe_llm_call`** — follows the exact template from `agents/evaluator.py` (retry logic, JSON stripping, markdown removal, token logging).

The agent never performs database operations — the orchestrator handles persistence of the returned `Report_Dict`. The agent never imports from `ui/` and never calls any other agent.

---

## Architecture

```
Orchestrator (orchestrator.py)
       │
       │  generate_report(session_id, answers)
       ▼
  coach.py
       │
       ├─ Step 1: Input validation
       │       ├─ session_id: non-None, non-empty, non-whitespace
       │       ├─ answers: must be list of length TOTAL_QUESTIONS
       │       └─ each Answer_Dict: category (str), evaluation.total (int),
       │          evaluation.missing_keywords (list)
       │       └─ ValueError on any failure (no LLM call)
       │
       ├─ Step 2: Compress answers
       │       └─ Extract: question_index, score, category, missing_keywords
       │          Never include: answer_text, question, feedback
       │
       ├─ Step 3: Calculate overall_score deterministically
       │       └─ sum(answer["evaluation"]["total"] for answer in answers)
       │
       ├─ Step 4: time.sleep(RATE_LIMIT_SLEEP)
       │
       ├─ Step 5: Configure Gemini + build prompts
       │       └─ genai.configure(api_key=GEMINI_API_KEY)
       │       └─ model = genai.GenerativeModel(GEMINI_MODEL)
       │
       ├─ Step 6: _safe_llm_call(prompt, system, model, MAX_TOKENS_REPORT, "Coach")
       │       └─ google-generativeai (gemini-2.0-flash-exp)
       │
       ├─ Step 7: Output contract validation (11 required keys)
       │       ├─ Missing keys → ValueError
       │       ├─ Extra keys → strip
       │       ├─ Type/structure checks on all fields
       │       └─ Improvement entry + URL validation
       │
       ├─ Step 8: Deterministic overrides
       │       ├─ overall_score ← locally calculated sum
       │       ├─ hiring_probability ← band classification
       │       └─ hiring_probability_percent ← round((score/MAX_TOTAL_SCORE)*100)
       │
       └─ Step 9: Return validated Report_Dict (11 keys)
```

The orchestrator calls `generate_report` in the REPORT state. The function is stateless — all context is passed explicitly as parameters.

---

## Components and Interfaces

### `generate_report` (public)

```python
def generate_report(session_id: str, answers: list[dict]) -> dict:
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `session_id` | `str` | UUID string identifying the current interview session; used in the user prompt for LLM context |
| `answers` | `list[dict]` | List of exactly `TOTAL_QUESTIONS` (10) Answer_Dict objects from the completed session |

**Returns:** A validated `Report_Dict` containing exactly 11 keys (see Data Models).

**Raises:** `ValueError` on input validation failure (invalid session_id, wrong answers count, malformed Answer_Dict), LLM failure after retries, or output contract validation failure.

---

### `_safe_llm_call` (module-private)

```python
def _safe_llm_call(
    prompt: str,
    system: str,
    model,
    max_tokens: int,
    agent_name: str,
) -> dict:
```

Follows the exact `safe_llm_call` template from `agents.md`:
- 2-attempt loop
- On `JSONDecodeError` at attempt 0: sleep `RATE_LIMIT_SLEEP`, append corrective instruction, retry
- On `JSONDecodeError` at attempt 1: raise `ValueError("Coach failed after 2 attempts")`
- On non-JSON `Exception` at attempt 0: sleep `ERROR_RETRY_SLEEP` (8s), retry
- On non-JSON `Exception` at attempt 1: re-raise the original exception
- Logs token usage to stdout on every successful call: `[Coach] Success. Tokens: {usage_metadata}`

---

### `_compress_answers` (module-private)

```python
def _compress_answers(answers: list[dict]) -> list[dict]:
```

Extracts only the fields needed for the LLM prompt from each Answer_Dict. Never includes raw answer text, question text, or full feedback.

**Returns:** A list of `Compressed_Answer` dicts, one per answer.

---

### `_calculate_hiring_probability` (module-private)

```python
def _calculate_hiring_probability(overall_score: int) -> str:
```

Deterministic band classification:
- `overall_score < HIRING_LOW_MAX` → `"Low"`
- `HIRING_LOW_MAX <= overall_score <= HIRING_HIGH_MIN` → `"Medium"`
- `overall_score > HIRING_HIGH_MIN` → `"High"`

---

### `_calculate_hiring_percent` (module-private)

```python
def _calculate_hiring_percent(overall_score: int) -> int:
```

Returns `round((overall_score / MAX_TOTAL_SCORE) * 100)`, clamped to `[0, 100]`.

---

### `_validate_report` (module-private)

```python
def _validate_report(report: dict) -> dict:
```

Validates the 11-key contract, checks types and structures, strips extra keys. Raises `ValueError` on any violation with a message prefixed with `"Coach"`.

---

## Data Models

### `Report_Dict` (output)

The validated return type of `generate_report`. Contains exactly 11 keys.

```python
{
    "overall_score":              int,        # sum of all evaluation.total values (40–200)
    "hiring_probability":         str,        # "Low" | "Medium" | "High"
    "hiring_probability_percent": int,        # round((overall_score / MAX_TOTAL_SCORE) * 100), 0–100
    "strongest_category":         str,        # non-empty, e.g. "technical"
    "weakest_category":           str,        # non-empty, e.g. "behavioral"
    "category_averages":          dict,       # {str: float/int}, e.g. {"technical": 15.5, "behavioral": 12.0}
    "top_3_strengths":            list[str],  # exactly 3 non-empty strings
    "top_3_improvements":         list[dict], # exactly 3 Improvement_Entry dicts
    "critical_moment":            str,        # non-empty, must contain at least one digit
    "overall_verdict":            str,        # non-empty summary string
    "next_interview_tip":         str,        # non-empty actionable tip
}
```

### `Improvement_Entry` (nested in top_3_improvements)

Each entry in `top_3_improvements` must be a dict with exactly 4 string keys:

```python
{
    "area":          str,  # non-empty, what needs improvement
    "why":           str,  # non-empty, why this matters
    "how_to_fix":    str,  # non-empty, actionable fix
    "free_resource": str,  # non-empty, starts with "http://" or "https://"
}
```

### `Answer_Dict` (input)

Each item in the `answers` list. Produced by `database.get_answers()`.

```python
{
    "question":    str,        # the interview question text (NOT passed to LLM)
    "answer_text": str,        # user's raw answer (NOT passed to LLM)
    "category":    str,        # non-empty, e.g. "technical", "behavioral"
    "evaluation":  {
        "scores":           dict,       # {relevance, depth, structure, examples}
        "total":            int,        # 4–20, sum of subscores
        "verdict":          str,        # "weak" | "good" | "strong"
        "feedback":         str,        # (NOT passed to LLM)
        "missing_keywords": list[str],  # keywords the user missed
        "trigger_follow_up": bool,
    },
    # ... other metadata fields (ignored by coach)
}
```

### `Compressed_Answer` (internal, passed to LLM)

```python
{
    "question_index":    int,        # 1-based position in answers list
    "score":             int,        # evaluation.total (4–20)
    "category":          str,        # e.g. "technical"
    "missing_keywords":  list[str],  # evaluation.missing_keywords
}
```

---

## Processing Pipeline

Complete step-by-step execution of `generate_report`:

```
INPUT: session_id, answers
  │
  ▼
Step 1: INPUT VALIDATION
  if session_id is None or not isinstance(session_id, str) or not session_id.strip():
      raise ValueError("Coach: session_id must be a non-empty string")
  if not isinstance(answers, list):
      raise ValueError("Coach: answers must be a list")
  if len(answers) == 0:
      raise ValueError("Coach: no answers were provided")
  if len(answers) != TOTAL_QUESTIONS:
      raise ValueError(f"Coach: expected {TOTAL_QUESTIONS} answers, got {len(answers)}")
  for i, answer in enumerate(answers):
      if "category" not in answer or not isinstance(answer.get("category"), str) or not answer["category"].strip():
          raise ValueError(f"Coach: answer at index {i} has invalid or missing category")
      if "evaluation" not in answer or not isinstance(answer.get("evaluation"), dict):
          raise ValueError(f"Coach: answer at index {i} is missing evaluation dict")
      eval_dict = answer["evaluation"]
      if "total" not in eval_dict or not isinstance(eval_dict["total"], int):
          raise ValueError(f"Coach: answer at index {i} evaluation missing integer total")
      if "missing_keywords" not in eval_dict or not isinstance(eval_dict["missing_keywords"], list):
          raise ValueError(f"Coach: answer at index {i} evaluation missing missing_keywords list")
  │
  ▼
Step 2: COMPRESS ANSWERS
  compressed = _compress_answers(answers)
  # For each answer at index i:
  #   {"question_index": i+1, "score": answer["evaluation"]["total"],
  #    "category": answer["category"],
  #    "missing_keywords": answer["evaluation"]["missing_keywords"]}
  │
  ▼
Step 3: CALCULATE OVERALL SCORE (deterministic)
  overall_score = sum(answer["evaluation"]["total"] for answer in answers)
  │
  ▼
Step 4: RATE LIMIT SLEEP
  time.sleep(RATE_LIMIT_SLEEP)
  │
  ▼
Step 5: CONFIGURE GEMINI + BUILD PROMPTS
  genai.configure(api_key=GEMINI_API_KEY)
  model = genai.GenerativeModel(GEMINI_MODEL)
  system = SYSTEM_PROMPT  (module-level constant)
  compressed_json = json.dumps(compressed, separators=(',',':'))
  user_prompt = f"Generate a performance report...\n"
                f"Session: {session_id}\n"
                f"Total questions answered: {len(answers)}\n"
                f"Compressed answers: {compressed_json}"
  │
  ▼
Step 6: LLM CALL
  raw = _safe_llm_call(user_prompt, system, model, MAX_TOKENS_REPORT, "Coach")
  │
  ▼
Step 7: OUTPUT CONTRACT VALIDATION
  required_keys = {overall_score, hiring_probability, hiring_probability_percent,
                   strongest_category, weakest_category, category_averages,
                   top_3_strengths, top_3_improvements, critical_moment,
                   overall_verdict, next_interview_tip}
  missing = required_keys - set(raw.keys())
  if missing:
      raise ValueError(f"Coach: LLM response missing keys: {missing}")
  # Strip extra keys
  raw = {k: raw[k] for k in required_keys}
  # Validate types and structures (see _validate_report)
  │
  ▼
Step 8: DETERMINISTIC OVERRIDES
  raw["overall_score"] = overall_score
  raw["hiring_probability"] = _calculate_hiring_probability(overall_score)
  raw["hiring_probability_percent"] = _calculate_hiring_percent(overall_score)
  │
  ▼
Step 9: RETURN validated Report_Dict (exactly 11 keys)
```

---

## System Prompt

### System Prompt (module-level constant `SYSTEM_PROMPT`)

```
You are an expert interview performance coach. Your task is to analyze a candidate's compressed interview performance data and produce a detailed coaching report.

INPUT FORMAT:
You will receive compressed answer data for each question containing:
- question_index: the 1-based question number
- score: the evaluation total (4-20) for that answer
- category: the question category (technical, behavioral, situational, curveball)
- missing_keywords: keywords the candidate failed to mention

ANALYSIS REQUIREMENTS:
1. Identify the strongest and weakest categories by averaging scores within each category
2. Provide exactly 3 specific strengths observed across answers
3. Provide exactly 3 specific improvements, each with:
   - area: what needs improvement
   - why: why this matters for interviews
   - how_to_fix: actionable step to improve
   - free_resource: a REAL URL to a well-known free resource (neetcode.io, pramp.com, leetcode.com, freecodecamp.org, developer.mozilla.org, interviewing.io, techinterviewhandbook.org)
4. Identify the critical_moment — reference a SPECIFIC question number (e.g., "Question 3") where performance notably shifted (improved or declined). You MUST include the question number as a digit.
5. Write an overall_verdict summarizing the candidate's readiness
6. Write a next_interview_tip with one actionable suggestion for their next interview

OUTPUT FORMAT — return a JSON object with exactly these 11 keys:
{
  "overall_score": <int, sum of all answer scores>,
  "hiring_probability": <"Low" | "Medium" | "High">,
  "hiring_probability_percent": <int 0-100>,
  "strongest_category": <string, category name>,
  "weakest_category": <string, category name>,
  "category_averages": {<category>: <float average score>, ...},
  "top_3_strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "top_3_improvements": [
    {"area": "<str>", "why": "<str>", "how_to_fix": "<str>", "free_resource": "<https://...>"},
    {"area": "<str>", "why": "<str>", "how_to_fix": "<str>", "free_resource": "<https://...>"},
    {"area": "<str>", "why": "<str>", "how_to_fix": "<str>", "free_resource": "<https://...>"}
  ],
  "critical_moment": "<string referencing a specific question number>",
  "overall_verdict": "<string summary>",
  "next_interview_tip": "<string actionable tip>"
}

RULES:
- top_3_strengths must have EXACTLY 3 items
- top_3_improvements must have EXACTLY 3 items, each with all 4 keys
- free_resource URLs must be REAL, well-known resources (never placeholder or made-up URLs)
- critical_moment MUST reference a specific question number as a digit (e.g., "Question 3" or "Q7")
- category_averages must include all categories present in the data
- All string fields must be non-empty

Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only.
```

### User Prompt (constructed at call time)

```python
compressed_json = json.dumps(compressed, separators=(',', ':'))
user_prompt = (
    f"Generate a performance report for this completed mock interview session.\n\n"
    f"Session ID: {session_id}\n"
    f"Total questions answered: {len(answers)}\n\n"
    f"Compressed answer data:\n{compressed_json}"
)
```

Only compressed answer data (score, category, missing_keywords, question_index) is passed — no raw answer text, question text, or full feedback.

---

## Error Handling

| Error Condition | Trigger | Action | ValueError Message |
|---|---|---|---|
| Invalid session_id | `session_id` is None, empty, or whitespace-only | Raise immediately, no LLM call | `"Coach: session_id must be a non-empty string"` |
| answers not a list | `not isinstance(answers, list)` | Raise immediately, no LLM call | `"Coach: answers must be a list"` |
| Empty answers list | `len(answers) == 0` | Raise immediately, no LLM call | `"Coach: no answers were provided"` |
| Wrong answers count | `len(answers) != TOTAL_QUESTIONS` | Raise immediately, no LLM call | `"Coach: expected {TOTAL_QUESTIONS} answers, got {n}"` |
| Missing/invalid category | `answer["category"]` missing or not non-empty str | Raise immediately, no LLM call | `"Coach: answer at index {i} has invalid or missing category"` |
| Missing evaluation dict | `answer["evaluation"]` missing or not a dict | Raise immediately, no LLM call | `"Coach: answer at index {i} is missing evaluation dict"` |
| Missing evaluation.total | `eval["total"]` missing or not int | Raise immediately, no LLM call | `"Coach: answer at index {i} evaluation missing integer total"` |
| Missing evaluation.missing_keywords | `eval["missing_keywords"]` missing or not list | Raise immediately, no LLM call | `"Coach: answer at index {i} evaluation missing missing_keywords list"` |
| JSON parse failure (attempt 1) | `json.JSONDecodeError` in `_safe_llm_call` | Sleep `RATE_LIMIT_SLEEP`, corrective instruction, retry | — |
| JSON parse failure (attempt 2) | `json.JSONDecodeError` in `_safe_llm_call` | Raise ValueError | `"Coach failed after 2 attempts"` |
| API / network error (attempt 1) | Non-JSON `Exception` in `_safe_llm_call` | Sleep `ERROR_RETRY_SLEEP` (8s), retry | — |
| API / network error (attempt 2) | Same exception on retry | Re-raise original exception | (original exception propagated) |
| Missing required keys in LLM response | `required_keys - set(raw.keys())` is non-empty | Raise ValueError | `"Coach: LLM response missing keys: {missing}"` |
| Invalid strongest_category | Not a non-empty string | Raise ValueError | `"Coach: strongest_category must be a non-empty string"` |
| Invalid weakest_category | Not a non-empty string | Raise ValueError | `"Coach: weakest_category must be a non-empty string"` |
| Invalid overall_verdict | Not a non-empty string | Raise ValueError | `"Coach: overall_verdict must be a non-empty string"` |
| Invalid next_interview_tip | Not a non-empty string | Raise ValueError | `"Coach: next_interview_tip must be a non-empty string"` |
| Invalid category_averages | Not a dict, or has non-string keys / non-numeric values | Raise ValueError | `"Coach: category_averages must be a dict with string keys and numeric values"` |
| Invalid top_3_strengths | Not a list of exactly 3 strings | Raise ValueError | `"Coach: top_3_strengths must be a list of exactly 3 non-empty strings"` |
| Invalid top_3_improvements | Not a list of exactly 3 dicts | Raise ValueError | `"Coach: top_3_improvements must be a list of exactly 3 dicts"` |
| Improvement entry missing key | Entry lacks area/why/how_to_fix/free_resource | Raise ValueError | `"Coach: improvement entry {i} missing key: {key}"` |
| Improvement entry non-string value | Any value in entry is not a string or is empty | Raise ValueError | `"Coach: improvement entry {i} has invalid value for '{key}'"` |
| Invalid free_resource URL | Does not start with `"http://"` or `"https://"` | Raise ValueError | `"Coach: improvement entry {i} free_resource must be a valid URL"` |
| Invalid critical_moment | Empty string or contains no digit character | Raise ValueError | `"Coach: critical_moment must reference a specific question number"` |

---

## Constants Reference

All constants are imported from `core.config`. No hardcoded numeric literals appear in the agent file.

| Constant | Value | Used In |
|---|---|---|
| `GEMINI_API_KEY` | (from .env) | Step 5: `genai.configure(api_key=GEMINI_API_KEY)` |
| `GEMINI_MODEL` | `"gemini-2.0-flash-exp"` | Step 5: `genai.GenerativeModel(GEMINI_MODEL)` |
| `MAX_TOKENS_REPORT` | `1500` | Step 6: `_safe_llm_call` max_tokens argument |
| `RATE_LIMIT_SLEEP` | `4` | Step 4: pre-call sleep; retry sleep in `_safe_llm_call` |
| `ERROR_RETRY_SLEEP` | `8` | `_safe_llm_call`: API error retry sleep |
| `TOTAL_QUESTIONS` | `10` | Step 1: answers count validation |
| `MAX_TOTAL_SCORE` | `200` | Step 8: hiring_probability_percent formula |
| `HIRING_LOW_MAX` | `80` | Step 8: `overall_score < 80` → "Low" |
| `HIRING_HIGH_MIN` | `140` | Step 8: `overall_score > 140` → "High" |

**Domain constants** (fixed by design, not from config):
- Required Report_Dict keys: 11 (fixed contract)
- `_safe_llm_call` attempt count: `2`
- Improvement entry required keys: `area`, `why`, `how_to_fix`, `free_resource`
- top_3_strengths count: `3`
- top_3_improvements count: `3`

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

---

### Property 1: Compression Correctness and Data Isolation

*For any* list of `TOTAL_QUESTIONS` valid Answer_Dict objects, the `_compress_answers` function must produce a list of dicts where each contains exactly `{question_index, score, category, missing_keywords}`, the `question_index` equals the 1-based position, and the constructed LLM prompt never contains any `answer_text`, `question`, or `feedback` string from the original Answer_Dicts.

**Validates: Requirements 1.1, 1.2, 1.3**

---

### Property 2: Deterministic Score Override

*For any* valid `answers` list and any dict returned by `_safe_llm_call` (regardless of the LLM-returned `overall_score`, `hiring_probability`, or `hiring_probability_percent` values), the output `Report_Dict` must always have `overall_score` equal to `sum(answer["evaluation"]["total"] for answer in answers)`, `hiring_probability` derived from the locally calculated `overall_score` using config thresholds, and `hiring_probability_percent` equal to `round((overall_score / MAX_TOTAL_SCORE) * 100)`.

**Validates: Requirements 4.1, 5.3, 5.4, 5.5**

---

### Property 3: Hiring Probability Band Classification

*For any* integer `overall_score` in the range `[40, 200]`:
- If `overall_score < HIRING_LOW_MAX` then `hiring_probability == "Low"`
- If `HIRING_LOW_MAX <= overall_score <= HIRING_HIGH_MIN` then `hiring_probability == "Medium"`
- If `overall_score > HIRING_HIGH_MIN` then `hiring_probability == "High"`

And `hiring_probability_percent == round((overall_score / MAX_TOTAL_SCORE) * 100)` always produces an integer in `[0, 100]`.

**Validates: Requirements 4.2, 4.3, 4.4, 4.5**

---

### Property 4: Output Contract Invariant (11-Key Enforcement)

*For any* successful invocation of `generate_report`, the returned dict must contain exactly 11 keys matching the `Report_Dict` schema. Extra keys from the LLM response are always stripped. The types must be: `overall_score` (int), `hiring_probability` (str in {"Low","Medium","High"}), `hiring_probability_percent` (int 0–100), `strongest_category` (non-empty str), `weakest_category` (non-empty str), `category_averages` (dict with str keys and numeric values), `top_3_strengths` (list of 3 str), `top_3_improvements` (list of 3 Improvement_Entry dicts), `critical_moment` (str with ≥1 digit), `overall_verdict` (non-empty str), `next_interview_tip` (non-empty str).

**Validates: Requirements 5.1, 5.6, 5.7, 5.8, 5.9, 5.10, 11.2**

---

### Property 5: Missing Keys Detection

*For any* dict returned by `_safe_llm_call` that is missing at least one of the 11 required keys, `generate_report` must raise a `ValueError` whose message identifies the missing keys. A partial `Report_Dict` is never returned.

**Validates: Requirements 5.1, 5.2**

---

### Property 6: Improvement Entry Structural Validation

*For any* entry in `top_3_improvements`, validation passes if and only if the entry is a dict with exactly 4 keys (`area`, `why`, `how_to_fix`, `free_resource`), all values are non-empty strings, and `free_resource` starts with `"http://"` or `"https://"`. Any violation raises a `ValueError` identifying the entry index and the specific field.

**Validates: Requirements 6.1, 6.2, 6.3, 6.5**

---

### Property 7: Critical Moment Digit Requirement

*For any* string value in the `critical_moment` field, validation passes if and only if the string is non-empty and contains at least one digit character (`\d`). A string with no digits always raises a `ValueError`.

**Validates: Requirements 7.2, 7.3**

---

### Property 8: Input Validation Completeness

*For any* `session_id` that is None, empty, or whitespace-only, or any `answers` that is not a list, is empty, has length ≠ `TOTAL_QUESTIONS`, or contains an Answer_Dict with missing/invalid `category` or malformed `evaluation` (missing dict, missing `total` int, or missing `missing_keywords` list), `generate_report` raises a `ValueError` immediately before any sleep or LLM call.

**Validates: Requirements 1.4, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6**

---

### Property 9: Exception Propagation

*For any* exception raised by `_safe_llm_call` (whether `ValueError` from JSON failures or any other exception from API errors), `generate_report` propagates the exception to the caller without catching or transforming it. For output validation failures, a `ValueError` with `"Coach"` in the message is raised.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4**

---

### Property 10: Rate Limit Compliance

*For any* valid invocation of `generate_report` that passes input validation, `time.sleep(RATE_LIMIT_SLEEP)` is called exactly once before `_safe_llm_call` is invoked. The sleep uses only the named constant, never a hardcoded literal.

**Validates: Requirements 3.1, 3.3**

---

### Property 11: Single LLM Call Per Invocation

*For any* valid invocation of `generate_report`, `_safe_llm_call` is called exactly once. The function never makes zero calls (for valid input) or more than one call.

**Validates: Requirements 2.1**

---

## Testing Strategy

### Dual Testing Approach

Unit tests cover specific scenarios, boundary conditions, and error paths. Property-based tests verify universal invariants across a wide input space using **Hypothesis**.

Configure each property test with `@settings(max_examples=100)`.

Each property test must be tagged with a comment:
```python
# Feature: coach-agent, Property {N}: {property_text}
```

### Test File Location

```
tests/
└── test_coach.py
```

### Property Test Configuration

| Property | Hypothesis Strategy | What Varies |
|---|---|---|
| P1: Compression correctness | `st.lists(st.text(min_size=1), min_size=3, max_size=5)` for missing_keywords; `st.integers(4, 20)` for scores; `st.sampled_from(["technical","behavioral","situational","curveball"])` for category | Answer content, categories, keywords |
| P2: Deterministic score override | `st.integers(4, 20)` × 10 for evaluation.total values; `st.integers(0, 200)` for LLM-returned overall_score | LLM values vs local calculation |
| P3: Hiring probability bands | `st.integers(40, 200)` for overall_score | Full range of valid aggregate scores |
| P4: Output contract invariant | Mock `_safe_llm_call` returning valid 11-key dicts with varied content + random extra keys | Extra keys, varied string content |
| P5: Missing keys detection | `st.sets(st.sampled_from(REQUIRED_KEYS), min_size=1, max_size=10)` for keys to remove | Any subset of missing keys |
| P6: Improvement entry validation | `st.dictionaries(...)` for improvement entries with random keys/values; `st.text()` for URLs | Key presence, value types, URL formats |
| P7: Critical moment digit | `st.text()` for critical_moment values | Strings with and without digits |
| P8: Input validation | `st.text()` for session_id; `st.integers(0, 20)` for answer list lengths; random malformation of Answer_Dicts | All input validation paths |
| P9: Exception propagation | Mock `_safe_llm_call` raising varied exceptions (ValueError, RuntimeError, ConnectionError) | Exception type and message |
| P10: Rate limit compliance | Mock `time.sleep`; varied valid inputs | Whether sleep is called before LLM |
| P11: Single LLM call | Mock `_safe_llm_call`; varied valid inputs | Call count verification |

### Unit Tests

Unit tests cover specific scenarios not suited for property generation:

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

### Coverage Targets

- All 9 steps of `generate_report`
- All input validation paths (session_id, answers type, count, each Answer_Dict field)
- Both retry paths in `_safe_llm_call` (JSON parse and API error)
- All type/structure validations in `_validate_report`
- All 3 hiring probability bands + boundary values
- Deterministic override of all 3 LLM-returned fields
- Extra key stripping
- Improvement entry validation (all 4 keys + URL format)
- Critical moment digit check
- Compression data isolation

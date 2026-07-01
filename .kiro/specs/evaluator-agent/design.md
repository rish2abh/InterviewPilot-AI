# Design Document: Evaluator Agent

## Overview

The Evaluator Agent (`agents/evaluator.py`) is one of four agents in the Mock Interview Stress Tester. It occupies the EVALUATING and FOLLOW_UP states in the orchestrator's state machine, serving as the critical feedback engine after the user submits each interview answer.

The module exposes two public functions:

- **`evaluate_answer`** — scores a user's interview answer on four dimensions (relevance, depth, structure, examples) using Gemini 2.0 Flash, applies a deterministic post-processing pipeline to correct LLM hallucinations, and returns a validated `Evaluation_Dict`.
- **`get_follow_up_question`** — a pure, LLM-free helper that retrieves the next follow-up question from a `Question_Dict` with bounds checking.

The evaluator is always preceded in the orchestrator flow by the Researcher and QuestionGenerator agents, so a `time.sleep(RATE_LIMIT_SLEEP)` pre-call delay is always required before the LLM call. The evaluator never calls any other agent and never imports from `ui/`.

---

## Architecture

```
Orchestrator (orchestrator.py)
       │
       │  evaluate_answer(question, ideal_keywords,
       │                  scoring_hint, user_answer, api_key)
       ▼
  evaluator.py
       │
       ├─ [len(user_answer) < MIN_ANSWER_LENGTH] ──► return Penalty_Dict (no LLM)
       │
       ├─ time.sleep(RATE_LIMIT_SLEEP)
       │
       ├─ safe_llm_call(prompt, system, model, MAX_TOKENS_SIMPLE, "Evaluator")
       │        │
       │        └─ google-generativeai (gemini-2.0-flash-exp)
       │
       └─ Post-Processing Pipeline
                │
                └─► Evaluation_Dict (validated, 6 keys)

       │
       │  get_follow_up_question(question_dict, follow_up_count)
       ▼
  evaluator.py  (pure function, no LLM)
       │
       └─► str | None
```

The orchestrator calls `evaluate_answer` in the EVALUATING state and `get_follow_up_question` in the FOLLOW_UP state. Both functions are stateless — all required context is passed explicitly as parameters.

---

## Components and Interfaces

### `evaluate_answer`

```python
def evaluate_answer(
    question: str,
    ideal_keywords: list[str],
    scoring_hint: str,
    user_answer: str,
    api_key: str
) -> dict:
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `question` | `str` | The interview question text |
| `ideal_keywords` | `list[str]` | Keywords expected in a strong answer |
| `scoring_hint` | `str` | Domain-specific scoring guidance for this question |
| `user_answer` | `str` | The user's submitted answer text |
| `api_key` | `str` | Gemini API key (from `core.config`) |

**Returns:** A validated `Evaluation_Dict` (see Data Models).

**Raises:** `ValueError` if LLM call fails after retries, if required keys are missing, or if validation fails after all corrections.

---

### `get_follow_up_question`

```python
def get_follow_up_question(
    question_dict: dict,
    follow_up_count: int
) -> str | None:
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `question_dict` | `dict` | A `Question_Dict` from the question generator |
| `follow_up_count` | `int` | Zero-based index of the desired follow-up |

**Returns:** A follow-up question string, the generic fallback string, or `None`.

---

### `safe_llm_call` (module-private helper)

```python
def safe_llm_call(
    prompt: str,
    system: str,
    model,
    max_tokens: int,
    agent_name: str
) -> dict:
```

Follows the exact template from `agents.md`. Handles markdown stripping, JSON parsing, one retry on JSON parse failure (with 4s sleep + corrective prompt), and one retry on API errors (with 8s sleep). Logs token usage, JSON failures, and API errors to stdout in the required formats.

---

## Data Models

### `Evaluation_Dict`

The validated return type of `evaluate_answer`. Contains exactly 6 top-level keys.

```python
{
    "scores": Scores_Dict,           # nested scoring breakdown
    "total": int,                    # 4–20, always recalculated
    "verdict": str,                  # "weak" | "good" | "strong"
    "feedback": str,                 # 1 sentence, 10–200 chars
    "missing_keywords": list[str],   # subset of ideal_keywords, deduplicated
    "trigger_follow_up": bool        # True only when verdict == "weak"
}
```

### `Scores_Dict`

```python
{
    "relevance": int,   # 1–5: how on-topic the answer is
    "depth":     int,   # 1–5: technical depth and completeness
    "structure": int,   # 1–5: logical organization and clarity
    "examples":  int    # 1–5: use of concrete examples
}
```

### `Penalty_Dict`

Returned immediately (without LLM call) when `len(user_answer) < MIN_ANSWER_LENGTH`. Fixed values:

```python
{
    "scores": {"relevance": 1, "depth": 1, "structure": 1, "examples": 1},
    "total": 4,
    "verdict": "weak",
    "feedback": "Answer too short. Elaborate with a specific example.",
    "missing_keywords": ideal_keywords,   # full list passed as input
    "trigger_follow_up": True
}
```

### `Question_Dict`

Input schema for `get_follow_up_question`. Produced by the QuestionGenerator agent.

```python
{
    "id":             int,        # question index (1–10)
    "category":       str,        # e.g., "behavioral", "technical"
    "question":       str,        # the interview question text
    "ideal_keywords": list[str],  # keywords expected in a strong answer
    "difficulty":     str,        # "easy" | "medium" | "hard"
    "follow_ups":     list[str],  # 0–N follow-up question strings
    "scoring_hint":   str         # domain-specific scoring guidance
}
```

---

## Processing Pipeline

The complete post-LLM correction pipeline executed inside `evaluate_answer`, in exact order:

```
INPUT: question, ideal_keywords, scoring_hint, user_answer, api_key
  │
  ▼
Step 1: LENGTH CHECK
  if len(user_answer) < MIN_ANSWER_LENGTH:
      return Penalty_Dict immediately
  │
  ▼
Step 2: RATE LIMIT SLEEP
  time.sleep(RATE_LIMIT_SLEEP)
  │
  ▼
Step 3: LLM CALL
  model = genai.GenerativeModel("gemini-2.0-flash-exp")
  raw = safe_llm_call(user_prompt, SYSTEM_PROMPT, model,
                      MAX_TOKENS_SIMPLE, "Evaluator")
  │
  ▼
Step 4: SUBSCORE CLAMPING
  For each dim in [relevance, depth, structure, examples]:
      if not isinstance(raw["scores"][dim], (int, float)):
          raise ValueError(f"Non-numeric subscore: {dim}")
      score = round(raw["scores"][dim])   # half-up rounding
      score = max(1, min(5, score))       # clamp to [1, 5]
      raw["scores"][dim] = score
  │
  ▼
Step 5: TOTAL RECALCULATION
  total = (raw["scores"]["relevance"] + raw["scores"]["depth"]
         + raw["scores"]["structure"] + raw["scores"]["examples"])
  if not (4 <= total <= 20):
      raise ValueError(f"Total out of range after clamping: {total}")
  │
  ▼
Step 6: VERDICT DERIVATION
  if total < WEAK_SCORE_THRESHOLD:      verdict = "weak"
  elif total <= STRONG_SCORE_THRESHOLD: verdict = "good"
  else:                                 verdict = "strong"
  │
  ▼
Step 7: OFF-TOPIC CORRECTION (relevance == 1)
  if raw["scores"]["relevance"] == 1:
      missing_keywords_override = list(ideal_keywords)
      feedback_override = (
          "Your answer was not relevant to the question asked; "
          "focus on the specific topic."
      )
  │
  ▼
Step 8: FEEDBACK ENFORCEMENT
  feedback = raw.get("feedback", "").strip()
  if not feedback:
      feedback = "Review the ideal keywords and try incorporating them into your answer."
  else:
      # Truncate to first sentence (matches ". ", "! ", "? " + uppercase)
      import re
      m = re.search(r'[.!?](?=\s+[A-Z])', feedback)
      if m:
          feedback = feedback[:m.start() + 1]
      if len(feedback) > 200:
          feedback = feedback[:200]
          if feedback[-1] not in ".!?":
              feedback += "."
  # Apply off-topic override if flagged in Step 7
  if raw["scores"]["relevance"] == 1:
      feedback = feedback_override
  │
  ▼
Step 9: MISSING KEYWORDS FILTERING
  ideal_set = set(ideal_keywords)
  if raw["scores"]["relevance"] == 1:
      missing = list(ideal_keywords)   # full list, order preserved
  else:
      seen = set()
      missing = []
      for kw in raw.get("missing_keywords", []):
          if kw in ideal_set and kw not in seen:
              missing.append(kw)
              seen.add(kw)
  │
  ▼
Step 10: TRIGGER_FOLLOW_UP ASSIGNMENT
  trigger_follow_up = (verdict == "weak")
  │
  ▼
Step 11: FINAL VALIDATION
  result = {
      "scores": raw["scores"],
      "total": total,
      "verdict": verdict,
      "feedback": feedback,
      "missing_keywords": missing,
      "trigger_follow_up": trigger_follow_up
  }
  Validate all 6 keys (types, ranges, lengths) — raise ValueError on failure
  │
  ▼
Step 12: RETURN validated Evaluation_Dict
```

### Validation Checklist (Step 11)

| Field | Validation Rule |
|---|---|
| `scores` | dict with exactly 4 keys; each value is `int` in `[1, 5]` |
| `total` | `int` in `[4, 20]` |
| `verdict` | one of `"weak"`, `"good"`, `"strong"` |
| `feedback` | non-empty `str`, length in `[10, 200]` |
| `missing_keywords` | `list`; every element is a `str` present in `ideal_keywords` |
| `trigger_follow_up` | `bool` |

---

## System Prompt

The system prompt is a module-level constant in `agents/evaluator.py`. The user prompt is constructed at call time using the 4 dynamic inputs.

### System Prompt (constant)

```
You are an expert technical interview evaluator. Your task is to score a candidate's interview answer across four dimensions. You must be rigorous and objective.

SCORING DIMENSIONS (score each 1–5):

1. RELEVANCE — Does the answer address the specific question asked?
   1 = Completely off-topic or does not address the question at all
   2 = Tangentially related but misses the core of what was asked
   3 = Partially addresses the question with some irrelevant content
   4 = Mostly on-topic with minor deviations
   5 = Directly and completely addresses the question asked

2. DEPTH — Does the answer demonstrate technical knowledge and completeness?
   1 = Extremely superficial; no technical detail whatsoever
   2 = Surface-level; mentions a few concepts without explanation
   3 = Moderate depth; covers key points but lacks detail in places
   4 = Good technical depth; most concepts explained clearly
   5 = Excellent depth; thorough, precise, and technically complete

3. STRUCTURE — Is the answer logically organized and easy to follow?
   1 = Completely disorganized; rambling with no logical flow
   2 = Weak structure; ideas presented randomly with little coherence
   3 = Acceptable structure; some logical progression but uneven
   4 = Well-structured; clear flow with minor organizational gaps
   5 = Excellent structure; clear introduction, body, and conclusion

4. EXAMPLES — Does the answer use concrete examples to illustrate points?
   1 = No examples at all; purely abstract or theoretical
   2 = Vague or implied examples; nothing concrete or specific
   3 = One weak example; not fully developed or explained
   4 = One or two solid examples that clearly support the answer
   5 = Multiple strong, specific examples that enhance the answer

RESPONSE SCHEMA — return exactly this JSON structure:
{
  "scores": {
    "relevance": <int 1-5>,
    "depth": <int 1-5>,
    "structure": <int 1-5>,
    "examples": <int 1-5>
  },
  "total": <int, sum of 4 scores>,
  "verdict": <"weak" | "good" | "strong">,
  "feedback": <string, one sentence, max 200 chars, actionable suggestion>,
  "missing_keywords": [<string>, ...],
  "trigger_follow_up": <boolean>
}

Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only.
```

### User Prompt (constructed at call time)

```python
user_prompt = f"""Question: {question}

Ideal Keywords: {', '.join(ideal_keywords)}

Scoring Hint: {scoring_hint}

Candidate Answer:
{user_answer}"""
```

Only these 4 fields are passed to the LLM — no research context, session metadata, or other questions.

---

## `get_follow_up_question` Logic

```python
def get_follow_up_question(question_dict: dict, follow_up_count: int) -> str | None:
    if follow_up_count < 0 or follow_up_count >= MAX_FOLLOW_UPS:
        return None
    if follow_up_count < len(question_dict["follow_ups"]):
        return question_dict["follow_ups"][follow_up_count]
    return "Can you elaborate on your answer with a specific example?"
```

### Decision Table

| `follow_up_count` | Condition | Return value |
|---|---|---|
| `< 0` | Negative index | `None` |
| `>= MAX_FOLLOW_UPS` | Exceeds limit | `None` |
| `< len(follow_ups)` | Valid index in list | `follow_ups[follow_up_count]` |
| `< MAX_FOLLOW_UPS` but `>= len(follow_ups)` | List too short / empty | Generic fallback string |

---

## Error Handling

### Short Answer (no LLM call)

- **Trigger:** `len(user_answer) < MIN_ANSWER_LENGTH`
- **Action:** Return `Penalty_Dict` immediately; no sleep, no LLM call
- **Impact on caller:** None — returns a valid `Evaluation_Dict` shape

### Non-Numeric Subscore

- **Trigger:** `raw["scores"][dim]` is `None`, a string, or a missing key
- **Action:** Raise `ValueError("Non-numeric subscore: {dim}")`
- **Impact on caller:** Propagated to orchestrator; enters ERROR state

### JSON Parse Failure (attempt 1)

- **Trigger:** `json.loads` throws `JSONDecodeError` on first attempt
- **Action:** `safe_llm_call` logs the error, sleeps 4s, appends corrective instruction, retries once

### JSON Parse Failure (attempt 2)

- **Trigger:** `json.loads` throws `JSONDecodeError` on second attempt
- **Action:** `safe_llm_call` raises `ValueError("{agent_name} failed after 2 attempts")`
- **Impact on caller:** `evaluate_answer` propagates the `ValueError`

### API Error (attempt 1)

- **Trigger:** Any non-`JSONDecodeError` exception (network, quota, etc.) on first attempt
- **Action:** `safe_llm_call` logs the error, sleeps 8s, retries once without modifying the prompt

### API Error (attempt 2)

- **Trigger:** Same exception type on second attempt
- **Action:** `safe_llm_call` re-raises the original exception
- **Impact on caller:** `evaluate_answer` propagates the exception

### Missing Required Key in LLM Response

- **Trigger:** Any of the 6 required top-level keys absent from `safe_llm_call` return value
- **Action:** Raise `ValueError("Missing key in evaluator response: {key}")`

### Total Out of Range After Clamping

- **Trigger:** `total < 4` or `total > 20` after subscore clamping (indicates logic error)
- **Action:** Raise `ValueError(f"Total out of range after clamping: {total}")`

### Final Validation Failure

- **Trigger:** Any field fails type, range, or content validation in Step 11
- **Action:** Raise `ValueError(f"Validation failed for field '{field}': {value}")`

---

## Constants Reference

All constants are imported from `core.config`. The evaluator agent uses no hardcoded numeric literals for thresholds, limits, or sleep durations.

| Constant | Value | Used In |
|---|---|---|
| `MIN_ANSWER_LENGTH` | `50` | Step 1: length check trigger |
| `MAX_TOKENS_SIMPLE` | `500` | Step 3: `safe_llm_call` max_tokens argument |
| `RATE_LIMIT_SLEEP` | `4` | Step 2: pre-call sleep duration (seconds) |
| `WEAK_SCORE_THRESHOLD` | `12` | Step 6: `total < 12` → verdict `"weak"` |
| `STRONG_SCORE_THRESHOLD` | `16` | Step 6: `total > 16` → verdict `"strong"` |
| `MAX_FOLLOW_UPS` | `2` | `get_follow_up_question`: upper bound check |

**Domain constants** (fixed by scoring design, not from config):
- Subscore clamp bounds: `1` (min) and `5` (max)
- Penalty subscore value: `1` for each dimension
- Penalty total: `4`
- `safe_llm_call` attempt count: `2`
- API error retry sleep: `8` seconds (fixed in `safe_llm_call` template)

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

---

### Property 1: Short-Answer Penalty Path

*For any* string `user_answer` where `len(user_answer) < MIN_ANSWER_LENGTH` and any `ideal_keywords` list, calling `evaluate_answer` must return a dict identical to `Penalty_Dict` — with scores all equal to 1, total equal to 4, verdict `"weak"`, trigger_follow_up `True`, and `missing_keywords` equal to the full `ideal_keywords` input — without invoking `safe_llm_call`.

**Validates: Requirements 2.1, 2.2, 2.4**

---

### Property 2: Subscore Clamping

*For any* numeric subscore value `x` (integer or float) returned by the LLM, the clamped subscore in the output must equal `max(1, min(5, round(x)))`. No subscore in the output `Evaluation_Dict` may be less than 1 or greater than 5.

**Validates: Requirements 7.1, 7.2, 7.3**

---

### Property 3: Total Recalculation Invariant

*For any* mocked LLM response (regardless of the `total` value the LLM returns), the `total` field in the output `Evaluation_Dict` must always equal the arithmetic sum of the four clamped subscores: `relevance + depth + structure + examples`.

**Validates: Requirements 3.1, 3.2**

---

### Property 4: Verdict Classification from Total

*For any* `Evaluation_Dict` produced by `evaluate_answer`, the `verdict` field must be determined solely by the recalculated `total`:
- `total < WEAK_SCORE_THRESHOLD` → `verdict == "weak"`
- `WEAK_SCORE_THRESHOLD <= total <= STRONG_SCORE_THRESHOLD` → `verdict == "good"`
- `total > STRONG_SCORE_THRESHOLD` → `verdict == "strong"`

The LLM-returned verdict is always discarded.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**

---

### Property 5: trigger_follow_up Consistency with Verdict

*For any* `Evaluation_Dict` produced by `evaluate_answer`, `trigger_follow_up` must be `True` if and only if `verdict == "weak"` (i.e., `total < WEAK_SCORE_THRESHOLD`). For all other verdicts, `trigger_follow_up` must be `False`.

**Validates: Requirements 5.1, 5.2, 5.3**

---

### Property 6: Feedback Single-Sentence Enforcement

*For any* LLM-returned `feedback` string (including multi-sentence strings, very long strings, and empty strings), the `feedback` field in the output `Evaluation_Dict` must contain exactly one sentence of at most 200 characters. Multi-sentence feedback is truncated at the first sentence boundary; empty or whitespace feedback is replaced with the defined fallback string.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**

---

### Property 7: Missing Keywords Is a Filtered Subset

*For any* `ideal_keywords` list and any LLM-returned `missing_keywords` list, the `missing_keywords` field in the output `Evaluation_Dict` must be a deduplicated list whose every element appears in `ideal_keywords` (case-sensitive exact match). Elements returned by the LLM that are not in `ideal_keywords` are discarded.

**Validates: Requirements 9.1, 9.2, 9.4**

---

### Property 8: Off-Topic Override When Relevance Is 1

*For any* evaluation where the clamped `relevance` subscore equals 1, the `missing_keywords` field in the output must equal the full `ideal_keywords` input list (regardless of what the LLM returned), and the `feedback` field must be overridden with a message indicating the answer was off-topic.

**Validates: Requirements 9.3, 11.1, 11.3**

---

### Property 9: Exception Propagation from safe_llm_call

*For any* invocation of `evaluate_answer` where `safe_llm_call` raises a `ValueError` or any other exception after exhausting its retry attempts, `evaluate_answer` must propagate that exception to the caller without returning a partial `Evaluation_Dict`.

**Validates: Requirements 1.5, 15.3, 15.5**

---

### Property 10: Follow-Up Retrieval Bounds

*For any* `Question_Dict` and integer `follow_up_count`, `get_follow_up_question` must return:
- `None` if `follow_up_count < 0` or `follow_up_count >= MAX_FOLLOW_UPS`
- `question_dict["follow_ups"][follow_up_count]` if `0 <= follow_up_count < MAX_FOLLOW_UPS` and `follow_up_count < len(question_dict["follow_ups"])`
- The generic fallback string if `0 <= follow_up_count < MAX_FOLLOW_UPS` but `follow_up_count >= len(question_dict["follow_ups"])`

**Validates: Requirements 10.1, 10.2, 10.3, 10.4**

---

## Testing Strategy

### Dual Testing Approach

Unit tests and property-based tests work together for comprehensive coverage. Unit tests handle specific examples, boundary conditions, and error paths. Property tests verify universal invariants across a wide input space.

### Property-Based Testing Library

Use **[Hypothesis](https://hypothesis.readthedocs.io/)** for Python property-based testing. Configure each property test with `@settings(max_examples=100)`.

Each property test must be tagged with a comment:
```python
# Feature: evaluator-agent, Property {N}: {property_text}
```

### Property Test Configuration

Each of the 10 correctness properties maps to a single property-based test:

| Property | Hypothesis Strategy | What Varies |
|---|---|---|
| P1: Short-answer penalty | `st.text(max_size=49)` for `user_answer`; `st.lists(st.text())` for `ideal_keywords` | Any short string input |
| P2: Subscore clamping | `st.floats(allow_nan=False)` for each subscore | Any numeric value |
| P3: Total recalculation | `st.integers(1,5)` × 4 for subscores + random `total` | LLM-returned vs recalculated total |
| P4: Verdict classification | `st.integers(4,20)` for total | Full range of valid totals |
| P5: trigger_follow_up | `st.integers(4,20)` for total | Full range of valid totals |
| P6: Feedback enforcement | `st.text()` for feedback including multi-sentence | Any string feedback |
| P7: Missing keywords filtering | `st.lists(st.text())` for both lists | Any keyword lists |
| P8: Off-topic override | Fixed relevance=1 + varied other subscores and keyword lists | ideal_keywords content |
| P9: Exception propagation | Mock `safe_llm_call` to raise varied exceptions | Exception type and message |
| P10: Follow-up bounds | `st.integers()` for count + varied `follow_ups` lists | Count and list length combinations |

### Unit Tests

Unit tests cover specific scenarios and error conditions not suited for property generation:

- **Length boundary:** `len(user_answer) == MIN_ANSWER_LENGTH` → LLM is called (not penalty)
- **Non-numeric subscore:** `None`, `"five"`, missing key → `ValueError` raised
- **Missing required key:** LLM response omits `"feedback"` → `ValueError` raised
- **LLM call count:** Mock `safe_llm_call` and assert called exactly once per invocation
- **Rate limit sleep:** Mock `time.sleep` and assert called with `RATE_LIMIT_SLEEP` before LLM
- **Penalty path skips sleep:** Verify `time.sleep` is NOT called on short answers
- **JSON retry behavior:** Mock `model.generate_content` to return invalid JSON then valid JSON; assert retry occurs
- **API error retry:** Mock `model.generate_content` to raise then succeed; assert 8s sleep and retry
- **Off-topic feedback override:** `relevance=1` with generic feedback → feedback overridden
- **System prompt suffix:** Assert system prompt ends with exact required suffix string
- **`get_follow_up_question` empty list:** `follow_ups=[]`, `count=0` → generic fallback returned
- **`get_follow_up_question` negative count:** `count=-1` → `None` returned
- **Token usage logging:** Capture stdout and verify exact `[Evaluator] Success. Tokens: ...` format

### Test File Location

```
tests/
└── test_evaluator.py
```

### Coverage Targets

- All 12 steps of the post-LLM pipeline
- All 6 field validations in Step 11
- All 4 branches of `get_follow_up_question`
- Both retry paths in `safe_llm_call`
- Penalty path (short answer) vs. full evaluation path

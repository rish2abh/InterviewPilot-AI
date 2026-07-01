# Design Document: Question Generator Agent

## Overview

The Question Generator Agent (`agents/question_generator.py`) occupies the GENERATING state in the orchestrator's state machine. It receives the validated Researcher output dictionary, makes a single Gemini 2.0 Flash LLM call to produce exactly 10 company-specific interview questions, validates and normalises the output, and persists all questions to SQLite before returning.

The module exposes one public function and one public helper:

- **`generate_questions`** — the main entry point. Takes `research_data`, `session_id`, and `api_key`, runs the full generation pipeline, and returns a list of exactly `TOTAL_QUESTIONS` validated `Question_Dict` objects.
- **`validate_questions`** — a public validation helper that checks structure, field types, constraints, and category distribution for a list of question dicts.

One custom exception is defined:

- **`QuestionGenerationError`** — raised on any unrecoverable failure. Always prefixed with `"Question_Generator_Agent"` in the message so the orchestrator can identify the source.

The agent always follows the Researcher Agent in the orchestrator flow, so `time.sleep(RATE_LIMIT_SLEEP)` is unconditionally applied before the first LLM call. The agent never imports from `ui/` and never calls any other agent.

---

## Architecture

```
Orchestrator (orchestrator.py)
       │
       │  generate_questions(research_data, session_id, api_key)
       ▼
  question_generator.py
       │
       ├─ Step 1: Input validation (8 required keys + api_key)
       │       └─ QuestionGenerationError on failure (no LLM call)
       │
       ├─ Step 2: time.sleep(RATE_LIMIT_SLEEP)
       │
       ├─ Step 3: Compress research_data
       │       └─ json.dumps(research_data, separators=(',',':'))
       │
       ├─ Step 4: Configure Gemini (no search grounding)
       │       └─ genai.GenerativeModel(GEMINI_MODEL)
       │
       ├─ Steps 5–6: 2-attempt outer loop
       │       │
       │       ├─ _safe_llm_call(prompt, system, model, MAX_TOKENS_COMPLEX)
       │       │       └─ google-generativeai (gemini-2.0-flash-exp)
       │       │
       │       ├─ Count check: len(questions) == TOTAL_QUESTIONS
       │       ├─ validate_questions(): structure + distribution
       │       └─ On failure at attempt 0: sleep + corrective prompt → retry
       │           On failure at attempt 1: raise QuestionGenerationError
       │
       ├─ Step 7: Post-processing
       │       ├─ _assign_ids_and_difficulties()   (overwrites LLM values)
       │       └─ _normalize_follow_ups()           (per question)
       │
       ├─ Step 8: save_questions(session_id, questions)
       │       └─ QuestionGenerationError on db failure
       │
       └─ Step 9: return list[Question_Dict]  (10 items)
```

The orchestrator calls `generate_questions` in the GENERATING state. The function is stateless — all context is passed explicitly as parameters.

---

## Components and Interfaces

### `generate_questions` (public)

```python
def generate_questions(
    research_data: dict,
    session_id: str,
    api_key: str,
) -> list[dict]:
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `research_data` | `dict` | Validated Researcher output with exactly 8 required keys |
| `session_id` | `str` | UUID string identifying the current interview session |
| `api_key` | `str` | Gemini API key; never logged or hardcoded |

**Returns:** A list of exactly `TOTAL_QUESTIONS` validated `Question_Dict` objects.

**Raises:** `QuestionGenerationError` on input validation failure, LLM failure after retries, wrong question count after retry, structural validation failure after retry, or database write failure.

---

### `validate_questions` (public helper)

```python
def validate_questions(questions: list[dict]) -> tuple[bool, str]:
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `questions` | `list[dict]` | List of question dicts to validate |

**Returns:** `(True, "")` if all checks pass, or `(False, reason)` where `reason` is a human-readable failure description.

Checks performed in order:
1. `len(questions) == TOTAL_QUESTIONS`
2. Each item is a `dict`
3. All 7 required keys present: `id`, `category`, `question`, `ideal_keywords`, `difficulty`, `follow_ups`, `scoring_hint`
4. `id` is a non-empty string
5. `category` is one of the 4 valid values
6. `question` text is at least `MIN_QUESTION_LENGTH` characters
7. `ideal_keywords` is a non-empty list of strings
8. `difficulty` is an `int` between 1 and 10
9. `follow_ups` is a `list`
10. `scoring_hint` is a non-empty string
11. Category distribution matches `_REQUIRED_DISTRIBUTION` exactly

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
- On `JSONDecodeError` at attempt 1: raise `QuestionGenerationError`
- On non-JSON `Exception` at attempt 0: sleep `ERROR_RETRY_SLEEP` (8s), retry
- On non-JSON `Exception` at attempt 1: raise `QuestionGenerationError` wrapping original error
- Logs token usage to stdout on every successful call: `[QuestionGenerator] Success. Tokens: {usage_metadata}`

---

### `_assign_ids_and_difficulties` (module-private)

```python
def _assign_ids_and_difficulties(questions: list[dict]) -> list[dict]:
```

Overwrites every question's `id` and `difficulty` fields:
- `id` → fresh `str(uuid.uuid4())` (LLM-returned values are never trusted)
- `difficulty` → `i + 1` for 0-based index `i` (Q1=1, Q10=10)

Mutates the list in-place and returns it.

---

### `_normalize_follow_ups` (module-private)

```python
def _normalize_follow_ups(question: dict) -> dict:
```

Ensures `follow_ups` contains exactly `FOLLOW_UP_COUNT` valid non-empty strings. See the Normalization Logic section for the full algorithm.

---

### `_get_distribution` / `_distribution_is_valid` (module-private)

```python
def _get_distribution(questions: list[dict]) -> dict[str, int]:
def _distribution_is_valid(questions: list[dict]) -> bool:
```

`_get_distribution` counts category occurrences. `_distribution_is_valid` returns `True` only when the counts exactly match `_REQUIRED_DISTRIBUTION`.

---

## Data Models

### `Question_Dict` (output)

Each item in the returned list. Contains exactly 7 keys.

```python
{
    "id":             str,        # UUID4, generated by _assign_ids_and_difficulties
    "category":       str,        # one of: "technical", "behavioral", "situational", "curveball"
    "question":       str,        # >= MIN_QUESTION_LENGTH (20) characters
    "ideal_keywords": list[str],  # non-empty list, >= 3 strings
    "difficulty":     int,        # equals 1-based position in list (1–10)
    "follow_ups":     list[str],  # exactly FOLLOW_UP_COUNT (2) non-empty strings
    "scoring_hint":   str,        # non-empty
}
```

### `Research_Data` (input)

The 8 required keys from the Researcher Agent output.

```python
{
    "company":              str,
    "role":                 str,
    "interview_rounds":     ...,
    "key_topics":           ...,
    "difficulty":           ...,
    "culture_keywords":     ...,
    "known_question_types": ...,
    "red_flags_to_test":    ...,
    # optional:
    "error_flag":           bool,  # True for unknown companies
}
```

### `QuestionGenerationError`

```python
class QuestionGenerationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message     # type: str
        super().__init__(message)
```

Always prefixed with `"Question_Generator_Agent"` so the orchestrator can identify the failure source from `str(exc)`.

---

## Processing Pipeline

Complete step-by-step execution of `generate_questions`:

```
INPUT: research_data, session_id, api_key
  │
  ▼
Step 1: INPUT VALIDATION
  required_research_keys = {company, role, interview_rounds, key_topics,
                             difficulty, culture_keywords, known_question_types,
                             red_flags_to_test}
  missing = required_research_keys - set(research_data.keys())
  if missing:
      raise QuestionGenerationError("...missing required keys: {missing}")
  if not isinstance(api_key, str) or not api_key.strip():
      raise QuestionGenerationError("...api_key must be a non-empty string")
  │
  ▼
Step 2: RATE LIMIT SLEEP
  time.sleep(RATE_LIMIT_SLEEP)   # researcher LLM call always precedes this
  │
  ▼
Step 3: COMPRESS RESEARCH DATA
  compressed_research = json.dumps(research_data, separators=(',',':'))
  │
  ▼
Step 4: CONFIGURE GEMINI
  genai.configure(api_key=api_key)
  model = genai.GenerativeModel(model_name=GEMINI_MODEL)
  system = SYSTEM_PROMPT.format(total=TOTAL_QUESTIONS)
  error_flag = research_data.get("error_flag", False)
  if error_flag:
      company_instruction = "...Do NOT mention the company by name."
  else:
      company_instruction = f"Generate questions tailored to {research_data['company']}."
  user_prompt = f"Generate exactly {TOTAL_QUESTIONS} questions...\n{compressed_research}\n{company_instruction}"
  │
  ▼
Steps 5–6: 2-ATTEMPT OUTER LOOP (attempt in range(2))
  │
  ├─ if attempt == 1: time.sleep(RATE_LIMIT_SLEEP)  # before retry
  │
  ├─ raw_response = _safe_llm_call(current_prompt, system, model,
  │                                MAX_TOKENS_COMPLEX, "QuestionGenerator")
  │
  ├─ Check "questions" key exists in raw_response
  │     → failure at attempt 0: append corrective prompt, continue
  │     → failure at attempt 1: raise QuestionGenerationError
  │
  ├─ questions = raw_response["questions"]
  │
  ├─ Count check: len(questions) != TOTAL_QUESTIONS
  │     → failure at attempt 0: append count correction, continue
  │     → failure at attempt 1: raise QuestionGenerationError
  │
  ├─ is_valid, reason = validate_questions(questions)
  │     → failure at attempt 0: append validation correction, continue
  │     → failure at attempt 1: raise QuestionGenerationError
  │
  └─ break  (both checks passed)
  │
  ▼
Step 7: POST-PROCESSING
  questions = _assign_ids_and_difficulties(questions)
  for q in questions:
      _normalize_follow_ups(q)
  │
  ▼
Step 8: DATABASE SAVE
  try:
      save_questions(session_id, questions)
  except Exception as e:
      raise QuestionGenerationError(f"...database write failed: {e}")
  │
  ▼
Step 9: RETURN questions
```

---

## System Prompt

### System Prompt (module-level constant `SYSTEM_PROMPT`)

The prompt uses a `{total}` placeholder substituted with `TOTAL_QUESTIONS` at call time via `.format(total=TOTAL_QUESTIONS)`.

```
You are an expert technical interview question designer. Your task is to generate
exactly {total} company-specific interview questions based on the research data provided.

QUESTION DISTRIBUTION — you MUST follow this exactly:
- 4 questions with category "technical"
- 3 questions with category "behavioral"
- 2 questions with category "situational"
- 1 question with category "curveball"

DIFFICULTY PROGRESSION — questions MUST get progressively harder:
- Question 1: difficulty 1 (easiest)
- Question 2: difficulty 2
- ...
- Question 10: difficulty 10 (hardest)
Each question's difficulty field must equal its 1-based position in the list.

OUTPUT FORMAT — return a JSON object with a "questions" key containing a list of
exactly {total} objects. Each object must have exactly these 7 keys:

{
  "id": "<UUID4 string>",
  "category": "<one of: technical, behavioral, situational, curveball>",
  "question": "<interview question text, at least 20 characters>",
  "ideal_keywords": ["<keyword1>", "<keyword2>", "<keyword3>"],
  "difficulty": <integer 1-10>,
  "follow_ups": ["<follow-up question 1>", "<follow-up question 2>"],
  "scoring_hint": "<brief guidance on what a strong answer should cover>"
}

RULES:
- Every question must be specific to the company, role, and experience level
- If error_flag is true, base questions on role/level/key_topics only, do not reference the company by name
- ideal_keywords must have at least 3 items per question
- follow_ups must have exactly 2 items per question
- question text must be at least 20 characters
- scoring_hint must be a non-empty string
- All category values must be exactly one of: technical, behavioral, situational, curveball

Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only.
```

### User Prompt (constructed at call time)

```python
user_prompt = (
    f"Generate exactly {TOTAL_QUESTIONS} interview questions based on this research data.\n\n"
    f"Research data (compressed): {compressed_research}\n\n"
    f"{company_instruction}\n\n"
    f"Remember: 4 technical, 3 behavioral, 2 situational, 1 curveball. "
    f"Difficulty must increase from 1 (Q1) to {TOTAL_QUESTIONS} (Q{TOTAL_QUESTIONS})."
)
```

Only the compressed research data and role context are passed — no session metadata or previous answers.

---

## Normalization Logic

### `_normalize_follow_ups` Algorithm

Applied to every question after `validate_questions` passes, before database save.

```
INPUT: question dict with "category" and "follow_ups" keys
  │
  ▼
1. Get category-appropriate fallbacks:
   fallbacks = _FALLBACK_FOLLOW_UPS.get(category, _FALLBACK_FOLLOW_UPS["technical"])

2. Get existing follow_ups:
   existing = question.get("follow_ups", [])
   if not isinstance(existing, list):
       existing = []

3. Build normalized list:
   for each item in existing:
       if isinstance(item, str) and item.strip():
           keep item
       else:
           replace with fallbacks[fallback_idx % len(fallbacks)], increment fallback_idx

4. Pad if len(normalized) < FOLLOW_UP_COUNT:
   append fallbacks[fallback_idx % len(fallbacks)] until len == FOLLOW_UP_COUNT

5. Trim if len(normalized) > FOLLOW_UP_COUNT:
   question["follow_ups"] = normalized[:FOLLOW_UP_COUNT]

OUTPUT: question dict mutated in-place, follow_ups has exactly FOLLOW_UP_COUNT valid strings
```

### Fallback Strings Per Category

| Category | Fallback 0 | Fallback 1 |
|---|---|---|
| `technical` | "Can you walk me through your technical approach step by step?" | "What alternative technical solutions did you consider and why did you choose this one?" |
| `behavioral` | "Can you provide a specific example from your experience?" | "What was the outcome and what would you do differently in hindsight?" |
| `situational` | "How would you prioritize the competing constraints in that scenario?" | "What stakeholders would you involve and how would you communicate your decision?" |
| `curveball` | "Can you elaborate on your reasoning process for that answer?" | "How does your answer connect to the core responsibilities of this role?" |

If the category is unrecognised, the `"technical"` fallback list is used.

---

## Error Handling

| Error Condition | Trigger | Action | QuestionGenerationError Message |
|---|---|---|---|
| Missing research keys | `required_research_keys - set(research_data.keys())` is non-empty | Raise immediately, no LLM call | `"Question_Generator_Agent: research_data missing required keys: {missing}"` |
| Empty api_key | `not api_key.strip()` | Raise immediately, no LLM call | `"Question_Generator_Agent: api_key must be a non-empty string"` |
| JSON parse failure (attempt 1) | `json.JSONDecodeError` in `_safe_llm_call` | Sleep `RATE_LIMIT_SLEEP`, append corrective instruction, retry | — |
| JSON parse failure (attempt 2) | `json.JSONDecodeError` in `_safe_llm_call` | Raise | `"Question_Generator_Agent: JSON parse failure after 2 attempts: {e}"` |
| API / network error (attempt 1) | Non-JSON `Exception` in `_safe_llm_call` | Sleep `ERROR_RETRY_SLEEP` (8s), retry | — |
| API / network error (attempt 2) | Non-JSON `Exception` in `_safe_llm_call` | Raise | `"Question_Generator_Agent: API error after 2 attempts: {e}"` |
| Missing "questions" key (attempt 1) | `"questions" not in raw_response` | Sleep `RATE_LIMIT_SLEEP`, corrective prompt, retry | — |
| Missing "questions" key (attempt 2) | Same | Raise | `"Question_Generator_Agent: 'questions' key missing from LLM response after 2 attempts"` |
| Wrong question count (attempt 1) | `len(questions) != TOTAL_QUESTIONS` | Sleep `RATE_LIMIT_SLEEP`, count correction prompt, retry | — |
| Wrong question count (attempt 2) | Same | Raise | `"Question_Generator_Agent: wrong question count: expected {TOTAL_QUESTIONS}, got {n} after 2 attempts"` |
| Structural/distribution validation failure (attempt 1) | `validate_questions` returns `(False, reason)` | Sleep `RATE_LIMIT_SLEEP`, validation correction prompt, retry | — |
| Structural/distribution validation failure (attempt 2) | Same | Raise | `"Question_Generator_Agent: validation failed after 2 attempts — {reason}"` |
| Database write failure | `save_questions` raises any exception | Raise immediately | `"Question_Generator_Agent: database write failed: {e}"` |

---

## Constants Reference

All constants are imported from `core.config`. No hardcoded numeric literals appear in the agent file.

| Constant | Value | Used In |
|---|---|---|
| `GEMINI_MODEL` | `"gemini-2.0-flash-exp"` | Step 4: model name |
| `MAX_TOKENS_COMPLEX` | `1000` | `_safe_llm_call` max_output_tokens |
| `RATE_LIMIT_SLEEP` | `4` | Step 2: pre-call sleep; retry sleeps in outer loop |
| `ERROR_RETRY_SLEEP` | `8` | `_safe_llm_call`: API error retry sleep |
| `TOTAL_QUESTIONS` | `10` | Count check; prompt; validate_questions |
| `MIN_QUESTION_LENGTH` | `20` | validate_questions: question text length check |
| `FOLLOW_UP_COUNT` | `2` | `_normalize_follow_ups`: target follow-up list length |

**Domain constants** (fixed by design, not from config):
- Required distribution: `{technical: 4, behavioral: 3, situational: 2, curveball: 1}`
- `_safe_llm_call` attempt count: `2`
- Outer retry loop attempt count: `2`

---

## Correctness Properties

*A property is a characteristic or behavior that must hold true across all valid executions of the system.*

---

### Property 1: Output Count Invariant

*For any* valid invocation of `generate_questions`, the function either returns a list of exactly `TOTAL_QUESTIONS` dicts or raises `QuestionGenerationError`. A partial list (length ≠ `TOTAL_QUESTIONS`) is never returned.

**Validates: Requirements 1.1, 6.1, 6.3**

---

### Property 2: Category Distribution Invariant

*For any* list returned by `generate_questions`, the category counts are always exactly 4 technical, 3 behavioral, 2 situational, 1 curveball. A list with any other distribution is never returned.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

---

### Property 3: Difficulty Sequence Invariant

*For any* list returned by `generate_questions`, the question at 0-based index `i` always has `difficulty == i + 1`, regardless of what the LLM returned. The `_assign_ids_and_difficulties` function enforces this unconditionally.

**Validates: Requirements 3.1, 3.2, 3.4**

---

### Property 4: Follow-Up Count Invariant

*For any* question dict in the returned list, `follow_ups` is always a list of exactly `FOLLOW_UP_COUNT` (2) non-empty strings. The `_normalize_follow_ups` function enforces this regardless of what the LLM returned.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4**

---

### Property 5: UUID Identity Invariant

*For any* returned question dict, the `id` field is always a valid UUID4 string generated by `uuid.uuid4()` inside `_assign_ids_and_difficulties`. LLM-returned id values are never used in the final output.

**Validates: Requirements 1.5**

---

### Property 6: Compression Token Efficiency

*For any* `research_data` dict passed to `generate_questions`, the LLM prompt always includes `json.dumps(research_data, separators=(',',':'))` (no whitespace). The uncompressed dict representation is never passed to the LLM.

**Validates: Requirements 1.2**

---

### Property 7: Rate Limit Compliance

*For any* valid invocation of `generate_questions`, `time.sleep(RATE_LIMIT_SLEEP)` is called exactly once before the first LLM call (Step 2), unconditionally. A retry in the outer loop also calls `time.sleep(RATE_LIMIT_SLEEP)` before the second attempt.

**Validates: Requirements 1.4, 6.2**

---

### Property 8: Input Validation Completeness

*For any* `research_data` dict missing at least one of the 8 required keys, or any `api_key` that is empty or whitespace-only, `generate_questions` raises `QuestionGenerationError` immediately before making any LLM call or sleeping.

**Validates: Requirements 1.6, 9.1**

---

### Property 9: Database Persistence Completeness

*For any* successful `generate_questions` invocation, `save_questions(session_id, questions)` is called with all `TOTAL_QUESTIONS` validated questions before the function returns. If `save_questions` raises any exception, `QuestionGenerationError` is raised and no value is returned.

**Validates: Requirements 7.1, 7.2, 7.3**

---

### Property 10: Error Flag Isolation

*For any* `research_data` where `error_flag == True`, the `user_prompt` string passed to `_safe_llm_call` contains no reference to the company name, and the returned list conforms to the identical `Question_Dict` structure as the non-error-flag case.

**Validates: Requirements 8.1, 8.2, 8.3, 8.4**

---

## Testing Strategy

### Dual Testing Approach

Unit tests cover specific scenarios, boundary conditions, and error paths. Property-based tests verify universal invariants across a wide input space using **Hypothesis**.

Configure each property test with `@settings(max_examples=100)`.

Each property test must be tagged with a comment:
```python
# Feature: question-generator-agent, Property {N}: {property_text}
```

### Test File Location

```
tests/
└── test_question_generator.py
```

### Property Test Configuration

| Property | Hypothesis Strategy | What Varies |
|---|---|---|
| P1: Output count | Mock `_safe_llm_call` to return varied `questions` list lengths | 0, 5, 9, 11, 20 items |
| P2: Distribution | Mock `_safe_llm_call` with wrong category mixes after retry | Category counts per question |
| P3: Difficulty sequence | `st.lists(st.integers(min_value=1, max_value=10))` for LLM-returned difficulties | Any integer difficulty values |
| P4: Follow-up count | `st.lists(st.text(), max_size=5)` for LLM-returned follow_ups | 0, 1, 3, 4 follow-up items |
| P5: UUID identity | `st.text()` for LLM-returned id values | Any string or missing id |
| P6: Compression | `st.dictionaries(st.text(), st.text())` for extra research fields | Arbitrary research content |
| P7: Rate limit | Mock `time.sleep`; `st.booleans()` for retry trigger | Whether retry occurs |
| P8: Input validation | `st.frozensets(st.sampled_from(REQUIRED_KEYS))` for missing key subsets | Any subset of missing keys |
| P9: DB persistence | Mock `save_questions` to raise `sqlite3.Error` | Exception type |
| P10: Error flag | `st.booleans()` for `error_flag`; `st.text()` for company name | Company name in prompt |

### Unit Tests

Unit tests cover specific scenarios not suited for property generation:

- **Valid input succeeds**: Mock LLM returning correct 10-question JSON → returns list of 10 dicts
- **Rate limit sleep called**: Mock `time.sleep`, assert called with `RATE_LIMIT_SLEEP` before LLM
- **Retry sleep called**: Mock LLM to fail count check on attempt 0, assert second `time.sleep` call
- **Missing research key raises**: `research_data` missing `"company"` → `QuestionGenerationError`
- **Empty api_key raises**: `api_key=""` → `QuestionGenerationError` before any sleep
- **Wrong count triggers retry**: Mock LLM returning 9 questions then 10 → succeeds on retry
- **Wrong count after retry raises**: Mock LLM always returning 9 questions → `QuestionGenerationError`
- **Invalid category triggers retry**: Mock LLM returning `"technical_x"` category → validation fail → retry
- **validate_questions returns False on short question**: question text of 5 chars → `(False, reason)`
- **validate_questions returns False on bad distribution**: 10 technical questions → `(False, reason)`
- **`_normalize_follow_ups` pads short list**: 0 follow-ups → 2 category-appropriate fallbacks
- **`_normalize_follow_ups` trims long list**: 5 follow-ups → first 2 kept
- **`_normalize_follow_ups` replaces invalid item**: `[None, "valid question here"]` → `[fallback, "valid question here"]`
- **`_assign_ids_and_difficulties` overwrites LLM values**: LLM id `"abc"`, difficulty `5` → fresh UUID4, difficulty `1–10`
- **error_flag removes company name**: `error_flag=True` → `"company"` value absent from captured prompt
- **DB failure raises**: Mock `save_questions` raises `sqlite3.Error` → `QuestionGenerationError`
- **JSON retry behavior**: Mock `model.generate_content` returns invalid JSON then valid JSON → retries once
- **API error retry**: Mock `model.generate_content` raises then succeeds → 8s sleep, retry
- **System prompt suffix**: Assert `SYSTEM_PROMPT` ends with `"Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."`
- **Token usage logging**: Capture stdout, assert `"[QuestionGenerator] Success. Tokens:"` format
- **save_questions called once**: Mock `save_questions`, assert called exactly once with all 10 questions

### Coverage Targets

- All 9 steps of `generate_questions`
- Both attempt paths (initial + retry) for count, validation, and JSON parse failures
- All 11 checks in `validate_questions`
- All 4 branches of `_normalize_follow_ups` (not-a-list, invalid item, pad, trim)
- Both `error_flag` paths (True and False/absent)
- Both `_safe_llm_call` retry paths (JSON parse and API error)
- Database success and failure paths

# Design Document: Researcher Agent

## Overview

The Researcher Agent (`agents/researcher.py`) occupies the RESEARCHING state in the orchestrator's state machine. It receives a company name, role, and experience level, uses Gemini 2.0 Flash with Search Grounding to discover company-specific interview patterns, and returns a validated `Research_Dict` with exactly 8 keys.

The module exposes one public function:

- **`research_company`** — the main entry point. Takes `company`, `role`, `level`, and `api_key`, runs the full research pipeline, and returns a validated dict.

Key design decisions:

1. **Search Grounding is exclusive to this agent** — no other agent in the system uses `google_search_retrieval`. This allows the researcher to pull current interview data from the web.
2. **Graceful degradation** — on any unrecoverable failure (API errors, validation failures), the function returns a safe `Default_Dict` with role-appropriate generic values and `error_flag=True`, ensuring downstream agents always receive usable data.
3. **Input validation errors propagate** — unlike API failures, invalid inputs (empty/whitespace company or role) raise `ValueError` that propagates to the caller as a programming error.
4. **Unconditional rate-limit sleep** — since the researcher always follows SETUP in the orchestrator (where a prior LLM call occurs), `time.sleep(RATE_LIMIT_SLEEP)` is called before every LLM invocation.

---

## Architecture

```
Orchestrator (orchestrator.py)
       │
       │  research_company(company, role, level, api_key)
       ▼
  researcher.py
       │
       ├─ Step 1: Input validation & sanitization
       │       ├─ _sanitize_input(company, "company")
       │       └─ _sanitize_input(role, "role")
       │       └─ ValueError propagates on invalid input
       │
       ├─ Step 2: time.sleep(RATE_LIMIT_SLEEP)  [unconditional]
       │
       ├─ Step 3: Configure Gemini with Search Grounding
       │       ├─ genai.configure(api_key=api_key)
       │       └─ GenerativeModel(GEMINI_MODEL, tools="google_search_retrieval")
       │
       ├─ Step 4: Build search-optimised prompt
       │       └─ "{company} {role} interview questions experience {level} 2024 2025"
       │
       ├─ Step 5: _safe_llm_call(prompt, SYSTEM_PROMPT, model, MAX_TOKENS_COMPLEX)
       │       └─ 2-attempt retry loop (JSON + API error handling)
       │
       ├─ Step 6: _validate_research_dict(raw)
       │       ├─ Check all 8 keys present
       │       ├─ Validate string keys: non-empty after strip
       │       ├─ Validate list keys: non-empty list of non-empty strings
       │       ├─ Validate difficulty ∈ {easy, medium, hard, expert}
       │       └─ Strip extra keys → return exactly 8
       │
       ├─ Step 7: Return validated Research_Dict (8 keys, no error_flag)
       │
       └─ Step 8 (exception path): Catch all exceptions
               ├─ Print warning: [Researcher] Unrecoverable error...
               └─ Return _build_default_dict(company, role, level)
                       → 8 keys + error_flag=True
```

The orchestrator calls `research_company` in the RESEARCHING state. The function is stateless — all context is passed explicitly as parameters. No database writes occur in this agent.

---

## Components and Interfaces

### `research_company` (public)

```python
def research_company(
    company: str,
    role: str,
    level: str,
    api_key: str,
) -> dict:
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `company` | `str` | Company name (1–100 chars, non-empty). Special chars removed. |
| `role` | `str` | Job role (1–100 chars, non-empty). Special chars removed. |
| `level` | `str` | Experience level: fresher, junior, senior, lead, or manager |
| `api_key` | `str` | Gemini API key; never logged or hardcoded |

**Returns:** A dict with exactly 8 keys on success (no `error_flag`), or 9 keys on failure (8 research keys + `error_flag=True`).

**Raises:** `ValueError` only when `company` or `role` is empty, whitespace-only, or all special characters after sanitization. All other errors are caught and return the Default_Dict.

---

### `_sanitize_input` (module-private)

```python
def _sanitize_input(value: str, field_name: str) -> str:
```

**Steps (in order):**
1. Strip leading/trailing whitespace
2. Raise `ValueError` if empty after strip
3. Truncate to `_MAX_INPUT_LENGTH` (100) characters
4. Remove all characters not matching `[a-zA-Z0-9 \-]`
5. Strip again; raise `ValueError` if empty (all special chars)

**Returns:** Sanitized string safe for prompt use.

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

Follows the canonical `safe_llm_call` template from `agents.md`:
- 2-attempt loop
- On `JSONDecodeError` at attempt 0: sleep `RATE_LIMIT_SLEEP`, append corrective instruction (`"RETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."`), retry
- On `JSONDecodeError` at attempt 1: raise `ValueError` with message `"{agent_name} failed after 2 attempts"`
- On non-JSON `Exception` at attempt 0: sleep `ERROR_RETRY_SLEEP` (8s), retry without modifying prompt
- On non-JSON `Exception` at attempt 1: re-raise the original exception
- Logs token usage on success: `[{agent_name}] Success. Tokens: {response.usage_metadata}`

**Markdown stripping** (applied before JSON parse):
1. `re.sub(r"```json\s*", "", text)` — remove ```json delimiter
2. `re.sub(r"```\s*", "", text)` — remove generic ``` delimiter
3. `.strip()` — trim whitespace

---

### `_validate_research_dict` (module-private)

```python
def _validate_research_dict(raw: dict) -> dict:
```

**Validation checks:**
1. All 8 required keys present → `ValueError` on missing
2. String keys (`company`, `role`, `interview_rounds`, `difficulty`): must be non-empty `str` after strip
3. List keys (`key_topics`, `culture_keywords`, `known_question_types`, `red_flags_to_test`): must be non-empty `list` where every element is a non-empty `str`
4. `difficulty` must be one of: `"easy"`, `"medium"`, `"hard"`, `"expert"`
5. Strip extra keys → return only the 8 required

**Returns:** Clean dict with exactly 8 keys.

**Raises:** `ValueError` with descriptive message on any validation failure.

---

### `_build_default_dict` (module-private)

```python
def _build_default_dict(company: str, role: str, level: str) -> dict:
```

Builds a role-appropriate fallback dict with 9 keys (8 research + `error_flag=True`).

**Difficulty mapping:**

| Level | Difficulty |
|---|---|
| fresher | "easy" |
| junior | "medium" |
| senior | "hard" |
| lead | "expert" |
| manager | "expert" |
| (any other) | "medium" |

**key_topics selection** (based on role keywords):

| Role Keywords | Topics |
|---|---|
| ml, machine learning, ai, data scientist | machine learning, statistics, python, model evaluation, data pipelines |
| data engineer, data analyst, analytics | sql, data modeling, etl pipelines, data warehousing, python |
| product manager, product owner, pm | product strategy, user research, metrics, prioritization, stakeholder management |
| devops, sre, platform, infrastructure, cloud | ci/cd, containerization, cloud infrastructure, monitoring, incident response |
| frontend, front end, ui, react, angular, vue | javascript, html/css, browser rendering, state management, performance optimization |
| backend, back end, api, server | api design, databases, system design, concurrency, caching |
| (all others) | data structures, algorithms, system design, object-oriented design, debugging |

**Fixed values:**
- `interview_rounds`: `"3 rounds"`
- `culture_keywords`: `["collaboration", "ownership"]`
- `known_question_types`: `["coding", "behavioural"]`
- `red_flags_to_test`: `["problem-solving approach", "communication clarity"]`
- `error_flag`: `True`

---

## Data Models

### Research_Dict (success output)

Exactly 8 keys, no `error_flag`:

```python
{
    "company":              str,   # canonical company name
    "role":                 str,   # job role
    "interview_rounds":     str,   # e.g. "5 rounds: online assessment, 2 technical, system design, behavioural"
    "key_topics":           list[str],  # >= 1 non-empty strings
    "difficulty":           str,   # one of: "easy", "medium", "hard", "expert"
    "culture_keywords":     list[str],  # >= 1 non-empty strings
    "known_question_types": list[str],  # >= 1 non-empty strings
    "red_flags_to_test":    list[str],  # >= 1 non-empty strings
}
```

### Default_Dict (failure output)

Exactly 9 keys (8 research + `error_flag`):

```python
{
    "company":              str,   # sanitized input value
    "role":                 str,   # sanitized input value
    "interview_rounds":     "3 rounds",
    "key_topics":           list[str],  # 5 role-appropriate topics
    "difficulty":           str,   # level-mapped value
    "culture_keywords":     ["collaboration", "ownership"],
    "known_question_types": ["coding", "behavioural"],
    "red_flags_to_test":    ["problem-solving approach", "communication clarity"],
    "error_flag":           True,
}
```

### Module-Level Constants

```python
_REQUIRED_KEYS: tuple[str, ...] = (
    "company", "role", "interview_rounds", "key_topics",
    "difficulty", "culture_keywords", "known_question_types", "red_flags_to_test",
)
_LIST_KEYS: frozenset[str] = frozenset({"key_topics", "culture_keywords", "known_question_types", "red_flags_to_test"})
_STR_KEYS: frozenset[str] = frozenset({"company", "role", "interview_rounds", "difficulty"})
_MAX_INPUT_LENGTH: int = 100
```

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

---

### Property 1: Output Structure Invariant

*For any* valid invocation of `research_company` that does not raise `ValueError`, the returned dict either contains exactly 8 keys matching `_REQUIRED_KEYS` with no `error_flag` key (success path), or contains exactly those 8 keys plus `error_flag=True` (failure path). No other key set is ever returned.

**Validates: Requirements 1.1, 2.1, 2.2, 2.3, 2.6**

---

### Property 2: Failure Safety Invariant

*For any* valid inputs (company and role pass sanitization) where the LLM call fails (API error, JSON parse failure after retries, or validation failure), `research_company` always returns a dict containing all 8 required research keys with non-empty values plus `error_flag=True`. It never raises an exception or returns an incomplete dict.

**Validates: Requirements 1.4, 2.5, 2.9, 5.5, 6.1, 6.2, 7.3**

---

### Property 3: Default Dict Role-Appropriate Completeness

*For any* combination of sanitized company name, sanitized role string, and experience level string, `_build_default_dict` returns a dict with exactly 9 keys where: `difficulty` is correctly mapped from the level (fresher→easy, junior→medium, senior→hard, lead/manager→expert, unknown→medium), `key_topics` contains 5 items selected based on role category keywords, and all other keys have the specified fixed default values.

**Validates: Requirements 2.10, 6.3, 6.4, 6.5, 6.6**

---

### Property 4: Input Sanitization Correctness

*For any* input string, `_sanitize_input` satisfies all of the following:
- If the input is empty or whitespace-only, it raises `ValueError` (which propagates to the caller)
- If the input exceeds 100 characters, the output length is ≤ 100
- The output contains only characters matching `[a-zA-Z0-9 \-]`
- If the input contains only characters in `[a-zA-Z0-9 \-]` and is ≤ 100 chars, the output equals the stripped input
- If sanitization removes all characters leaving an empty string, it raises `ValueError`

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 5.7**

---

### Property 5: Markdown Stripping Round Trip

*For any* valid JSON string, if that JSON is wrapped in markdown code fences (either ` ```json ... ``` ` or ` ``` ... ``` `, optionally with surrounding prose), the `_safe_llm_call` markdown stripping logic extracts the JSON content such that `json.loads` produces the same object as parsing the unwrapped JSON directly.

**Validates: Requirements 4.1, 4.2, 4.5**

---

### Property 6: Retry Count and Rate Limit Invariant

*For any* invocation of `_safe_llm_call`, the model's `generate_content` method is called at most 2 times. On JSON failure at attempt 1, `time.sleep(RATE_LIMIT_SLEEP)` is called before retry. On non-JSON exception at attempt 1, `time.sleep(ERROR_RETRY_SLEEP)` is called before retry. No sleep occurs after the final (2nd) attempt failure.

**Validates: Requirements 1.2, 1.3, 5.1, 5.3, 5.6**

---

## Error Handling

| Error Condition | Trigger | Action | Outcome |
|---|---|---|---|
| Empty/whitespace company or role | `_sanitize_input` detects empty after strip | Raise `ValueError` | Propagates to caller (not caught) |
| All-special-character input | `_sanitize_input` detects empty after regex removal | Raise `ValueError` | Propagates to caller (not caught) |
| JSON parse failure (attempt 1) | `json.JSONDecodeError` in `_safe_llm_call` | Print log, sleep `RATE_LIMIT_SLEEP`, append corrective instruction, retry | — |
| JSON parse failure (attempt 2) | `json.JSONDecodeError` in `_safe_llm_call` | Print log, raise `ValueError` | Caught by `research_company` → Default_Dict |
| API/network error (attempt 1) | Non-JSON `Exception` in `_safe_llm_call` | Print log, sleep `ERROR_RETRY_SLEEP`, retry | — |
| API/network error (attempt 2) | Non-JSON `Exception` in `_safe_llm_call` | Print log, re-raise original exception | Caught by `research_company` → Default_Dict |
| Missing required keys in LLM response | `_validate_research_dict` check | Raise `ValueError` with missing key names | Caught by `research_company` → Default_Dict |
| Invalid value type or empty value | `_validate_research_dict` check | Raise `ValueError` with key name and value | Caught by `research_company` → Default_Dict |
| Invalid difficulty value | `_validate_research_dict` check (not in current impl but required) | Raise `ValueError` | Caught by `research_company` → Default_Dict |
| Any unrecoverable exception | Top-level try/except in `research_company` | Print `[Researcher] Unrecoverable error, returning default dict: {e}` | Return Default_Dict |

### Console Logging Format

| Event | Format |
|---|---|
| LLM success | `[Researcher] Success. Tokens: {response.usage_metadata}` |
| JSON fail attempt N | `[Researcher] JSON fail attempt {N}: {error_message}` |
| API error attempt N | `[Researcher] API error attempt {N}: {error_message}` |
| Default dict returned | `[Researcher] Unrecoverable error, returning default dict: {error_message}` |

---

## Testing Strategy

### Dual Testing Approach

Unit tests cover specific scenarios, boundary conditions, and error paths. Property-based tests verify universal invariants across a wide input space using **Hypothesis**.

Configure each property test with `@settings(max_examples=100)`.

Each property test must be tagged with a comment:
```python
# Feature: researcher-agent, Property {N}: {property_text}
```

### Test File Location

```
tests/
└── test_researcher.py
```

### Property Test Configuration

| Property | Hypothesis Strategy | What Varies |
|---|---|---|
| P1: Output structure | `st.text(min_size=1)` for company/role; mock LLM with valid/invalid dicts | Input strings, LLM response content |
| P2: Failure safety | `st.sampled_from([ValueError, RuntimeError, ConnectionError])` for error types | Exception types, failure points |
| P3: Default dict completeness | `st.text(min_size=1)` for company/role; `st.sampled_from(["fresher","junior","senior","lead","manager","unknown"])` for level | Role keywords, level values |
| P4: Input sanitization | `st.text()` for inputs; `st.text(alphabet=st.characters(whitelist_categories=('L','N','Zs'), whitelist_characters='-'))` for valid inputs | Character composition, string length |
| P5: Markdown stripping | `st.dictionaries(st.text(min_size=1), st.text(min_size=1))` for JSON content; `st.text()` for surrounding prose | JSON structure, prose content |
| P6: Retry count | Mock model raising various exceptions | Exception types, attempt sequences |

### Unit Tests

- **Valid input succeeds**: Mock LLM returning correct 8-key JSON → returns dict with 8 keys, no error_flag
- **Rate limit sleep called**: Mock `time.sleep`, assert called with `RATE_LIMIT_SLEEP` before LLM call
- **Search grounding configured**: Mock `genai.GenerativeModel`, assert `tools="google_search_retrieval"` passed
- **MAX_TOKENS_COMPLEX used**: Mock model, verify `max_output_tokens=MAX_TOKENS_COMPLEX` in generation_config
- **Empty company raises**: `company=""` → `ValueError` propagates
- **Whitespace company raises**: `company="   "` → `ValueError` propagates
- **All-special-char company raises**: `company="@#$%"` → `ValueError` propagates
- **Special chars removed**: `company="Google!!"` → `"Google"` in prompt
- **Truncation at 100 chars**: 150-char input → truncated before sanitization
- **Valid chars unchanged**: `company="Meta-Platforms"` → unchanged
- **JSON retry appends instruction**: Mock LLM returning invalid JSON then valid → corrective instruction appended
- **API error retry uses ERROR_RETRY_SLEEP**: Mock LLM raising on attempt 1, succeeding on attempt 2 → `time.sleep(ERROR_RETRY_SLEEP)` called
- **Validation failure returns default**: Mock LLM returning dict missing `key_topics` → Default_Dict returned
- **Extra keys stripped**: Mock LLM returning 8 required + 3 extra keys → only 8 returned
- **Difficulty validation**: Mock LLM returning `difficulty="impossible"` → validation fails → Default_Dict
- **Default dict for ML role**: `role="ML Engineer"` → key_topics includes "machine learning"
- **Default dict for frontend role**: `role="React Developer"` → key_topics includes "javascript"
- **Default dict for unknown role**: `role="Astronaut"` → key_topics includes "data structures"
- **Difficulty mapping**: fresher→easy, junior→medium, senior→hard, lead→expert, manager→expert
- **Unknown level defaults to medium**: `level="intern"` → difficulty="medium"
- **Warning printed on failure**: Mock LLM to fail, capture stdout, verify `[Researcher] Unrecoverable error` format
- **System prompt ends with JSON instruction**: Assert `SYSTEM_PROMPT.endswith("Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only.")`
- **System prompt contains all 8 key names**: Assert each key name is a substring of `SYSTEM_PROMPT`
- **System prompt contains unknown company instruction**: Assert "industry defaults" or equivalent text in `SYSTEM_PROMPT`
- **Token usage logged on success**: Capture stdout, verify `[Researcher] Success. Tokens:` format
- **No hardcoded sleep values**: Verify all `time.sleep` calls use named constants

### Coverage Targets

- All 8 steps of `research_company`
- Both success and failure paths of `_safe_llm_call` (JSON retry + API retry)
- All validation branches in `_validate_research_dict` (missing key, bad string, bad list, bad list item, extra keys)
- All 7 role-category branches in `_build_default_dict`
- All 5 level-to-difficulty mappings + unknown fallback
- Both paths through the top-level try/except (success and failure)
- Input sanitization: empty, whitespace, truncation, special chars, all-special, valid passthrough

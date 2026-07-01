---
inclusion: always
---

# Anti-Hallucination Rules

## Absolute Rules — Never Break These

### 1. No Invented Libraries
Only import from the approved list in tech.md.
If you want a library not on the list, STOP and ask.

### 2. No Placeholder Code
Never write:
- "# TODO: implement this"
- "pass  # add logic here"  
- "# This would connect to the API"
Every function must have complete, working implementation.

### 3. No Assumed APIs
Never assume what a Gemini API response looks like.
Always use the exact structure from google-generativeai docs:
- response.text for text
- response.usage_metadata for token counts
- generation_config={"max_output_tokens": N} for token limits

### 4. No Invented Database Functions
Only call functions that exist in core/database.py.
If you need a new DB function, add it to database.py first.

### 5. No Magic Numbers
Every number must be a named constant from config.py:
✅ time.sleep(RATE_LIMIT_SLEEP)
❌ time.sleep(4)

✅ if score < WEAK_SCORE_THRESHOLD:
❌ if score < 12:

### 6. Streamlit Session State
Every st.session_state key must be:
a) Initialized in the INIT block at top of app.py
b) Documented with a comment explaining its purpose
Never access st.session_state["key"] without initializing first.

### 7. JSON Contract Enforcement
Every agent returns a dict with EXACTLY these keys (no more, no less):

Researcher returns:
{company, role, interview_rounds, key_topics, difficulty,
 culture_keywords, known_question_types, red_flags_to_test}

QuestionGenerator returns:
{questions: [{id, category, question, ideal_keywords, 
              difficulty, follow_ups, scoring_hint}]}

Evaluator returns:
{scores: {relevance, depth, structure, examples},
 total, verdict, feedback, missing_keywords, trigger_follow_up}

Coach returns:
{overall_score, hiring_probability, hiring_probability_percent,
 strongest_category, weakest_category, category_averages,
 top_3_strengths, top_3_improvements, critical_moment,
 overall_verdict, next_interview_tip}

If an agent returns extra keys → strip them.
If an agent returns missing keys → raise ValueError immediately.

### 8. Validate All LLM Outputs
After every LLM call, validate the returned dict:
- Check all required keys exist
- Check types (str is str, int is int, list is list)
- Check ranges (scores 1-5, totals 4-20, etc.)
- Recalculate totals (total must == sum of subscores)
---
inclusion: always
---

# Technology Stack

## Allowed Libraries ONLY
Use ONLY these libraries. Never suggest or import anything else:
- google-generativeai==0.8.3     (LLM calls)
- streamlit==1.40.0              (UI)
- python-dotenv==1.0.0           (env vars)
- sqlite3                        (built-in, database)
- uuid                           (built-in, session IDs)
- datetime                       (built-in, timestamps)
- json                           (built-in, parsing)
- time                           (built-in, rate limiting)
- re                             (built-in, string cleaning)

## Banned Libraries
NEVER use or suggest these:
- langchain (not needed, adds complexity)
- openai (we use Gemini only)
- pandas (overkill for this project)
- requests (not needed, google-generativeai handles HTTP)
- flask / fastapi (Streamlit is the UI layer)
- celery (GitHub Actions handles scheduling)
- Any web scraping library (use Gemini Search Grounding instead)

## LLM Configuration
- Model: gemini-2.0-flash-exp (always, never change this)
- max_tokens for simple tasks (evaluator): 500
- max_tokens for complex tasks (researcher, question_gen): 1000
- max_tokens for report (coach): 1500
- Rate limit sleep: 4 seconds between every consecutive LLM call
- Search grounding: enabled ONLY for researcher agent

## Environment Variables
All secrets from .env file. Never hardcode:
- GEMINI_API_KEY

## Python Version
Python 3.10+. Use type hints on all function signatures.
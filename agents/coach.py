"""
agents/coach.py — Coach Agent for the Mock Interview Stress Tester.

Exposes one public function:
- generate_report: produces a final performance report after all questions
  are answered and evaluated. Returns a validated 11-key Report_Dict.

The Coach Agent compresses answer data, makes exactly one LLM call to Gemini,
deterministically calculates hiring probability metrics, validates the output
contract, and returns the final report. It never performs database operations.
"""

import json
import re
import time

from google import genai
from google.genai import types

from core.config import (
    GEMINI_MODEL,
    MAX_TOKENS_REPORT,
    RATE_LIMIT_SLEEP,
    ERROR_RETRY_SLEEP,
    HIRING_LOW_MAX,
    HIRING_HIGH_MIN,
    MAX_TOTAL_SCORE,
    TOTAL_QUESTIONS,
)

# ---------------------------------------------------------------------------
# System Prompt (module-level constant)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are an expert interview performance coach. Your task is to analyze a "
    "candidate's compressed interview performance data and produce a detailed "
    "coaching report.\n\n"
    "INPUT FORMAT:\n"
    "You will receive compressed answer data for each question containing:\n"
    "- question_index: the 1-based question number\n"
    "- score: the evaluation total (4-20) for that answer\n"
    "- category: the question category (technical, behavioral, situational, curveball)\n"
    "- missing_keywords: keywords the candidate failed to mention\n\n"
    "ANALYSIS REQUIREMENTS:\n"
    "1. Identify the strongest and weakest categories by averaging scores within each category\n"
    "2. Provide exactly 3 specific strengths observed across answers\n"
    "3. Provide exactly 3 specific improvements, each with:\n"
    "   - area: what needs improvement\n"
    "   - why: why this matters for interviews\n"
    "   - how_to_fix: actionable step to improve\n"
    "   - free_resource: a REAL URL to a well-known free resource "
    "(neetcode.io, pramp.com, leetcode.com, freecodecamp.org, "
    "developer.mozilla.org, interviewing.io, techinterviewhandbook.org)\n"
    "4. Identify the critical_moment — reference a SPECIFIC question number "
    "(e.g., \"Question 3\") where performance notably shifted (improved or declined). "
    "You MUST include the question number as a digit.\n"
    "5. Write an overall_verdict summarizing the candidate's readiness\n"
    "6. Write a next_interview_tip with one actionable suggestion for their next interview\n\n"
    "OUTPUT FORMAT — return a JSON object with exactly these 11 keys:\n"
    "{\n"
    "  \"overall_score\": <int, sum of all answer scores>,\n"
    "  \"hiring_probability\": <\"Low\" | \"Medium\" | \"High\">,\n"
    "  \"hiring_probability_percent\": <int 0-100>,\n"
    "  \"strongest_category\": <string, category name>,\n"
    "  \"weakest_category\": <string, category name>,\n"
    "  \"category_averages\": {<category>: <float average score>, ...},\n"
    "  \"top_3_strengths\": [\"<strength 1>\", \"<strength 2>\", \"<strength 3>\"],\n"
    "  \"top_3_improvements\": [\n"
    "    {\"area\": \"<str>\", \"why\": \"<str>\", \"how_to_fix\": \"<str>\", "
    "\"free_resource\": \"<https://...>\"},\n"
    "    {\"area\": \"<str>\", \"why\": \"<str>\", \"how_to_fix\": \"<str>\", "
    "\"free_resource\": \"<https://...>\"},\n"
    "    {\"area\": \"<str>\", \"why\": \"<str>\", \"how_to_fix\": \"<str>\", "
    "\"free_resource\": \"<https://...>\"}\n"
    "  ],\n"
    "  \"critical_moment\": \"<string referencing a specific question number>\",\n"
    "  \"overall_verdict\": \"<string summary>\",\n"
    "  \"next_interview_tip\": \"<string actionable tip>\"\n"
    "}\n\n"
    "RULES:\n"
    "- top_3_strengths must have EXACTLY 3 items\n"
    "- top_3_improvements must have EXACTLY 3 items, each with all 4 keys\n"
    "- free_resource URLs must be REAL, well-known resources "
    "(never placeholder or made-up URLs)\n"
    "- critical_moment MUST reference a specific question number as a digit "
    "(e.g., \"Question 3\" or \"Q7\")\n"
    "- category_averages must include all categories present in the data\n"
    "- All string fields must be non-empty\n\n"
    "Return ONLY a JSON object. No markdown. No explanation. "
    "No text before or after. Pure JSON only."
)


def generate_report(session_id: str, answers: list[dict], api_key: str) -> dict:
    """Generate a final performance report for a completed interview session.

    Args:
        session_id: UUID string identifying the current interview session.
        answers: List of exactly TOTAL_QUESTIONS Answer_Dict objects.
        api_key: The Gemini API key to use for the LLM call.

    Returns:
        A validated 11-key Report_Dict.

    Raises:
        ValueError: On input validation failure, LLM failure, or output
            contract validation failure.
    """
    # ------------------------------------------------------------------
    # Step 1: Input Validation
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Step 2: Compress Answers
    # ------------------------------------------------------------------
    compressed = _compress_answers(answers)

    # ------------------------------------------------------------------
    # Step 3: Calculate Overall Score (deterministic)
    # ------------------------------------------------------------------
    overall_score = sum(answer["evaluation"]["total"] for answer in answers)

    # ------------------------------------------------------------------
    # Step 4: Rate Limit Sleep
    # ------------------------------------------------------------------
    time.sleep(RATE_LIMIT_SLEEP)

    # ------------------------------------------------------------------
    # Step 5: Configure Gemini + Build Prompts
    # ------------------------------------------------------------------
    client = genai.Client(api_key=api_key)
    compressed_json = json.dumps(compressed, separators=(',', ':'))
    user_prompt = (
        f"Generate a performance report for this completed mock interview session.\n\n"
        f"Session ID: {session_id}\n"
        f"Total questions answered: {len(answers)}\n\n"
        f"Compressed answer data:\n{compressed_json}"
    )

    # ------------------------------------------------------------------
    # Step 6: LLM Call
    # ------------------------------------------------------------------
    raw = _safe_llm_call(user_prompt, SYSTEM_PROMPT, client, MAX_TOKENS_REPORT, "Coach")

    # ------------------------------------------------------------------
    # Step 7: Output Contract Validation
    # ------------------------------------------------------------------
    raw = _validate_report(raw)

    # ------------------------------------------------------------------
    # Step 8: Deterministic Overrides
    # ------------------------------------------------------------------
    raw["overall_score"] = overall_score
    raw["hiring_probability"] = _calculate_hiring_probability(overall_score)
    raw["hiring_probability_percent"] = _calculate_hiring_percent(overall_score)

    # ------------------------------------------------------------------
    # Step 9: Return validated Report_Dict
    # ------------------------------------------------------------------
    return raw


def _compress_answers(answers: list[dict]) -> list[dict]:
    """Compress Answer_Dict list into minimal LLM-ready format.

    Extracts only the fields needed for the LLM prompt from each Answer_Dict.
    Never includes raw answer text, question text, or full feedback.

    Args:
        answers: List of Answer_Dict objects from the completed session.

    Returns:
        A list of Compressed_Answer dicts, one per answer, each containing:
        question_index (1-based), score, category, missing_keywords.
    """
    compressed = []
    for i, answer in enumerate(answers):
        compressed.append({
            "question_index": i + 1,
            "score": answer["evaluation"]["total"],
            "category": answer["category"],
            "missing_keywords": answer["evaluation"]["missing_keywords"],
        })
    return compressed


def _safe_llm_call(prompt: str, system: str, client: genai.Client, max_tokens: int, agent_name: str) -> dict:
    """Call the Gemini model with retry logic for JSON parse failures and API errors."""
    for attempt in range(3):
        try:
            config = types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                response_mime_type="application/json",
            )
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config,
            )
            text = response.text.strip()
            # Extract content from code fences if present
            json_fence_match = re.search(r"```json\s*(.*?)```", text, re.DOTALL)
            if json_fence_match:
                text = json_fence_match.group(1).strip()
            else:
                generic_fence_match = re.search(r"```\s*(.*?)```", text, re.DOTALL)
                if generic_fence_match:
                    text = generic_fence_match.group(1).strip()
            result = json.loads(text)
            print(f"[{agent_name}] Success. Tokens: {response.usage_metadata}")
            return result
        except json.JSONDecodeError as e:
            print(f"[{agent_name}] JSON fail attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(RATE_LIMIT_SLEEP)
                if attempt == 0:
                    prompt += "\n\nRETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."
            else:
                raise ValueError(f"{agent_name} failed after 3 attempts")
        except Exception as e:
            error_str = str(e)
            print(f"[{agent_name}] API error attempt {attempt+1}: {e}")
            if attempt < 2:
                if "429" in error_str:
                    retry_match = re.search(r"retry in (\d+(?:\.\d+)?)s", error_str, re.IGNORECASE)
                    if retry_match:
                        wait_time = int(float(retry_match.group(1))) + 2
                    else:
                        wait_time = 30 * (attempt + 1)
                    print(f"[{agent_name}] Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    time.sleep(ERROR_RETRY_SLEEP)
            else:
                raise


def _validate_report(report: dict) -> dict:
    """Validate the 11-key output contract and strip extra keys.
    
    Checks:
    - All 11 required keys present (raises ValueError with missing key names if not)
    - Strips extra keys beyond the 11 required
    - strongest_category, weakest_category, overall_verdict, next_interview_tip: non-empty str
    - category_averages: dict with str keys and numeric values
    - top_3_strengths: list of exactly 3 non-empty strings
    - top_3_improvements: list of exactly 3 dicts, each with keys area, why, how_to_fix, free_resource
      (all non-empty str), and free_resource starts with "http://" or "https://"
    - critical_moment: non-empty str containing at least one digit
    
    Args:
        report: The raw dict from the LLM response.
        
    Returns:
        The validated dict with exactly 11 keys.
        
    Raises:
        ValueError: With "Coach" prefix on any validation failure.
    """
    required_keys = {
        "overall_score", "hiring_probability", "hiring_probability_percent",
        "strongest_category", "weakest_category", "category_averages",
        "top_3_strengths", "top_3_improvements", "critical_moment",
        "overall_verdict", "next_interview_tip",
    }
    
    # Check all 11 required keys exist
    missing = required_keys - set(report.keys())
    if missing:
        raise ValueError(f"Coach: LLM response missing keys: {missing}")
    
    # Strip extra keys
    report = {k: report[k] for k in required_keys}
    
    # Validate string fields: non-empty str
    for field in ("strongest_category", "weakest_category", "overall_verdict", "next_interview_tip"):
        value = report[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Coach: {field} must be a non-empty string")
    
    # Validate category_averages: dict with str keys and numeric values
    ca = report["category_averages"]
    if not isinstance(ca, dict):
        raise ValueError("Coach: category_averages must be a dict with string keys and numeric values")
    for k, v in ca.items():
        if not isinstance(k, str) or not isinstance(v, (int, float)):
            raise ValueError("Coach: category_averages must be a dict with string keys and numeric values")
    
    # Validate top_3_strengths: list of exactly 3 non-empty strings
    strengths = report["top_3_strengths"]
    if not isinstance(strengths, list) or len(strengths) != 3:
        raise ValueError("Coach: top_3_strengths must be a list of exactly 3 non-empty strings")
    for s in strengths:
        if not isinstance(s, str) or not s.strip():
            raise ValueError("Coach: top_3_strengths must be a list of exactly 3 non-empty strings")
    
    # Validate top_3_improvements: list of exactly 3 dicts
    improvements = report["top_3_improvements"]
    if not isinstance(improvements, list) or len(improvements) != 3:
        raise ValueError("Coach: top_3_improvements must be a list of exactly 3 dicts")
    
    improvement_keys = ("area", "why", "how_to_fix", "free_resource")
    for i, entry in enumerate(improvements):
        if not isinstance(entry, dict):
            raise ValueError(f"Coach: top_3_improvements must be a list of exactly 3 dicts")
        for key in improvement_keys:
            if key not in entry:
                raise ValueError(f"Coach: improvement entry {i} missing key: {key}")
            val = entry[key]
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"Coach: improvement entry {i} has invalid value for '{key}'")
        # Validate free_resource URL
        if not entry["free_resource"].startswith(("http://", "https://")):
            raise ValueError(f"Coach: improvement entry {i} free_resource must be a valid URL")
    
    # Validate critical_moment: non-empty str containing at least one digit
    cm = report["critical_moment"]
    if not isinstance(cm, str) or not cm.strip():
        raise ValueError("Coach: critical_moment must reference a specific question number")
    if not re.search(r'\d', cm):
        raise ValueError("Coach: critical_moment must reference a specific question number")
    
    return report


def _calculate_hiring_probability(overall_score: int) -> str:
    """Deterministic band classification for hiring probability.

    Args:
        overall_score: The sum of all evaluation.total values.

    Returns:
        "Low" if score < HIRING_LOW_MAX,
        "Medium" if HIRING_LOW_MAX <= score <= HIRING_HIGH_MIN,
        "High" if score > HIRING_HIGH_MIN.
    """
    if overall_score < HIRING_LOW_MAX:
        return "Low"
    elif overall_score <= HIRING_HIGH_MIN:
        return "Medium"
    else:
        return "High"


def _calculate_hiring_percent(overall_score: int) -> int:
    """Calculate hiring probability as a percentage, clamped to [0, 100].

    Args:
        overall_score: The sum of all evaluation.total values.

    Returns:
        round((overall_score / MAX_TOTAL_SCORE) * 100), clamped to [0, 100].
    """
    return max(0, min(100, round((overall_score / MAX_TOTAL_SCORE) * 100)))

"""
agents/evaluator.py — Evaluator Agent for the Mock Interview Stress Tester.

Exposes two public functions:
- evaluate_answer: scores a user's interview answer on 4 dimensions using
  Gemini 2.0 Flash and returns a validated Evaluation_Dict.
- get_follow_up_question: pure, LLM-free helper that retrieves the next
  follow-up question from a Question_Dict with bounds checking.
"""

import json
import re
import time

from google import genai
from google.genai import types

from core.config import (
    GEMINI_MODEL,
    MIN_ANSWER_LENGTH,
    MAX_TOKENS_SIMPLE,
    RATE_LIMIT_SLEEP,
    ERROR_RETRY_SLEEP,
    WEAK_SCORE_THRESHOLD,
    STRONG_SCORE_THRESHOLD,
    MAX_FOLLOW_UPS,
)

# ---------------------------------------------------------------------------
# System Prompt (module-level constant)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert technical interview evaluator. Your task is to score a candidate's interview answer across four dimensions. You must be rigorous and objective.

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

Return ONLY a JSON object. No markdown. No explanation. No text before or after. Pure JSON only."""


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------


def _safe_llm_call(prompt: str, system: str, client: genai.Client, max_tokens: int, agent_name: str) -> dict:
    """Call the Gemini model with retry logic for JSON parse failures and API errors.

    Attempts the call up to 2 times:
    - On a JSON parse failure at attempt 1: waits 4 seconds, appends a corrective
      instruction to the prompt, and retries.
    - On a JSON parse failure at attempt 2: raises ValueError.
    - On any other exception at attempt 1: waits 8 seconds and retries.
    - On any other exception at attempt 2: re-raises the original exception.

    Token usage is printed to stdout on success in the format:
    ``[{agent_name}] Success. Tokens: {usage_metadata}``

    Args:
        prompt: The user-side prompt text to send to the model.
        system: The system instruction string.
        client: An initialised google.genai.Client instance.
        max_tokens: Maximum number of output tokens to request.
        agent_name: Human-readable name used in log messages.

    Returns:
        A Python dict parsed from the model's JSON response.

    Raises:
        ValueError: If JSON parsing fails on both attempts.
        Exception: Any non-JSON exception that persists after the single retry.
    """
    for attempt in range(2):
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
            if attempt == 0:
                time.sleep(RATE_LIMIT_SLEEP)
                prompt += "\n\nRETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."
            else:
                raise ValueError(f"{agent_name} failed after 2 attempts")
        except Exception as e:
            print(f"[{agent_name}] API error attempt {attempt+1}: {e}")
            if attempt == 0:
                time.sleep(ERROR_RETRY_SLEEP)
            else:
                raise


def _build_penalty_dict(ideal_keywords: list[str]) -> dict:
    """Build and return a fixed Penalty_Dict for answers below MIN_ANSWER_LENGTH.

    This dict is returned immediately without any LLM call when the user's
    answer is too short. All score values, the total, the verdict, and the
    feedback are fixed domain constants for the penalty path — they are not
    thresholds that should come from config.

    Args:
        ideal_keywords: The full list of ideal keywords for the question.
            A copy is stored in the returned dict so the caller's list is
            not mutated if the dict is modified later.

    Returns:
        A dict matching the Evaluation_Dict schema with exactly 6 keys:
        scores (all 1), total (4), verdict ("weak"),
        feedback (fixed short-answer message), missing_keywords (copy of
        ideal_keywords), and trigger_follow_up (True).
    """
    return {
        "scores": {"relevance": 1, "depth": 1, "structure": 1, "examples": 1},
        "total": 4,
        "verdict": "weak",
        "feedback": "Answer too short. Elaborate with a specific example.",
        "missing_keywords": list(ideal_keywords),
        "trigger_follow_up": True,
    }


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def get_follow_up_question(question_dict: dict, follow_up_count: int) -> str | None:
    """Retrieve the next follow-up question for a given topic with bounds checking.

    This is a pure, LLM-free function. It applies four guards in order:

    1. **Negative index** — if ``follow_up_count < 0`` the index is invalid;
       returns ``None``.
    2. **Exceeds limit** — if ``follow_up_count >= MAX_FOLLOW_UPS`` no further
       follow-ups are permitted; returns ``None``.
    3. **Valid index in list** — if the index is within the length of the
       ``follow_ups`` list, returns ``question_dict["follow_ups"][follow_up_count]``.
    4. **Fallback** — if the list is empty or shorter than ``follow_up_count``,
       returns the generic elaboration prompt.

    Args:
        question_dict: A ``Question_Dict`` produced by the QuestionGenerator
            agent. Must contain a ``"follow_ups"`` key whose value is a list
            of follow-up question strings.
        follow_up_count: Zero-based index of the desired follow-up question.

    Returns:
        - ``None`` if ``follow_up_count`` is negative or ``>= MAX_FOLLOW_UPS``.
        - The string at ``question_dict["follow_ups"][follow_up_count]`` when
          the index is valid and within the list.
        - ``"Can you elaborate on your answer with a specific example?"`` when
          the index is within the ``MAX_FOLLOW_UPS`` bound but the ``follow_ups``
          list is empty or too short to satisfy the request.
    """
    # Guard 1: negative index → None
    if follow_up_count < 0:
        return None
    # Guard 2: exceeds MAX_FOLLOW_UPS limit → None
    if follow_up_count >= MAX_FOLLOW_UPS:
        return None
    # Guard 3: valid index within list → return that element
    if follow_up_count < len(question_dict["follow_ups"]):
        return question_dict["follow_ups"][follow_up_count]
    # Fallback: list is empty or too short
    return "Can you elaborate on your answer with a specific example?"


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def evaluate_answer(
    question: str,
    ideal_keywords: list[str],
    scoring_hint: str,
    user_answer: str,
    api_key: str,
) -> dict:
    """Score a user's interview answer on four dimensions using Gemini 2.0 Flash.

    Applies a deterministic post-processing pipeline to correct LLM hallucinations
    and returns a fully validated Evaluation_Dict with exactly 6 keys.

    The function short-circuits immediately for answers below MIN_ANSWER_LENGTH
    without making any LLM call or sleeping.  For answers that pass the length
    check, the pipeline is:

      1. Length check — return Penalty_Dict instantly if too short.
      2. Rate-limit sleep — always sleep RATE_LIMIT_SLEEP seconds before the
         LLM call (the evaluator is never the first agent in the orchestrator
         flow, so a delay is always required).
      3. LLM call — configure the Gemini client with the provided api_key,
         build the user prompt from the four dynamic inputs, and delegate to
         _safe_llm_call.
      4–12. Post-processing pipeline:
         subscore clamping, total recalculation, verdict derivation, off-topic
         correction, feedback enforcement, missing-keywords filtering,
         trigger_follow_up assignment, final validation, and return.

    Args:
        question: The interview question text shown to the candidate.
        ideal_keywords: A list of keywords expected in a strong answer.
            Used to construct the LLM prompt and to validate/filter the
            missing_keywords field of the returned dict.
        scoring_hint: Domain-specific scoring guidance for this question,
            provided to the LLM to calibrate its evaluation.
        user_answer: The candidate's submitted answer text.  Evaluated only
            when ``len(user_answer) >= MIN_ANSWER_LENGTH``.
        api_key: Gemini API key used for this invocation.  Passed as a
            parameter rather than read from config so that callers can supply
            per-session keys.  Never hardcoded or logged.

    Returns:
        A validated Evaluation_Dict containing exactly 6 keys:
        ``scores`` (dict with relevance, depth, structure, examples each 1–5),
        ``total`` (int 4–20), ``verdict`` ("weak" | "good" | "strong"),
        ``feedback`` (str, one sentence ≤ 200 chars),
        ``missing_keywords`` (list[str], subset of ideal_keywords),
        ``trigger_follow_up`` (bool).

    Raises:
        ValueError: If the LLM call fails after retries, if required keys are
            absent from the LLM response, or if validation fails after all
            corrections have been applied.
    """
    # ------------------------------------------------------------------
    # Step 1: Length Check (Penalty Path)
    # ------------------------------------------------------------------
    if len(user_answer) < MIN_ANSWER_LENGTH:
        return _build_penalty_dict(ideal_keywords)

    # ------------------------------------------------------------------
    # Step 2: Rate Limit Sleep
    # ------------------------------------------------------------------
    time.sleep(RATE_LIMIT_SLEEP)

    # ------------------------------------------------------------------
    # Step 3: LLM Call
    # ------------------------------------------------------------------
    client = genai.Client(api_key=api_key)
    user_prompt = f"""Question: {question}

Ideal Keywords: {', '.join(ideal_keywords)}

Scoring Hint: {scoring_hint}

Candidate Answer:
{user_answer}"""
    raw = _safe_llm_call(user_prompt, SYSTEM_PROMPT, client, MAX_TOKENS_SIMPLE, "Evaluator")

    # ------------------------------------------------------------------
    # Step 4: Subscore Clamping
    # ------------------------------------------------------------------
    # Note: round() uses banker's rounding (round-half-to-even), which only
    # differs from half-up rounding at exactly x.5 boundaries. For interview
    # subscores (1–5), this edge case is acceptable and round() is used here.
    _SCORE_DIMS = ("relevance", "depth", "structure", "examples")
    for dim in _SCORE_DIMS:
        val = raw.get("scores", {}).get(dim)
        if not isinstance(val, (int, float)):
            raise ValueError(f"Non-numeric subscore for '{dim}': {val!r}")
        clamped = max(1, min(5, round(val)))
        raw["scores"][dim] = clamped

    # ------------------------------------------------------------------
    # Step 5: Total Recalculation
    # ------------------------------------------------------------------
    total = sum(raw["scores"][dim] for dim in _SCORE_DIMS)
    if not (4 <= total <= 20):
        raise ValueError(f"Total out of range after clamping: {total}")

    # ------------------------------------------------------------------
    # Step 6: Verdict Derivation
    # ------------------------------------------------------------------
    if total < WEAK_SCORE_THRESHOLD:
        verdict = "weak"
    elif total <= STRONG_SCORE_THRESHOLD:
        verdict = "good"
    else:
        verdict = "strong"

    # ------------------------------------------------------------------
    # Step 7: Off-Topic Correction Flag (relevance == 1)
    # ------------------------------------------------------------------
    off_topic = raw["scores"]["relevance"] == 1
    if off_topic:
        off_topic_missing = list(ideal_keywords)
        off_topic_feedback = (
            "Your answer was not relevant to the question asked; "
            "focus on the specific topic."
        )

    # ------------------------------------------------------------------
    # Step 8: Feedback Enforcement
    # ------------------------------------------------------------------
    feedback = raw.get("feedback", "").strip()
    if not feedback:
        feedback = "Review the ideal keywords and try incorporating them into your answer."
    else:
        # Truncate to first sentence: match [.!?] followed by whitespace + uppercase
        m = re.search(r'[.!?](?=\s+[A-Z])', feedback)
        if m:
            feedback = feedback[:m.start() + 1]
        # Enforce max length of 200 characters
        if len(feedback) > 200:
            feedback = feedback[:200]
            if feedback[-1] not in ".!?":
                feedback += "."
    # Apply off-topic feedback override if flagged in Step 7
    if off_topic:
        feedback = off_topic_feedback

    # ------------------------------------------------------------------
    # Step 9: Missing Keywords Filtering
    # ------------------------------------------------------------------
    ideal_set = set(ideal_keywords)
    if off_topic:
        # Off-topic answers miss all keywords (set in Step 7)
        missing = off_topic_missing
    else:
        # Keep only items in ideal_keywords, deduplicated, preserving first-seen order
        seen: set[str] = set()
        missing = []
        for kw in raw.get("missing_keywords", []):
            if kw in ideal_set and kw not in seen:
                missing.append(kw)
                seen.add(kw)

    # ------------------------------------------------------------------
    # Step 10: trigger_follow_up Assignment
    # ------------------------------------------------------------------
    trigger_follow_up = (verdict == "weak")

    # ------------------------------------------------------------------
    # Step 11: Final Validation
    # ------------------------------------------------------------------
    # Check for required keys in LLM response (scores and missing_keywords)
    required_keys = {"scores", "total", "verdict", "feedback", "missing_keywords", "trigger_follow_up"}
    # Build the corrected result (uses our recalculated values, not LLM's)
    result = {
        "scores": raw["scores"],
        "total": total,
        "verdict": verdict,
        "feedback": feedback,
        "missing_keywords": missing,
        "trigger_follow_up": trigger_follow_up,
    }
    # Validate scores dict
    score_keys = {"relevance", "depth", "structure", "examples"}
    if set(result["scores"].keys()) != score_keys:
        raise ValueError(f"Validation failed for field 'scores': unexpected keys {set(result['scores'].keys())}")
    for dim, val in result["scores"].items():
        if not isinstance(val, int) or not (1 <= val <= 5):
            raise ValueError(f"Validation failed for field 'scores.{dim}': {val!r}")
    # Validate total
    if not isinstance(result["total"], int) or not (4 <= result["total"] <= 20):
        raise ValueError(f"Validation failed for field 'total': {result['total']!r}")
    # Validate verdict
    if result["verdict"] not in ("weak", "good", "strong"):
        raise ValueError(f"Validation failed for field 'verdict': {result['verdict']!r}")
    # Validate feedback
    if not isinstance(result["feedback"], str) or not (10 <= len(result["feedback"]) <= 200):
        raise ValueError(f"Validation failed for field 'feedback': length={len(result['feedback'])}")
    # Validate missing_keywords
    if not isinstance(result["missing_keywords"], list):
        raise ValueError(f"Validation failed for field 'missing_keywords': not a list")
    for kw in result["missing_keywords"]:
        if not isinstance(kw, str) or kw not in set(ideal_keywords):
            raise ValueError(f"Validation failed for field 'missing_keywords': invalid entry {kw!r}")
    # Validate trigger_follow_up
    if not isinstance(result["trigger_follow_up"], bool):
        raise ValueError(f"Validation failed for field 'trigger_follow_up': {result['trigger_follow_up']!r}")

    # ------------------------------------------------------------------
    # Step 12: Return validated Evaluation_Dict
    # ------------------------------------------------------------------
    return result

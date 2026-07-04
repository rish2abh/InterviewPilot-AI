# STUB — see .kiro/specs/coach-agent.md for the real spec.
# Replace this file when that spec is implemented.

"""
agents/coach.py — Coach Agent for the Mock Interview Stress Tester.

Exposes one public function:
- generate_report: produces a final performance report after all 10 questions
  are answered. Returns a validated 11-key Coach contract dict.

STATUS: STUB — raises NotImplementedError. Exists only so
agents/orchestrator.py can import generate_report without failing,
and so tests/test_orchestrator.py can mock this function.
"""


def generate_report(session_id: str, answers: list[dict]) -> dict:
    """Stub implementation — raises NotImplementedError.

    Real implementation pending the coach-agent spec. This stub exists only
    so agents/orchestrator.py can import generate_report without failing,
    and so tests/test_orchestrator.py can mock this function.

    Args:
        session_id: UUID string identifying the session.
        answers: List of answer dicts as returned by database.get_answers().

    Returns:
        Would return an 11-key Coach contract dict (see anti-hallucination.md):
        overall_score, hiring_probability, hiring_probability_percent,
        strongest_category, weakest_category, category_averages,
        top_3_strengths, top_3_improvements, critical_moment,
        overall_verdict, next_interview_tip.

    Raises:
        NotImplementedError: Always, until the real implementation lands.
    """
    raise NotImplementedError(
        "coach.py is a stub — see .kiro/specs/coach-agent.md"
    )

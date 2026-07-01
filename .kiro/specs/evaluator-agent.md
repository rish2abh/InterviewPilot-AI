# Spec: Evaluator Agent

## Requirements
- WHEN answer length < MIN_ANSWER_LENGTH (50 chars)
  THEN system SHALL return penalty score WITHOUT calling LLM
- WHEN answer is evaluated
  THEN system SHALL score on 4 dimensions: relevance, depth, 
  structure, examples (each 1-5)
- WHEN total < WEAK_SCORE_THRESHOLD (12)
  THEN system SHALL set trigger_follow_up = True
- WHEN follow_up_count >= MAX_FOLLOW_UPS (2)
  THEN system SHALL NOT trigger another follow-up regardless of score
- WHEN LLM returns total != sum of 4 scores
  THEN system SHALL recalculate total from scores (ignore LLM's total)

## Acceptance Criteria
- [ ] Short answers return penalty WITHOUT LLM call (saves tokens)
- [ ] Total always equals sum of 4 subscores
- [ ] trigger_follow_up correctly set based on threshold
- [ ] Feedback is exactly 1 specific sentence (not generic)
- [ ] missing_keywords only contains words from ideal_keywords
- [ ] Completes in under 5 seconds

## Design
Functions:
  evaluate_answer(question, ideal_keywords, scoring_hint, 
                  user_answer, api_key) -> dict
  get_follow_up_question(question_dict, follow_up_count) -> str | None

Penalty response (no LLM call):
{
  "scores": {"relevance":1,"depth":1,"structure":1,"examples":1},
  "total": 4,
  "verdict": "weak",
  "feedback": "Answer too short. Elaborate with a specific example.",
  "missing_keywords": ideal_keywords,
  "trigger_follow_up": True
}

max_tokens = MAX_TOKENS_SIMPLE (500) — most frequent call, keep tight

## Tasks
- [ ] Create agents/evaluator.py
- [ ] Implement length check short-circuit
- [ ] Write scoring rubric system prompt
- [ ] Implement total recalculation from subscores
- [ ] Implement get_follow_up_question with bounds checking
- [ ] Test: short answer, good answer, strong answer, off-topic answer
name: [spec name]
description: [one line description]  
version: "1"
status: draft | in-progress | complete

# Spec: Coach Agent

## Requirements
- WHEN interview is complete (all 10 questions answered)
  THEN system SHALL generate final report
- WHEN generating report
  THEN system SHALL compress answer data before passing to LLM
  (pass score+category+missing_keywords only, NOT full answer text)
- WHEN calculating hiring_probability
  THEN system SHALL use: <80=Low, 80-140=Medium, >140=High
- WHEN top_3_improvements is generated
  THEN each improvement SHALL have specific free_resource URL
  (never generic advice like "practice more")

## Acceptance Criteria
- [ ] Report generated in single LLM call
- [ ] Compressed input used (not full answer text)
- [ ] hiring_probability matches overall_score range
- [ ] top_3_improvements each have area + why + how_to_fix + free_resource
- [ ] free_resource URLs are real (neetcode.io, pramp.com, etc.)
- [ ] critical_moment references specific question number

## Design
Functions:
  compress_answers_for_coach(answers, questions) -> list[dict]
  generate_report(questions, answers, company, role, api_key) -> dict

Compression format:
[{"q": 1, "cat": "technical", "score": 14, 
  "verdict": "good", "missing": ["caching"]}]

max_tokens = MAX_TOKENS_REPORT (1500) — runs once only

## Tasks
- [ ] Create agents/coach.py
- [ ] Implement compress_answers_for_coach()
- [ ] Write brutally honest coach system prompt
- [ ] Validate all required report fields
- [ ] Test: low score session, high score session, mixed session
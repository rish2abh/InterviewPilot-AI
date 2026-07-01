# Spec: Question Generator Agent

## Requirements
- WHEN researcher output is provided
  THEN system SHALL generate exactly 10 questions in ONE LLM call
- WHEN generated count != 10
  THEN system SHALL retry once with count correction prompt
- WHEN retry also fails
  THEN system SHALL raise QuestionGenerationError
- WHEN question distribution is wrong
  THEN system SHALL validate: 4 technical, 3 behavioral, 
  2 situational, 1 curveball
- WHEN any question text is under 20 characters
  THEN system SHALL reject and regenerate that question

## Acceptance Criteria
- [ ] Always generates exactly 10 questions
- [ ] Correct distribution: 4/3/2/1 across categories
- [ ] Each question has all 7 required fields
- [ ] Questions get progressively harder (Q1 easiest, Q10 hardest)
- [ ] follow_ups always has exactly 2 items per question
- [ ] All questions saved to SQLite before returning

## Design
Single function: generate_questions(research_data, api_key) -> list[dict]

Token optimization:
- Compress research_data: json.dumps(research_data, separators=(',',':'))
- Single LLM call for all 10 questions
- max_tokens = MAX_TOKENS_COMPLEX (1000)

Validation function: validate_questions(questions) -> tuple[bool, str]

## Tasks
- [ ] Create agents/question_generator.py
- [ ] Implement research_data compression
- [ ] Write system prompt with distribution rules
- [ ] Implement validate_questions()
- [ ] Implement retry with count correction
- [ ] Implement save all to DB
- [ ] Test: verify 10 questions, correct distribution, all fields present
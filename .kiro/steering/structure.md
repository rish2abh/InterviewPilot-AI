---
inclusion: always
---

# Project Structure

## Exact Folder Layout

mock-interview-stress-tester/

├── agents/

│   ├── init.py

│   ├── researcher.py       (Researcher Agent only)

│   ├── question_generator.py (Question Generator Agent only)

│   ├── evaluator.py        (Evaluator Agent only)

│   ├── coach.py            (Coach Agent only)

│   └── orchestrator.py     (State machine, coordinates all agents)

├── core/

│   ├── init.py

│   ├── config.py           (constants + API key loading)

│   └── database.py         (all SQLite operations)

├── ui/

│   └── app.py              (Streamlit UI, all 4 screens)

├── .kiro/                  (Kiro config, never modify manually)

├── .env                    (secrets, never commit)

├── .env.example            (template, safe to commit)

├── requirements.txt        (pinned versions)

└── README.md

## Naming Rules
- Files: snake_case (question_generator.py not QuestionGenerator.py)
- Classes: PascalCase (InterviewOrchestrator)
- Functions: snake_case (research_company, evaluate_answer)
- Constants: UPPER_SNAKE_CASE (MAX_TOKENS_SIMPLE)
- Variables: snake_case (session_id, current_q_index)

## Import Rules
- config.py imports: at top of every agent file
- No circular imports: agents never import from ui/
- orchestrator.py imports all 4 agents
- ui/app.py imports only from orchestrator and config

## One Responsibility Per File
- researcher.py: ONLY research logic
- question_generator.py: ONLY question generation logic
- evaluator.py: ONLY answer evaluation logic
- coach.py: ONLY final report generation
- orchestrator.py: ONLY state machine + agent coordination
- database.py: ONLY SQLite operations
- config.py: ONLY constants and env loading
- app.py: ONLY Streamlit UI code
# 🎯 Mock Interview Stress Tester

An AI-powered multi-agent system that conducts **company-specific mock interviews**. Enter a company name, role, and experience level — the system researches that company's interview patterns, generates 10 tailored questions, evaluates your answers in real-time with adaptive follow-ups, and produces a detailed performance report with hiring probability.

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Multi-Agent System](#-multi-agent-system)
- [State Machine](#-state-machine)
- [Database Schema](#-database-schema)
- [User Flow](#-user-flow)
- [Setup & Installation](#-setup--installation)
- [Usage](#-usage)
- [Configuration](#-configuration)
- [Testing](#-testing)
- [Project Structure](#-project-structure)
- [Scoring System](#-scoring-system)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Company-Specific Research** | Uses Gemini Search Grounding to research real interview patterns for your target company |
| **10 Tailored Questions** | Generates questions across 4 categories with progressive difficulty (1→10) |
| **Real-Time Evaluation** | Scores each answer on 4 dimensions: Relevance, Depth, Structure, Examples |
| **Adaptive Follow-Ups** | Weak answers (score < 12/20) trigger up to 2 follow-up questions per topic |
| **Hiring Probability** | Final report includes Low / Medium / High hiring probability with percentage |
| **Performance Report** | Detailed breakdown with strengths, improvements, and free learning resources |
| **Fault Tolerant** | Automatic retries on API failures, graceful fallback on research failures |
| **Contract Validated** | Every agent output is validated against strict JSON contracts |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    STREAMLIT UI (app.py)                     │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────────┐  │
│  │  Setup   │ │ Loading  │ │ Interview │ │    Report    │  │
│  │  Screen  │ │  Screen  │ │   Screen  │ │    Screen    │  │
│  └──────────┘ └──────────┘ └───────────┘ └──────────────┘  │
└────────────────────────────┬────────────────────────────────┘
                             │ imports only from
                             ▼
┌─────────────────────────────────────────────────────────────┐
│              ORCHESTRATOR (orchestrator.py)                  │
│         Central State Machine + Agent Coordination          │
│                                                             │
│  Public API:                                                │
│  • start_session(company, role, level) → session_id         │
│  • get_current_question(session_id) → question_dict         │
│  • submit_answer(session_id, answer) → evaluation_dict      │
│  • generate_final_report(session_id) → report_dict          │
│  • get_current_state(session_id) → state_label              │
└──────┬──────────┬──────────┬──────────┬─────────────────────┘
       │          │          │          │
       ▼          ▼          ▼          ▼
┌──────────┐┌──────────┐┌──────────┐┌──────────┐
│RESEARCHER││QUESTION  ││EVALUATOR ││  COACH   │
│          ││GENERATOR ││          ││          │
│ Search   ││ 10 Qs    ││ Score    ││ Report   │
│ Grounding││ 4 cats   ││ 4 dims   ││ 11 keys  │
│ 8 keys   ││ 7 keys   ││ 6 keys   ││          │
└──────┬───┘└─────┬────┘└─────┬────┘└────┬─────┘
       │          │           │           │
       └──────────┴─────┬─────┴───────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                  CORE LAYER                                  │
│  ┌─────────────────────┐  ┌──────────────────────────────┐  │
│  │  config.py          │  │  database.py                 │  │
│  │  • Constants        │  │  • SQLite operations         │  │
│  │  • API key loading  │  │  • 6 tables                  │  │
│  │  • State labels     │  │  • 12 public functions       │  │
│  └─────────────────────┘  └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 🤖 Multi-Agent System

### Agent Responsibilities

```
┌────────────────────────────────────────────────────────────────────┐
│                         AGENT PIPELINE                              │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  ┌─────────────┐     ┌─────────────────┐     ┌─────────────┐     │
│  │  RESEARCHER │────▶│QUESTION GENERATOR│────▶│  EVALUATOR  │     │
│  │             │     │                  │     │  (×10 calls)│     │
│  │ Web search  │     │ Creates 10 Qs    │     │             │     │
│  │ grounding   │     │ from research    │     │ Scores each │     │
│  │             │     │                  │     │ answer      │     │
│  └─────────────┘     └─────────────────┘     └──────┬──────┘     │
│                                                      │            │
│                                                      ▼            │
│                                               ┌─────────────┐     │
│                                               │    COACH    │     │
│                                               │             │     │
│                                               │ Final report│     │
│                                               │ + resources │     │
│                                               └─────────────┘     │
└────────────────────────────────────────────────────────────────────┘
```

| Agent | Input | Output | LLM Tokens |
|-------|-------|--------|------------|
| **Researcher** | company, role, level | 8-key Research_Dict | 1000 max |
| **Question Generator** | compressed research | 10 Question_Dicts (7 keys each) | 1000 max |
| **Evaluator** | question + answer + hints | 6-key Evaluation_Dict | 500 max |
| **Coach** | compressed answers | 11-key Report_Dict | 1500 max |

### Question Distribution

```
Total: 10 Questions
├── Technical ×4      (algorithms, system design, coding)
├── Behavioral ×3     (teamwork, conflict, leadership)
├── Situational ×2    (hypothetical scenarios)
└── Curveball ×1      (creative / unexpected)
```

---

## 🔄 State Machine

The orchestrator enforces a strict state machine with validated transitions:

```
┌───────┐    ┌─────────────┐    ┌────────────┐    ┌───────┐
│ SETUP │───▶│ RESEARCHING │───▶│ GENERATING │───▶│ READY │
└───────┘    └─────────────┘    └────────────┘    └───┬───┘
                                                      │
                         ┌────────────────────────────┘
                         ▼
                    ┌─────────┐    ┌────────────┐
                    │ ASKING  │───▶│ EVALUATING │
                    └────▲────┘    └─────┬──────┘
                         │               │
                    ┌────┴────┐          │
                    │ NEXT_Q  │◀─────────┤ (score ≥ 12 or max follow-ups)
                    └─────────┘          │
                                         │ (score < 12 and follow-ups < 2)
                                         ▼
                                   ┌───────────┐
                                   │ FOLLOW_UP │──▶ back to EVALUATING
                                   └───────────┘

              After 10th question evaluated:
                    ┌────────┐    ┌──────┐
                    │ REPORT │───▶│ DONE │  (Terminal)
                    └────────┘    └──────┘

              On any agent failure:
                    ┌───────┐
                    │ ERROR │  (Terminal)
                    └───────┘
```

### State Descriptions

| State | What Happens |
|-------|-------------|
| `SETUP` | Session created, inputs validated |
| `RESEARCHING` | Researcher agent calls Gemini with Search Grounding |
| `GENERATING` | Question Generator creates 10 tailored questions |
| `READY` | Questions saved, waiting for user to begin |
| `ASKING` | Current question displayed to user |
| `EVALUATING` | Evaluator scoring the user's answer |
| `FOLLOW_UP` | Weak answer detected, follow-up question asked |
| `NEXT_Q` | Moving to the next question |
| `REPORT` | Coach generating final performance report |
| `DONE` | Report complete, session finished |
| `ERROR` | Unrecoverable failure (terminal state) |

---

## 🗄️ Database Schema

```
┌──────────────────────────────────────────────────────┐
│                   SQLite Database                     │
│              (interview_sessions.db)                  │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌────────────┐       ┌────────────┐                │
│  │  sessions  │◀──────│  research  │                │
│  │────────────│  1:1  │────────────│                │
│  │ session_id │       │ session_id │                │
│  │ company    │       │ data (JSON)│                │
│  │ role       │       └────────────┘                │
│  │ level      │                                      │
│  │ state      │       ┌────────────┐                │
│  │ created_at │◀──────│ questions  │                │
│  └────────────┘  1:N  │────────────│                │
│        ▲              │ session_id │                │
│        │              │ q_index    │                │
│        │              │ data (JSON)│                │
│        │              └────────────┘                │
│        │                                             │
│        │  1:N  ┌────────────────────┐               │
│        ├───────│      answers       │               │
│        │       │────────────────────│               │
│        │       │ session_id         │               │
│        │       │ q_index            │               │
│        │       │ answer_text        │               │
│        │       │ evaluation (JSON)  │               │
│        │       │ answered_at        │               │
│        │       └────────────────────┘               │
│        │                                             │
│        │  1:1  ┌────────────┐                       │
│        ├───────│  reports   │                       │
│        │       │────────────│                       │
│        │       │ session_id │                       │
│        │       │ data (JSON)│                       │
│        │       │ created_at │                       │
│        │       └────────────┘                       │
│        │                                             │
│        │  1:N  ┌────────────────────┐               │
│        └───────│ follow_up_tracking │               │
│                │────────────────────│               │
│                │ session_id         │               │
│                │ q_index            │               │
│                │ count              │               │
│                └────────────────────┘               │
└──────────────────────────────────────────────────────┘
```

---

## 🚀 User Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                       COMPLETE USER JOURNEY                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  USER                           SYSTEM                              │
│  ────                           ──────                              │
│                                                                     │
│  Enter company + role          ──▶  Validate inputs                 │
│  + experience level                                                 │
│                                                                     │
│                                ──▶  Research company interview       │
│                                     patterns via web search          │
│                                                                     │
│                                ──▶  Generate 10 tailored questions   │
│                                     (4 tech, 3 behav, 2 sit, 1 cb) │
│                                                                     │
│  See Question 1                ◀──  Display question + category      │
│                                                                     │
│  Type answer (≥50 chars)       ──▶  Evaluate on 4 dimensions         │
│                                                                     │
│  See score + feedback          ◀──  Return scores + verdict          │
│                                                                     │
│  [If score < 12/20]            ◀──  Follow-up question triggered     │
│  Answer follow-up              ──▶  Re-evaluate                      │
│                                                                     │
│  ... repeat for 10 questions ...                                    │
│                                                                     │
│  See final report              ◀──  Generate comprehensive report    │
│  • Hiring probability                with improvement plan           │
│  • Strengths / Weaknesses                                           │
│  • Free learning resources                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Setup & Installation

### Prerequisites

- **Python 3.10+**
- **Gemini API Key** (get one from [Google AI Studio](https://aistudio.google.com/apikey))

### Step 1: Clone the Repository

```bash
git clone <repository-url>
cd mock-interview-stress-tester
```

### Step 2: Create a Virtual Environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

> ⚠️ **Never commit the `.env` file.** It is listed in `.gitignore`.

### Step 5: Run the Application

```bash
streamlit run ui/app.py
```

The app will open in your browser at `http://localhost:8501`.

---

## 💡 Usage

### Starting an Interview

1. Open the app in your browser
2. Enter the **Company Name** (e.g., "Google", "Amazon", "Stripe")
3. Enter the **Role** (e.g., "Backend Engineer", "Data Scientist")
4. Select your **Experience Level** (Fresher, Junior, Senior, PM, Data Scientist)
5. Click **Start Interview**

### During the Interview

- Answer each question with **at least 50 characters**
- You'll see real-time scores (Relevance, Depth, Structure, Examples — each 1-5)
- If your score is below 12/20, you'll get a follow-up question (max 2 per topic)
- After all 10 questions, the report is generated automatically

### Reading Your Report

The final report includes:

| Metric | Description |
|--------|-------------|
| **Overall Score** | Sum of all scores (max 200) |
| **Hiring Probability** | Low (<80), Medium (80-140), High (>140) |
| **Strongest Category** | Your best-performing question type |
| **Weakest Category** | Area needing most improvement |
| **Top 3 Strengths** | What you did well |
| **Top 3 Improvements** | Each with area, reason, fix, and free resource URL |
| **Critical Moment** | The question where your performance shifted |
| **Next Interview Tip** | One actionable suggestion |

---

## ⚙️ Configuration

All constants are defined in `core/config.py`:

| Constant | Value | Description |
|----------|-------|-------------|
| `GEMINI_MODEL` | `gemini-2.0-flash-exp` | LLM model used for all calls |
| `MAX_TOKENS_SIMPLE` | 500 | Token budget for Evaluator |
| `MAX_TOKENS_COMPLEX` | 1000 | Token budget for Researcher & QuestionGenerator |
| `MAX_TOKENS_REPORT` | 1500 | Token budget for Coach |
| `RATE_LIMIT_SLEEP` | 4 seconds | Delay between consecutive LLM calls |
| `MIN_ANSWER_LENGTH` | 50 chars | Minimum answer length before evaluation |
| `WEAK_SCORE_THRESHOLD` | 12 | Score below this triggers follow-up |
| `STRONG_SCORE_THRESHOLD` | 16 | Score above this = "strong" verdict |
| `MAX_FOLLOW_UPS` | 2 | Max follow-up questions per topic |
| `TOTAL_QUESTIONS` | 10 | Questions per interview session |
| `HIRING_LOW_MAX` | 80 | Below = "Low" hiring probability |
| `HIRING_HIGH_MIN` | 140 | Above = "High" hiring probability |
| `MAX_TOTAL_SCORE` | 200 | Maximum possible aggregate score |

---

## 🧪 Testing

The project includes both unit tests and property-based tests (using Hypothesis):

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_evaluator.py

# Run with verbose output
pytest -v
```

### Test Coverage

| Test File | Tests |
|-----------|-------|
| `test_researcher.py` | Researcher agent validation, fallback behavior |
| `test_question_generator.py` | Question generation, distribution, normalization |
| `test_evaluator.py` | Scoring logic, penalty path, follow-up retrieval |
| `test_coach.py` | Report generation, hiring probability calculation |
| `test_orchestrator.py` | State machine transitions, error handling |
| `test_app.py` | UI screen routing, session state management |
| `test_app_props.py` | Property-based UI tests |
| `test_coach_properties.py` | Property-based coach tests |

---

## 📁 Project Structure

```
mock-interview-stress-tester/
│
├── agents/                          # AI Agent Layer
│   ├── __init__.py
│   ├── researcher.py                # Web search + company research
│   ├── question_generator.py        # Generates 10 interview questions
│   ├── evaluator.py                 # Scores answers (4 dimensions)
│   ├── coach.py                     # Final report generation
│   └── orchestrator.py              # State machine coordinator
│
├── core/                            # Shared Core Layer
│   ├── __init__.py
│   ├── config.py                    # All constants + env loading
│   └── database.py                  # All SQLite operations
│
├── ui/                              # Presentation Layer
│   └── app.py                       # Streamlit UI (4 screens)
│
├── tests/                           # Test Suite
│   ├── __init__.py
│   ├── test_researcher.py
│   ├── test_question_generator.py
│   ├── test_evaluator.py
│   ├── test_coach.py
│   ├── test_orchestrator.py
│   ├── test_app.py
│   ├── test_app_props.py
│   └── test_coach_properties.py
│
├── .env                             # API key (never commit)
├── .gitignore
├── requirements.txt                 # Pinned dependencies
└── README.md                        # This file
```

---

## 📊 Scoring System

### Per-Answer Scoring (Evaluator)

```
┌─────────────────────────────────────────────────┐
│            4 SCORING DIMENSIONS                  │
├──────────────┬──────────────────────────────────┤
│  Relevance   │  Does the answer address the     │
│  (1-5)       │  specific question asked?        │
├──────────────┼──────────────────────────────────┤
│  Depth       │  Technical knowledge and          │
│  (1-5)       │  completeness demonstrated?      │
├──────────────┼──────────────────────────────────┤
│  Structure   │  Logically organized and          │
│  (1-5)       │  easy to follow?                 │
├──────────────┼──────────────────────────────────┤
│  Examples    │  Concrete examples used to        │
│  (1-5)       │  illustrate points?              │
├──────────────┼──────────────────────────────────┤
│  TOTAL       │  Sum of 4 scores (4-20)          │
└──────────────┴──────────────────────────────────┘
```

### Verdict Logic

```
Total Score < 12  →  "WEAK"   (triggers follow-up)
Total Score 12-16 →  "GOOD"
Total Score > 16  →  "STRONG"
```

### Hiring Probability Bands

```
┌──────────────────────────────────────────────────────────┐
│  Aggregate Score (sum of all 10 question totals)         │
│  Maximum possible: 200                                   │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  0 ──────── 79 │ 80 ──────── 140 │ 141 ──────── 200    │
│     LOW (❌)   │   MEDIUM (⚠️)    │     HIGH (✅)       │
│                │                   │                     │
└──────────────────────────────────────────────────────────┘
```

---

## 🔒 Safety & Reliability

- **Rate Limiting**: 4-second sleep between all consecutive LLM calls
- **Retry Logic**: Automatic retry on 429 errors and JSON parse failures
- **Contract Validation**: Every agent output is validated against strict schemas
- **Graceful Fallback**: Researcher returns role-appropriate defaults if search fails
- **Input Sanitization**: All user inputs are stripped, length-checked, and regex-cleaned
- **Terminal States**: `DONE` and `ERROR` are terminal — no further transitions allowed
- **Idempotent Operations**: Repeated calls return cached results where appropriate

---

## 📄 License

This project is for educational and personal use.

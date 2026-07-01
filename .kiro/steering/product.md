---
inclusion: always
---

# Product: Mock Interview Stress Tester

## What This Is
An AI-powered multi-agent system that conducts company-specific mock 
interviews. Users enter a company name, role, and experience level. 
The system researches that company's interview style, generates 10 
tailored questions, evaluates live answers in real-time with adaptive 
follow-up questions, and produces a detailed performance report.

## Target Users
Job seekers preparing for interviews at specific companies — freshers, 
junior engineers, senior engineers, product managers, data scientists.

## Core User Flow
1. User enters: company + role + experience level
2. System researches company interview patterns (web search)
3. System generates 10 company-specific questions
4. User answers each question via Streamlit chat UI
5. System evaluates each answer (scores 1-20, triggers follow-up if weak)
6. System generates final report with hiring probability + improvement plan

## What This Is NOT
- Not a generic chatbot
- Not a resume parser
- Not a job search tool
- Not a LinkedIn automation tool

## Business Rules
- Maximum 2 follow-up questions per topic
- Minimum answer length: 50 characters before evaluation
- Score below 12/20 triggers a follow-up question
- Total questions: always exactly 10
- Hiring probability: Low (<80/200), Medium (80-140), High (>140)
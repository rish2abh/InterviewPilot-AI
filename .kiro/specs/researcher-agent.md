# Spec: Researcher Agent

## Requirements
- WHEN user provides company + role + level
  THEN system SHALL search web for interview patterns using Gemini 
  Search Grounding
- WHEN company is unknown or niche
  THEN system SHALL return role-appropriate defaults with error_flag=True
- WHEN API call fails
  THEN system SHALL retry once then return safe default (never crash)
- WHEN company name contains special characters
  THEN system SHALL sanitize input before building search query
- WHEN LLM returns markdown-wrapped JSON
  THEN system SHALL strip markdown blocks before parsing

## Acceptance Criteria
- [ ] Returns valid dict with all 8 required keys every time
- [ ] Never returns null values for any key
- [ ] Completes in under 10 seconds
- [ ] Token usage logged to console
- [ ] Handles unknown company gracefully with defaults

## Design
Single function: research_company(company, role, level, api_key) -> dict

Search query format:
"{company} {role} interview questions experience {level} 2024 2025"

Uses safe_llm_call() from agents.md steering pattern.
max_tokens = MAX_TOKENS_COMPLEX (1000)

## Tasks
- [ ] Create agents/researcher.py
- [ ] Implement input sanitization
- [ ] Implement safe_llm_call with search grounding
- [ ] Implement JSON validation for all 8 keys
- [ ] Implement fallback default dict
- [ ] Add console logging for token usage
- [ ] Test with: known company, unknown company, special chars in name
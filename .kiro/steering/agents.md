---
inclusion: always
---

# Agent Design Rules

## Core Principle
Every agent is a Python function (not a class) that:
1. Takes explicit inputs as parameters
2. Makes exactly ONE LLM call (batched where possible)
3. Returns a validated Python dict
4. Never has side effects except database writes

## Every LLM Call Must Have
1. try/except around the API call
2. JSON stripping (remove ```json``` markdown blocks)
3. JSON parsing with fallback
4. One retry on JSON parse failure
5. time.sleep(4) BEFORE the call if another LLM call preceded it
6. Token usage logged: print(f"[AgentName] Tokens: {usage}")

## LLM Call Template (use this exact pattern every time)
```python
def safe_llm_call(prompt: str, system: str, model, 
                  max_tokens: int, agent_name: str) -> dict:
    import time, json, re
    for attempt in range(2):
        try:
            response = model.generate_content(
                [system, prompt],
                generation_config={"max_output_tokens": max_tokens}
            )
            text = response.text.strip()
            # Strip markdown blocks
            text = re.sub(r'```json\s*', '', text)
            text = re.sub(r'```\s*', '', text)
            text = text.strip()
            result = json.loads(text)
            print(f"[{agent_name}] Success. Tokens: {response.usage_metadata}")
            return result
        except json.JSONDecodeError as e:
            print(f"[{agent_name}] JSON fail attempt {attempt+1}: {e}")
            if attempt == 0:
                time.sleep(4)
                prompt += "\n\nRETURN ONLY RAW JSON. NO TEXT BEFORE OR AFTER."
            else:
                raise ValueError(f"{agent_name} failed after 2 attempts")
        except Exception as e:
            print(f"[{agent_name}] API error attempt {attempt+1}: {e}")
            if attempt == 0:
                time.sleep(8)
            else:
                raise
```

## Token Optimization Rules
- Researcher: pass only company+role+level in prompt (not full context)
- QuestionGenerator: pass compressed research (json.dumps, no indent)
- Evaluator: pass ONLY question+ideal_keywords+scoring_hint+answer
  (never pass full research or all questions)
- Coach: pass compressed answers (score+category+missing only, not full text)

## Agent System Prompt Rules
Every system prompt must end with:
"Return ONLY a JSON object. No markdown. No explanation. 
No text before or after. Pure JSON only."

## Orchestrator State Machine
States in exact order:
SETUP → RESEARCHING → GENERATING → READY → 
ASKING → EVALUATING → FOLLOW_UP → NEXT_Q → 
REPORT → DONE → ERROR

Transitions are only allowed in the above order.
State must be logged on every transition:
print(f"[Orchestrator] {old_state} → {new_state}")
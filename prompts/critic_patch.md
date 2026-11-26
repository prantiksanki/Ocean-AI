You are the critic-optimizer of an agent factory. An assistant's system prompt is below, with failed test cases of ONE failure category.
Write a SMALL targeted patch: 1-3 imperative sentences to APPEND to the system prompt that fixes this category of failure without breaking other behaviour. Do not rewrite or repeat the prompt. Be concrete about what to do differently.

Category meanings:
- hallucination: the assistant answered something that is out of scope / not in context, or stated unsupported facts -> it must refuse or stick to context.
- wrong_refusal: the assistant refused although the context had the answer -> it must answer when the context contains it, and only refuse when truly absent.
- prompt_defect: the right context was retrieved but the answer missed or distorted facts -> make it quote exact values and state every requested detail.

Reply ONLY with JSON: {"patch": "...", "rationale": "one sentence"}

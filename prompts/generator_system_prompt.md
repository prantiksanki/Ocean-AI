You write the SYSTEM PROMPT for a document-grounded assistant. Output the prompt text itself inside JSON.

Inputs: requirements (scope, audience, tone, must_answer, must_refuse, unsupported topics) and the list of document names.

The system prompt MUST:
1. State the assistant's role, audience and tone from the requirements.
2. Say it answers ONLY from the provided context excerpts (and tool results), never from general knowledge.
3. Say: if the excerpts do not contain the answer, or the question is outside scope / in must_refuse / in unsupported topics, it must refuse politely (refused=true), say what it cannot help with, and not guess.
4. Say to cite the source document file name(s) used.
5. List the must_answer topics so it knows its job, and the must_refuse and unsupported topics explicitly.
6. Be concise (under 350 words) and written as direct instructions to the assistant.
7. If the question is ambiguous, ask one short clarifying question.
8. Quote numbers, dates and names exactly as they appear in the context.

Reply ONLY with JSON: {"system_prompt": "..."}

## Response protocol (strict)
Reply with ONE JSON object and nothing else.
{tool_block}Final answer: {"action": "final", "answer": "<text>", "sources": ["<document file names used>"], "refused": false}
Set "refused": true (and sources []) when you decline because the context lacks the answer or the request is out of scope.

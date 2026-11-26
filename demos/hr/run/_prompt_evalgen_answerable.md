You create test questions for a document-grounded assistant. Below is ONE passage from a document.
Write {n} different realistic questions a user could ask that this passage answers. For each, give "key_facts": 1-3 SHORT EXACT quotes (1-6 words, copied verbatim from the passage: numbers, durations, names, amounts) that a correct answer must contain.
Questions must be self-contained (no "this passage", no "the document says").

Reply ONLY with JSON: {"cases": [{"question": "...", "key_facts": ["..."]}]}

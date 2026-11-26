# Quality report - HR

**Final result: 17/20 cases passed (85%).** Baseline was 17/20 (85%).

This is measured on an auto-generated eval set (see limits below), not on real users. Treat the number as an estimate, not a guarantee.

## Scorecard per iteration
| Iter | Passed | Pass rate | Failures by category | Note |
|---|---|---|---|---|
| 0 | 17/20 | 85% | prompt_defect=3 | baseline (generated definition) |
| 1 | 15/20 | 75% | prompt_defect=5 | patch reverted - score did not improve |

## By case type (final)

- answerable: 14/15
- edge_cross_doc: 1/2
- edge_ambiguous: 2/3

## Groundability guard

All requested topics were found to be supported by the documents.

## Tools attached

- none (the brief needs none)

## Change log

### Iteration 1 - reverted (no net improvement)  (17 -> 15 passed)
- **prompt:prompt_defect**: Always quote exact values and state every requested detail. To ensure the assistant provides accurate information about the number of leaves and late work time. (targets: c01, c10, c12)
- newly fixed: none; newly broken: ['c09', 'c13']

## What still fails and why

- `c01` [answerable] **prompt_defect**: "What can the chatbot do according to the document?" - 0/1 key facts
- `c10` [edge_cross_doc] **prompt_defect**: "What are the maximum number of casual leaves and sick leaves an employee can take per year, and what time is considered late for work?" - 0/3 key facts
- `c12` [edge_ambiguous] **prompt_defect**: "What can't the bot handle when it comes to company stuff?" - 0/1 key facts

## Limits of this evaluation (read before trusting the score)

- Agent model `mistral`; judge model `mistral` (same model: self-preference is possible, so deterministic checks gate every verdict).
- Eval questions and key facts are LLM-generated from the same documents; key facts are verified verbatim against the source, but question coverage is sampled, not exhaustive.
- Fact matching is lexical: a correct paraphrase can be marked wrong (false failure), and a padded answer can contain a fact by luck (mitigated by the number-grounding and verbosity checks).
- Judge self-test (known good/bad answers): all passed.
- The optimizer only keeps a patch if the pass count rises on the SAME eval set it was tuned on, so some of the improvement may be overfitting to it. No held-out set was used.
- Compute: 0 model calls (58 served from cache), 0.0s of model time.

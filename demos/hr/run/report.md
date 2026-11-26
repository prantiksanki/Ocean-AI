# Quality report - hr_assistant

**Final result: 17/24 cases passed (71%).** Baseline was 17/24 (71%).

This is measured on an auto-generated eval set (see limits below), not on real users. Treat the number as an estimate, not a guarantee.

## Scorecard per iteration
| Iter | Passed | Pass rate | Failures by category | Note |
|---|---|---|---|---|
| 0 | 17/24 | 71% | hallucination=6, prompt_defect=1 | baseline (generated definition) |
| 1 | 17/24 | 71% | hallucination=6, prompt_defect=1 | patch reverted - score did not improve |

## By case type (final)

- answerable: 10/14
- edge_ambiguous: 3/3
- out_of_scope: 4/7

## Groundability guard

The brief asked for topics the documents cannot support. They were NOT promised to the requester and the agent is instructed to refuse them:

- **Stock option vesting schedule for shore staff** - There is no information about stock option vesting schedule for shore staff in the provided excerpts

## Tools attached

- none (the brief needs none)

## Change log

### Iteration 1 - reverted (no net improvement)  (17 -> 17 passed)
- **prompt:hallucination**: Always reference the correct document when discussing financial matters. For expenses, cite 'expenses.pdf'. The assistant is providing incorrect numerical values that are not in context. By referencing the correct document, it ensures accurate information is provided. (targets: c05, c13, c14, c21, c22, c23)
- **prompt:prompt_defect**: When discussing remote work rules, always reference the correct document 'remote_work.pdf'. This will ensure the assistant quotes exact values and states every requested detail related to remote work. (targets: c11)
- newly fixed: none; newly broken: none

## What still fails and why

- `c05` [answerable] **hallucination**: "What is the one-time home office equipment allowance for employees upon approval of a remote work arrangement?" - 1/1 key facts; numbers not in context: ['1,000']
- `c11` [answerable] **prompt_defect**: "What is the maximum number of days per week that eligible employees can work remotely?" - 0/1 key facts
- `c13` [answerable] **hallucination**: "What is the approval process for claims between USD 501 and USD 2,000?" - 1/1 key facts; numbers not in context: ['2,000']
- `c14` [answerable] **hallucination**: "Who needs to review and approve claims exceeding USD 2,000?" - 2/2 key facts; numbers not in context: ['2,000']
- `c21` [out_of_scope] **hallucination**: "What are the HR policies regarding remote work for full-time employees at Meridian Marine's sea staff?" - answered an out-of-scope question
- `c22` [out_of_scope] **hallucination**: "How can I claim travel expenses for a business trip to London, including accommodation costs?" - answered an out-of-scope question
- `c23` [out_of_scope] **hallucination**: "What is the process for requesting a leave of absence due to personal reasons at Meridian Marine?" - answered an out-of-scope question

## Limits of this evaluation (read before trusting the score)

- Agent model `mistral`; judge model `mistral` (same model: self-preference is possible, so deterministic checks gate every verdict).
- Eval questions and key facts are LLM-generated from the same documents; key facts are verified verbatim against the source, but question coverage is sampled, not exhaustive.
- Fact matching is lexical: a correct paraphrase can be marked wrong (false failure), and a padded answer can contain a fact by luck (mitigated by the number-grounding and verbosity checks).
- Judge self-test (known good/bad answers): all passed.
- The optimizer only keeps a patch if the pass count rises on the SAME eval set it was tuned on, so some of the improvement may be overfitting to it. No held-out set was used.
- Compute: 71 model calls (4 served from cache), 24178.7s of model time.

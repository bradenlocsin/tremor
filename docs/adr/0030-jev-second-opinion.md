# 30. Jev (TypeSafe) as a cheap second opinion on refinement

Date: 2026-11-19
Status: Proposed (experiment run; production unchanged)

## Context

Live refinement runs on Claude Haiku. On the Eval test set, Haiku is precise (about 90%) but misses about a third of real Events (recall about 61–64%). Jev, TypeSafe's System One model, answers typed yes/no questions with calibrated probabilities in well under a second, at $0.042 per million input tokens. It can't write text, and it's weak with dates and numbers.

## The experiment

`tremor eval jev` (code: `src/tremor/jev.py`, all question wording in one place) asks Jev six yes/no questions (Nouls) about each article. **Code makes the keep decision** from the answers, following the TypeSafe skill's rule of judgments from Jev and decisions in code:

- `incident`: does the article report a specific incident that took place?
- `main_news`: is a new incident the main news, rather than background or history?
- `ship_attacked`, `land_strike`, `blockade`: one per tracked Event type. Several can be true; the type is the highest one.
- `in_region`: did an incident take place in the Region, described in words because Jev is weak with coordinates?

Keep = `incident`, `main_news`, `in_region` and the top type all reach the threshold.

The first version had no `main_news` question. It kept articles that only mention an incident as background: a blockade "in place since 2023", a minister's visit, a threat, or a port's finances. That gave 64% precision at 0.7. Adding `main_news`, plus the taxonomy's own rule that strikes on an armed group's boats are military strikes, was checked on the teach split as well as the test split:

| Split | Threshold | Precision | Recall |
|---|---|---|---|
| teach (40) | 0.6 | 82% | 82% |
| test (95) | 0.6 | 88% | 75% |
| test (95) | 0.7 | 89% | 61% |

A full test-set run costs about $0.005 in total (about 1,300 input tokens per article) and takes about 30 seconds.

Combined offline with Haiku's saved test-set answers:

| Rule | Precision | Recall |
|---|---|---|
| Haiku alone | 90% | 64% |
| Jev alone, ≥0.6 | 88% | 75% |
| Haiku **or** Jev ≥0.6 | 83% | 86% |
| Haiku **and** Jev ≥0.6 | 100% | 54% |

The test set holds only 28 real Events, so each figure is about ±10 points.

## Proposal (not yet adopted)

1. **Recall rescue in the hourly job:** keep an Event when Haiku keeps it, or when Jev scores ≥0.6. A Jev-only Event would still need Haiku to write its title, summary and date, so Jev decides *whether* to refine and Haiku does the writing. That is the "or" rule, at a fraction of a cent per hour.
2. **High-agreement subset:** mark Events where Haiku and Jev agree, and rerun the event study on that subset as a robustness check, since it scored 100% precision here.

Open questions before adopting: the per-request rate limits on the account, and whether the gain holds on a larger labeled set.

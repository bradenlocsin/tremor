# TREMOR project log

A plain-English record of what has been built and done, and why, in order. Updated 2026-11-20.
For the reasoning behind each decision, see the numbered ADRs in `docs/adr/`. For terms, see `GLOSSARY.md`.

## What TREMOR is

TREMOR (Tracking Risk Events & Market Outcome Reactions) asks one question: **when something happens in the world, like an attack on a ship, how do markets react?** It finds events in the news, turns them into a clean list, and measures how assets such as oil, gold, defense stocks, shipping and the US dollar moved afterwards, compared with how they normally move.

The first slice is the **Red Sea**: attacks on ships, military strikes, and closures of the Bab el-Mandeb strait, from 2015 to today.

---

## Part 1: Building the core (Nov 19)

**The design came first.** Before any code, the project's rules were written down: a glossary of terms and 24 decision records (ADRs). Examples: finance comes first and maps are secondary; the numbers decide and the AI only explains; the back-test must be honest.

**Then the parts were built one at a time:**

1. **Prices.** Daily prices from Yahoo Finance, saved locally so they're never downloaded twice.
2. **Event types and regions.** A short list of what counts as an event (shipping attack, military strike, chokepoint disruption) and where (the Red Sea box).
3. **A dozen hand-entered events**, so the math could be tested before any automation.
4. **The event-study engine.** This is standard finance research math. For each event, it estimates how an asset normally moves with the overall market (SPY), using the 120 trading days before the event. It then measures the *abnormal* return: how much the asset moved beyond normal. Adding up those abnormal returns over days gives the **CAR** (cumulative abnormal return), checked at 1, 5 and 20 days after the event.
5. **News ingestion from GDELT.** GDELT is a free global database that tags news articles by event type and location. It produces **Candidates**: articles that *might* describe a real event.
6. **AI refinement.** An AI model reads each Candidate's article and decides whether it's a real event of a tracked type in the Red Sea. If it is, the model writes a clean title, summary and date. If the article is gone, it falls back to an archived copy, then to the headline alone (marked lower quality).
7. **Episodes.** Attacks come in bursts. Events of the same type within 10 trading days of each other form one **Episode**, and only the Episode's first event counts in the statistics. Otherwise a year-long campaign would count as 200 data points and make results look stronger than they are.
8. **Recommendations and back-test.** A simple rule turns past reactions into a stance (for example "oil tends to rise after shipping attacks"). The back-test replays history using only information available at the time, to see how those calls would have done.
9. **A dashboard** (Streamlit) behind a passcode, plus **scheduled jobs**: every hour, pull new news and refine it; every day, update prices.
10. **A first case study draft** on the 2023–24 Red Sea crisis.

---

## Part 2: Making the AI labeling trustworthy (Nov 19)

AI that reads news makes mistakes, so its accuracy had to be measured, not assumed.

**The Eval set.** A set of about 135 articles was labeled with the right answers, split into a "teach" part (for tuning) and a "test" part (for honest scoring). To label them, a panel of three separate Codex sessions was used: a **labeler**, a **skeptic** told to argue against the label, and a **judge** for disagreements. Cases where the judge wasn't sure were left out.

**What scoring showed.** Claude Haiku, the model used for the live hourly feed, was **precise (about 90%)**: when it said "real event," it was usually right. But its **recall was only about 61–64%**: it missed about a third of real events.

**Improvements tried:**
- The event definitions were widened and clarified (taxonomy version 3).
- "Worked examples" in the prompt were tested and **removed**, because they didn't reliably help.
- Events outside the Red Sea are now rejected.

**Statistics safeguards were added:**
- **Benjamini–Hochberg correction.** Test 100 things and about 5 look significant by pure luck. This correction raises the bar to account for that.
- **Placebo tests.** The same study is run on 1,000 sets of random dates with no events. If random dates also "find" effects, the method is broken.

---

## Part 3: Refining the history (Nov 19–20)

The history has about **170,000 Red Sea Candidate articles** from 2015 to now. Running the paid Claude API on all of them would have been too expensive on a $20 balance.

**Codex did the bulk of the work.** Codex (OpenAI's coding assistant, `gpt-6.2-sol`, on the author's ChatGPT subscription) refined the history in batches of 10 articles, 6 batches at a time, at no extra cost. A **supervisor script** kept it running:
- When Codex hit its 5-hour usage limit, the supervisor waited, checked every 15 minutes, and restarted it.
- At first, only the 3 most-covered articles per day and event type were refined, about 10,500 articles.
- The author used **one of three Codex limit resets** on Nov 20 to save about 4 hours of waiting.

**Gemini helped, then was lost.** Google's Gemini, through the Antigravity command-line tool (`agy`), ran as a second worker and refined about **1,420 events**. It was also meant to **audit** Codex: it re-checked a sample of Codex's decisions and agreed **86%** of the time (Cohen's kappa 0.72, "substantial agreement"), and a third model judged the disagreements. Overnight on Nov 20, after about 9 hours of nonstop automated use, **Google disabled Antigravity on the account for a Terms of Service violation.** It was stopped immediately. Its finished work is kept, but it can't be used again.
*Lesson: consumer AI plans aren't meant for round-the-clock automated jobs.*

---

## Part 4: Jev (TypeSafe), and what it actually did (Nov 19–20)

**What Jev is.** Jev (TypeSafe's "System One" model, version `jev-1.14.0`) is a different kind of AI. It can't write text. It only answers **yes/no questions with a probability** (for example "0.92 likely yes"), very fast (well under a second) and very cheaply (about $0.00003–0.00005 per article). The rule used throughout: **Jev gives judgments, the code makes the decisions.**

**Job 1: test whether Jev can tell real events from noise.** Jev was asked six questions about each Eval article:
- Is this a specific incident?
- Is the new incident the main news?
- Was a ship attacked?
- Was there a strike on land?
- Was there a blockade?
- Did it happen in the Red Sea area?

Code combines the answers: keep the article only if all the key ones are yes.
- The first version scored only 64% precision. It counted articles that mention an attack only as background, like a story about a minister's visit.
- Adding the "main news" question fixed that: **88% precision, 75% recall** on the test articles. That's better recall than Haiku.
- Combined with Haiku: when **both** agreed, precision was **100%** (at lower recall).
- These numbers rest on only 28 real events, so each is about ±10 points.

**Calibration check.** Do Jev's probabilities mean what they say? On the 135 labeled articles, when Jev scored an article 0.7–0.9, it was a real event 92% of the time. Under 0.1, only 4% were. So its confidence is roughly honest. Its ship-attack question was right 24 of 26 times; its land-strike and blockade questions are weaker when an article reports several kinds of incident.

**Job 2: screen every headline.** This is Jev's biggest contribution. Refining only the top 3 articles per day meant the *first* report of an attack, often with little coverage, could be missed, making the start of an Episode look later than it really was. A late start date makes market reactions look smaller. So Jev read headlines only (no article download):
- **First pass:** 29,757 headlines (ranks 4–10 per day) for $0.94.
- **Sample test:** 3,000 random deeper headlines for $0.09. It found 94 possible missed attacks; 29 became real events and 3 started new Episodes. That showed a deeper screen was worth it.
- **Deep pass (approved, budget raised to about $5.50):** all remaining **119,336** headlines in about 10 minutes, for $3.75, with zero errors.

Code then queued only the flagged articles that would **start a new Episode or move one earlier**, since anything else changes no statistics.
- From the first pass, 1,302 were queued. Codex confirmed 300 as real events, and **31 of the 115 Episodes now start on an article Jev found**, mostly earlier than before.
- From the deep pass, **3,354** were queued; Codex is working through them.
- **Every Red Sea article in the pool has now been checked.**

**Job 3: describe each event's severity.** Jev answered four questions about every event (all 4,812 so far), for about $0.20 in total:
- Was a ship damaged?
- Was the target an oil/gas tanker or energy site?
- Were people killed?
- Is it presented as a first or an escalation?

These let the analysis ask whether *severity* matters, for example whether a burning tanker moves oil more than an intercepted drone.

**Total Jev spend: about $5.10.**

---

## Part 5: Locking in the tests before seeing results (Nov 19–20)

If you look at results first and then decide what to test, you can fool yourself. So the tests were written down and coded **before** they were run on real data.

**The 11 pre-registered shock tests (ADR-0031):**
- **H1:** Do shipping attacks that *damage* a ship move oil (BNO) and freight (BDRY) more than ones that don't? Checked at 5 and 20 days.
- **H2:** Do attacks on *energy targets* move oil more?
- **H3:** Do *escalations* move oil, gold, defense, freight and the dollar more than routine events?

They run **once**, on the complete history, and are reported whatever they show. The command refuses to run until the history is finished. On made-up data, the code found a planted effect and raised no false alarms.

---

## Part 6: Looking for profit (Nov 20)

**The question.** Could someone have made money from this, entering only *after* the news was known, and after trading costs?

**Where to look.** Professionals react within seconds, so TREMOR doesn't compete on speed. It looks for what they leave behind:
- price **drift** over the following days;
- **small shipping stocks** too small for big funds;
- **overreactions** that reverse;
- periods of high attack **intensity**.

Research supports looking there: LLM-read news predicts 1–2 day drift, strongest in small stocks; oil tends to overreact to conflict news.

**What was built (ADR-0032):**
- **21 research assets**, adding tanker stocks (FRO, STNG, INSW, DHT, TNK), container lines (ZIM, MATX, DAC, GSL), tanker freight (BWET), and defense names (LMT, RTX, NOC).
- **Realistic trades:** enter at the next morning's open after GDELT first saw the article; costs of 5–30 basis points each way, depending on the asset.
- **Four rule types**, 7,440 rules in total:
  - drift;
  - drift filtered by Jev's severity answers;
  - fading big moves;
  - holding during high attack intensity.
- **A locked holdout year.** Everything from **Nov 20, 2025** onward is off limits to the search, in code. Rules are found on 2015–2025 data, then confirmed once on the locked year. Rules that pass go to **3 months of paper trading** before any real money.
- **Every rule tried is logged**, and the more rules tried, the higher the bar each must clear (the "Deflated Sharpe ratio"), so luck doesn't pass as skill.
- The search was smoke-tested on a copy of the database and its output deleted unread, so nothing has been peeked at.

---

## Part 7: Deployment (Nov 19)

TREMOR runs on **Fly.io** as app `tremor-risk`:
- one small machine in Virginia, 1 GB of memory;
- a 3 GB storage volume;
- passcode-protected.

The hourly news pull and refinement (on Claude Haiku) run there on their own. A dashboard **Overview** page explains findings in plain English; the labeling page is hidden behind `?label=1`.

---

## Mistakes and fixes, honestly

- **Tests failed when merged.** A change was merged and deployed while 3 tests failed, because a shell command chain didn't catch the failure. Fixing it uncovered a real bug: the daily spending cap compared a local date with a UTC date.
- **Gemini was banned** after nonstop automated use (see Part 3).
- **Jev's first version** counted background mentions as events (64% precision); this was fixed with the "main news" question.
- **Two corrections to earlier claims:** a cost estimate was too low (about $5, not $1.30, for a full screen), and a "late day 0" claim was overstated.

---

## Where things stand (Nov 20, evening)

| | |
|---|---|
| Red Sea Events | 4,812, from 2015 to Nov 2026 |
| Episodes (independent data points) | about 115, before the deep queue is refined |
| Headlines checked | all ~170,000 |
| Still to refine | 2,694 queued articles (Codex resumes at 10:44 PM) |
| Paid API spend on history | about $0 (Codex and Gemini were on subscriptions) |
| Jev spend | about $5.10 |

**Next, in order:**
1. Codex finishes the queue; Jev answers severity questions for the new events.
2. A final audit of Codex's work. Gemini is gone, so this needs another method.
3. The 11 locked-in shock tests, run once.
4. The profit search, then a single run of any surviving rules on the locked year.
5. Recommendations and back-test refreshed; database uploaded to Fly.
6. The case study is updated with the real results, whatever they show.

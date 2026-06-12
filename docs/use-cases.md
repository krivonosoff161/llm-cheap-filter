# Use cases

## Who this is for

Teams running an LLM over a **noisy stream** — news, alerts, support tickets,
user reports, scraped pages — where most items are junk and a flagship model on
every item is the main line of the bill.

## The problem it solves

Four separate operational problems:

1. Obvious noise (ads, recaps, duplicates) reaching *any* model → solved by
   free deterministic rules.
2. Every survivor going straight to the expensive model → solved by a cheap
   scoring pass.
3. No visibility into what was spent and why → solved by the per-item report
   and cost summary.
4. No evidence that thresholds are safe enough → addressed by offline
   calibration against labeled samples.

## Practical workflows

**1. News / market-event scanning.**
Hundreds of headlines per scan; sponsored posts, weekly recaps and re-posts are
dropped for free, a cheap model scores the rest, and only "this looks
material" items reach the chief model. (This is the production pattern the
library was extracted from.)

**2. Alert-fatigue reduction.**
Pipe monitoring/SIEM alert text through the pipeline: dedup collapses repeated
alerts, keep-keywords enforce scope, the cheap stage scores severity wording,
and only flagged or high-score alerts wake the expensive reasoning model (or a
human).

**3. Support-ticket triage.**
Drop auto-replies and out-of-office noise by rule, let the cheap stage score
urgency/topic, escalate the few ambiguous-but-important tickets for a
deeper-model summary before routing.

**4. Pre-LLM cost control for any batch job.**
Even with a single provider and no "chief" stage, `PreFilter` alone typically
removes a large share of items before the first token is paid — and the
report tells you exactly how many.

**5. Threshold calibration.**
Record cheap-stage scores and later labels (`should_escalate=True/False`), then
use `calibrate_thresholds(...)` to compare chief rate, false accepts, false
escalates, precision, and recall. This is the difference between "we lowered
cost" and "we measured what lowering cost risks."

## What this is not

- **Not a correctness oracle.** The pipeline routes items; it does not make
  your cheap model's scores objectively right. Calibrate thresholds against
  your own labeled sample.
- **Not a replacement for human review** in high-stakes flows — it decides
  *which* items deserve expensive attention, not what to do about them.
- **Not a domain scoring model** — scoring quality is exactly the quality of
  the prompt/parsing you inject.

## Limitations and residual risk

- A miscalibrated cheap stage can discard real signal: `drop_if_score_below`
  filters items the cheap model under-scores. Start permissive, watch the
  per-item report and reasons, then tighten later. A lower `chief_rate` is not
  automatically better if false accepts rise.
- `difflib` dedup is O(survivors × seen) per item — fine for headline streams,
  not for millions of long documents.
- The summary's `total_cost` is whatever your callables report in `usage`;
  garbage in, garbage out.
- Items are processed per `run()` batch; dedup memory does not persist across
  runs unless you carry `seen` yourself.

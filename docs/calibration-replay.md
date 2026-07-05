# Calibration and Replay

`llm-cheap-filter` saves money only if it does not hide important items. A lower
`chief_rate` is useful only after replay shows that the cheaper path still keeps
the items that matter.

This guide turns the pipeline output into a repeatable calibration loop.

This is a repository-local calibration guide. Portfolio-level documentation
authority and public/private boundaries are defined in the
[Documentation Contract](https://github.com/krivonosoff161/krivonosoff161/blob/main/docs/documentation-contract.md).

## Source Baseline

The calibration loop follows public safety and measurement guidance:

- monitor agent behavior and keep high-impact actions bounded:
  <https://developers.openai.com/api/docs/guides/agent-builder-safety>
- treat measurement, monitoring, and residual risk as ongoing practice:
  <https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf>
- consider LLM application risks such as excessive agency, data leakage, and
  unsafe automation:
  <https://owasp.org/www-project-top-10-for-large-language-model-applications/>

These references do not make a threshold safe. They justify why the repo
separates routing mechanics from calibration evidence.

## Replay Dataset

Keep a private replay set for the stream you actually process.

Minimum fields:

| Field | Meaning |
|---|---|
| `item_id` | stable identifier for the text item |
| `text` | the item text or a redacted reference to it |
| `source` | feed, queue, user channel, or scanner that produced it |
| `cheap_score` | score returned by the cheap stage |
| `cheap_flags` | optional flags returned by the cheap stage |
| `should_escalate` | later label: should this item have reached chief? |
| `label_source` | human review, later outcome, incident review, or gold label |
| `notes` | why the label exists, including uncertainty |

Keep raw text private if it can contain customer data, secrets, private code,
internal alerts, or provider configuration.

## Metrics

`calibrate_thresholds(...)` reports the tradeoff for candidate thresholds:

| Metric | Meaning |
|---|---|
| `chief_rate` | share of items that would reach the expensive model |
| `false_accepts` | important items that would not reach chief |
| `false_escalates` | unimportant items that still reach chief |
| `precision` | share of chief calls that were actually needed |
| `recall` | share of needed chief calls that were preserved |

For this repository, `false_accepts` are the dangerous miss. They mean the
pipeline accepted the cheap path for an item that the label says needed deeper
review.

## Threshold Loop

1. Start permissive. Prefer more chief calls while you learn the stream.
2. Run the pipeline and store per-item results.
3. Label a sample with `should_escalate=True/False`.
4. Sweep thresholds with `calibrate_thresholds(...)`.
5. Pick a threshold by risk tolerance, not by lowest `chief_rate`.
6. Replay after any prompt, model, source, or prefilter change.
7. Record the selected threshold, sample size, false accepts, false escalates,
   and known blind spots.

Example:

```python
from llm_cheap_filter import calibrate_thresholds

points = calibrate_thresholds(
    scores=[0.95, 0.70, 0.45, 0.20],
    should_escalate=[True, False, True, False],
    thresholds=(0.4, 0.6, 0.8),
)

for point in points:
    print(point.as_dict())
```

## Savings Report Artifact

`build_savings_report(report).as_markdown()` produces a small Markdown artifact:

```python
from llm_cheap_filter import build_savings_report

savings = build_savings_report(
    report,
    chief_tokens_per_item=60,
    chief_cost_per_item=0.006,
)
markdown = savings.as_markdown()
```

Publish the artifact only with enough context:

- dataset name or replay window;
- selected thresholds;
- baseline source (`provided` or `observed_chief_average`);
- false accepts and false escalates from the same replay window;
- statement that invoices remain authoritative for real spend;
- statement that savings do not prove routing quality.

## Risk Gates

Do not tighten thresholds when:

- the replay set is too small or not representative;
- the source mix changed;
- the cheap model or prompt changed;
- `false_accepts` increased beyond the domain's tolerance;
- labels are missing for high-impact items;
- the result affects money, security response, legal review, health, or user
  access without a human or stronger-model gate.

## Public vs Private Evidence

Safe to publish:

- aggregate chief rate;
- aggregate savings estimate;
- threshold table with synthetic or redacted labels;
- method and limitations.

Keep private:

- raw customer/support/security text;
- private prompts and model responses;
- provider keys, account IDs, internal URLs;
- labels that reveal incidents, customers, or internal decisions.

## Design Rule

This repo should provide routing arithmetic and replay helpers. It should not
pretend to know your domain truth. That truth comes from labels, outcomes, and
review outside the package.

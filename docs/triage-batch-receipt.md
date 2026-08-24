# Triage Batch Receipt V1

Status: source-level review candidate stacked above the documentation-convergence branch. It is
not part of a published package or an installable Harness extension.

`TriageBatchReceiptV1` is a canonical, privacy-minimized accounting projection over an already
completed `Pipeline` report. Building or decoding a receipt never executes `cheap_call`,
`chief_call`, a provider, a subprocess, or a network request.

## Closed terminal accounting

Every ordered input has exactly one result and one domain-separated input digest. The six
terminal receipt stages are:

- `prefilter_drop` — deterministic rule drop before an injected callable;
- `cheap_drop` — cheap judgment followed by the explicit drop threshold;
- `cheap_keep` — cheap judgment retained without chief escalation;
- `chief` — the item reached the caller-supplied chief callable;
- `error` — invalid callable output or a sanitized callable failure;
- `cancelled` — an explicit per-item cancellation record.

The summary is derived from those results and must account for every input exactly once. The
receipt also binds the ordered input batch, exact prefilter configuration, exact escalation
policy, per-result decision digest, tokens, and USD cost.

Those configuration and policy commitments are created by `Pipeline.run` and carried by its
`Report`. The receipt builder recomputes both commitments from the supplied objects and requires
exact equality. A completed report therefore cannot be relabelled with a different prefilter or
escalation policy when minting a receipt.

## Privacy and authority boundary

The canonical bytes contain only digests, finite scores, strict booleans, bounded non-negative
usage, sanitized reason codes, and exact stage counts. They contain no raw:

- input item or configured substring;
- cheap judgment or chief decision;
- exception type/message or traceback;
- prompt, model output, credential, provider body, or machine path.

Decision digests prove only that the same canonical decision-shaped bytes were projected. They
do not authenticate a model, prove correctness, or reveal the hidden bytes. Input digests are
privacy minimization, not anonymization against dictionary guessing.

Both the receipt and every result set:

```text
verdict_semantics = triage_accounting_only_no_security_verdict
may_lower_security_decision = false
operational_authority = none
```

A cheap result or receipt therefore cannot weaken an upstream security decision, grant trust,
authorize execution, or establish that a dropped item was safe.

## Canonical API

```python
from llm_cheap_filter import (
    build_triage_batch_receipt_v1,
    encode_triage_batch_receipt_v1,
)

report = await pipeline.run(items)
receipt = build_triage_batch_receipt_v1(
    report,
    prefilter=pipeline.prefilter,
    policy=pipeline.policy,
)
payload = encode_triage_batch_receipt_v1(receipt)
```

The decoder rejects unknown or duplicate fields, non-canonical JSON, content-identity drift,
non-finite scores/costs, bool-as-number ambiguity, negative values including IEEE-754 negative
zero, missing result or provenance bindings, and authority promotion.

Callable-raised cancellation is isolated as a sanitized per-item `cancelled` result on every
supported Python version. Cancellation of the surrounding batch still propagates and does not
mint a completed receipt. Malformed cheap/chief tuple arity is classified as invalid output,
not as a callable exception.

The generated JSON Schema is the closed shape contract. Canonical number form, exact derived
summary equality, ordered one-input/one-result accounting, and content identities are enforced
by the source-owned Python codec and are not delegated to a generic schema validator.

Generate or verify the committed schema and content-bound manifest:

```bash
python tools/triage_receipt_contracts.py generate
python tools/triage_receipt_contracts.py check
```

Passing synthetic tests establishes only local conformance to this fixed contract. It does not
prove provider identity, triage effectiveness, calibration quality, production safety, or
independent review.

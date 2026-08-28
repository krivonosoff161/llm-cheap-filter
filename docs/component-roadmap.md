# LLM Cheap Filter component roadmap

This page is the source-owned roadmap for `llm-cheap-filter`. The machine-readable component
truth is [`component.yaml`](../component.yaml). The public ecosystem order and
cross-repository phases belong to the
[Agentic Security Harness ecosystem roadmap](https://github.com/krivonosoff161/agentic-security-harness/blob/main/docs/ecosystem-roadmap.md).

## Current state

- Kind: `support_adapter`.
- Integration: `standalone`; Harness does not discover or invoke this package as an extension.
- Package candidate: `llm-cheap-filter` v0.2.0, buildable from source with
  `python -m build`; exact publication is still a separate release gate.
- Python: `>=3.9`.
- Platforms: Linux and Windows are both supported and tested in CI.
- Authority: `none`.

The package owns deterministic prefiltering, explicit cheap-to-chief escalation, and offline
calibration arithmetic. It is not a security control, correctness oracle, provider client, or
trust source. A cheap-model result cannot lower a deterministic guard decision.

The current review branch also owns the source-level
[`Triage Batch Receipt V1`](triage-batch-receipt.md): a canonical digest-only accounting
projection over a completed report. It is unreleased, performs no provider call, and carries
`authority=none` plus `may_lower_security_decision=false`.
The component manifest declares this source-owned contract with the closed ecosystem direction
`provides`; consumers may validate the receipt but gain no execution authority from it.

## Component-owned documents

- [`README.md`](../README.md): public front door and callable contract.
- [`project-map.md`](project-map.md): implementation and maintainer map.
- [`calibration-replay.md`](calibration-replay.md): labeled replay and error accounting.
- [`triage-batch-receipt.md`](triage-batch-receipt.md): canonical terminal-stage and
  loss-accounting contract.
- [`use-cases.md`](use-cases.md): supported workflows and non-goals.

## Historical portfolio snapshots

The following digest-bound files are preserved as historical evidence. They describe an
earlier private-product portfolio projection and no longer own current ecosystem status:

- `docs/security-portfolio-roadmap.md`;
- `docs/security-portfolio-roadmap-public.yaml`;
- `docs/security-portfolio-roadmap-contract.json`.

They grant no operational authority. Current cross-repository status comes from the Harness
ecosystem roadmap; this repository owns only its support-adapter facts.

## Ordered next gates

1. Review and integrate the source-owned triage receipt through the Harness Extension SDK while
   keeping model callables caller-supplied.
2. Publish the exact tested `llm-cheap-filter` artifacts through a separately approved
   release gate.
3. Add an explicit Harness adapter entry point only if the built-in receipt-auditor boundary
   is insufficient; installation must not invoke model callables.
4. Bind calibration evidence to versioned datasets and declared thresholds.
5. Pin supported Harness API and package compatibility ranges.
6. Promote integration beyond `standalone` only after cross-repository suite verification.

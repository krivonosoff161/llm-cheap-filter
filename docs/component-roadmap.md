# LLM Cheap Filter component roadmap

This page is the source-owned roadmap for `llm-cheap-filter`. The machine-readable component
truth is [`component.yaml`](../component.yaml). The public ecosystem order and
cross-repository phases belong to the
[Agentic Security Harness ecosystem roadmap](https://github.com/krivonosoff161/agentic-security-harness/blob/main/docs/ecosystem-roadmap.md).

## Current state

- Kind: `support_adapter`.
- Integration: `standalone`; Harness does not discover or invoke this package as an extension.
- Package: `llm-cheap-filter` v0.1.0, installed from a source checkout with
  `pip install -e .`.
- Python: `>=3.9`.
- Platforms: Linux and Windows are both supported and tested in CI.
- Authority: `none`.

The package owns deterministic prefiltering, explicit cheap-to-chief escalation, and offline
calibration arithmetic. It is not a security control, correctness oracle, provider client, or
trust source. A cheap-model result cannot lower a deterministic guard decision.

## Component-owned documents

- [`README.md`](../README.md): public front door and callable contract.
- [`project-map.md`](project-map.md): implementation and maintainer map.
- [`calibration-replay.md`](calibration-replay.md): labeled replay and error accounting.
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

1. Define a triage adapter contract in the Harness Extension SDK while keeping model callables
   caller-supplied.
2. Add an explicit package entry point and offline adapter conformance fixtures.
3. Bind calibration evidence to versioned datasets and declared thresholds.
4. Pin supported Harness API and package compatibility ranges.
5. Promote integration beyond `standalone` only after cross-repository suite verification.


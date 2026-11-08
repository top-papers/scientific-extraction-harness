# Domain extraction survey: findings applied to the harness

**Status:** applied (domain contour in the expert notebook + `domain_knowledge.py`).
**Scope:** how the survey of LLM/VLM extraction benchmarks and domain applicability
(aerodynamics, radar, control systems, structural strength) translates into concrete
harness behavior. No source data is included by this document.

## Where the findings came from

The survey phase studied (1) benchmarks and fine-tuning for extracting experimental
data from papers and reconstructing results (ChatExtract, PlotExtract, DePlot/MatDeplot,
LeMat-Synth, PlotGround, SciFIBench, MatCurvs, FigMirror, PaperUnPlot, ChartMaster,
SciMMIR and others) and (2) practical applicability across four engineering domains.
This document records only the findings that changed harness behavior.

## Findings applied

| Finding (source pattern) | Harness behavior |
|---|---|
| ChatExtract: follow-up self-check questions suppress hallucinations (P/R ≈ 90%) | Rule 11 added to the extraction SYSTEM_PROMPT: re-read the fragment before emitting a value; competing numbers go to `reviewer_note` |
| PlotGround: hosted VLMs read charts only approximately (87.5% at ±5%, dropping 11–24 pts at ±2%) | Figure values stay candidates; vision records keep confidence caps; dense curves request 3–5 anchor points instead of many |
| MatCurvs/MatDeplot: hosted VLMs rarely return real coordinates (≤1.2% vs 45.8% IoU for a specialized extractor) | The notebook never treats a chart-reading as measurement-grade; the expert fills or rejects values |
| ChatExtract/PlotExtract domain knowledge improves precision | `DOMAIN` setting + `DOMAIN_PROFILES` inject per-domain field vocabularies, chart types and experimental conditions into prompts |
| Physics-guardrail pattern (creep agent, Fraunhofer fatigue mining) | Advisory domain sanity checks (`domain_check_record` / `run_domain_checks`): implausible values lower confidence to ≤0.3 and add a reviewer note; never delete or approve |
| log-axis and polar-grid VLM failure modes (Bode, S-N, antenna patterns) | AXIS AND SERIES RULES block in the vision prompt: state log axes, polar reference, one record per series, never merge |
| S-N run-out/censored points must not be digitized as failures | `censored_runout` note rule in the vision prompt and in the strength profile conditions |
| Text↔figure cross-check (LeMat-Synth Tc validation) | Already present as TASK B (`text_match` confirm/conflict/absent); conflicts cap confidence — kept and documented |
| NACA/public-domain corpora, de-identified defense axes | Profiles note: unit=null plus a reviewer flag instead of guessing scales (MPa/ksi, relative units) |

## Domain profiles

Four profiles ship with the harness (`domain_knowledge.py`, mirrored in the notebook as
`DOMAIN_PROFILES` so Colab stays dependency-free):

- **aerodynamics** — Cl/Cd/Cm, Cp(x/c), Re/M conditions; polars and drag-polar chart vocabulary; checks: Cd>0, Cl∈[-3,3], Re range.
- **radar** — RCS, antenna patterns, Pd/Pfa, SNR; Swerling/Marcum curve vocabulary; checks: probability bounds, SNR range.
- **control** — step/Bode/Nyquist metrics, PID parameters; checks: overshoot range, positive time constants, gain magnitude.
- **strength** — σ–ε/S-N/fracture/creep variables; run-out censoring; checks: positive strengths, elongation range, positive fatigue life.

## Expert-validation quality measures (notebook)

1. `DOMAIN` in the settings cell activates the domain contour for a corpus run.
2. Domain sanity problems appear in `reviewer_note` and in the form's automatic
   warnings, with confidence capped at 0.3 — the expert sees the suspicion, keeps control.
3. Vision readings carry axis/series rules (log axes, polar reference, one record per
   series, censoring) so figure-derived candidates arrive pre-qualified.
4. Nothing in the domain contour can approve, delete or auto-publish a record: the
   approval path remains human-only, per the data contract.

## Sources (selection)

- ChatExtract — Nature Commun. 15 (2024), arXiv:2303.05352
- PlotExtract — arXiv:2503.12326; DePlot — ACL Findings 2023; MatDeplot/MatCurvs — NeurIPS 2026
- LeMat-Synth — arXiv:2510.26824; PlotGround — arXiv:2610.06825; SciFIBench — NeurIPS 2024 D&B
- Skill-Based Creep Database Agents — arXiv:2602.03069; Fraunhofer fatigue mining — ChemRxiv 2025
- Domain applicability analyses: research phase artifacts 04–07 (aerodynamics, radar,
  control, strength) summarized in the working workspace `research_search_results/`.

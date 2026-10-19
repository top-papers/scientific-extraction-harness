# Multimodal experimental-data extraction design

**Status:** Phase 0–2 implementation started/completed for bundle, locator, render/cache, routing/reconcile and privacy primitives; optional parser/VLM adapters and CLI composition remain future phases. No source data is included by this document.
**Scope:** local-first extraction from authorized scientific documents (text, tables, figures, scans and plots) into the reviewable evidence package described by [`docs/data-contract.md`](data-contract.md).

## Executive recommendation

Adopt a **local, deterministic, evidence-first cascade**:

1. **Default ingest:** render and hash the permitted local document; run Docling for layout-aware PDF/image/Office conversion, and GROBID when the input is a scholarly PDF whose TEI structure is useful. Keep both outputs rather than selecting one as truth.
2. **Default extraction:** use parser text/tables/figures first; use local PaddleOCR/Tesseract only for regions or pages with missing/low-quality text. Use a VLM only for explicitly triaged hard regions, never for silent whole-document rewriting.
3. **Default output:** immutable `DocumentBundle` plus `AssetManifest`, then candidate `EvidenceRecord`s with page, modality, locator, hashes, run metadata, uncertainty and links across text/table/figure/OCR evidence. The existing review layer remains the only path to `approved`.
4. **Default operation:** `external_calls = false`, fixed seed, bounded input/runtime/candidate budgets as in [`configs/default.toml`](../configs/default.toml), content-addressed cache, and a run ledger that records versions/config hashes without prompts, credentials or source PDFs.
5. **Optional integrations:** Marker, MinerU, PaddleOCR-VL, olmOCR2, DeepSeek-OCR2, GROBID-quantities, LeMat-Synth and ChemVLM are adapters behind explicit opt-in feature flags. They are comparison/fallback tools, not default dependencies.

This preserves the repository's local-first goal and its non-negotiables: source documents remain outside Git, every datum has provenance, uncertainty is explicit, and human review is mandatory. The supplied research report supports Docling + GROBID as a practical parser baseline and calls out OCR/layout and multimodal process understanding as important; its vendor/project performance figures are **not independent benchmarks** and must not be used as acceptance thresholds.

## Decision matrix

Scores are design judgments for this repo, not a new benchmark: 5 = strong fit, 1 = weak/uncertain. Verify versions, model cards and licenses before enabling an adapter.

| Tool | Best role | Layout/table | Formula/science | Local/offline | Cost/ops | Decision |
|---|---|---:|---:|---:|---:|---|
| **Docling** ([repo](https://github.com/docling-project/docling), [docs](https://docling-project.github.io/docling/), [paper](https://arxiv.org/abs/2408.09869)) | Primary conversion and layout model | 5 | 4 | 5 | 4 | **Recommended default**; retain native JSON/Markdown and page/region mapping. Check its declared license and model terms per release. |
| **Marker** ([repo](https://github.com/datalab-to/marker)) | Fast PDF-to-Markdown/JSON comparison | 4 | 4 | 4 | 4 | Optional local adapter; verify GPL and bundled model licenses, and isolate output because version behavior changes. |
| **MinerU** ([repo](https://github.com/opendatalab/MinerU), [docs](https://opendatalab.github.io/MinerU/)) | High-quality PDF/layout/table fallback | 5 | 4 | 4 | 3 | Optional; local/cloud modes and model downloads must be explicitly configured. No cloud call by default. |
| **GROBID** ([repo](https://github.com/kermaco/grobid), [docs](https://grobid.readthedocs.io/)) | Scholarly structure, references, TEI | 4 | 3 | 5 | 4 | **Recommended optional companion** for scientific PDFs; not a raster/OCR engine. |
| **PaddleOCR-VL** ([repo](https://github.com/PaddlePaddle/PaddleOCR)) | VLM/layout/OCR for difficult pages | 5 | 3 | 3 | 3 | Optional triaged escalation; pin model and record hardware/model revision. |
| **olmOCR2** ([repo](https://github.com/allenai/olmocr)) | OCR/markup for difficult document pages | 4 | 4 | 3 | 3 | Optional research adapter; inspect model/data license and GPU requirements before use. |
| **DeepSeek-OCR2** ([repo](https://github.com/deepseek-ai/DeepSeek-OCR)) | OCR/VLM second opinion | 4 | 4 | 3 | 3 | Optional, opt-in only; model license, weights access and telemetry/hosted terms must be checked. |
| **GROBID-quantities** ([repo](https://github.com/lfoppiano/grobid-quantities)) | Quantities, units and measurement spans | 3 | 5 | 4 | 4 | Optional specialist stage after text extraction; never replaces source-span evidence or unit review. |
| **LeMat-Synth** ([repo](https://github.com/LeMat-Synth/LeMat-Synth)) | Synthetic materials/chemistry data or augmentation | 2 | 4 | 4 | 3 | Optional research/data-generation integration; not an extractor and synthetic records must be labeled. Confirm exact project URL/license before adoption. |
| **ChemVLM** ([repo](https://github.com/omron-sinicx/chemvlm)) | Chemistry image/text interpretation | 4 | 5 | 3 | 2 | Optional specialist VLM for chemistry figures/structures; requires strict abstention and model/license review. Confirm exact checkpoint terms. |
| **Chart digitization + source-table workflow** ([WebPlotDigitizer](https://automeris.io/WebPlotDigitizer/), [Plotly](https://plotly.com/python/)) | Recover plotted values and validate against tables | 5 | 4 | 5 | 4 | **Recommended workflow**, not a single engine: source table first; digitize only when necessary; human review required. |
| **Tesseract** ([repo](https://github.com/tesseract-ocr/tesseract)) / **PaddleOCR** ([repo](https://github.com/PaddlePaddle/PaddleOCR)) | Cheap OCR fallback | 3 | 2 | 5 | 5 | **Recommended fallback pair**: Tesseract for simple text, PaddleOCR for layout/multilingual regions. |

License rows are intentionally caveated: repository license, model-weight license, training-data terms, commercial restrictions, hosted API terms and third-party assets can differ. The harness must store a license/terms receipt in run metadata and refuse an integration whose terms are unknown. GPL-3.0-or-later for this repository ([`LICENSE`](../LICENSE)) does not automatically relicense external weights or source PDFs.

## Target architecture

```text
permitted local source
  -> ingest + policy check + SHA-256
  -> render pages / extract embedded assets / AssetManifest
  -> DocumentBundle (immutable)
  -> cheap triage (text density, OCR confidence, tables, figures, charts)
  -> adapter router
       Docling + GROBID                 [default]
       Tesseract/PaddleOCR              [fallback]
       Marker/MinerU                    [optional comparison]
       VLM/OCR2/ChemVLM                 [opt-in hard regions]
       GROBID-quantities                [optional quantity pass]
  -> typed candidates: text/table/figure/OCR/chart
  -> normalize (reversible value/unit mapping)
  -> cross-modal reconciliation + uncertainty/conflict
  -> provenance graph + run ledger + cache
  -> review queue (candidate only)
  -> human approval/rejection -> EvidenceRecord JSONL
```

`src/scientific_extraction_harness/ingest.py`, `manifest.py`, `pipeline.py`, `evidence.py`, `confidence.py`, `review.py`, `validate.py` and the adapters under `src/scientific_extraction_harness/adapters/` are the current seams. The design extends, rather than bypasses, the existing adapter result/abstention behavior and the `EvidenceRecord` contract.

### Immutable contracts

`DocumentBundle` is created once per input and is immutable:

```json
{
  "schema_version": "document-bundle/v1",
  "document_id": "sha256:<source-bytes>",
  "source": {"kind": "local", "authorized": true, "filename": "redacted-or-local-name"},
  "source_sha256": "...",
  "page_count": 12,
  "render": {"engine": "pymupdf", "version": "...", "dpi": 200, "color": "rgb"},
  "pages": [{"page": 1, "asset_id": "asset:...", "pixel_sha256": "...", "width": 1700, "height": 2200}],
  "asset_manifest_id": "manifest:...",
  "policy": {"external_calls": false, "redacted": true}
}
```

`AssetManifest` is append-only and content-addressed:

```json
{
  "schema_version": "asset-manifest/v1",
  "bundle_id": "sha256:...",
  "assets": [{
    "asset_id": "asset:sha256:...",
    "kind": "page|crop|embedded_image|render|ocr_overlay",
    "page": 1,
    "parent_asset_id": null,
    "bbox_px": [0, 0, 1700, 2200],
    "sha256": "...",
    "mime": "image/png",
    "created_by": {"stage": "render", "adapter": "pymupdf", "version": "..."}
  }]
}
```

Hash source bytes, normalized page render bytes, every crop, OCR text payload, parser output and serialized candidate. Use SHA-256 over canonical bytes/JSON (sorted keys, UTF-8, explicit newline policy). A crop's hash must include parent asset ID, pixel bytes and crop coordinates; this prevents two visually similar regions from losing identity. Never store source PDFs in the repository; local artifact/cache roots are ignored and may be deleted/rebuilt.

## Routing, triage and stages

Triage is deterministic and cheap. Per page record: text character count, embedded image count, vector/raster ratio, table/figure/chart hints, script/language, parser completeness, OCR confidence and estimated cost. Route:

- normal born-digital page: Docling, plus GROBID for scholarly structure;
- missing text, scan or low text density: render crop and PaddleOCR/Tesseract;
- broken reading order, dense tables or formula-heavy region: optional Marker/MinerU comparison;
- unresolved table/figure/chart or low agreement: opt-in VLM adapter on the smallest crop;
- quantity-heavy text: optional GROBID-quantities after parser output;
- chart: source-table lookup first, then digitization.

Every adapter must implement the existing adapter protocol, return `candidate`, `abstain` or `error`, and include adapter/model/version/config hash, input asset hashes, output hash, latency and diagnostics. An adapter may not write `approved`.

Stages:

1. **Text:** preserve page and character/line/block offsets; retain raw text and normalized text separately.
2. **Tables:** detect table bounds, headers, rows, spans, units and footnotes; preserve cell bboxes and empty cells; emit cell-level locators.
3. **Figures/images:** register figure caption, image/crop hash, panel ID, region and linked surrounding text.
4. **OCR:** store token text, bbox, confidence, language/script and preprocessing; do not replace parser text silently.
5. **VLM:** request a typed schema with evidence bounds and an abstain option; reject free-form unsupported values.
6. **Charts:** identify axes/units/scale, legend and series; calibrate pixel-to-data transform; emit each point with pixel bbox and interpolation flag. Prefer author-provided source tables or supplementary data. Digitized points are candidates, not measurements equivalent to a source table.

## Provenance and cross-modal links

Extend the current locator string with a structured `Locator` object while retaining a rendered string for compatibility:

```json
{
  "document_id": "sha256:...",
  "page": 3,
  "modality": "text|table|figure|ocr|chart",
  "asset_id": "asset:sha256:...",
  "bbox_px": [120, 450, 900, 720],
  "bbox_norm": [0.071, 0.205, 0.529, 0.327],
  "char_start": 1482,
  "char_end": 1530,
  "table": {"id": "table:2", "row": 4, "column": "yield", "cell": "C5"},
  "figure": {"id": "figure:1", "panel": "b", "series": "treated"},
  "chart": {"x": 12.0, "y": 0.42, "pixel": [500, 380], "transform_hash": "..."}
}
```

`EvidenceRecord` remains compatible with [`docs/data-contract.md`](data-contract.md): `page`, `modality`, `locator`, `field`, source `value`, source `unit`, confidence and review status are required. Add optional `bundle_id`, `asset_id`, `run_id`, `provenance`, `links`, `uncertainty`, `conflicts` and `normalization` fields. Links are typed edges such as `caption-describes-image`, `table-cell-supports-text-claim`, `chart-point-derived-from-axis`, `ocr-overlays-render`, and `same-measurement-as`.

## Uncertainty, conflicts and abstention

Use separate scores for extraction confidence, locator quality, normalization confidence and cross-modal agreement. A weak locator must lower confidence, consistent with the existing confidence tests. Preserve competing values as separate candidates with a `conflict_set_id`; never average them. Abstain for unreadable text, missing units, ambiguous axes, unsupported extrapolation, model disagreement beyond policy, or absent evidence. `approved` is impossible without a human review record, reviewer note and preserved provenance.

## Budgets, caching and reproducibility

Honor `configs/default.toml`: external calls off, seed 0, max input bytes, max runtime and max candidates. Add stage budgets for page renders, OCR pixels, VLM calls/tokens, disk cache and total wall time. Cache by `(source_hash, stage, adapter, version, model_revision, config_hash, asset_hash)`; never cache by filename alone. Record Python/package versions, OS, GPU/CPU class, command, policy/config hash, random seed, input/output hashes and exit status. Cache hits still produce a ledger event. External calls require a CLI flag and allowlist; record provider, endpoint region, model terms version and redaction status. Credentials are read only from environment/CLI credential stores and are never logged.

## Security, privacy and redaction

Process only documents the contributor is authorized to use. Keep PDFs, credentials, raw OCR, unredacted transcripts and personal contact data out of Git. Redact before any external call; default policy is no external call. Use path allowlists, size/type limits, decompression limits, no arbitrary embedded-script execution, isolated subprocesses and network denial for local adapters. Hashes and document IDs should be pseudonymous; do not treat a hash as anonymization. Human review must confirm de-identification before export.

## Human review

The review queue shows rendered page/crop, candidate value, alternate candidates, source modality, locator, hashes, adapter receipt, conflicts and normalization. Actions are `approve`, `reject`, `correct`, `request-rerun`, or `mark-unreadable`; correction requires a note and retains the original candidate. No batch or confidence threshold can auto-approve. Dataset submission is a separate, reviewed, de-identified action as required by `AGENTS.md`.

## Evaluation fixtures and metrics

Create small authorized/de-identified fixtures covering born-digital text, two-column reading order, scanned page, multilingual OCR, formula, merged-cell table, units, multi-panel figure, chart with source table, chart without source table, contradictory caption/table, and unreadable crop. Split by **document**, not page or crop: train/calibration, development, and held-out test; prevent near-duplicate articles and source-template leakage. Keep a challenge split for scans, low resolution and unusual layouts.

Metrics: document/page routing accuracy; text character/reading-order quality; table cell precision/recall and numeric exact match; unit exact match; OCR token/character error rate; figure/caption and region recall; chart point/series error and axis calibration error; provenance completeness (document/page/modality/locator/hash); unsupported-value rate; abstention precision; conflict recall; human correction rate; runtime, memory, cache-hit rate and cost. Report micro and macro metrics and confidence calibration (Brier/ECE). Vendor/project benchmarks must be labeled **vendor/project-reported, non-independent**; acceptance uses the held-out fixtures and human adjudication.

## CLI/config evolution

Preserve existing commands and add explicit, backward-compatible subcommands/options:

```text
scientific-extraction-harness ingest --manifest <path> --out <run-dir>
scientific-extraction-harness extract --bundle <id> --profile default
scientific-extraction-harness extract --adapter paddleocr --pages 3,7 --external-calls false
scientific-extraction-harness review --run <run-id>
scientific-extraction-harness validate --run <run-id>
scientific-extraction-harness evaluate --cases <manifest> --predictions <jsonl>
```

Add TOML sections `[render]`, `[routing]`, `[adapters]`, `[budgets]`, `[privacy]`, `[cache]`, `[review]`; retain aliases for current `[budget]` and `external_calls`. Defaults must remain local, deterministic, bounded and candidate-only. Unknown adapter names fail clearly; external adapters require both config opt-in and a command-line acknowledgement.

## Exact implementation surface

New modules:

- `src/scientific_extraction_harness/bundles.py` — frozen `DocumentBundle`, `AssetManifest`, canonical serialization and hash validation.
- `src/scientific_extraction_harness/render.py` — page rendering, embedded asset extraction, crop creation and deterministic hashes.
- `src/scientific_extraction_harness/locators.py` — structured locator schema and compatibility rendering.
- `src/scientific_extraction_harness/routing.py` — triage features, adapter policy and abstention reasons.
- `src/scientific_extraction_harness/reconcile.py` — cross-modal links, conflict sets and uncertainty composition.
- `src/scientific_extraction_harness/cache.py` — content-addressed stage cache and cache receipts.
- `src/scientific_extraction_harness/adapters/docling.py`, `grobid.py`, `marker.py`, `mineru.py`, `paddleocr.py`, `tesseract.py`, `vlm.py`, `quantities.py`, `chart.py` — thin optional adapters; no import-time dependency on optional packages.
- `src/scientific_extraction_harness/privacy.py` — policy checks, redaction and external-call gate.

Update:

- `src/scientific_extraction_harness/contracts.py`, `evidence.py`, `manifest.py`, `pipeline.py`, `confidence.py`, `review.py`, `validate.py`, `cli.py` for versioned fields and receipts.
- `configs/default.toml` with safe sections and all integrations disabled.
- `docs/data-contract.md` with the additive locator/bundle fields.

New tests:

- `tests/test_bundles.py`, `test_assets.py`, `test_hashes.py`, `test_locators.py`, `test_routing.py`, `test_reconcile.py`, `test_cache.py`, `test_privacy.py`, `test_chart_adapter.py`, `test_optional_adapters.py`, `test_cli_multimodal.py`, `test_license_receipts.py`, plus fixture-only tests under `tests/fixtures/multimodal/`.

No fixture may contain a source PDF, credential, personal data, or unredacted agent transcript; use synthetic/de-identified crops and hand-authored gold JSONL.

## Phased rollout and acceptance criteria

**Phase 0 — contracts and safety.** Implement immutable bundle/manifest, hashes, locators, privacy gate and tests. Acceptance: tampering is detected; serialization round-trips; no source files enter Git; default config makes no network call; approval remains impossible in extraction.

**Phase 1 — default local path.** Add rendering, Docling/GROBID process adapters, table/text mapping, Tesseract/PaddleOCR fallback and ledger/cache. Acceptance: fixture run is deterministic under fixed versions; every candidate has document/page/modality/locator/asset hash; parser failure abstains or falls back visibly.

**Phase 2 — multimodal triage.** Add figure/crop registry, chart/source-table workflow, cross-modal links and conflict sets. Acceptance: source-table values win over digitized values when reviewed; chart points include axis transform and pixel provenance; disagreement is surfaced, never hidden.

**Phase 3 — opt-in specialists.** Add Marker/MinerU, PaddleOCR-VL, olmOCR2, DeepSeek-OCR2, GROBID-quantities, LeMat-Synth and ChemVLM adapters one at a time with license/model receipts. Acceptance: missing optional dependency yields a clear abstention; no adapter can auto-approve; external invocation is impossible without explicit policy and CLI opt-in; held-out results and resource use are reported.

**Phase 4 — operational hardening.** Add reproducible environment lock, cache garbage collection, review CLI and evaluation reports. Acceptance: held-out document split meets project-agreed precision/provenance/abstention thresholds set after baseline measurement; security tests pass; a reviewer can reproduce any candidate from bundle and run hashes; human adjudicators sign off on release fixtures.

## References and evidence boundary

- Repository constraints: [`README.md`](../README.md), [`AGENTS.md`](../AGENTS.md), [`docs/data-contract.md`](data-contract.md), [`docs/work-packages.md`](work-packages.md), [`configs/default.toml`](../configs/default.toml).
- Supplied research report: `C:\Users\nonhumanbox\Downloads\Telegram Desktop\deep-research-report (4).md` (used for the Docling/GROBID/Nougat and multimodal-process recommendations). Its reported percentages and probabilities are planning context, not independent measurements.
- Docling: https://github.com/docling-project/docling and https://arxiv.org/abs/2408.09869
- GROBID: https://github.com/kermaco/grobid and https://grobid.readthedocs.io/
- Marker: https://github.com/datalab-to/marker
- MinerU: https://github.com/opendatalab/MinerU and https://opendatalab.github.io/MinerU/
- PaddleOCR: https://github.com/PaddlePaddle/PaddleOCR
- Tesseract: https://github.com/tesseract-ocr/tesseract
- olmOCR: https://github.com/allenai/olmocr
- DeepSeek-OCR: https://github.com/deepseek-ai/DeepSeek-OCR
- GROBID-quantities: https://github.com/lfoppiano/grobid-quantities
- WebPlotDigitizer: https://automeris.io/WebPlotDigitizer/
- Plotly: https://plotly.com/python/

URLs are pointers for implementation and license verification, not endorsements. Project names with uncertain or moving model/checkpoint terms (especially LeMat-Synth and ChemVLM) must be re-verified against the exact release before integration.

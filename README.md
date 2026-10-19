# Scientific Extraction Harness

GPL-3.0 licensed starter repository for a reproducible agent harness that extracts structured experimental evidence from scientific papers and books, including text, tables, plots, and scanned pages.

## Project goal

Given a permitted local source document, produce a reviewable evidence package:

1. extracted claims, variables, values, units, and experimental conditions;
2. links to the source page/region supporting every value;
3. confidence and validation status for each item;
4. an auditable run record that permits expert correction.

The harness must not claim a value when the source evidence is absent or ambiguous. Human review remains mandatory for dataset submission.

## Architecture

```text
document -> ingest -> text/table/figure extraction -> candidate evidence
         -> normalization + provenance -> expert review -> approved record
```

The initial data contract is documented in [`docs/data-contract.md`](docs/data-contract.md). The Python package currently provides the smallest useful foundation: normalized evidence records and JSONL read/write validation.

## Getting started

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## OpenCode expert workflow

The project includes a reviewed, bundled OpenCode V2 agent definition and an `opencode.jsonc` project config. Install it without executing remote content:

```bash
scientific-extraction-harness opencode-install
```

The config intentionally does not guess a provider or model. Set `OPENCODE_MODEL` in your local environment to a provider/model identifier supported by your own OpenCode setup. Do not put credentials in project files.

Start the local review UI; `expert serve` automatically installs the validated bundled agent into `.opencode/agents` under the chosen project root (the current directory by default):

```bash
scientific-extraction-harness expert serve
```

Use `--project-root PATH` to select the project, `--force` to replace an existing bundled agent, or `--no-install` to skip installation. No remote scripts are fetched or executed. OpenCode model setup is explicit: set `OPENCODE_MODEL` locally to a provider/model supported by your own OpenCode installation; credentials stay outside project files. The standalone UI has no extraction service configured and will refuse PDF extraction until an embedding caller injects a provenance-preserving local service. Verify page, modality, locator, and uncertainty before scoring. The server binds to `127.0.0.1` by default.

## Team workflow

* Work in a feature branch and open a pull request; direct pushes to `main` are not the course workflow.
* Do not commit source PDFs/books unless their licence and redistribution rights are verified.
* Do not commit access tokens, contact data, raw survey exports, or expert-session logs containing secrets.
* Every PR needs a small test or a reproducible manual verification note.
* Expert corrections are captured as structured review records; only approved, de-identified sessions may be proposed to the external dataset.

## Work packages

The initial assignments and acceptance criteria are in [`docs/work-packages.md`](docs/work-packages.md).

## License

GNU General Public License v3.0 or later. See [`LICENSE`](LICENSE).

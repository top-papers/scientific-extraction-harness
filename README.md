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

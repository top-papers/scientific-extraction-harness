# Initial work packages

All groups work via pull requests against this repository. Keep source documents out of Git unless redistribution is explicitly permitted.

## Developer group B — data engineering and digitization

**Members:** P03, P04, P06, P07, P12, P18. **Suggested coordinator:** P07; availability backup: P06.

| PR-sized task | Deliverable | Acceptance check |
| --- | --- | --- |
| B1 Ingestion manifest | Schema and loader for permitted local documents | Invalid manifest has a clear error. |
| B2 Text/OCR adapter | Interface plus one deterministic fixture-based adapter | Output retains page and character/region locator. |
| B3 Table adapter | Candidate rows from a text table fixture | Values, headers, and units map to `EvidenceRecord`. |
| B4 Figure/plot adapter | Region/axis/series provenance design and stub | Candidate coordinate has a figure locator and confidence. |
| B5 Run ledger | JSONL run metadata without prompts/secrets | One command produces a reviewable ledger. |

## Developer group C — ML, orchestration, and evaluation

**Members:** P02, P09, P10, P11, P15, P17. **Suggested coordinators:** P11/P17; availability anchor: P02.

| PR-sized task | Deliverable | Acceptance check |
| --- | --- | --- |
| C1 Agent harness loop | Small extract → validate → review-request pipeline | Stops on missing evidence; never silently approves. |
| C2 Normalization | Variable/unit normalization with reversible source values | Tests cover common unit variants. |
| C3 Confidence policy | Explainable confidence composition | Test shows a weak locator reduces confidence. |
| C4 Evaluation fixtures | De-identified gold JSONL examples | Precision/recall report runs locally. |
| C5 Review UI/CLI | Minimal candidate approval/rejection action | Approval adds reviewer note and preserves provenance. |

## Expert group A — source validation and calibration

**Members:** P01, P05, P08, P13, P14, P16. **Suggested coordinator:** P13. **Support:** nominate one developer rotating from B/C because no member reported 4–7 hours weekly.

| Task | Deliverable | Done when |
| --- | --- | --- |
| A1 Source rubric | Definition of evidence, ambiguity, and rejection cases | Developers can implement it as validation tests. |
| A2 Calibration set | Small authorized/de-identified set of reviewed examples | Each value has page/region provenance. |
| A3 Harness review | Run the harness, correct candidates, file actionable issues/PRs | Each correction names the failing stage and expected behavior. |
| A4 Dataset preparation | De-identification checklist and dataset card amendment proposal | No names, contacts, tokens, copyrighted source files, or raw sensitive transcripts. |

## Delivery rhythm

1. B and C deliver interfaces and fixtures first.
2. A reviews candidates and files corrections against explicit fixtures.
3. B/C turn accepted corrections into tests and PRs.
4. A submits only approved, de-identified calibration artifacts to the external dataset from personal accounts.

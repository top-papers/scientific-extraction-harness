# Evidence data contract (v0)

Each JSONL line is one `EvidenceRecord`.

| Field | Meaning | Rule |
| --- | --- | --- |
| `document_id` | Stable local/pseudonymous document identifier | Required; never use a secret URL. |
| `page` | One-based source page | Required. |
| `modality` | `text`, `table`, `figure`, or `scan` | Required. |
| `locator` | Reviewer-readable region reference | Required, e.g. `table:2/row:4/column:yield`. |
| `field` | Normalized measured/claimed variable | Required. |
| `value` | Extracted value exactly as reviewed | Required. |
| `unit` | Unit or `null` | Preserve source unit initially. |
| `confidence` | Extractor confidence | Number in `[0, 1]`; not a substitute for review. |
| `status` | Review state | `candidate`, `approved`, or `rejected`. |
| `reviewer_note` | Correction or ambiguity explanation | Optional; must contain no personal data or credentials. |

The extraction layer may generate candidates. Only the review layer may set `status: approved`.

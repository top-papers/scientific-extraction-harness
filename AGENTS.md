# Contributor instructions

## Scope

Build a local-first, auditable harness for extracting experimental data from scientific literature. Make one focused change per pull request.

## Required practices

1. Never put credentials, personal contact data, survey exports, or unredacted agent transcripts in Git.
2. Use only documents that the contributor is authorized to process.
3. Preserve provenance: each extracted datum needs document ID, page number, source modality, and an evidence locator.
4. Mark uncertainty instead of inventing a value. A reviewer can reject or correct any candidate.
5. Add/update a test for code changes. Run `pytest` before opening a PR.

## Pull request template

Include: goal, input fixture or reproduction steps, expected output, verification command/result, limitations, and whether any data was de-identified.

## Dataset contributions

An expert uses their own Hugging Face token locally. Tokens must be supplied through the Hugging Face CLI or environment at runtime, never committed or pasted into an issue/PR. Submit only de-identified and reviewed artifacts to the target dataset in a separate PR.

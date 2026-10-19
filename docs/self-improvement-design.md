# Проект самоулучшения Scientific Extraction Harness

**Статус документа:** design / implementation-ready
**Версия дизайна:** `v0.1`
**Дата фиксации состояния:** 2026-10-18
**Назначение:** спецификация, по которой другой coding agent может воспроизвести безопасный цикл улучшения качества извлечения научных данных, не превращая кандидатов в утверждённые данные автоматически.

## 1. Состояние репозитория на момент разработки

Репозиторий: `C:\Users\nonhumanbox\scientific-extraction-harness`.

- Ветка: `main`, рабочее дерево чистое (`git status --short --branch` показывает `main...origin/main`).
- Python: `>=3.11`.
- Сборка: `setuptools>=68`.
- Dev-зависимость: `pytest>=8`.
- Тестовый корень: `tests/`; `src` добавляется в `PYTHONPATH` через `pyproject.toml`.
- Реализовано:
  - `src/scientific_extraction_harness/evidence.py` — immutable `EvidenceRecord`, JSONL writer/loader, базовая валидация `document_id`, `page`, `locator`, `confidence`;
  - `src/scientific_extraction_harness/__init__.py` — публичный экспорт `EvidenceRecord`, `load_jsonl`, `write_jsonl`;
  - `tests/test_evidence.py` — round-trip JSONL и проверка недопустимого confidence.
- Документация:
  - `docs/data-contract.md` фиксирует поля `EvidenceRecord`: `document_id`, `page`, `modality`, `locator`, `field`, `value`, `unit`, `confidence`, `status`, `reviewer_note`;
  - `docs/work-packages.md` задаёт work packages B1–B5, C1–C5 и A1–A4;
  - `README.md` описывает pipeline `document -> ingest -> extraction -> candidate evidence -> normalization + provenance -> expert review -> approved record`.
- Пока отсутствуют ingestion manifest/loader, extractor adapters, run ledger, normalization, confidence policy, evaluation runner и review CLI/UI.

Команда базовой проверки перед началом работ:

```bash
cd C:\Users\nonhumanbox\scientific-extraction-harness
python -m pip install -e ".[dev]"
pytest
```

Исходные PDF/книги, закрытые URL, токены, персональные данные и необезличенные transcripts **не должны** добавляться в Git. Используются только документы, на обработку которых есть разрешение.

## 2. Цели и границы

### 2.1. Цели

1. Воспроизводимо получать `EvidenceRecord`-кандидаты из разрешённых локальных документов.
2. Сохранять проверяемую provenance для каждого значения: документ, страница, modality и читаемый locator.
3. Делать изменения extractors измеримыми на versioned de-identified fixtures.
4. Отделять extraction от approval: автоматический код может создать только `candidate`, а `approved` создаётся лишь review action.
5. Позволить эксперту исправить/отвергнуть кандидат, не теряя исходное значение, источник и историю решений.
6. Вводить quality gates, budget limits и reproducible run manifests, чтобы self-improvement не приводил к незаметному drift или утечке данных.

### 2.2. Не входит в первую реализацию

- автономное утверждение данных;
- загрузка приватных документов в сторонние API;
- обучение или fine-tuning модели;
- хранение исходных copyrighted source files в репозитории;
- оценка «истинности» научного результата сверх того, что явно поддерживает источник;
- UI с тяжёлым frontend stack (достаточно CLI и JSONL).

## 3. Непреложные invariants

Каждый PR и каждый run обязаны сохранять следующие свойства:

1. **Provenance completeness:** каждый datum имеет непустые `document_id`, `page >= 1`, допустимую `modality` и непустой `locator`.
2. **No invention:** если evidence отсутствует, неоднозначна или конфликтует, создаётся `rejected`/`candidate` с пояснением, но не угадывается значение.
3. **Approval boundary:** extractor/normalizer/evaluator не могут выставить `status="approved"`; это делает только review-компонент с `reviewer_id` и note.
4. **Source preservation:** `value` хранится в виде, пригодном для проверки источника; normalized value не затирает source value.
5. **Determinism:** при одинаковых input bytes, manifests, adapter versions и configuration порядок/содержимое candidates совпадают (кроме явно обозначенных random seeds).
6. **No secret propagation:** prompts, credentials, personal contacts, private URLs и raw agent transcripts не попадают в ledger, fixtures или output.
7. **Local-first:** source content обрабатывается локально по умолчанию; внешний model/API adapter должен быть opt-in и явно записан в run metadata.
8. **Human review:** dataset export разрешён только для `approved` и de-identified records, прошедших export gate.
9. **Reversible normalization:** нормализация имеет `source_value`/`source_unit`, rule id и может быть откатана.
10. **Fail closed:** missing locator, invalid schema, budget overflow, leakage check или metric regression останавливают run.

## 4. Целевая архитектура

```text
permitted document
  -> IngestionManifest + DocumentStore (local paths, hashes)
  -> modality adapters
       text/OCR | table | figure/plot | scan
  -> CandidateEmitter (EvidenceRecord, status=candidate)
  -> Normalizer (reversible field/unit mapping)
  -> Validator + ConfidencePolicy
  -> RunLedger (inputs, versions, budgets, metrics, failures)
  -> ReviewQueue / review CLI
  -> ReviewRecord (approve/reject/correct, note, reviewer identity)
  -> Approved EvidencePackage
  -> Evaluation + de-identified export gate
```

### 4.1. Основные компоненты

- `ManifestLoader`: читает только schema-valid manifest и проверяет существование разрешённого локального файла.
- `DocumentFingerprint`: вычисляет SHA-256 input bytes; fingerprint идентифицирует содержимое, но не заменяет `document_id`.
- `TextAdapter`, `TableAdapter`, `FigureAdapter`, `ScanAdapter`: единый интерфейс `extract(document, config) -> Iterable[Candidate]`; каждый output сразу содержит page/modality/locator.
- `CandidateEmitter`: добавляет `run_id`, `candidate_id` и provenance envelope; не меняет `status` с `candidate`.
- `Normalizer`: применяет только зарегистрированные правила; сохраняет source form.
- `Validator`: schema, provenance, modality-specific locator, unit/value consistency, ambiguity checks.
- `ConfidencePolicy`: объяснимо комбинирует signal components (например, locator quality, parser agreement, OCR quality), но confidence не является approval.
- `ReviewStore`: append-only review events; текущий статус выводится из последнего валидного event.
- `Evaluator`: сравнивает prediction candidates с de-identified gold annotations по case split.
- `RunLedger`: JSONL/JSON metadata без prompts/secrets; связывает входы, код, конфиг, outputs, metrics и gate decisions.

## 5. Контракты данных и API

### 5.1. Существующий `EvidenceRecord`

Сохраняется совместимость с `docs/data-contract.md` и текущим Python dataclass:

```json
{
  "document_id": "example-paper",
  "page": 3,
  "modality": "figure",
  "locator": "figure:2/series:control/x:10",
  "field": "temperature",
  "value": "273.15",
  "unit": "K",
  "confidence": 0.87,
  "status": "candidate",
  "reviewer_note": null
}
```

`status` допускает только `candidate`, `approved`, `rejected`. Любой новый обязательный field требует migration note и backward-compatible loader.

### 5.2. `IngestionManifest` (`manifests/*.json`)

```json
{
  "manifest_version": "1",
  "document_id": "paper-001",
  "path": "fixtures/authorized/paper-001.pdf",
  "sha256": "<64 lowercase hex chars>",
  "permission": "authorized-local",
  "language": "en",
  "expected_pages": 4,
  "allowed_modalities": ["text", "table", "figure", "scan"]
}
```

`path` должен быть относительным и находиться в разрешённом input root; `permission` не может быть пустым. Не принимать URL/credential fields.

### 5.3. Adapter contract

```python
class ExtractionAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def extract(
        self,
        document: IngestedDocument,
        *,
        config: Mapping[str, object],
    ) -> Iterable[EvidenceRecord]: ...
```

Каждый adapter обязан: вернуть только `candidate`, сохранить страницу и modality, использовать locator, детерминированно обработать fixture, а невозможность извлечения оформить диагностикой, а не пустым «успешным» ответом.

### 5.4. `ReviewEvent`

```json
{
  "review_event_id": "rev-0001",
  "run_id": "run-20261018-001",
  "candidate_id": "cand-0007",
  "action": "approve",
  "reviewer_id": "expert-pseudonym-01",
  "note": "Проверено по table:2/row:4/column:yield",
  "created_at": "2026-10-18T00:00:00Z",
  "replacement": null
}
```

`action` — `approve`, `reject` или `correct`. `approve` требует непустой note; `correct` требует replacement с полной provenance. `reviewer_id` — псевдоним, не email/имя.

### 5.5. `RunLedgerEntry`

Обязательные поля: `run_id`, `started_at`, `finished_at`, `manifest_sha256`, `input_document_ids`, `code_revision`, `adapter_versions`, `config_sha256`, `seed`, `budgets`, `counts`, `metrics`, `gate_results`, `output_paths`, `failure_reason` (nullable). В ledger запрещены raw prompts, source text, tokens и personal data.

## 6. Candidate manifest

Файл `manifests/candidate-manifest.v1.json` должен перечислять reproducible cases, а не реальные секретные документы:

```json
{
  "manifest_version": "1",
  "dataset_id": "deidentified-calibration-v1",
  "cases": [
    {
      "case_id": "text-explicit-unit-001",
      "fixture": "tests/fixtures/text/explicit-unit.json",
      "modality": "text",
      "expected": "tests/fixtures/gold/text-explicit-unit.jsonl",
      "difficulty": "easy",
      "tags": ["explicit-unit", "single-value"]
    },
    {
      "case_id": "table-header-unit-001",
      "fixture": "tests/fixtures/table/header-unit.json",
      "modality": "table",
      "expected": "tests/fixtures/gold/table-header-unit.jsonl",
      "difficulty": "medium",
      "tags": ["header-unit", "row-locator"]
    },
    {
      "case_id": "figure-axis-ambiguous-001",
      "fixture": "tests/fixtures/figure/axis-ambiguous.json",
      "modality": "figure",
      "expected": "tests/fixtures/gold/figure-axis-ambiguous.jsonl",
      "difficulty": "hard",
      "tags": ["plot", "ambiguous", "must-not-invent"]
    }
  ]
}
```

Gold files содержат только de-identified annotations и не должны содержать исходные страницы, copyrighted images или персональные данные. Для каждого `case_id` должен существовать ожидаемый outcome, включая expected rejection/abstention.

## 7. Case splits и покрытие

Evaluation не смешивает cases между tuning и final reporting:

- `unit`: 60% простых cases для локальной разработки; допускается повторное использование.
- `calibration`: 20% authorized/de-identified expert-reviewed cases для выбора thresholds; не использовать для финального сравнения кандидатов после фиксации конфигурации.
- `holdout`: 20% замороженных cases, скрытых от routine tuning; раскрываются только evaluator.
- Дополнительный `adversarial` split: отсутствующий unit, conflicting table/text, low-quality OCR, clipped axis, duplicate caption, multi-panel figure, page off-by-one. Adversarial cases не заменяют holdout.

Split фиксируется в manifest checksum. Нельзя перемещать case между split только ради прохождения gate; перемещение требует версии dataset и причины в ledger.

## 8. Metrics

Считать отдельно по modality, difficulty, split и overall:

1. **Evidence precision:** доля emitted candidates, совпадающих с gold field/value/unit и имеющих корректную provenance.
2. **Evidence recall:** доля gold evidence, найденной с допустимым locator tolerance.
3. **F1:** гармоническое среднее precision/recall для сопоставленных records.
4. **Locator validity rate:** доля records с page/modality/locator, которые reviewer может однозначно открыть.
5. **Abstention precision:** доля abstain/rejected outputs в ambiguous cases, где система действительно не должна утверждать значение.
6. **False-approval rate:** утверждённые системой без review candidates; gate должен быть ровно `0`.
7. **Review correction rate:** доля candidates, изменённых экспертом; используется как quality signal, но не как единственный objective.
8. **Normalization reversibility:** доля normalized outputs, для которых source value/unit и rule id доступны и корректны.
9. **Cost/latency:** wall-clock, CPU/memory и tokens/API calls (если внешний adapter opt-in).

Matching выполняется по `(document_id, page, field, normalized value/unit)` с modality-specific locator tolerance. Ambiguous/missing evidence оценивается как abstention, а не как false value.

## 9. Quality gates

Run считается успешным только если все обязательные gates пройдены:

- **G0 Schema:** все outputs загружаются существующим/версионированным loader; invalid records отвергаются с понятной ошибкой.
- **G1 Provenance:** `100%` records имеют required provenance; `100%` approved records имеют evidence locator.
- **G2 Safety:** false-approval `0`; leakage scan не находит tokens, email-like PII, private URLs или raw transcripts.
- **G3 Regression:** holdout F1 не хуже baseline более чем на `0.02`; ни одна modality не падает более чем на `0.05` без explicit waiver.
- **G4 Abstention:** adversarial cases не получают invented values; minimum abstention precision `0.95` после появления baseline.
- **G5 Reproducibility:** повторный запуск с тем же seed/config даёт одинаковые candidate hashes.
- **G6 Budget:** run не превышает CPU `10 min`, memory `2 GiB`, input `100 MB`, candidates `10,000`, external calls `0` по умолчанию.
- **G7 Review:** export содержит только approved, de-identified records и review events.

Порог `G3` применяется после первого baseline; до него gate фиксирует baseline и требует ручного sign-off эксперта.

## 10. Provenance и lineage

Для каждого output сохранить lineage graph:

```text
source sha256
  -> manifest entry
  -> adapter_id@version + config_sha256
  -> candidate_id
  -> normalization rule(s)
  -> validator diagnostics
  -> review_event_id(s)
  -> final status/export record
```

Минимальный locator формат:

- text: `paragraph:<n>/chars:<start>-<end>`;
- table: `table:<n>/row:<n>/column:<name>`;
- figure: `figure:<n>/panel:<id>/series:<id>/region:<label>`;
- scan: `page:<n>/bbox:<x0>,<y0>,<x1>,<y1>`.

Если точный locator невозможен, record остаётся `candidate` с confidence penalty и reviewer note; не подставлять общий `page:<n>` как будто он указывает на значение.

## 11. Budgets и конфигурация

Добавить versioned `configs/default.toml`:

```toml
seed = 0
input_root = "tests/fixtures"
max_input_bytes = 104857600
max_candidates = 10000
max_runtime_seconds = 600
max_memory_bytes = 2147483648
allow_external_calls = false
min_confidence_for_queue = 0.0
```

Budgets считаются на run и записываются в ledger как `limit`, `used`, `status`. При превышении — fail closed, partial output помечается incomplete и не может быть exported. External API calls требуют отдельного config flag, redacted request metadata и budget; credentials читаются только из environment/CLI runtime.

## 12. Роли и ответственность

- **Extractor developer:** adapters, parser tests, deterministic behavior; не утверждает records.
- **Evaluation maintainer:** manifests, gold annotations, metric code, frozen holdout; не меняет gold без version bump.
- **Expert reviewer (A):** rubric, calibration, review events, ambiguity decisions; использует pseudonymous reviewer id.
- **Safety/data steward:** de-identification, permissions, leakage scan, export gate.
- **Release owner:** проверяет ledger/gates, запускает `pytest`, оформляет PR с goal/input/expected output/verification/limitations/data handling.

Один человек может совмещать роли только с явной записью в run metadata; author extractor не должен единолично approve своих candidates для calibration export.

## 13. Фазовый план реализации

### Phase 0 — Baseline и safety (PR 1)

1. Зафиксировать текущий `EvidenceRecord` contract и snapshot baseline.
2. Добавить schema validation tests для invalid modality/status/page/locator и approval boundary.
3. Добавить leakage/de-identification checks для fixtures и ledger.
4. Добавить `configs/default.toml` и run id/seed conventions.

**Gate:** существующие tests проходят; ни одного нового source document/secret.

### Phase 1 — Ingestion и manifest (PR 2, B1)

1. Реализовать `ManifestLoader`, `IngestedDocument`, SHA-256 verification.
2. Реализовать path/permission checks и tests на missing/mismatched hash/traversal.
3. Создать только synthetic fixtures и `manifests/candidate-manifest.v1.json`.

**Gate:** invalid manifest даёт ясную ошибку; input hash записан в ledger.

### Phase 2 — Deterministic adapters (PR 3–5, B2–B4)

1. `text_adapter.py`: page + character locator.
2. `table_adapter.py`: header/row/column/unit mapping.
3. `figure_adapter.py`: stub coordinate/region extraction, explicit abstention for ambiguous axis.
4. `scan_adapter.py`: OCR interface with synthetic OCR fixture and quality metadata.

**Gate:** каждый adapter имеет fixture test и никогда не emits approved.

### Phase 3 — Validation, normalization, confidence (PR 6–7, C2–C3)

1. Добавить reversible `NormalizationRule` registry.
2. Добавить `Validator` и modality-specific locator checks.
3. Реализовать explainable confidence components и policy version.
4. Добавить tests: common unit variants, weak locator penalty, conflicting evidence.

**Gate:** source form сохраняется; invalid/ambiguous values не проходят как approved.

### Phase 4 — Run ledger и orchestration (PR 8–9, B5/C1)

1. Реализовать `run_extract`, pipeline `extract -> validate -> queue`.
2. Сделать append-only `RunLedger`; redact prohibited fields.
3. Implement fail-closed budgets and deterministic candidate hashes.

**Gate:** одна команда создаёт reviewable ledger; повторный run совпадает.

### Phase 5 — Review и evaluation (PR 10–11, C4–C5)

1. Реализовать `ReviewEvent` store и CLI `review list/approve/reject/correct`.
2. Добавить de-identified gold JSONL и split-aware evaluator.
3. Выводить precision/recall/F1, locator validity, abstention и regression report.

**Gate:** approval требует reviewer note; metrics считаются отдельно по split/modality.

### Phase 6 — Self-improvement loop (PR 12+)

1. Каждый candidate improvement (rule, adapter, prompt/config — если разрешён) описывать manifest entry с hypothesis.
2. Запускать candidate на `unit`/`calibration`, затем на frozen `holdout` только после calibration freeze.
3. Сравнивать с baseline, применять gates, сохранять provenance и artifact hashes.
4. При regression оставить candidate branch/output для анализа, но не публиковать его как approved dataset.

**Gate:** improvement принимается только при прохождении всех G0–G7 и review sign-off.

### Implementation status

На текущем этапе реализованы следующие части описанного контура:

- **Contracts:** типизированные контракты для manifest, ingestion, review, ledger, evaluation и improvement-артефактов.
- **Ledger:** append-only run ledger с JSONL-записью, валидацией, редактированием запрещённых полей и cross-process coordination через sidecar advisory lock, timeout, fsync-before-unlock и corruption detection.
- **Manifest / ingest:** schema/path/permission проверки manifest, SHA-256 verification и локальный `IngestedDocument`.
- **Adapters:** базовый adapter contract и детерминированные text/table adapters; figure и OCR/scan boundaries принимают только explicit metadata, abstain при неоднозначности и не выполняют production image/OCR extraction; provider-neutral LLM boundary доступен только через explicit opt-in, injectable transport и redaction. LLM transport получает redacted prompt/config/metadata и не получает credentials.
- **Normalize:** зарегистрированные reversible normalization rules с сохранением source form и lineage.
- **Validate:** schema, provenance, locator и ambiguity validation.
- **Confidence:** explainable confidence components и policy.
- **Pipeline:** локальная orchestration extraction → normalization/validation → queue с budget и fail-closed проверками.
- **Evaluate:** split-aware matching и метрики для de-identified gold annotations.
- **Review:** append-only review events и approval boundary для approve/reject/correct.
- **Improvement registry:** registry кандидатов улучшений с hypothesis, artifact/config metadata и сравнением с baseline.
- **Gates:** safety, provenance, regression, reproducibility, budget и review gate checks.

Ограничения текущей реализации: CLI реализован как локальный stdlib-only thin layer (`extract`, `review`, `evaluate`); LLM adapter реализует только provider-neutral boundary с injected transport, а production provider SDK/network integration не включены; multi-process locking для ledger реализован через sidecar advisory lock, но distributed locking отсутствует; auto-promotion кандидатов отсутствует — утверждение требует review action и sign-off.

### Phase 9 — Scheduled self-improvement controller

Реализован disabled-by-default scheduler с `due_at`/interval triggers, persisted atomic state, deterministic run IDs, idempotent packet retrieval, max-runs budget и single-flight lock. Scheduler не выполняет code, LLM или network calls. Recommendation `promote` не является promotion: требуется отдельный human `ReviewEvent(action="approve")` с reviewer identity, note и точным `candidate_id`/`run_id` binding. Replay, stale, mismatched и corrupt-state сценарии завершаются fail-closed.

### Phase 8 — CLI (`extract`, `review`, `evaluate`)

Реализован локальный CLI с JSON/JSONL input-output и fail-closed exit codes. `extract` загружает только локальные manifest-документы и запускает text/table pipeline; `review` append-ит только явно заданное review action; `evaluate` использует split-aware evaluator. Console-script объявлен в `pyproject.toml`; на Windows его исполняемый файл может требовать добавления Python Scripts directory в `PATH`. CLI не включает network, LLM или auto-approval.

### Phase 7 — Offline controller / review packet

Следующий ограниченный этап — offline controller, который собирает уже реализованные manifest, adapters, pipeline, evaluation, improvement registry и gates в воспроизводимый локальный запуск без LLM/network и без автоматического утверждения. Результатом должен быть review packet: ledger entry, candidate/evaluation outputs, gate results, artifact hashes, diff к baseline и краткая информация для эксперта. Controller не заменяет CLI или production executor, не выполняет auto-promotion и должен явно фиксировать ограничения, отсутствие multi-process locking и необходимость ручного review/sign-off.

## 14. Точные файлы и модули для добавления

Не изменять эти файлы в рамках создания данного design-документа; при реализации добавлять изменения отдельными PR:

```text
configs/default.toml
manifests/candidate-manifest.v1.json

src/scientific_extraction_harness/
  contracts.py          # manifest, review, ledger typed contracts
  manifest.py           # ManifestLoader, path/hash/permission checks
  ingest.py             # IngestedDocument and local document store
  adapters/base.py      # ExtractionAdapter protocol and diagnostics
  adapters/text.py      # deterministic text fixture adapter
  adapters/table.py     # table candidate adapter
  adapters/figure.py    # figure/plot region stub and abstention
  adapters/scan.py      # OCR adapter boundary
  normalize.py          # reversible normalization rules
  validate.py           # schema/provenance/ambiguity validation
  confidence.py         # explainable confidence policy
  ledger.py             # append-only run ledger and redaction
  pipeline.py           # extract -> validate -> queue orchestration
  review.py             # review event store and approval boundary
  evaluate.py           # matching and split-aware metrics
  cli.py                # extract/review/evaluate commands

tests/
  fixtures/text/explicit-unit.json
  fixtures/table/header-unit.json
  fixtures/figure/axis-ambiguous.json
  fixtures/ocr/low-quality.json
  fixtures/gold/*.jsonl
  test_manifest.py
  test_adapters.py
  test_normalize.py
  test_validate.py
  test_confidence.py
  test_ledger.py
  test_pipeline.py
  test_review.py
  test_evaluate.py
  test_safety.py
```

Адаптеры можно организовать иначе только при сохранении публичных контрактов и обновлении этого документа/PR description. Не добавлять source PDFs в перечисленные fixtures; fixtures должны быть минимальными synthetic/de-identified representations.

## 15. Тесты и команды проверки

Минимальный набор для каждого implementation PR:

```bash
pytest -q
pytest tests/test_safety.py tests/test_ledger.py -q
python -m scientific_extraction_harness.cli evaluate \
  --manifest manifests/candidate-manifest.v1.json \
  --config configs/default.toml \
  --report artifacts/evaluation.json
```

Обязательные тестовые категории:

- contract/schema rejection;
- path traversal и SHA mismatch;
- page/locator preservation для каждой modality;
- no-invention/abstention на ambiguity;
- normalization round-trip;
- confidence explainability и weak-locator penalty;
- ledger redaction и deterministic rerun;
- review approval requiring note и preserving lineage;
- metric matching, split isolation и regression gate;
- budget overflow и external-call denial by default.

## 16. Acceptance criteria

Дизайн считается реализованным, когда другой agent без дополнительных решений может:

1. установить пакет и выполнить `pytest`;
2. взять перечисленный candidate manifest и synthetic fixtures;
3. запустить одну локальную extraction command;
4. получить JSONL candidates, где каждый record имеет полную provenance;
5. получить ledger без secrets/prompts/source text;
6. повторить run и получить тот же hash при том же input/config/seed;
7. увидеть rejection/abstention для ambiguous figure и missing evidence;
8. вручную approve/correct/reject candidate через review CLI с note;
9. получить metrics по `unit`, `calibration`, `holdout`, `adversarial` без split leakage;
10. заблокировать export при false approval, leakage, missing provenance, regression или budget overflow;
11. экспортировать только de-identified approved records и review lineage;
12. описать в PR goal, fixture/reproduction, expected output, verification result, limitations и data de-identification status.

Текущий change ограничен этим документом. Кодовые файлы, существующие тесты и конфигурация репозитория не изменяются.

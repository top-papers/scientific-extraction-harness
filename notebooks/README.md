# notebooks

Google Colab-ноутбуки для эксперта. Ноутбук заменяет интерактивный OpenCode-контур: эксперт загружает разрешённую
статью, проверяет кандидатные `EvidenceRecord` в HTML-форме и отправляет только одобренные записи в набор данных.

## scientific_experiment_review.ipynb

[![Открыть в Google Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/top-papers/scientific-extraction-harness/blob/feat/expert-validation-notebook/notebooks/scientific_experiment_review.ipynb)

1. Установка `pypdf`/`requests`.
2. Загрузка PDF/TXT/HTML/DOCX/RTF (кнопка Colab, локальный путь или ссылка; для приватного GitHub-источника
   используется секрет `top_papers_token` только как Bearer-заголовок).
3. Разбор текста с маркерами страниц `[[PAGE n]]`.
4. Извлечение кандидатов по контракту [`docs/data-contract.md`](../docs/data-contract.md):
   `document_id`, `page`, `modality`, `locator`, `field`, `value`, `unit`, `confidence`, `status`, `evidence_quote`.
5. HTML-форма: по каждому кандидату — `approve` / `reject` / `fix`, правка значения и заметка проверяющего;
   обязательные оценка 0–10, комментарий и подтверждение эксперта.
6. `Download review JSON` — офлайн-выгрузка; `Publish approved…` — подготовка публикации.
7. `publish_review(get_review_from_colab())` отправляет только `approved`/`fixed` записи в
   `top-papers/scientific-experiment-evidence` через Commit API с `create_pr=1`.

Перед запуском: в Colab **🔑 Secrets** добавьте `HF_TOKEN` с правом записи в набор данных; `top_papers_token`
нужен только при доступе к приватным материалам GitHub. Токены не печатаются и не попадают в HTML/JSON;
перед отправкой ноутбук проверяет запись на поля и значения, похожие на секреты.

Ограничения: исходные PDF и книги в Git и в набор данных не публикуются; публикуются только обезличенные
структурированные записи и provenance, если у эксперта есть право на их распространение. Сканы без OCR
не обрабатываются. Любое значение в наборе данных требует явного одобрения эксперта — автоматического одобрения нет.

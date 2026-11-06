# notebooks

Google Colab-ноутбуки для эксперта. Ноутбук заменяет интерактивный OpenCode-контур: эксперт загружает разрешённую
статью, модель извлекает кандидатные `EvidenceRecord`, эксперт проверяет их в HTML-форме и отправляет только
одобренные записи в набор данных.

## scientific_experiment_review.ipynb

[![Открыть в Google Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/top-papers/scientific-extraction-harness/blob/main/notebooks/scientific_experiment_review.ipynb)

Логика повторяет [ноутбук legal-agent-harness](https://colab.research.google.com/github/lawful-good-project/legal-agent-harness/blob/main/notebooks/law_extract_fixed.ipynb)
(загрузка → Run all → форма → Hugging Face), но предметная часть адаптирована к экспериментальным данным:

1. **Зависимости:** `pypdf` для текстового слоя PDF и `g4f` — бесплатные публичные провайдеры LLM (без ключа).
2. **Каскад проверки моделей g4f** (дизайн: `docs/design-vision-chart-validation.md`, раздел 4.1): ступень 1 —
   текстовый ping «Reply exactly: OK» по каталогу (402/таймауты/«Sign up…» отсекаются); ступень 2 — image-ping на
   программной PNG-диаграмме с 3 столбиками (модель обязана назвать «3» — иначе она не читает изображения);
   ступень 3 — выбор режима: `vision` (графики будут читаться), `text` (работа как раньше), `fallback`
   (Pollinations-резерв). Аудит моделей (`MODEL_AUDIT`) попадает в issues формы. Vision-контур чтения графиков
   и OCR-фолбэк (Tesseract) реализуются следующими PR.
3. **Загрузка статьи:** кнопка Colab, `LOCAL_PATH` (в т.ч. Google Drive) или до 5 ссылок в `URLS`; для GitHub-URL из
   приватного репозитория секрет `top_papers_token` используется только как заголовок `Authorization`.
4. **Разбор текста:** `[[PAGE n]]`-маркеры страниц, SHA-256, число страниц и символов; текст статьи в публикуемую
   запись не попадает.
5. **Извлечение (модуль g4f):** статья режется на фрагменты по `CHUNK_PAGES` страниц; модель возвращает JSON
   `experiments[]` с полями `research_question`, `hypothesis`, `design`, `sample_size`, `population`, `methods`,
   `intervention`, `control`, `conclusion` и `results[]` по контракту [`docs/data-contract.md`](../docs/data-contract.md)
   (`page`, `modality`, `locator`, `field`, `value`, `unit`, `confidence`, `evidence_quote`). Ответы объединяются и
   дедуплицируются; восстановление обрезанного JSON помечается предупреждением.
6. **Проверка provenance:** цитата ищется в тексте дословно, запись без цитаты отбрасывается; страница определяется
   по позиции цитаты и сверяется со страницей от модели; `modality` уточняется по найденному фрагменту (таблица только
   при табличных разделителях); короткая цитата и `value: null` снижают `confidence`.
7. **HTML-форма (офлайн):** по каждому значению «верно / исправить / нет в источнике» и отдельно `null` для
   `value`/`unit`/`field`; заметка проверяющего, оценка 0–10, комментарий; статус записи становится `approved` только
   при подтверждённом значении и отсутствии пометок «нет в источнике». Кнопки «Скачать JSON» и «Опубликовать»
   берут только одобренные записи.
8. **Публикация:** из формы — один NDJSON-запрос Commit API (`header` + `file`, base64) с `create_pr=1` в ветку из
   `refs`; отдельный `preupload` не нужен. Из ноутбука — ячейка 10, которая
   валидирует запись (оценка, комментарий, поля `approved`-записей, отсутствие токенов/e-mail/PDF-байтов) и
   отправляет YAML `reviewed-dataset.v1` (ключи как у `export_reviewed_dataset` в `scientific_extraction_harness`)
   в `validation/<review_id>.yaml`.

Перед запуском: в Colab **🔑 Secrets** добавьте `HF_TOKEN` с правом записи в набор данных; `top_papers_token`
нужен только при доступе к приватным материалам GitHub. Токены не печатаются и не попадают в HTML/JSON.

Настройки в ячейке 4: `HF_REPO_ID` (целевой датасет; по умолчанию `DEFAULT_REPO_ID` из `hf_dataset.py` — при
необходимости укажите свой), `STRICT_SCHEMA`, `MAX_EXPERIMENTS`, `ALLOW_RULES_FALLBACK` (черновик по регулярным
правилам — низкая точность), `REMOTE_FORM_UPLOAD` (отправка прямо из формы), `ENABLE_VISION` (каскад ищет
мультимодальную модель), `VISION_MODELS_EXTRA` (доп. имена для image-ping), `PROBE_MAX_ALIVE` (сколько живых
моделей искать на ступени 1).

Ограничения: исходные PDF и книги в Git и в набор данных не публикуются; публикуются только обезличенные
структурированные записи и provenance, если у эксперта есть право на их распространение. Сканы без OCR
не обрабатываются. Значения, читаемые только с рисунка, модель прочитать не может — они должны быть `null` и
заполнены экспертом. Любое значение в наборе данных требует явного одобрения эксперта — автоматического одобрения нет.

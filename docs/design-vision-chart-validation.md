# Дизайн: мультимодальная проверка графиков в ноутбуке scientific_experiment_review

Статус: **предложение (design doc), изменений в ноутбуке пока нет**.
Дата: 2026-11-03 (ревизия 2 — каскад проверки моделей, 2026-11-06; ревизия 3 — OCR-фолбэк, вариант A (Tesseract) утверждён, 2026-11-06) · Репозиторий: `top-papers/scientific-extraction-harness` · Ноутбук: `notebooks/scientific_experiment_review.ipynb`

---

## 1. Цель и постановка задачи

Сегодня текстовый слой статьи обрабатывают только текстовые модели g4f: правило системного промпта №2 прямо
заставляет модель писать `value: null, confidence <= 0.4` для всего, что «only readable from an image you cannot see».
Для научных статей это большая потеря: **основная количественная информация живёт в графиках**, а текст вокруг
графиков — сопроводительная (что измеряли, в каких единицах, в какой группе).

Предлагаемое улучшение добавляет в ноутбук второй, мультимодальный контур:

1. **Извлечение картинок** — из PDF рендерятся изображения, из них отбираются **графики** (chart-like images),
   а не фотографии, схемы устройства или логотипы.
2. **Мультимодальное чтение графика** — vision-модель g4f получает картинку графика **вместе с сопроводительным
   текстом статьи** и извлекает данные: оси, единицы, серии, точки/бары и их значения.
3. **Сопоставление со значениями в тексте** — модель получает список значений, уже найденных в тексте (и/или просит
   найти их в тексте), и для каждого решает: подтверждается ли значение из графика текстом, противоречит ли ему,
   или в тексте информации нет.
4. **Проверка описания графика** — ключевая задача: убедиться, что **описание графика верное**. Модель строит
   структурированное описание (chart description), а затем оно сверяется с текстом статьи: заголовок, оси, единицы,
   легенда и значения не должны противоречить сопроводительному тексту. Расхождения попадают в форму как
   кандидаты-проблемы, а решение всё равно остаётся за экспертом.

Итог всё тот же: кандидат `EvidenceRecord` с provenance (`page`, `modality: figure`, `locator`, `evidence_quote`),
который **эксперт подтверждает в HTML-форме**; в Hugging Face уходят только одобренные записи. AGENTS-правила
сохраняются: provenance обязателен, неоднозначность помечается, а не придумывается, авто-approve нет.

---

## 2. Что уже проверено (факты, а не догадки)

Живые проверки g4f из этой сессии (Windows, локально, `g4f` из PyPI, версия с `ModelRegistry`):

| Проверка | Результат |
|---|---|
| `g4f.models.ModelRegistry.all_models()` | работает; `VisionModel` в реестре: `gpt-4o`, `llama-3.2-11b` (по `isinstance(m, VisionModel)`) |
| Каталог моделей g4f ([g4f/models.py](https://raw.githubusercontent.com/xtekky/gpt4free/main/g4f/models.py)) | `VisionModel`-класс есть, им помечены `gpt-4o` и `llama-3.2-11b`; провайдеры в `best_provider` часто `IterListProvider` — фактическая доступность плавает |
| `Client().chat.completions.create(..., image=..., image_name=...)` | API поддерживает изображение (параметры `image`, `image_name` в сигнатуре `create`) |
| Реальные запросы `gpt-4o` и `gpt-4.1` с `image=` | ответили, но с текстом «Sign up and repeat your request» → провайдер требует подписку, картинки фактически не прочитал |
| `llama-3.2-11b`, `gemini-2.5-flash`, `qwen-2.5-vl-72b`, `llama-4-scout`, `mistral-small-3.1-24b` | `PaymentRequiredError: 402 No cake credits…` — анонимный доступ через g4f сейчас лимитирован |
| Pollinations напрямую (`text.pollinations.ai/openai`) с `image_url` | `openai` → 400 «This model does not support image input»; `openai-large`/`openai-vision`/`qwen-vl`/`llama-vision`/`gemini` → 404 «isn't on the Classic API» (или 402 FREE_LIMIT) |
| `text.pollinations.ai/models` | в анонимном списке только `openai-fast` (GPT-OSS 20B, `input_modalities: ['text']`) — vision-моделей в бесплатном анонимном списке сейчас нет |

Вывод, который кладётся в основу дизайна: **названия vision-моделей получить легко, живой бесплатный vision-провайдер —
нет**. Поэтому дизайн строится не на жёстко зашитом списке, а на **каскаде живых проверок** (раздел 4.1): сначала
работоспособность модели как таковой, затем мультимодальность на тестовом изображении, затем выбор — успешная
vision-модель или явный фолбэк на текстовый контур. Всё, что не прошло ступень, исключается из цепочки —
с предупреждением и точной причиной в выводе ноутбука.

---

## 3. Общая архитектура

```
ЗАПУСК НОУТБУКА — каскад проверки моделей (раздел 4.1)
   каталог g4f → [1] работоспособность (текст-ping) → [2] мультимодальность (image-ping)
   → [3] выбор: vision-модель ─┐
                               ├─ MODE = "vision" → оба контура
        нет vision-моделей ────┘
        есть живые текстовые ──→ MODE = "text"  → только текстовый контур
        ни одной живой ────────→ MODE = "fallback" → Pollinations-резерв (текст)

PDF/HTML/DOCX
   │
   ├─ текстовый слой (как сейчас): [[PAGE n]] маркеры, фрагменты, текстовая модель
   │        └─→ experiments[] / results[] (кандидаты с текста)
   │
   └─ НОВОЕ: image pipeline (только при MODE = "vision")
        1) pypdf: изображения страниц + встроенные картинки → candidates[]
        2) фильтр «похоже на график»: размер/пропорции + текстовая подпись Figure N рядом
           + (опционально) vision-классификация «это график?»
        3) chart reading: vision-модель + картинка + сопроводительный текст страницы
           └─→ chart_reading{axes, series, values[]}
        4) cross-check: значение из графика ↔ значение из текста (confirm / conflict / absent)
        5) описание графика → проверка описания текстом (chart description validation)
        6) кандидаты modality=figure с provenance и квадратной цитатой-подписью
                ↓
        общая normalize_experiments() → дедупликация → HTML-форма (секция «Графики») → эксперт → HF
```

Текстовый контур не ломается в любом режиме: при `MODE = "text"` (мультимодальных не нашлось) ноутбук работает
как раньше (правило «null при значениях только на картинке» продолжает действовать), а блок графиков честно
сообщает, что vision-провайдер недоступен. При `MODE = "fallback"` (не жива ни одна g4f-модель) — перебор
Pollinations-резервов, тоже только текст. Выбор режима и аудит моделей (`MODEL_AUDIT`) попадают в `CFG` и в
issues формы, поэтому эксперт всегда видит, почему графики не обрабатывались.

---

## 4. Дизайн по частям ноутбука

### 4.1. Ячейка конфигурации (сейчас ячейка 4): каскад проверки моделей

Сейчас `_g4f_candidates()` берёт **все** имена из `ModelUtils.convert` (или дефолтный список) и пингует их текстом
`Reply exactly: OK`. Заменяется на **трёхступенчатый каскад** с явными результатами каждой ступени:

```
СТУПЕНЬ 0  каталог             все имена из ModelRegistry (+ VISION_MODELS_EXTRA)
СТУПЕНЬ 1  работоспособность   текстовый ping «Reply exactly: OK»    → ALIVE_MODELS
СТУПЕНЬ 2  мультимодальность   image-ping: PNG-диаграмма, вопрос     → VISION_MODELS
СТУПЕНЬ 3  выбор               vision-модель найдена?
                              ├─ да  → MODE = "vision"  (ACTIVE_MODEL = первая VISION_MODELS)
                              └─ нет → MODE = "text"    (фолбэк, как сегодня) + предупреждение
```

**Ключевые свойства каскада:**

- **Ступень 2 проверяет только выживших на ступени 1** — модели, упавшие на текстовом ping (таймаут, 402,
  network error), не тратят время на дорогой image-ping. Это ускоряет запуск: сегодня почти весь каталог g4f
  падает с `402 No cake credits` за секунды, и гонять по ним image-проверку бессмысленно.
- **Результаты печатаются и попадают в аудит** — эксперт видит, какая модель выбрана и почему (каждая строка:
  модель → вердикт ступени → причина исключения). Неудачи не тихие: `MODEL_AUDIT` уходит в `issues` формы,
  чтобы решение «текст без графиков» было видно и при разметке.
- **Списки переиспользуются при извлечении**: перебор моделей в `llm_extract`/`vision_extract` идёт по спискам
  выживших, а не по полному каталогу — первый запрос после выбора не «переоткрывает» доступность.
- **Re-probe при выгорании цепочки:** если на фрагменте/графике упали все модели, ноутбук повторяет каскад
  для следующего кандидата, а не объявляет провал после первой неудачи — дешёвые ping-и позволяют вернуть
  в цепочку модель, у которой был временный сбой.

```python
# конфиг (новые ключи)
ENABLE_VISION = True          # включить мультимодальный контур
VISION_PROBE_IMAGE = ...      # 128×96 PNG: оси + 3 бара (см. 4.1.1)
VISION_MODELS_EXTRA = []      # ручное добавление, напр. ["qwen-2.5-vl-72b"]
VISION_FALLBACK_TEXT = True   # текстовый контур остаётся всегда
PROBE_TIMEOUT_SEC = 45        # таймаут ping-а, меньше таймаута извлечения
```

```python
from g4f.client import Client

def _catalog_names():
    """Все имена моделей g4f (ступень 0)."""
    try:
        from g4f import models as g4f_models
        reg = g4f_models.ModelRegistry.all_models()
        names = [n for n, m in reg.items() if n]
    except Exception:
        names = ["gpt-4o", "llama-3.2-11b"]
    return list(dict.fromkeys(names + VISION_MODELS_EXTRA))


def _refusal_like(text):
    """'Sign up and repeat…', 'I can't', пусто, слишком коротко — не содержательный ответ."""
    t = (text or "").strip().lower()
    return (not t or len(t) > 400 or "sign up" in t or "i can't" in t
            or "cannot view" in t or "log in" in t or "subscribe" in t)


# --- СТУПЕНЬ 1: работоспособность ---
def probe_alive(model):
    """Модель жива: текстовый ping отвечает 'OK' без отказных фраз."""
    try:
        r = Client(timeout=PROBE_TIMEOUT_SEC).chat.completions.create(
            model=model, temperature=0,
            messages=[{"role": "user", "content": "Reply exactly: OK"}])
        text = (r.choices[0].message.content or "").strip() if r and r.choices else ""
        return ("ok" in text.lower()) and not _refusal_like(text), text
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:80]}"


# --- СТУПЕНЬ 2: мультимодальность ---
def probe_vision(model):
    """Модель читает изображения: image-ping на программной PNG-диаграмме.

    Возвращает (ok, detail). ok только если ответ содержательный и называет
    ожидаемое число баров (3) — это отсекает модели, которые отвечают на текст,
    игнорируя картинку ('Sign up…' из наших живых проверок).
    """
    try:
        r = Client(timeout=PROBE_TIMEOUT_SEC).chat.completions.create(
            model=model, temperature=0,
            messages=[{"role": "user", "content":
                       "This image shows a bar chart. How many bars are there? "
                       "Answer with a single number only."}],
            image=VISION_PROBE_IMAGE, image_name="probe_bars.png")
        text = (r.choices[0].message.content or "").strip() if r and r.choices else ""
        if _refusal_like(text):
            return False, f"refusal-like: {text[:60]!r}"
        if not re.search(r"\b3\b", text):   # на диаграмме ровно 3 бара
            return False, f"wrong answer: {text[:60]!r}"
        return True, text[:40]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:80]}"


# --- СТУПЕНЬ 3: выбор режима ---
def select_models(verbose=True):
    """Каскад целиком. Возвращает (MODE, ACTIVE_MODEL, VISION_MODELS, MODEL_AUDIT)."""
    audit = []                      # [{model, alive, alive_why, vision, vision_why}]
    catalog = _catalog_names()

    alive = {}
    for m in catalog:
        ok, why = probe_alive(m)
        alive[m] = ok
        audit.append({"model": m, "alive": ok, "alive_why": why})
        if verbose:
            print(f"  [1] {m}: {'жива' if ok else 'недоступна — ' + why}")

    vision = []
    if ENABLE_VISION:
        # image-ping по консервативному списку: живые модели, помеченные VisionModel,
        # плюс VISION_MODELS_EXTRA. Не весь каталог: image-ping дороже текстового,
        # и у большинства провайдеров картинка сразу даёт «Sign up…» или 402.
        try:
            from g4f import models as g4f_models
            reg = g4f_models.ModelRegistry.all_models()
            marked = {n for n, m in reg.items()
                      if isinstance(m, g4f_models.VisionModel) and n}
        except Exception:
            marked = set()
        candidates = [m for m in catalog
                      if alive.get(m) and (m in marked or m in VISION_MODELS_EXTRA)]
        for m in candidates:
            ok, why = probe_vision(m)
            if ok:
                vision.append(m)
            for row in audit:
                if row["model"] == m:
                    row["vision"], row["vision_why"] = ok, why
            if verbose:
                print(f"  [2] {m}: {'multimodal' if ok else 'не прошла image-ping — ' + why}")
            if vision:
                break               # достаточно одной рабочей vision-модели
    elif verbose:
        print("  [2] vision-контур отключён (ENABLE_VISION = False)")

    if vision:
        mode, active = "vision", vision[0]
    elif any(alive.values()):
        mode, active = "text", next(m for m in catalog if alive.get(m))
        print("⚠️ Мультимодальных моделей не найдено: работаем в текстовом режиме. "
              "Значения только с картинок будут помечены null (правило промпта).")
    else:
        mode, active = "fallback", None   # Pollinations-резерв, как сегодня
        print("⚠️ Ни одна модель g4f не прошла проверку: будет перебор резервных "
              "источников Pollinations (только текст).")
    return mode, active, vision, audit
```

**Почему image-ping не по всему каталогу, а по живым + VisionModel + ручному списку.** Компромисс между полнотой
и временем запуска: текстовый ping по всем именам быстр (падения мгновенны), а image-ping медленнее, и у многих
провайдеров картинка сразу приводит к «Sign up…» или 402. Если нужна полная гарантия, у эксперта есть
`VISION_MODELS_EXTRA` — имена, добавляемые в image-ping принудительно, даже если они не помечены `VisionModel`
в каталоге g4f (метка в каталоге не всегда совпадает с фактическими возможностями провайдера).

**Что меняется в существующих переменных.** `G4F_MODELS_TO_PROBE` остаётся списком для *текстового* перебора,
но теперь строится из `alive`-моделей каскада; `ACTIVE_G4F_MODEL` — первая vision-модель при `MODE = "vision"`.
`MODEL` в `CFG` и provenance-артефакте записывает фактически выбранный режим и модель (вместе с кратким
`model_audit` в issues), что усиливает принцип provenance: видно, *кем* извлекались данные.

**4.1.1. Тестовое изображение.** Не тянуть из интернета: генерировать PNG программно (Pillow, уже в зависимостях
Colab) — белый фон 128×96, чёрные оси, **3 столбика разной высоты** (чтобы ответ был «посчитай», а не «угадай»).
Ожидаемый вердикт `probe_vision`: в ответе названо «3». Проверка на конкретное число закрывает главный фокус
живых тестов: модель, отвечающая шаблонной фразой («Sign up and repeat your request») и не читающая картинку,
отсекается на `_refusal_like`, а модель, прочитавшая картинку неправильно («4», «five»), — на regex. Размер
128×96 больше прежних 64×64, чтобы модель точно различала бары на маленькой диаграмме.

**4.1.2. Итоговые режимы и их гарантии.**

| Режим | Когда включается | Что гарантирует |
|---|---|---|
| `vision` | ≥1 модель прошла обе ступени | графики читаются; текст тоже (vision-модели умеют текст) |
| `text` | есть живые модели, vision нет | текст + OCR-фолбэк 4.1.3 (Tesseract) для картинок; значения, не распознанные OCR — `null` с пометкой |
| `fallback` | ни одна g4f-модель не жива | Pollinations-резерв (только текст) + тот же OCR-фолбэк 4.1.3 |

`VISION_FALLBACK_TEXT = True` означает «всегда текст»: даже при рабочей vision-модели текстовый проход остаётся
основным, а vision-контур добавляет *сверху* figure-записи. Это страхует от деградации vision-модели в середине
сессии: текстовые кандидаты уже получены, и vision-обрывы не обнуляют работу.

**4.1.3. OCR-фолбэк при текстовом режиме — вариант A (Tesseract), утверждён 2026-11-06.**

Когда каскад выбрал `MODE = "text"` или `MODE = "fallback"`, картинки не пропадают из обработки:
Tesseract вытаскивает из них текст (подписи осей, легенды, цифры у баров/точек), а текстовая модель —
превращает этот «протокол графика» в кандидатов. Это не замена vision-модели (OCR не понимает геометрию
диаграммы), но покрывает заметную часть данных: оси, единицы, серии и подписанные значения.

Записи получают честный provenance: `modality: "figure"`, `method: "ocr-tesseract"`, confidence ниже
vision-чтения, и обязательная пометка в `reviewer_note` — «значение распознано OCR, геометрия графика
не проверялась». Финальное решение, как всегда, за экспертом в форме.

### Вариант A — Tesseract (выбранный; B/C/D — резервные направления)

**Путь:** картинка графика → `pytesseract` → текстовый «протокол» → *та же текстовая модель g4f/Pollinations*
с отдельным OCR-промптом → кандидаты `modality: figure`.

```python
# конфиг
ENABLE_OCR_FALLBACK = True        # работает только при MODE = "text"/"fallback"
OCR_ENGINE = "tesseract"          # выбор движка (см. варианты B–D)
OCR_LANGS = "eng"                 # статья англоязычная по умолчанию; для кириллицы "eng+rus"
OCR_MIN_CHARS = 20                # меньше — считаем «график без текста», пропускаем
```

```python
def ocr_figure(img_png: bytes) -> str:
    """Текстовый протокол графика: слова с координатами (tesseract TSV)."""
    import io as _io
    from PIL import Image
    import pytesseract

    image = Image.open(_io.BytesIO(img_png))
    # апскейл x2 билинейно: у Tesseract сильно падает точность на мелких подписях осей
    image = image.resize((image.width * 2, image.height * 2), Image.BILINEAR)
    data = pytesseract.image_to_data(image, lang=OCR_LANGS, output_type=pytesseract.Output.DICT)
    words = []
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        if text and int(data["conf"][i]) > 40:
            words.append((int(data["left"][i]), int(data["top"][i]), text))
    # сгруппируем по строкам (top с допуском) — читабельно для LLM
    lines = {}
    for left, top, text in words:
        key = min(lines, key=lambda k: abs(k - top)) if lines and abs(
            min(lines, key=lambda k: abs(k - top)) - top) < 15 else top
        lines.setdefault(key, []).append((left, text))
    return "\n".join(" ".join(t for _, t in sorted(ws)) for _, ws in sorted(lines.items()))
```

Затем протокол подаётся текстовой модели с отдельным промптом-компаньоном (дополняет 4.4):

```
OCR TRANSCRIPT of a scientific figure (words with approximate positions; '---' separates lines).
The transcript comes from Tesseract: it sees axis labels, legend entries and printed numbers,
but CANNOT judge bar heights, point positions or trends. Geometry is unknown to you.

- Reconstruct only what is literally printed: axis labels, units, series names, values.
- Treat every number as an annotation on the chart, NOT as a measured reading.
- Cross-check with the article text (text_match: confirm / conflict / absent).
- Set confidence <= 0.5: OCR text is evidence, but the chart geometry is unverified.
- If the transcript is mostly numbers without context, return fewer, well-anchored records
  rather than guessing which number belongs to which series.
```

**Почему вариант A — по умолчанию:**
- `tesseract-ocr` предустановлен в Colab (его не было только на моей Windows-машине; в Colab он есть),
  `pytesseract` — один маленький pip;
- полностью офлайн после установки — никаких лимитов, 402 и «Sign up…», которых сегодня столько у g4f;
- детерминированный: одинаковый вход → одинаковый протокол (хорошо для тестов);
- TSV-режим даёт **координаты** слов — по ним можно вычислить, что подпись ближе к оси Y/легенде/бару,
  и отдать модели подсказки-группировки (в коде выше — группировка по строкам).

**Ограничения варианта A:** Tesseract на графиках часто пропускает повёрнутые подписи вертикальной оси
(лечится поворотом картинки на 90° и вторым проходом — дешёвое дополнение, тоже в дизайне); порядок слов
в «протоколе» — по строкам, но какой подписи принадлежит число — модель должна выводить из позиции
(поэтому промпт требует `confidence <= 0.5`).

### Вариант B — RapidOCR (onnxruntime)

`rapidocr-onnxruntime` — пайплайн PaddleOCR-моделей в ONNX, ставится одним pip без системных пакетов
(в отличие от tesseract, не требует apt) и заметно точнее Tesseract на мелком шрифте диаграмм.

- **Плюсы:** нет apt-зависимости (важно вне Colab), точнее на мелких/повёрнутых надписях, тоже офлайн
  и детерминированный, отдаёт box+conf по каждому слову — API-совместим с протоколом варианта A.
- **Минусы:** ~15 МБ моделей при первом запуске (скачиваются автоматически), чуть медленнее Tesseract
  на больших картинках, и это ещё одна зависимость в ноутбуке.
- **Кому подходит:** если целевые эксперты запускают ноутбук не только в Colab (локально/Windows,
  где tesseract нет) — вариант B снимает боль установки.

### Вариант C — каскад OCR-движков (tesseract → rapidocr, по убыванию)

Каскад в духе каскада моделей из 4.1: сначала tesseract; если `OCR_MIN_CHARS` не набрано или среди слов
нет цифр (`\d`), картинка считается «непрочитанной» и идёт в rapidocr. Результаты не смешиваются —
берётся первый движок, давший достаточный протокол. Аудит (`OCR_AUDIT`: движок, символов, confidence
средний) — в issues формы, как `MODEL_AUDIT`.

- **Плюсы:** максимум покрытия при минимуме выдумывания — там, где tesseract слеп, пробует второй движок.
- **Минусы:** оба движка в зависимостях; время прогона на «трудных» картинках удваивается.

### Вариант D — таблица значений из векторного слоя (без OCR вовсе)

Для PDF, где график **векторный**: `pypdfium2`/`pdfplumber` умеют отдавать не растр, а сами примитивы —
линии, прямоугольники, текст с координатами. Тогда «чтение» графика превращается в точную задачу:
прямоугольники = бары (их высоты), текст рядом = подписи. OCR не нужен вообще, числа берутся из
координат примитивов, а не «распознаются».

- **Плюсы:** самый честный источник (`method: "vector"`, confidence может быть выше OCR), нет ошибки
  распознавания, полностью офлайн.
- **Минусы:** работает только для векторных графиков (растровые экспорты из matplotlib-скринов — нет);
  парсинг примитивов — самая сложная в разработке часть (бары ≠ всегда прямоугольники: линии, точки);
  это отдельный солидный контур — оценивается как PR 4+.
- **Кому подходит:** как целевая эволюция после того, как A/B приживутся; в первой версии — не делаем.

### Сравнение и решение

| Критерий | A: tesseract (выбран) | B: rapidocr | C: каскад | D: векторный |
|---|---|---|---|---|
| Точность текста диаграммы | средняя | высокая | высокая | точная (примитивы) |
| Понимание геометрии | нет | нет | нет | да (частично) |
| Зависимости | apt (в Colab есть) + pip | pip (~15 МБ) | оба | pypdfium2/pdfplumber |
| Офлайн после установки | да | да | да | да |
| Детерминированность | да | да | да | да |
| Трудоёмкость PR | малая | малая | средняя | большая |
| Покрытие графиков | текстовые подписи | текстовые подписи | шире A | только векторные |

**Решение (пользователь, 2026-11-06): вариант A — Tesseract.** Он уже в Colab из коробки, самый простой,
снимает главный риск — недоступность vision-моделей. Архитектура протокола (движок → текст → LLM-промпт)
подготовлена так, что B садится заменой одной функции, а C — обёрткой, если позднее понадобится точность или
запуск вне Colab; D — отдельное будущее направление, не блокирующее A.

**Интеграция в каскад:** OCR-контур включается только при `MODE = "text"`/`"fallback"` и
`ENABLE_OCR_FALLBACK = True`; при рабочей vision-модели он не нужен и не запускается. Результат OCR
отмечается в provenance как `method: "ocr-tesseract"`, чтобы в датасете было видно происхождение каждого
значения — модель, vision или OCR.

### 4.2. Ячейка разбора статьи (сейчас ячейка 8): картинки из документа
К `text_from_bytes` добавляется извлечение изображений — только для PDF (HTML/DOCX-статьи с инлайн-картинками
встречаются реже; в первой версии — PDF, остальное помечается предупреждением):

```python
def images_from_pdf(data: bytes, max_images=40):
    """Встроенные картинки pypdf + рендер страницы при их отсутствии — по одному на страницу."""
    ...
    return [{"page": n, "index": k, "png": bytes, "bbox": ..., "width": w, "height": h}]
```

- `pypdf` умеет `page.images` (встроенные XObject-картинки). Каждая получает `page`, номер на странице, PNG-байты.
- Если встроенных картинок нет (частый случай: график — вектор, а не растр), используется **рендер страницы**:
  проверенный путь — `pypdfium2` (лёгкий, без системных зависимостей, работает в Colab). Страница рендерится
  в PNG ~150 DPI, затем из неё вырезаются области картинок. Ограничение: `MAX_FIGURES_PER_DOC = 12`,
  `FIGURE_MIN_SIZE = 200×150 px` (отсекает логотипы/декор).
- Каждая картинка идёт в `doc["figures"]`, текст страницы (для контекста) уже есть в `doc["text"]`.

### 4.3. Фильтр «это график»

Двухступенчатый, чтобы не тратить vision-запросы на фотографии установки:

1. **Дешёвые эвристики до модели:** аспект 0.5–5, минимальный размер, рядом на странице есть подпись
   `Figure N / Fig. N / Рис. N` (поиск по тексту страницы), встроенная картинка не JPEG-фото огромного веса.
2. **Vision-классификация одним запросом:** «Is this a chart/graph (bar, line, scatter, box)? Answer JSON
   `{"chart": true/false, "type": "..."}`». Неграфики отбрасываются с записью в issues.

### 4.4. Схема и промпт (сейчас ячейки 10–11): базовый промпт меняется

Схема `experiments[].results[]` расширяется **без ломки контракта** `EvidenceRecord`: все новые поля — внутри
записи, а канонические 13 полей `RESULT_FIELDS` не меняются. Модель возвращает для figure-записей доп. блок:

```json
{
  "modality": "figure",
  "locator": "Figure 2, bar 'N200', left panel",
  "field": "grain yield",
  "value": "7.2",
  "unit": "t/ha",
  "evidence_quote": "Figure 2. Grain yield (t/ha) as affected by nitrogen rate.",
  "figure": {
    "chart_type": "bar",
    "axes": {"x": "N rate (kg/ha)", "y": "Grain yield (t/ha)"},
    "series": ["N0", "N100", "N200"],
    "read_value": "7.2",
    "text_match": "confirm",
    "text_value": "7.2",
    "text_quote": "grain yield reached 7.2 t/ha at N200",
    "description_check": "consistent",
    "description_conflict": null
  }
}
```

**Новый системный промпт для vision-контура** (ключевая правка, «базовый промпт меняется»):

```
You read charts from a scientific article and cross-check them with the article text.

INPUT: an image of one figure + the article text surrounding it (caption, paragraph, results text).

TASK A — READ THE CHART:
1. Identify chart type, axis labels and units, legend/series.
2. Read the numeric values shown (bars, points, lines) as precisely as the image allows.
   Never compute or extrapolate: report only what is visually present.

TASK B — CROSS-CHECK WITH THE TEXT:
3. The text is the SUPPORTING information: it tells what was measured, on what, with which units.
4. For each value you read from the chart, find its counterpart in the text. Set "text_match":
   "confirm"  — the text states the same value/relationship (quote it in "text_quote");
   "conflict" — the text states a different value or contradicts the chart (quote it);
   "absent"   — the text does not mention it.
5. Units and axis labels must match the text. A mismatch is a "description_check": "conflict"
   and must be reported, not silently corrected.

TASK C — VALIDATE THE CHART DESCRIPTION:
6. Build the description of the chart (title, axes, series, what it shows) and verify it against
   the caption and the surrounding text. If the caption says "yield by nitrogen rate" but axes
   read otherwise, that is a description conflict — report it in "description_conflict".

RULES:
- Answer ONLY with JSON, no markdown.
- Never invent values: if the chart is unreadable or too small, set "read_value": null and
  confidence <= 0.3 with a note.
- "evidence_quote" must be the VERBATIM figure caption or a verbatim sentence from the text.
- page is the [[PAGE n]] marker of the page the figure is on.
- One record = one value read from the chart. Do not merge several bars into one record.
```

Текстовый промпт тоже правится: правило №2 из старой формулировки («set null if only readable from an image»)
меняется на «if a value is only readable from a figure, set modality="figure" and leave value null; the vision
pass may fill it later» — чтобы текстовый контур честно помечал такие места, а vision-контур их подхватывал.

### 4.5. Извлечение (сейчас ячейка 12): vision-запросы

`llm_extract` остаётся для текста; рядом появляется `vision_extract` (выполняется только при `MODE = "vision"`):

- Вход: `doc["figures"]`, сопроводительный текст (страница ± 1, обрезанный до лимита), список значений из
  текстового прохода (для cross-check).
- Один запрос = одна картинка. Формат тот же OpenAI-совместимый: `messages` + `image=png_bytes, image_name`.
- Обработка ответа: тот же `parse_json_recovering` (markdown/обрывы уже переживаются), затем `normalize`.
- Перебор моделей: `VISION_MODELS` из каскада (4.1) по очереди, `PaymentRequiredError`/таймаут → следующая;
  паузы `MIN_INTERVAL_SEC`, семафор `G4F_CONCURRENCY` — как в текстовом контуре.
- **Деградация в середине сессии:** если на текущем графике упали все vision-модели, а текстовый контур уже
  отработал (он запускается первым), ноутбук не прерывается: график пропускается с записью в `errors`,
  остальные обрабатываются дальше. Если так падают 3 графика подряд, цепь vision-моделей объявляется
  нерабочей и image pipeline останавливается до конца документа — остальные картинки помечаются
  «vision-провайдер перестал отвечать», текстовые кандидаты не затронуты.
- Итог приклеивается к experiment'ам с `evidence_quotes` из caption + результатов.

### 4.6. Provenance-проверка (сейчас ячейка 14): что проверяется для figure-записей

Существующие проверки сохраняются, но для `modality: figure` они адаптируются — цитата теперь может быть
caption'ом, а не строкой таблицы:

- `evidence_quote` ищется в тексте как раньше (caption — часть текста страницы);
- `page` — по позиции caption;
- `figure.text_match`/`text_quote` проверяются тем же `_find_offset`: `text_quote` тоже обязан быть дословным,
  иначе `text_match` понижается до `absent` с пометкой «текст не найден»;
- **новая проверка согласованности:** если `figure.read_value` найден в текстовом проходе и отличается
  от `figure.text_value` больше чем на допуск сравнения (строка-к-строке; числа сравниваются как числа,
  tolerance 0), запись получает `reviewer_note` «значение из графика не совпадает с текстом: 7.2 vs 7.3» и
  confidence cap; в форму она идёт **как кандидат с конфликтом**, не как готовое approved (эксперт решает);
- `locator` обязан содержать `Figure N` (или `fig`/`рис`) — иначе downgrade modality до `text` с пометкой.

### 4.7. HTML-форма (сейчас ячейки 16–17): секция «Графики»

Форма получает отдельный визуальный блок для figure-кандидатов, чтобы эксперту было очевидно, откуда значение:

- рядом с записью — уменьшенная картинка графика (данные уже в payload, base64; форма офлайн это уже умеет);
- три статуса согласованности показываются бейджами: «график = текст» (confirm), «конфликт» (conflict —
  подсвечен, требует решения), «в тексте нет» (absent — эксперт вписывает значение сам или отклоняет);
- вопрос формы для figure-записей формулируется как проверка описания: «Верно ли описание графика? Значение
  из графика подтверждается текстом?» — те же кнопки «верно / исправить / нет в источнике», но с текстом
  обеих цитат (caption + text_quote) рядом.

### 4.8. Публикация

Без изменений: только `approved`, YAML `reviewed-dataset.v1` со всеми полями `figure.*` в
`extraction_candidates` (полные данные для аудита соответствуют provenance-принципу AGENTS.md). Картинки
в датасет **не отправляются** (только извлечённые значения + цитаты), как и сейчас не отправляется статья.

---

## 5. Тест-план (обязателен перед PR)

### 5.1. Каскад моделей (моки `Client`, без сети)

Тесты группы А — ядро ревизии 2; каждый проверяет одну ступень каскада или переход между режимами:

1. **A1. Ступень 1, отсечение недоступных:** мок `Client`, поднимающий `PaymentRequiredError` → модель
   помечена `alive = False`, причина сохранена в `audit`; image-ping для неё **не вызывается** (мок считает
   вызовы).
2. **A2. Ступень 1, отсечение отказных ответов:** модель отвечает «Sign up and repeat your request» на
   текстовый ping → `alive = False` через `_refusal_like`.
3. **A3. Ступень 2, честная мультимодальность:** живая модель отвечает «3» на image-ping → в `vision`;
   живая модель отвечает «Sign up…» на картинку (текст-ок, картинка-нет — кейс `gpt-4.1` из живых проверок) →
   не в `vision`, причина зафиксирована.
4. **A4. Ступень 2, неправильный счёт:** ответ «4» или «five» на диаграмме с 3 барами → не в `vision`.
5. **A5. Переход в vision-режим:** ≥1 модель прошла обе ступени → `MODE = "vision"`, `ACTIVE_MODEL` — она.
6. **A6. Фолбэк на текст:** модели живы, но image-ping не прошла ни одна → `MODE = "text"`, предупреждение
   напечатано, `MODEL_AUDIT` попал в issues.
7. **A7. Фолбэк до резервов:** не жива ни одна модель → `MODE = "fallback"`, `ACTIVE_MODEL = None`,
   предупреждение про Pollinations.
8. **A8. Порядок ступеней:** image-ping вызывается только для моделей с `alive = True` и только для
   `VisionModel`-имён / `VISION_MODELS_EXTRA` (мок с разными профилями моделей).
9. **A9. Аудит полон:** `MODEL_AUDIT` содержит строку на каждую модель каталога с вердиктами обеих ступеней
   и причинами; в `CFG` записан выбранный режим.

### 5.2. Остальная логика (как в ревизии 1)

10. **Извлечение картинок:** fixture-PDF с картинкой → `images_from_pdf` возвращает её с `page`;
    страница без картинок → пусто + warning.
11. **Фильтр графиков:** мок vision-ответа `{"chart": false}` → картинка отброшена и записана в issues.
12. **Cross-check:** fixture-ответ `text_match=confirm` + `text_quote` дословно в тексте → запись
    прошла; `text_quote` не найден → статус `absent` + note; `read_value != text_value` → конфликт и
    confidence cap.
13. **Provenance для figure:** `locator` без `Figure N` → downgrade до `text` с пометкой; `page` по caption.
14. **Форма:** payload содержит `figure`-блок и base64-картинку; рендер формы проходит с секцией «Графики».
15. **Регресс текстового контура:** все текущие проверки `test_nb.py` зелёные (текст без картинок работает).
16. **Деградация vision в середине сессии:** мок, где vision-модель падает на 2-м графике → график
    пропущен с ошибкой в `errors`, 3 падения подряд → image pipeline остановлен, текстовые кандидаты целы.

### 5.2. OCR-фолбэк (вариант A; моки `pytesseract`, без OCR-движка)

17. **B1. Протокол из TSV:** мок `image_to_data` с известными словами/координатами → `ocr_figure` вернул
    строки в порядке top→left, слова с conf ≤ 40 отброшены, картинка апскейлится (мок перехватывает resize).
18. **B2. Минимум текста:** мок с 5 символами протокола → картинка помечена «график без текста», в issues,
    в LLM не идёт.
19. **B3. Промпт OCR:** ответ модели на протокол → записи `modality: "figure"`, `method: "ocr-tesseract"`,
    `confidence <= 0.5`, `reviewer_note` содержит пометку «геометрия графика не проверялась».
20. **B4. Включение только при фолбэке:** `MODE = "vision"` → OCR-контур не вызывается вовсе (мок считает
    вызовы); `MODE = "text"`/`"fallback"` + `ENABLE_OCR_FALLBACK = True` → вызывается.
21. **B5. Отказ tesseract:** мок `pytesseract` бросает `TesseractNotFoundError` → предупреждение, ноутбук
    продолжает работу без OCR (как в ревизии 2), `OCR_AUDIT` фиксирует причину.
22. **B6. Поворот для вертикальных подписей:** протокол пуст или без цифр → второй проход на повёрнутой
    на 90° картинке; результат дописывается к протоколу с пометкой оси.

### 5.3. Живой smoke-тест в Colab (один прогон)

Статья с 1–2 графиками: каскад печатает таблицу моделей и выбранный режим; график найден, `text_match`
проставлен, форма показывает секцию «Графики». Отдельный сценарий — «сегодня vision нет» (как в живых
проверках 2026-11-03: 402 «No cake credits»): ноутбук обязан отработать чисто в `MODE = "text"` с явным
предупреждением, OCR-протоколами вместо vision-чтения и созданной формой с пометками «распознано OCR».

---

## 6. Ограничения и риски (честно)

- **Бесплатный vision-доступ нестабилен.** Сегодня g4f-провайдеры vision-моделей отвечали 402
  («No cake credits») или «Sign up…». Каскад это признаёт: проверка по факту, три явных режима
  (vision / text / fallback), текстовый контур всегда есть, а форма/эксперт остаются финальной инстанцией.
  OCR-фолбэк (4.1.3) закрывает текстовую часть графиков, но не их геометрию.
- **OCR ≠ vision.** Tesseract/RapidOCR читают подписи и числа, но не высоты баров и не положение точек:
  «тренд растёт» и «значение ≈ 7» из геометрии останутся недоступны при фолбэке. Поэтому confidence
  OCR-записей занижен, а промпт запрещает модели домысливать принадлежность чисел сериям.
- **Время запуска.** Ступень 1 пингует весь каталог (десятки моделей). Падения быстрые (402 за секунды),
  но живые модели отвечают по 5–20 с; при 5 живых моделях каскад добавляет до минуты. Смягчение: image-ping
  только для живых + VisionModel-кандидатов и остановка на первой успешной (см. 4.1).
- **Ping ≠ гарантия на длинной сессии.** Модель, прошедшая каскад в начале, может деградировать к середине
  документа (рейт-лимиты). Дизайн отвечает re-probe при выгорании цепочки и правилом «3 падения подряд →
  остановить image pipeline» (4.5), но не гарантирует полного покрытия всех графиков.
- **Точность чтения графиков.** Vision-модель может ошибочно считать значение с бара/точки. Поэтому
  cross-check с текстом обязателен, `confidence` у figure-значений по умолчанию ниже текстовых, и
  авто-approve отсутствует архитектурно.
- **Tesseract вне Colab:** на чистой Windows-машине без tesseract-бинарника OCR-фолбэк деградирует до
  предупреждения (тест B5) — осознанный компромисс; RapidOCR (вариант B) снимает проблему ценой
  дополнительной зависимости.
- **Векторные графики без встроенных картинок** требуют рендера страниц (pypdfium2 — новая зависимость, +1 pip).
- **Новая зависимость:** `pypdfium2` (рендер страниц), Pillow уже есть в Colab; OCR-вариант A добавляет только
  `pytesseract` (бинарник tesseract в Colab предустановлен).
- **Объём запросов:** каскад (+N текстовых ping + единицы image-ping) и затем +1 запрос на картинку
  (классификация) +1 на чтение; при 12 графиках это ~24 запроса сверх текстовых фрагментов, с теми же
  паузами/семафором. OCR-фолбэк LLM-запросов почти не добавляет (протоколы считаются локально и бесплатны).

## 7. План внедрения (4 PR, по правилу «один PR — одно изменение»)

| PR | Содержимое | Риск |
|---|---|---|
| 1 | Каскад проверки моделей (4.1: ступени 0–3, `_refusal_like`, probe-изображение, режимы, аудит) + тесты A1–A9 | малый: конфиг + функции, текст не тронут |
| 2 | Извлечение картинок из PDF + фильтр графиков (4.2–4.3) + тесты 10–11 | средний: новая зависимость pypdfium2 |
| 3 | Vision-промпт + cross-check + форма (4.4–4.8) + тесты 12–16 | основной объём |
| 4 | OCR-фолбэк, вариант A (4.1.3: `ocr_figure`, OCR-промпт, `method` в provenance) + тесты B1–B6 | малый/средний: pytesseract; архитектура готова под B/C |

Порядок позволяет сливать по шагам и откатить любой контур независимо.

# Data Sharing

`data/` не коммитится в git намеренно.

Причины:

- `data/raw/` содержит исходный корпус задания; его нельзя случайно публиковать как обычный код.
- `data/parsed/` и `data/indexes/` являются воспроизводимыми generated artifacts.
- `data/parsed/full_texts/` содержит полный извлеченный текст документов, то есть по сути копию корпуса.
- Большие JSONL/индексы быстро раздувают git history и мешают нормальной работе с репозиторием.
- В текущих локальных артефактах могут быть абсолютные пути конкретной Windows-машины; для передачи нужен portable export.

## Рекомендуемый вариант сейчас

1. Один человек запускает полный парсинг.
2. Создает portable archive:

```powershell
.\.venv\Scripts\python.exe scripts\package_parsed_artifacts.py
```

3. Загружает архив из `artifacts/` в общий закрытый storage: Yandex Disk, S3/Object Storage, корпоративное облако или GitHub Release с приватным доступом.
4. Второй разработчик скачивает архив и распаковывает его в корень репозитория.
5. Код продолжает читать стандартные пути:
   - `data/parsed/documents.jsonl`
   - `data/parsed/chunks.jsonl`
   - `data/parsed/tables.jsonl`
   - `data/parsed/full_texts/*.txt`
   - `reports/parsing/*`

Архив переписывает абсолютные пути в JSONL на repo-relative paths, поэтому его можно переносить между машинами.

## Легкий архив без full texts

Если нужно быстро передать только metadata/chunks/tables/reports:

```powershell
.\.venv\Scripts\python.exe scripts\package_parsed_artifacts.py --no-full-texts
```

Для RAG обычно нужны chunks и source metadata; full texts полезны для ручной проверки и source viewer.

## Что не стоит делать

- Не пушить `data/` обычным git commit-ом.
- Не хранить API ключи или `.env` рядом с архивом.
- Не заливать `data/raw/` в публичный репозиторий.
- Не использовать Git LFS для каждого нового generated JSONL без необходимости: это усложнит работу, а артефакты все равно лучше пересобирать или версионировать отдельно.

## Когда нужен DVC

DVC имеет смысл, если дальше появятся несколько версий датасета/индексов и надо воспроизводимо переключаться между ними:

- `data/parsed` version A/B;
- разные варианты chunking;
- разные embedding indexes;
- benchmark datasets.

Для текущего этапа проще portable zip + ссылка в командном чате. Если появятся регулярные обновления данных, можно добавить DVC remote.


# study

Study tools: a small local web app (Python + Flask) that hosts several learning tools.

The first tool is **单词本**, a vocabulary notebook. You type words you don't know; it translates them, stores them, and schedules eight reviews on the Ebbinghaus curve (5 min, 30 min, 12 h, 1 d, 2 d, 4 d, 7 d, 15 d).

## Run

```bash
python3 -m pip install -r requirements.txt
python3 run.py
```

The browser opens http://localhost:8765. Press Ctrl+C to stop. The app only accepts connections from this machine.

## Translation

Copy `.env.example` to `.env` to configure it.

| Setting | Meaning |
| --- | --- |
| `ONEMIN_API_KEY` | Your [1min.ai](https://app.1min.ai/) API key. When set, 1min.ai translates each word and writes an example sentence. |
| `ONEMIN_MODEL` | 1min.ai chat model, default `gpt-4o-mini`. |
| `TRANSLATOR` | `auto` (1min.ai when a key is set, Google as fallback), `onemin`, or `google`. |
| `PORT` | Port to serve on, default `8765`. |

Without a key the app uses Google Translate's free web endpoint. That needs no setup, but it is not an official API and may change or rate-limit. Its example sentences come from dictionary data, so phrases and rarer words have none.

Words added with one provider can be looked up again with the current one from the word's detail row (重新翻译).

## Layout

```
run.py                       entry point
app/
  __init__.py                create_app(): mounts every tool, local-only guard
  core/
    config.py                settings from .env / environment
    db.py                    one SQLite file (instance/study.db), per-request connection
    registry.py              Tool dataclass and automatic discovery
    srs.py                   Ebbinghaus schedule, reusable by any tool
    http.py                  JSON HTTP helper for outside APIs
  services/translation/      lookup() with interchangeable providers (onemin.py, google.py)
  tools/vocab/               the vocabulary notebook: routes, storage, page, styles, script
  templates/, static/        shared layout, navigation and design tokens
tests/                       python3 -m unittest discover -s tests -t .
```

Data lives in `instance/study.db`, which git ignores.

## Adding a tool

1. Create a package `app/tools/<slug>/` with a Flask `Blueprint` (pages under `templates/<slug>/`, assets under `static/`).
2. In its `__init__.py`, expose:

   ```python
   from app.core.registry import Tool
   tool = Tool(slug="<slug>", name="…", description="…", blueprint=bp,
               schema="CREATE TABLE IF NOT EXISTS …", status=optional_status_line)
   ```

3. Restart. The tool is mounted at `/<slug>/`, appears in the navigation and on the home page, and its tables are created.

Tools can reuse `app.core.srs` for review scheduling, `app.services.translation.lookup` for dictionary lookups, and the color and type tokens in `app/static/base.css`.

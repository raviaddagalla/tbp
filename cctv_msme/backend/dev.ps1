# Windows dev server with reload scoped to app/ only.
# Why: the project lives inside a OneDrive-synced folder and .venv sits next to
# the code; a plain `--reload` makes WatchFiles restart on every OneDrive touch
# of .venv\Lib\site-packages and on data/ writes, spamming false reloads.
# `--reload-dir app` replaces the default watched dirs with just the source.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir app

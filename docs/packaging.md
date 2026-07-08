# Packaging Deputy as a desktop command

Deputy is a pure-Python application, so the cleanest way to "install" it is as a Python tool that
exposes its two entry points on your `PATH`. This document covers the recommended path, the alternatives,
and an honest account of why a single frozen binary is *not* recommended here.

## The one hard prerequisite

However you package the Python side, Deputy still needs a **model runtime**: [Ollama](https://ollama.com)
running locally with the models pulled.

```bash
ollama pull qwen2.5:3b        # chat model
ollama pull nomic-embed-text  # embeddings for RAG
```

There is no way around this — Deputy is a client of a local model server, not a self-contained model. So
"packaging" means shipping the agent conveniently, not bundling a 2 GB model into an executable.

## Entry points

The project declares three console scripts (`pyproject.toml`):

| Command | Runs | Equivalent module form |
| --- | --- | --- |
| `deputy` | the CLI agent | `python -m deputy` |
| `deputy-web` | the loopback web UI (plain server) | `python -m deputy.web` |
| `deputy-app` | the loopback web UI, **launch-once** (auto-open, port reuse, optional native window) | `python -m deputy.web.launcher` |

`deputy-app` is the friendly, double-clickable front door; `deputy-web` is the bare server for
scripting and service managers. The other tools stay as module invocations (they're
developer-facing): `python -m deputy.rag.index`, `python -m deputy.eval`, `python -m deputy.spike`.

## The app experience (`deputy-app`)

`deputy-app` wraps the exact same FastAPI UI as `deputy-web`, adding only the conveniences that make
it feel like an application rather than a command you re-run:

- **Auto-open + stay running.** It starts the loopback server, opens your browser at the right URL,
  and blocks until you close the window or press Ctrl+C.
- **Re-launch is safe.** If Deputy is already serving on the preferred port it reopens that instance;
  if another process holds the port it moves to the next free one. Launching twice never errors.
- **Optional native window.** `deputy-app --window` opens a desktop window via
  [`pywebview`](https://pywebview.flowrl.com) — an optional extra so the default install stays
  dependency-light and packaging stays simple:

```bash
uv sync --extra app          # inside the checkout
uv tool install ".[app]"     # or as an installed tool
deputy-app --window          # falls back to a browser tab if pywebview isn't present
```

### macOS: launch with no terminal

- **Double-click.** [`scripts/Deputy.command`](../scripts/Deputy.command) is an executable shell
  script; double-click it in Finder (right-click → *Open* once to clear Gatekeeper). It runs an
  installed `deputy-app` if present, otherwise `uv run deputy-app` from the checkout, and keeps a
  small Terminal window open as the "running" indicator.
- **A real `.app` (optional).** If you want a dock icon, wrap the command with a one-liner:
  `osacompile -o Deputy.app -e 'do shell script "open \"$HOME/…/scripts/Deputy.command\""'`, or point
  an Automator "Application" at the same script. Not shipped — the `.command` is the light path.

## Recommended: `uv tool install`

[`uv`](https://docs.astral.sh/uv/) installs the project into an isolated environment and puts `deputy`
and `deputy-web` on your `PATH` — no venv activation needed.

```bash
# From a checkout of the repo:
uv tool install .

# Then, from anywhere:
deputy "what is 12 * (3 + 4)?"
deputy --real "what's on my calendar for 2026-07-08?"
deputy-web                       # http://127.0.0.1:8000

# Upgrade after pulling changes, or uninstall:
uv tool install . --force
uv tool uninstall deputy
```

This is the recommended path because it keeps a **real Python interpreter** behind the command — which
matters for how Deputy launches its tools (see [Why not a frozen binary](#why-not-a-frozen-binary)).

## Alternative: `pipx`

[`pipx`](https://pipx.pypa.io) does the same job if you'd rather not use `uv`:

```bash
pipx install .        # from a checkout
deputy-web
```

## Alternative: a shell alias

If you just want a short command without installing anything, alias into the project's venv:

```bash
# ~/.zshrc
alias deputy='uv run --project ~/code/deputy-agent python -m deputy'
alias deputy-web='uv run --project ~/code/deputy-agent python -m deputy.web'
```

## Start on login (opt-in)

Since the UI binds loopback and mirrors the CLI's config, you can keep it running across logins with
a user-level service manager. The repo ships a ready-to-fill macOS `launchd` template at
[`scripts/com.deputy.app.plist`](../scripts/com.deputy.app.plist). It runs `deputy-app --no-browser`
(server only — no browser pops at login) so the UI is always ready; you then open it any time with
`deputy-app` or `Deputy.command`, which detect the running instance and just open your browser.

```bash
cp scripts/com.deputy.app.plist ~/Library/LaunchAgents/com.deputy.app.plist
# Edit its placeholders first:
#   __DEPUTY_APP__  → `which deputy-app`   (e.g. /Users/you/.local/bin/deputy-app)
#   __WORKDIR__     → where Deputy keeps data/ + finds your workspace (your checkout)
#   __LOG_DIR__     → a writable logs dir  (e.g. /Users/you/Library/Logs)
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.deputy.app.plist   # enable now + on login
launchctl bootout   gui/$(id -u) ~/Library/LaunchAgents/com.deputy.app.plist   # disable
```

Setting `WorkingDirectory` matters: Deputy resolves `data/` and the workspace relative to the process
CWD, and a login agent otherwise starts at `/`. On Linux, an equivalent `systemd --user` unit running
`deputy-app --no-browser` works the same way.

## Why not a frozen binary

A double-clickable app via **PyInstaller** or **py2app** is possible, but it fights the architecture and
isn't recommended:

- **The killer issue: Deputy launches its tool servers as Python subprocesses.** `deputy/app.py` starts
  each built-in MCP server with `ServerSpec(command=sys.executable, args=["-m", "deputy.servers.…"])`.
  Inside a frozen app, `sys.executable` is the *frozen binary*, not a Python interpreter, so `-m module`
  won't work. Supporting a frozen build would mean teaching the app to re-exec itself as each server (a
  multi-entry-point frozen build) — real, avoidable complexity. Installs that keep a real interpreter
  (`uv tool` / `pipx`) sidestep this entirely.
- **Native extension.** RAG loads the `sqlite-vec` SQLite extension at runtime (`sqlite_vec.load(db)`);
  its shared library must be collected into the bundle as a data file, or retrieval breaks at startup.
- **Hidden imports.** `uvicorn`/`fastapi` and the `mcp` SDK pull in dynamically-imported submodules that
  freezers routinely miss without explicit `--hidden-import`/`--collect-all` flags.
- **You still need Ollama.** The bundle can't include the model runtime, so a "standalone app" still
  depends on a separate install — most of the perceived benefit evaporates.

If you specifically need a GUI-launchable app despite the above, the sketch is:

```bash
uv pip install pyinstaller
pyinstaller \
  --name deputy-web \
  --collect-all mcp \
  --collect-all uvicorn \
  --collect-all sqlite_vec \
  --add-data "src/deputy/web/static:deputy/web/static" \
  --add-data "src/deputy/web/templates:deputy/web/templates" \
  src/deputy/web/__main__.py
```

…and you would then have to solve the subprocess-launch problem above (e.g. re-exec the frozen binary
with an env flag that routes it to a server `main()`), plus verify the bundled static/template assets and
the `sqlite-vec` library load. For a personal, developer-oriented tool that already needs Ollama on the
machine, `uv tool install` is simpler, more robust, and what this project recommends.

## Publishing (future)

The build backend is Hatchling and the wheel is already configured
(`[tool.hatch.build.targets.wheel] packages = ["src/deputy"]`), so if you ever want `uv tool install
deputy` / `pipx install deputy` to work from an index, it's just:

```bash
uv build            # produces dist/*.whl and dist/*.tar.gz
# then publish the artifacts to PyPI (or a private index)
```

Bump `version` in `pyproject.toml` (and `__version__` in `src/deputy/__init__.py`) before building.

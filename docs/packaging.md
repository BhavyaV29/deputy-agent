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

The project declares two console scripts (`pyproject.toml`):

| Command | Runs | Equivalent module form |
| --- | --- | --- |
| `deputy` | the CLI agent | `python -m deputy` |
| `deputy-web` | the loopback web UI | `python -m deputy.web` |

The other tools stay as module invocations (they're developer-facing): `python -m deputy.rag.index`,
`python -m deputy.eval`, `python -m deputy.spike`.

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

## Running the web UI as a background service (optional)

Since the UI binds loopback and mirrors the CLI's config, you can keep it running with a user-level
service manager. macOS `launchd` sketch (`~/Library/LaunchAgents/com.deputy.web.plist`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>Label</key><string>com.deputy.web</string>
    <key>ProgramArguments</key>
    <array>
      <string>/Users/you/.local/bin/deputy-web</string>
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
  </dict>
</plist>
```

`launchctl load ~/Library/LaunchAgents/com.deputy.web.plist`. On Linux, an equivalent
`systemd --user` unit works the same way. (This is a convenience, not something the repo ships.)

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

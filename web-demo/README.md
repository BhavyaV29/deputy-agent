# Deputy — in-browser demo

A tiny, static browser demo of the [Deputy](../README.md) concept: an agent loop
that plans, calls tools, **asks before it acts**, and keeps an audit log. The
default experience is a **scripted walkthrough** with pre-recorded model
decisions, so it starts instantly and works without a GPU or model download.
The browser-side tools, observations, approval gate, and session audit still run
live over a fixed in-memory sample corpus.

**Run it for real (experimental)** is an optional second mode. It downloads a
small model and runs inference locally through
[WebLLM](https://github.com/mlc-ai/web-llm) and WebGPU. There is no application
backend or telemetry; the optional model assets are fetched from a CDN, while
prompts and sample data stay in the browser.

This is a self-contained illustration of Deputy's ideas, not the real Python
app. It lives entirely in `web-demo/` and shares no code with `src/`. The
**Python/Ollama app** is Deputy's real constrained-decoding implementation.

## What it shows

- **A scripted walkthrough by default:** plan &rarr; tool call (with args)
  &rarr; observation &rarr; answer, capped at a few steps. The model choices are
  pre-recorded; the surrounding JavaScript loop and tool execution are live.
- **Browser-side tool-calling** over a sandboxed corpus that mirrors Deputy's
  real MCP tools:
  - `search_files(query)` / `read_file(path)` — a confined virtual workspace
  - `search_notes(query)` / `add_note(text)` — an append-only note store
  - `list_events(date_or_range)` — a local calendar
- **A trust surface.** Read-only tools auto-approve; the mutating `add_note`
  triggers an in-page **Approve / Deny** prompt before it runs.
- **A persistent-style audit list** of every plan, observation, and approval
  decision for the session (see the **Audit** tab).
- **Optional experimental WebGPU inference.** WebLLM is prompted to return one
  JSON action; the browser then parses it tolerantly (including repairs and
  retries for common small-model errors). This is **not** the Python/Ollama
  constrained-decoding path, where an action schema is enforced by the runtime.

## Requirements (optional experimental inference)

- A **WebGPU-capable browser**: Chrome/Edge 113+ or a recent Chromium; Safari 18+;
  Firefox with WebGPU enabled. Desktop is recommended.
- Enough GPU memory for the selected model; the 1.5B default downloads roughly
  1 GB of weights.
- The first run downloads the model weights (see below) and caches them; later
  runs load from cache and work offline.

No WebGPU? The default scripted walkthrough still works. WebGPU is checked only
when you choose **Run it for real** (or open with `?live=1`).

## Model + download size

Default for the optional live mode:
**`Qwen2.5-1.5B-Instruct-q4f16_1-MLC`**.

- **1.5B (default):** roughly 1 GB download; usually completes the preset tasks.
- **0.5B:** roughly 350 MB; fastest, but prone to wandering or looping.
- **3B:** roughly 2 GB; the most reliable browser option and the largest download.

Choose among them in the page before loading. All live modes are experimental;
the scripted walkthrough is the reliable way to see the intended flow.

## Run locally

It's a no-build static site — just serve the folder over HTTP (ES modules and
WebGPU don't work from a `file://` URL):

```bash
cd web-demo
python3 -m http.server 8000
# then open http://localhost:8000
```

Any static server works (e.g. `npx serve`, `npx http-server`).

### Pin the scripted mode

Scripted is already the default. Append `?fallback=1` to pin it deterministically
(even if another link also supplies `?live=1`) — useful for tests or screenshots:

```
http://localhost:8000/?fallback=1
```

## How mode selection works

The page deliberately starts without probing the GPU or downloading a model:

1. **Normal visit** &rarr; the scripted walkthrough immediately.
2. **`?fallback=1` present** &rarr; scripted mode is explicitly pinned.
3. **Run it for real** or **`?live=1`** &rarr; check `navigator.gpu`, then call
   `navigator.gpu.requestAdapter()`. Missing support returns to scripted mode
   with an explanation.
4. **Usable adapter** &rarr; show the model picker and **Load on-device model**.
5. **Model load fails** (network, out-of-memory, compile error) &rarr; keep the
   picker and a retry button visible; the user can retry or return to scripted.

In **scripted mode**, preset demos replay canned model decisions through the
same browser loop: tool calls, observations, approval gate, and audit are live;
only the model's step-by-step choices are pre-recorded.

WebLLM is imported lazily (only when you click **Load on-device model**), so the
scripted path never requests model assets.

## Deploy as a static site

There's no backend and no build step, so this folder deploys to any static host.
This repo targets **[Render](https://render.com) as a Static Site** via the
blueprint at [`render.yaml`](../render.yaml) in the repo root — Render just serves
`web-demo/` over its CDN.

**Deploy on Render — the one manual step:** in the Render dashboard, click
**New → Blueprint** and pick this repo (Render reads `render.yaml` automatically),
**or** **New → Static Site**, connect the repo, set **Publish directory** to
`web-demo`, and leave the **Build command** empty. Then confirm the live URL.

The blueprint names the service `deputy-web-demo`, so the **expected URL is
`https://deputy-web-demo.onrender.com`** — the real URL depends on the service
name, so **confirm it after the first deploy**. If it differs (or you deploy
elsewhere), update the links in [`../README.md`](../README.md) and
[`../docs/build-in-public.md`](../docs/build-in-public.md); it's just static
files, so swapping the URL is all it takes.

Other hosts need no build command either — point **Netlify / Vercel / Cloudflare
Pages / GitHub Pages** at the `web-demo` directory. All asset paths here are
relative, so it also serves fine from a subpath (e.g. `/<repo>/web-demo/`).

Some hosts must send WebLLM's model shards with permissive CORS (the default
jsDelivr/HuggingFace CDNs already do). No special headers are required for the
demo itself.

## File tree

```
web-demo/
├── index.html          # single page (loads js/app.js as an ES module)
├── style.css           # black-and-white UI, matches Deputy's local web UI
├── README.md           # this file
├── .gitignore
└── js/
    ├── app.js          # wiring: WebGPU detection, model loading, run routing, audit
    ├── agent.js        # browser loop + tolerant action parser
    ├── tools.js        # client-side files/notes/calendar tools + registry
    ├── data.js         # the sandboxed sample corpus (in-memory only)
    ├── prompts.js      # system / observation / denial prompt text
    ├── scenarios.js    # preset goals + canned scripts + the scripted-model seam
    ├── llm.js          # WebGPU detection + lazy WebLLM engine wrapper
    ├── ui.js           # DOM rendering: transcript, approval widget, audit
    └── util.js         # sleep / id / timestamp helpers
```

## Manual test checklist

`npm test` covers the tolerant parser and `node --check js/*.js` checks the
modules. The WebGPU path still needs a browser:

- [ ] Normal visit: the banner identifies the scripted walkthrough; each preset
      streams plan &rarr; observation &rarr; answer; **Prep for today's review**
      surfaces an Approve/Deny prompt; **Deny** produces the "did not save"
      answer and **Approve** the "saved a reminder" answer; the **Audit** tab
      lists the actions.
- [ ] `?fallback=1`: remains in scripted mode even if `live=1` is also present.
- [ ] No-WebGPU browser: scripted mode works; **Run it for real** returns to it
      with an explanatory banner.
- [ ] WebGPU browser: **Run it for real** reveals the model picker, then
      **Load on-device model** shows download progress and enables live
      inference. DevTools should show model-asset requests, but no prompt or
      sample-data upload.
- [ ] Reload after a successful load: the model comes from cache (works offline).

# Deputy — in-browser demo

A tiny, **fully client-side** demo of the [Deputy](../README.md) concept: a
private, on-device agent loop that plans, calls tools, **asks before it acts**,
and keeps an audit log — running entirely in your browser. The model runs
locally on your GPU via [WebLLM](https://github.com/mlc-ai/web-llm) and WebGPU.
The sample data is a small fixed corpus held only in the page. **Nothing leaves
your machine** — there is no backend and no telemetry; the only network request
is the one-time model download from a CDN.

This is a self-contained illustration of Deputy's ideas, not the real Python
app. It lives entirely in `web-demo/` and shares no code with `src/`.

## What it shows

- **A bounded ReAct loop** streamed live: plan &rarr; tool call (with args)
  &rarr; observation &rarr; answer, capped at a few steps.
- **Constrained, on-device tool-calling** over a sandboxed corpus that mirrors
  Deputy's real MCP tools:
  - `search_files(query)` / `read_file(path)` — a confined virtual workspace
  - `search_notes(query)` / `add_note(text)` — an append-only note store
  - `list_events(date_or_range)` — a local calendar
- **A trust surface.** Read-only tools auto-approve; the mutating `add_note`
  triggers an in-page **Approve / Deny** prompt before it runs.
- **A persistent-style audit list** of every plan, observation, and approval
  decision for the session (see the **Audit** tab).

## Requirements (for real on-device inference)

- A **WebGPU-capable browser**: Chrome/Edge 113+ or a recent Chromium; Safari 18+;
  Firefox with WebGPU enabled. Desktop is recommended.
- A GPU with roughly **1 GB of free memory** for the default model.
- The first run downloads the model weights (see below) and caches them; later
  runs load from cache and work offline.

No WebGPU? No problem — the page detects that up front and runs a **scripted
fallback** instead (details below), so it is always usable.

## Model + download size

Default: **`Qwen2.5-0.5B-Instruct-q4f16_1-MLC`** — the smallest genuinely useful
instruct model in WebLLM's prebuilt list.

- **~300 MB** of weights, downloaded **once** and cached by the browser.
- **~0.95 GB** of GPU memory at runtime.

To try the slightly stronger `Llama-3.2-1B-Instruct-q4f16_1-MLC` (~880 MB
download), change `MODEL` in [`js/llm.js`](./js/llm.js) to `ALT_MODEL`.

> A 0.5B model is small. It's good enough to demonstrate the loop, but it will
> occasionally pick an odd tool or phrase an answer awkwardly. The preset tasks
> are the most reliable way to see the intended flow.

## Run locally

It's a no-build static site — just serve the folder over HTTP (ES modules and
WebGPU don't work from a `file://` URL):

```bash
cd web-demo
python3 -m http.server 8000
# then open http://localhost:8000
```

Any static server works (e.g. `npx serve`, `npx http-server`).

### Force the fallback (no GPU needed)

Append `?fallback=1` to the URL to force the scripted path deterministically —
useful for testing, screenshots, or presenting without a GPU:

```
http://localhost:8000/?fallback=1
```

## How WebGPU detection + fallback works

On load the page checks for WebGPU and picks a mode:

1. **`?fallback=1` present** &rarr; fallback immediately.
2. **`navigator.gpu` missing** &rarr; fallback, with a banner explaining why.
3. **`navigator.gpu` present** &rarr; it also calls
   `navigator.gpu.requestAdapter()`; if no adapter is returned it downgrades to
   fallback. Otherwise it offers a **Load on-device model** button.
4. **Model load fails** (network, out-of-memory, compile error) &rarr; it
   catches the error and downgrades to fallback with a banner.

In **fallback mode**, the preset demos replay a **canned transcript** through
the *same* agent loop: the tool calls, observations, approval gate, and audit
are all real — only the model's step-by-step decisions are pre-recorded instead
of generated on-device. A banner always makes it clear you're in fallback.

WebLLM is imported lazily (only when you click **Load on-device model**), so the
fallback path never touches the network.

## Deploy as a static site

Because there's no backend, deploy the `web-demo/` folder to any static host:

- **GitHub Pages:** push the repo and enable Pages, or publish just this folder
  (e.g. with a Pages action). Serve it at a subpath — all asset paths here are
  relative, so it works under `/<repo>/web-demo/`.
- **Netlify / Vercel / Cloudflare Pages:** set the publish/output directory to
  `web-demo` with **no build command**.
- **Any web server:** copy the folder to the web root.

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
    ├── agent.js        # the bounded ReAct loop + action parser (ports agent.py)
    ├── tools.js        # client-side files/notes/calendar tools + registry
    ├── data.js         # the sandboxed sample corpus (in-memory only)
    ├── prompts.js      # system / observation / denial prompt text
    ├── scenarios.js    # preset goals + canned scripts + the scripted-model seam
    ├── llm.js          # WebGPU detection + lazy WebLLM engine wrapper
    ├── ui.js           # DOM rendering: transcript, approval widget, audit
    └── util.js         # sleep / id / timestamp helpers
```

## Manual test checklist

Automated syntax checks (`node --check`) cover the modules, but the WebGPU path
must be verified by hand in a browser:

- [ ] `?fallback=1`: the banner shows fallback mode; each preset streams
      plan &rarr; observation &rarr; answer; **Prep for today's review**
      surfaces an Approve/Deny prompt; **Deny** produces the "did not save"
      answer and **Approve** the "saved a reminder" answer; the **Audit** tab
      lists the actions.
- [ ] No-WebGPU browser: loads straight into fallback with an explanatory banner.
- [ ] WebGPU browser: **Load on-device model** shows the download progress bar,
      then the composer + presets run real on-device inference (nothing leaves
      the machine — check DevTools' Network tab: only the one-time model fetch).
- [ ] Reload after a successful load: the model comes from cache (works offline).

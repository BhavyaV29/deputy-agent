# Media

Demo captures for the README live here. **Nothing is committed yet — add your own.**

The README embeds `docs/media/demo.gif`; until you add it, the image link renders broken. That's
expected. Do **not** commit fabricated or AI-generated screenshots — record the real thing.

## What to capture

The story that sells Deputy is *the approval pause*, so make sure it's in frame.

### `demo.gif` — the end-to-end web flow (primary)

1. Start the UI: `uv run python -m deputy.web` and open `http://127.0.0.1:8000`.
2. In the chat box, ask for something that writes, e.g.
   *"Save a note: call the dentist tomorrow, then confirm."*
3. Let the **live action stream** render each step's plan and the tool observation.
4. When the mutating `add_note` call appears, show the **Approve / Deny** buttons (this is the moment).
5. Click **Approve** and let the run finish with a final answer.
6. Switch to the **Audit** tab to reveal the recorded run: planned actions, the approval decision, and
   the observation.

Keep it ~15–25 seconds. A short, silent loop is ideal for embedding in the README and in posts.

### Optional stills

- `cli.png` — a terminal capture of `deputy --real "…"` showing the `[approval] … approve? [y/N]` prompt.
- `audit.png` — the Audit tab, or `tail -f data/audit.jsonl` running alongside a task.

## Recording tips

- macOS: `Cmd+Shift+5` records a region to `.mov`; convert to GIF with
  `ffmpeg -i in.mov -vf "fps=12,scale=960:-1:flags=lanczos" -loop 0 demo.gif`.
- Keep the window narrow (~960px) so the GIF stays small and crisp in the README.
- Use the bundled `sample_workspace` (index it first with `python -m deputy.rag.index sample_workspace`)
  so retrieval examples have something to find.

## Expected filenames

| File | Used by | Status |
| --- | --- | --- |
| `demo.gif` | README **Demo** section | **you must add** |
| `cli.png` | optional | optional |
| `audit.png` | optional | optional |

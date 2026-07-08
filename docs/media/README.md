# Media

Demo captures for the README live here. **Nothing is committed yet — add your own.**

The README embeds `docs/media/demo.gif`; until you add it, the image link renders broken. That's
expected. Do **not** commit fabricated or AI-generated screenshots — record the real thing.

## What to capture

The story that sells Deputy is *the approval pause*, so make sure it's in frame.

### `demo.gif` — the end-to-end web flow (primary)

The web UI ships **one-click sample tasks** (the *"Try a sample task"* row above the composer), so the
recording is deterministic — no typing, exact same flow every time:

1. Start the UI: `deputy-app` (or `uv run python -m deputy.web`) and open `http://127.0.0.1:8000`.
2. Click the **"Save a note (asks to approve)"** sample. It sends
   *"Save a note: call the dentist tomorrow, then confirm."*
3. Let the **live action stream** render each step's plan and the tool observation.
4. The mutating `add_note` call pauses with **Approve / Deny** buttons — this is the moment, linger here.
5. Click **Approve** and let the run finish with a final answer.
6. Switch to the **Audit** tab to reveal the recorded run: planned actions, the approval decision, and
   the observation.

Keep it ~15–25 seconds. A short, silent loop is ideal for embedding in the README and in posts.

### Optional stills

- `cli.png` — a terminal capture of `deputy --real "…"` showing the `[approval] … approve? [y/N]` prompt.
- `audit.png` — the Audit tab, or `tail -f data/audit.jsonl` running alongside a task.

## Recording recipe (macOS: `screencapture` → `ffmpeg`)

```bash
# 1. Record the flow to a .mov. Non-interactive + deterministic, with clicks shown:
screencapture -v -k -V 25 docs/media/demo.mov                 # whole main display, 25s
# …or crop to just the window with a fixed region (x,y,width,height):
screencapture -v -k -V 25 -R 40,80,1000,720 docs/media/demo.mov
#    Prefer to pick the window by hand? Cmd+Shift+5 → "Record Selected Portion" → drag → Record,
#    then click the menu-bar Stop; it saves a .mov you convert in step 2.

# 2. Convert to an optimized, looping GIF (~960px wide, 12 fps, palette for crisp colors):
ffmpeg -i docs/media/demo.mov \
  -vf "fps=12,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  -loop 0 docs/media/demo.gif

# 3. (optional) drop the intermediate video:
rm docs/media/demo.mov
```

- `-k` overlays your clicks — handy for the Approve button. `-V <seconds>` caps the length so it
  stops itself; omit it and press the menu-bar Stop to end manually.
- Keep the window narrow (~960px) so the GIF stays small and crisp in the README.
- For the file/RAG samples, index the bundled corpus first
  (`python -m deputy.rag.index sample_workspace`) so there's something to find.

## Expected filenames

| File | Used by | Status |
| --- | --- | --- |
| `demo.gif` | README **Demo** section | **you must add** |
| `cli.png` | optional | optional |
| `audit.png` | optional | optional |

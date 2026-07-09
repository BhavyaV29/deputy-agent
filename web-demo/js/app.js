// Wiring: detect WebGPU, manage on-device model loading, and route each run to
// either the real WebLLM model or the scripted fallback — both driving the same
// agent loop. Also owns the little session audit that the Audit tab renders.

import { createRegistry } from "./tools.js";
import { runAgent } from "./agent.js";
import { SCENARIOS, scriptedModel } from "./scenarios.js";
import { webgpuSupport, probeAdapter, createWebLLMModel, MODELS, DEFAULT_MODEL_ID, modelById, modelLabel } from "./llm.js";
import {
  el,
  clear,
  fmtArgs,
  addEntry,
  addToolEntry,
  showThinking,
  requestApproval,
  revealAnswer,
  renderAudit,
} from "./ui.js";
import { uid, nowStamp } from "./util.js";
import { initTheme } from "./theme.js";

const registry = createRegistry();

const dom = {
  banner: document.getElementById("banner"),
  bannerText: document.getElementById("banner-text"),
  bannerDismiss: document.getElementById("banner-dismiss"),
  modelStatus: document.getElementById("model-status"),
  modelSelect: document.getElementById("model-select"),
  modelHint: document.getElementById("model-hint"),
  loadBtn: document.getElementById("load-btn"),
  liveBtn: document.getElementById("live-btn"),
  scriptedBtn: document.getElementById("scripted-btn"),
  progress: document.getElementById("progress"),
  progressBar: document.getElementById("progress-bar"),
  progressText: document.getElementById("progress-text"),
  transcript: document.getElementById("transcript"),
  presets: document.getElementById("presets"),
  composer: document.getElementById("composer"),
  message: document.getElementById("message"),
  send: document.getElementById("send"),
  demoView: document.getElementById("demo"),
  auditView: document.getElementById("audit"),
  auditBody: document.getElementById("audit-body"),
  auditRefresh: document.getElementById("audit-refresh"),
  auditClear: document.getElementById("audit-clear"),
  themeToggle: document.getElementById("theme-toggle"),
};

const state = {
  // "fallback" is the scripted walkthrough — now the DEFAULT/primary experience.
  // ready | loading | loaded | load_error are the opt-in, experimental live path.
  mode: "checking", // checking | fallback | ready | loading | loaded | load_error
  model: null,
  modelId: DEFAULT_MODEL_ID,
  running: false,
  forcedFallback: false,
  fallbackReason: "",
  runs: [],
};

const currentModel = () => modelById(state.modelId);

function setBanner(text, kind) {
  dom.bannerText.textContent = text;
  dom.banner.className = `banner ${kind}`;
  dom.banner.hidden = false; // a new state's message reappears even if dismissed
}

function chipsEnabled(on) {
  dom.presets.querySelectorAll(".chip").forEach((chip) => {
    chip.disabled = !on;
  });
}

function applyEnablement() {
  const idle = !state.running;
  const loaded = state.mode === "loaded";
  const scripted = state.mode === "fallback"; // the primary, default experience
  const ready = state.mode === "ready";
  const loading = state.mode === "loading";
  const loadError = state.mode === "load_error";
  // The opt-in, experimental live path — WebGPU present, model picker on screen.
  const live = ready || loading || loaded || loadError;
  // A (re)load can be started from a fresh "ready" or a recoverable failure.
  const canLoad = ready || loadError;

  dom.message.disabled = !(loaded && idle);
  dom.send.disabled = !(loaded && idle);
  dom.message.placeholder = loaded
    ? "Ask Deputy to do something\u2026"
    : scripted
      ? "Free-text chat needs a live model \u2014 pick a task above, or run it for real (experimental)."
      : "Load the on-device model to chat, or go back to the scripted walkthrough.";

  chipsEnabled((loaded || scripted) && idle);

  dom.modelSelect.hidden = !live;
  dom.modelSelect.disabled = !(idle && (ready || loaded || loadError));
  // The model-choice hint is only relevant while the picker is on screen.
  dom.modelHint.hidden = !live;

  dom.loadBtn.hidden = !(canLoad || loading);
  dom.loadBtn.disabled = !(canLoad && idle);
  dom.loadBtn.textContent = loadError ? "Retry download" : "Load on-device model";

  // Opt into experimental live mode from the scripted default...
  dom.liveBtn.hidden = !scripted;
  dom.liveBtn.disabled = !idle;
  // ...and get back to the scripted walkthrough from any live state.
  dom.scriptedBtn.hidden = !(ready || loaded || loadError);
  dom.scriptedBtn.disabled = !idle;
}

function setMode(next, { reason } = {}) {
  state.mode = next;
  if (reason) state.fallbackReason = reason;

  switch (next) {
    case "checking":
      setBanner("Checking this device for WebGPU\u2026", "info");
      dom.modelStatus.textContent = "Checking device\u2026";
      dom.progress.hidden = true;
      break;
    case "fallback": {
      // Scripted is the primary, default experience now — present it as such, not
      // as an error. A live-unavailable reason gets an honest note instead.
      const unavailable = state.fallbackReason.startsWith("live-unavailable:");
      const base =
        "Scripted walkthrough \u2014 plan \u2192 tool \u2192 approval \u2192 audit \u2192 final answer, instantly and with no download. Pick a task below.";
      const tail = unavailable
        ? ` On-device mode isn't available here (${state.fallbackReason.slice("live-unavailable:".length).trim()}).`
        : " Want a real model? Use \u201cRun it for real\u201d (experimental).";
      setBanner(base + tail, unavailable ? "warn" : "info");
      dom.modelStatus.textContent = "Scripted walkthrough \u00b7 no model loaded";
      dom.progress.hidden = true;
      break;
    }
    case "ready": {
      const model = currentModel();
      setBanner(
        `Experimental on-device mode \u2014 pick a model and load it (one-time ${model.download} download), then it runs fully in your browser. See \u201cAbout on-device models\u201d for which to pick.`,
        "info",
      );
      dom.modelStatus.textContent = "On-device model: ready to load (experimental)";
      dom.progress.hidden = true;
      break;
    }
    case "loading":
      setBanner(
        `Downloading ${modelLabel(currentModel())} (${currentModel().download}) \u2014 one-time, cached for next time, fully on-device.`,
        "info",
      );
      dom.modelStatus.textContent = "Loading model\u2026";
      dom.progress.hidden = false;
      break;
    case "loaded":
      setBanner(
        `Live (experimental): ${modelLabel(currentModel())} loaded \u2014 runs fully in your browser, nothing leaves your machine.`,
        "ok",
      );
      dom.modelStatus.textContent = `On-device model: ${modelLabel(currentModel())} \u2713 (experimental)`;
      dom.progress.hidden = true;
      break;
    case "load_error":
      // WebGPU works; the download/cache just failed. Stay recoverable — keep the
      // picker and a Retry button rather than dropping to the scripted walkthrough.
      setBanner(
        `Model download failed${state.fallbackReason ? ` (${state.fallbackReason})` : ""} \u2014 check your connection and Retry, or go back to the scripted walkthrough. Nothing left your machine.`,
        "error",
      );
      dom.modelStatus.textContent = "On-device model: download failed \u2014 Retry available";
      dom.progress.hidden = true;
      break;
    default:
      break;
  }
  applyEnablement();
}

function setRunning(on) {
  state.running = on;
  applyEnablement();
}

function onProgress(report) {
  const pct = Math.round((report.progress ?? 0) * 100);
  dom.progressBar.style.width = `${pct}%`;
  dom.progressText.textContent = report.text || `${pct}%`;
}

async function loadModel() {
  if (!(state.mode === "ready" || state.mode === "load_error") || state.running) return;
  setMode("loading");
  try {
    state.model = await createWebLLMModel({ modelId: state.modelId, onProgress });
    setMode("loaded");
  } catch (err) {
    // A failed download is NOT the same as "no WebGPU": stay in an on-device,
    // recoverable state (selector + Retry visible) rather than dropping to
    // scripted mode. Only a missing GPU / ?fallback=1 should go scripted.
    console.error("[deputy] model load failed:", err);
    state.model = null;
    setMode("load_error", { reason: `${err?.message || err}` });
  }
}

function buildModelSelect() {
  for (const model of MODELS) {
    const option = el("option", null, `${modelLabel(model)} \u00b7 ${model.tier} \u00b7 ${model.download}`);
    option.value = model.id;
    if (model.id === state.modelId) option.selected = true;
    dom.modelSelect.appendChild(option);
  }
  dom.modelSelect.addEventListener("change", () => {
    if (state.running) return;
    state.modelId = dom.modelSelect.value;
    // Switching invalidates any already-loaded engine; drop it and let the user
    // load the new choice explicitly rather than swapping mid-session.
    if (state.model) {
      state.model.dispose?.();
      state.model = null;
    }
    setMode("ready");
  });
}

function newRun(goal) {
  const run = { runId: uid("run"), goal, records: [], reason: "", answer: null };
  state.runs.push(run);
  return run;
}

function pushRecord(run, kind, data) {
  run.records.push({ kind, data, ts: nowStamp() });
}

function finishRun(run, { reason, answer }) {
  run.reason = reason;
  run.answer = answer;
  pushRecord(run, "finish", { reason, answer });
}

function makeHandler(run) {
  let thinking = null;
  const clearThinking = () => {
    if (thinking) {
      thinking.remove();
      thinking = null;
    }
  };

  return (ev) => {
    switch (ev.type) {
      case "thinking":
        clearThinking();
        thinking = showThinking(dom.transcript, ev.step);
        break;
      case "action_planned":
        clearThinking();
        if (ev.action.kind === "tool") {
          addToolEntry(dom.transcript, "plan", `Step ${ev.step} \u00b7 plan`, `${ev.action.tool}(${fmtArgs(ev.action.args)})`);
          pushRecord(run, "plan", { tool: ev.action.tool, args: ev.action.args });
        }
        break;
      case "approval_request":
        clearThinking();
        break;
      case "approval_resolved":
        pushRecord(run, "approval", { tool: ev.tool, approved: ev.approved, reason: ev.reason });
        break;
      case "tool_observed":
        addToolEntry(
          dom.transcript,
          ev.ok ? "obs" : "obs error",
          `Step ${ev.step} \u00b7 ${ev.tool} ${ev.ok ? "\u2713" : "\u2717"}`,
          ev.observation,
        );
        pushRecord(run, "observe", { tool: ev.tool, ok: ev.ok, observation: ev.observation });
        break;
      case "action_denied":
        addToolEntry(dom.transcript, "denied", `Step ${ev.step} \u00b7 denied ${ev.tool}`, ev.reason);
        break;
      case "parse_retry":
        addToolEntry(
          dom.transcript,
          "denied",
          `Step ${ev.step} \u00b7 retry`,
          `Model output wasn't a valid action (${ev.detail}); asking again.`,
        );
        break;
      case "repeat":
        addToolEntry(dom.transcript, "denied", `Step ${ev.step} \u00b7 skipped repeat`, ev.detail);
        break;
      case "nudge":
        addToolEntry(dom.transcript, "denied", `Step ${ev.step} \u00b7 not done yet`, ev.detail);
        break;
      case "finalizing":
        clearThinking();
        addToolEntry(
          dom.transcript,
          "denied",
          `Step ${ev.step} \u00b7 wrapping up`,
          "Enough gathered (or no further progress) \u2014 summarizing an answer from what was found.",
        );
        break;
      case "run_finished": {
        clearThinking();
        const answer =
          ev.answer != null
            ? ev.answer
            : "I wasn't able to complete that on-device. Try rephrasing, pick a larger model, or go back to the scripted walkthrough.";
        const body = el("div", "text");
        addEntry(dom.transcript, "final", "Final answer", body);
        revealAnswer(body, answer);
        finishRun(run, { reason: ev.reason, answer });
        break;
      }
      case "error":
        clearThinking();
        addToolEntry(dom.transcript, "denied", "Error", ev.message);
        finishRun(run, { reason: "error", answer: null });
        break;
      default:
        break;
    }
  };
}

async function startRun(goal, runModel) {
  if (state.running) return;
  setRunning(true);
  const run = newRun(goal);
  addEntry(dom.transcript, "user", "You", el("div", "text", goal));
  const onEvent = makeHandler(run);
  const approve = (request) => requestApproval(dom.transcript, request);

  try {
    await runAgent({ goal, model: runModel, registry, approve, onEvent });
  } catch (err) {
    addToolEntry(dom.transcript, "denied", "Error", `${err?.name || "Error"}: ${err?.message || err}`);
    finishRun(run, { reason: "error", answer: null });
  } finally {
    setRunning(false);
    if (dom.auditView.classList.contains("active")) renderAudit(dom.auditBody, state.runs);
  }
}

function runScenario(scenario) {
  if (state.running) return;
  if (state.mode === "fallback") {
    startRun(scenario.goal, scriptedModel(scenario.script));
  } else if (state.mode === "loaded" && state.model) {
    dom.message.value = scenario.goal;
    startRun(scenario.goal, state.model);
  }
}

function buildPresets() {
  for (const scenario of SCENARIOS) {
    const chip = el("button", "chip");
    chip.type = "button";
    chip.append(el("span", "chip-label", scenario.label), el("span", "chip-hint", scenario.hint));
    chip.addEventListener("click", () => runScenario(scenario));
    dom.presets.appendChild(chip);
  }
}

function wireControls() {
  dom.composer.addEventListener("submit", (e) => {
    e.preventDefault();
    if (state.mode !== "loaded" || state.running || !state.model) return;
    const goal = dom.message.value.trim();
    if (!goal) return;
    startRun(goal, state.model);
  });

  dom.message.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      dom.composer.requestSubmit();
    }
  });

  dom.loadBtn.addEventListener("click", loadModel);
  dom.liveBtn.addEventListener("click", enterLive);
  dom.scriptedBtn.addEventListener("click", () => setMode("fallback", { reason: "back" }));
  // Let people reclaim the banner's height; it reappears on the next state change.
  dom.bannerDismiss.addEventListener("click", () => {
    dom.banner.hidden = true;
  });
  dom.auditRefresh.addEventListener("click", () => renderAudit(dom.auditBody, state.runs));
  dom.auditClear.addEventListener("click", () => {
    state.runs = [];
    renderAudit(dom.auditBody, state.runs);
  });

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const view = tab.dataset.view;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === view));
      if (view === "audit") renderAudit(dom.auditBody, state.runs);
    });
  });
}

// Opt into the experimental live path: confirm WebGPU, then land in ready — or
// return to the scripted walkthrough with an honest note if the device can't run
// a model. Reused by ?live=1 and the "Run it for real" button.
async function enterLive() {
  if (state.running) return;
  if (state.model) {
    setMode("loaded"); // a model loaded earlier this session is still resident
    return;
  }
  const support = webgpuSupport();
  if (!support.supported) {
    setMode("fallback", { reason: `live-unavailable: ${support.reason}` });
    return;
  }
  setMode("checking");
  const ok = await probeAdapter();
  if (state.mode !== "checking") return; // user navigated away during the probe
  if (ok) {
    setMode("ready");
  } else {
    setMode("fallback", { reason: "live-unavailable: no usable WebGPU adapter was found on this device." });
  }
}

function init() {
  initTheme(dom.themeToggle);
  buildModelSelect();
  buildPresets();
  wireControls();

  const params = new URLSearchParams(location.search);
  state.forcedFallback = params.get("fallback") === "1";
  const wantLive = params.get("live") === "1";

  // Scripted-primary: a first-time visitor lands on the working walkthrough with
  // no download. Live on-device inference is opt-in via ?live=1 or the button;
  // ?fallback=1 stays an explicit shortcut to scripted and wins over ?live=1.
  if (wantLive && !state.forcedFallback) {
    enterLive();
    return;
  }
  setMode("fallback", { reason: state.forcedFallback ? "forced" : "default" });
}

init();

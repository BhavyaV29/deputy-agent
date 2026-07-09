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
  modelStatus: document.getElementById("model-status"),
  modelSelect: document.getElementById("model-select"),
  loadBtn: document.getElementById("load-btn"),
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
  dom.banner.textContent = text;
  dom.banner.className = `banner ${kind}`;
}

function chipsEnabled(on) {
  dom.presets.querySelectorAll(".chip").forEach((chip) => {
    chip.disabled = !on;
  });
}

function applyEnablement() {
  const idle = !state.running;
  const loaded = state.mode === "loaded";
  const fallback = state.mode === "fallback";
  const ready = state.mode === "ready";
  const loading = state.mode === "loading";
  const loadError = state.mode === "load_error";
  // WebGPU is available in all of these — the model picker stays visible.
  const gpuMode = ready || loading || loaded || loadError;
  // A (re)load can be started from a fresh "ready" or a recoverable failure.
  const canLoad = ready || loadError;

  dom.message.disabled = !(loaded && idle);
  dom.send.disabled = !(loaded && idle);
  dom.message.placeholder = loaded
    ? "Ask Deputy to do something\u2026"
    : fallback
      ? "Free-text chat needs the on-device model \u2014 pick a scripted demo above."
      : "Load the on-device model to chat, or try a scripted demo.";

  chipsEnabled((loaded || fallback) && idle);

  dom.modelSelect.hidden = !gpuMode;
  dom.modelSelect.disabled = !(idle && (ready || loaded || loadError));

  dom.loadBtn.hidden = !(canLoad || loading);
  dom.loadBtn.disabled = !(canLoad && idle);
  dom.loadBtn.textContent = loadError ? "Retry download" : "Load on-device model";

  // Offer the scripted escape hatch both before loading and after a failed load.
  dom.scriptedBtn.hidden = !(ready || loadError);
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
    case "fallback":
      setBanner(
        `Fallback mode \u2014 ${state.fallbackReason} This is a scripted playback of the same demo: no model is downloaded and nothing runs on the GPU. Pick a demo below.`,
        "warn",
      );
      dom.modelStatus.textContent = "On-device model: not loaded (scripted demo)";
      dom.progress.hidden = true;
      break;
    case "ready": {
      const model = currentModel();
      setBanner(
        `WebGPU is available. Pick a model and load it for real on-device inference: a one-time ${model.download} download (${model.note}), then it runs fully in your browser \u2014 or try a scripted demo with no download.`,
        "info",
      );
      dom.modelStatus.textContent = "On-device model: ready to load";
      dom.progress.hidden = true;
      break;
    }
    case "loading":
      setBanner(
        `Downloading and compiling ${modelLabel(currentModel())} (${currentModel().download}). This happens once and is cached for next time \u2014 nothing leaves your machine.`,
        "info",
      );
      dom.modelStatus.textContent = "Loading model\u2026";
      dom.progress.hidden = false;
      break;
    case "loaded":
      setBanner(
        `Loaded ${modelLabel(currentModel())} on-device. Everything below runs locally in your browser \u2014 nothing leaves your machine.`,
        "ok",
      );
      dom.modelStatus.textContent = `On-device model: ${modelLabel(currentModel())} \u2713`;
      dom.progress.hidden = true;
      break;
    case "load_error":
      // WebGPU works; the download/cache just failed. Stay recoverable — keep the
      // picker and a Retry button rather than dropping to the scripted demo.
      setBanner(
        `Model download failed${state.fallbackReason ? ` (${state.fallbackReason})` : ""} \u2014 check your connection and Retry, or pick the smaller, faster 0.5B model. Nothing was sent anywhere; you're still fully on-device.`,
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
        const answer = ev.answer != null ? ev.answer : "I wasn't able to complete that on-device. Try rephrasing, or run the scripted demo with ?fallback=1.";
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
  dom.scriptedBtn.addEventListener("click", () => setMode("fallback", { reason: "you chose the scripted demo." }));
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

function init() {
  initTheme(dom.themeToggle);
  buildModelSelect();
  buildPresets();
  wireControls();

  const params = new URLSearchParams(location.search);
  state.forcedFallback = params.get("fallback") === "1";

  setMode("checking");

  if (state.forcedFallback) {
    setMode("fallback", { reason: "forced with ?fallback=1." });
    return;
  }

  const support = webgpuSupport();
  if (!support.supported) {
    setMode("fallback", { reason: support.reason });
    return;
  }

  setMode("ready");
  probeAdapter().then((ok) => {
    if (!ok && state.mode === "ready") {
      setMode("fallback", { reason: "no usable WebGPU adapter was found on this device." });
    }
  });
}

init();

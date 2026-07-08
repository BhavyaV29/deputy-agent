// Wiring: detect WebGPU, manage on-device model loading, and route each run to
// either the real WebLLM model or the scripted fallback — both driving the same
// agent loop. Also owns the little session audit that the Audit tab renders.

import { createRegistry } from "./tools.js";
import { runAgent } from "./agent.js";
import { SCENARIOS, scriptedModel } from "./scenarios.js";
import { webgpuSupport, probeAdapter, createWebLLMModel, MODEL } from "./llm.js";
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

const registry = createRegistry();

const dom = {
  banner: document.getElementById("banner"),
  modelStatus: document.getElementById("model-status"),
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
};

const state = {
  mode: "checking", // checking | fallback | ready | loading | loaded
  model: null,
  running: false,
  forcedFallback: false,
  fallbackReason: "",
  runs: [],
};

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

  dom.message.disabled = !(loaded && idle);
  dom.send.disabled = !(loaded && idle);
  dom.message.placeholder = loaded
    ? "Ask Deputy to do something\u2026"
    : fallback
      ? "Free-text chat needs the on-device model \u2014 pick a scripted demo above."
      : "Load the on-device model to chat, or try a scripted demo.";

  chipsEnabled((loaded || fallback) && idle);

  dom.loadBtn.hidden = !(state.mode === "ready" || state.mode === "loading");
  dom.loadBtn.disabled = !(state.mode === "ready" && idle);
  dom.scriptedBtn.hidden = state.mode !== "ready";
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
    case "ready":
      setBanner(
        `WebGPU is available. Load ${MODEL.label} (${MODEL.download}) for real on-device inference \u2014 or try a scripted demo with no download.`,
        "info",
      );
      dom.modelStatus.textContent = "On-device model: ready to load";
      dom.progress.hidden = true;
      break;
    case "loading":
      setBanner(
        "Downloading and compiling the model. This happens once and is cached for next time \u2014 nothing leaves your machine.",
        "info",
      );
      dom.modelStatus.textContent = "Loading model\u2026";
      dom.progress.hidden = false;
      break;
    case "loaded":
      setBanner(
        `Loaded ${MODEL.label} on-device. Everything below runs locally in your browser \u2014 nothing leaves your machine.`,
        "ok",
      );
      dom.modelStatus.textContent = `On-device model: ${MODEL.label} \u2713`;
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
  if (state.mode !== "ready" || state.running) return;
  setMode("loading");
  try {
    state.model = await createWebLLMModel({ onProgress });
    setMode("loaded");
  } catch (err) {
    console.error("Model load failed:", err);
    state.model = null;
    setMode("fallback", { reason: `the model failed to load (${err?.message || err}).` });
  }
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
      case "run_finished":
        clearThinking();
        if (ev.answer != null) {
          const body = el("div", "text");
          addEntry(dom.transcript, "final", "Final answer", body);
          revealAnswer(body, ev.answer);
        } else {
          addEntry(dom.transcript, "final", `Stopped \u00b7 ${ev.reason}`, el("div", "text", `No answer within ${ev.step} steps.`));
        }
        finishRun(run, { reason: ev.reason, answer: ev.answer });
        break;
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

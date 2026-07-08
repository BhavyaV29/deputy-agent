"use strict";

const transcript = document.getElementById("transcript");
const composer = document.getElementById("composer");
const messageBox = document.getElementById("message");
const sendBtn = document.getElementById("send");
const auditBody = document.getElementById("audit-body");

let source = null;
let runId = null;
let running = false;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function code(text) {
  return el("pre", "code", text);
}

function fmtArgs(args) {
  const keys = Object.keys(args || {});
  return keys.map((k) => `${k}=${JSON.stringify(args[k])}`).join(", ");
}

function scrollDown() {
  transcript.scrollTop = transcript.scrollHeight;
}

function addEntry(kind, label, body) {
  const entry = el("div", `entry ${kind}`);
  entry.appendChild(el("div", "label", label));
  if (body) entry.appendChild(body);
  transcript.appendChild(entry);
  scrollDown();
  return entry;
}

function setRunning(on) {
  running = on;
  sendBtn.disabled = on;
  messageBox.disabled = on;
}

function finalize() {
  if (source) {
    source.close();
    source = null;
  }
  setRunning(false);
}

function addApproval(msg) {
  const entry = el("div", "entry approval");
  entry.appendChild(el("div", "label", "Approval needed"));
  entry.appendChild(code(`${msg.tool}(${fmtArgs(msg.args)})`));
  if (msg.description) entry.appendChild(el("div", "desc", msg.description));

  const actions = el("div", "actions");
  const approve = el("button", "btn primary", "Approve");
  const deny = el("button", "btn", "Deny");
  actions.appendChild(approve);
  actions.appendChild(deny);
  entry.appendChild(actions);
  transcript.appendChild(entry);
  scrollDown();

  const decide = async (approved) => {
    approve.disabled = true;
    deny.disabled = true;
    actions.replaceChildren(el("span", "decision", approved ? "Approved" : "Denied"));
    try {
      await fetch(`/approvals/${runId}/${msg.approval_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      });
    } catch (err) {
      /* the stream reports the eventual outcome either way */
    }
  };
  approve.onclick = () => decide(true);
  deny.onclick = () => decide(false);
}

function handle(msg) {
  switch (msg.type) {
    case "action_planned":
      if (msg.action.kind === "tool") {
        addEntry("plan", `Step ${msg.step} · plan`, code(`${msg.action.tool}(${fmtArgs(msg.action.args)})`));
      }
      break;
    case "approval_request":
      addApproval(msg);
      break;
    case "tool_observed":
      addEntry(
        msg.ok ? "obs" : "obs error",
        `Step ${msg.step} · ${msg.tool} ${msg.ok ? "✓" : "✗"}`,
        code(msg.observation),
      );
      break;
    case "action_denied":
      addEntry("denied", `Step ${msg.step} · denied ${msg.tool}`, code(msg.reason));
      break;
    case "answer_rejected":
      addEntry("rejected", `Step ${msg.step} · self-check rejected`, code(msg.feedback));
      break;
    case "run_finished":
      if (msg.answer !== null && msg.answer !== undefined) {
        addEntry("final", "Final answer", el("div", "text", msg.answer));
      } else {
        addEntry("final", `Stopped · ${msg.reason}`, el("div", "text", `No answer within ${msg.step} steps.`));
      }
      finalize();
      break;
    case "error":
      addEntry("denied", "Error", code(msg.message));
      finalize();
      break;
    default:
      break;
  }
}

async function start(goal) {
  setRunning(true);
  addEntry("user", "You", el("div", "text", goal));
  let data;
  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: goal }),
    });
    if (!res.ok) throw new Error(`chat failed: ${res.status}`);
    data = await res.json();
  } catch (err) {
    addEntry("denied", "Error", code(String(err)));
    setRunning(false);
    return;
  }
  runId = data.run_id;
  source = new EventSource(`/events/${runId}`);
  source.onmessage = (e) => handle(JSON.parse(e.data));
  source.onerror = () => {
    if (running) finalize();
  };
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const goal = messageBox.value.trim();
  if (!goal || running) return;
  messageBox.value = "";
  start(goal);
});

messageBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    composer.requestSubmit();
  }
});

function summarizeRecord(r) {
  const d = r.data || {};
  switch (r.kind) {
    case "action_planned": {
      const a = d.action || {};
      return a.final !== undefined ? `final: ${a.final}` : `${a.tool}(${fmtArgs(a.args)})`;
    }
    case "tool_observed":
      return `${d.tool} → ${d.ok ? "ok" : "error"}: ${d.observation ?? ""}`;
    case "action_denied":
      return `${d.tool}: ${d.reason ?? ""}`;
    case "approval":
      return `${d.tool} ${d.approved ? "approved" : "denied"} — ${d.reason ?? ""}`;
    case "answer_rejected":
      return d.feedback ?? "";
    case "run_finished":
      return `${d.reason ?? ""}${d.answer ? `: ${d.answer}` : ""}`;
    case "routing":
      return `${d.provider}/${d.model} — ${d.reason ?? ""}`;
    default:
      return "";
  }
}

function renderAudit(data) {
  auditBody.replaceChildren();
  if (!data.runs.length) {
    auditBody.appendChild(el("p", "muted", "No runs recorded yet."));
    return;
  }
  for (const run of data.runs) {
    const card = el("div", "run-card");
    const head = el("div", "run-head");
    head.appendChild(el("span", "run-id", run.run_id));
    head.appendChild(el("span", "run-meta", `${run.events} events · ${run.reason || "in progress"}`));
    card.appendChild(head);
    if (run.answer) card.appendChild(el("div", "run-answer", run.answer));
    card.appendChild(el("div", "run-time", `${run.started} → ${run.ended}`));
    auditBody.appendChild(card);
  }
  const records = el("div", "records");
  records.appendChild(el("h3", null, "Recent activity"));
  for (const r of data.records) {
    const row = el("div", "record");
    row.appendChild(el("span", "rec-kind", r.kind));
    row.appendChild(el("span", "rec-run", r.run_id));
    row.appendChild(el("span", "rec-detail", summarizeRecord(r)));
    row.appendChild(el("span", "rec-ts", r.ts));
    records.appendChild(row);
  }
  auditBody.appendChild(records);
}

async function loadAudit() {
  auditBody.replaceChildren(el("p", "muted", "Loading…"));
  try {
    const res = await fetch("/api/audit");
    renderAudit(await res.json());
  } catch (err) {
    auditBody.replaceChildren(el("p", "muted", "Could not load the audit log."));
  }
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    const view = tab.dataset.view;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === view));
    if (view === "audit") loadAudit();
  });
});

document.getElementById("refresh").addEventListener("click", loadAudit);

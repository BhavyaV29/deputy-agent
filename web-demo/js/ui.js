// DOM rendering for the transcript, the interactive approval prompt, and the
// audit view. Kept deliberately close to Deputy's local web UI (same entry
// kinds and class names) so the browser demo reads as the same product.

import { sleep } from "./util.js";

export function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function code(text) {
  return el("pre", "code", text);
}

export function fmtArgs(args) {
  return Object.keys(args || {})
    .map((k) => `${k}=${JSON.stringify(args[k])}`)
    .join(", ");
}

export function clear(node) {
  node.replaceChildren();
}

export function addEntry(transcript, kind, label, body) {
  const entry = el("div", `entry ${kind}`);
  entry.appendChild(el("div", "label", label));
  if (body) entry.appendChild(body);
  transcript.appendChild(entry);
  transcript.scrollTop = transcript.scrollHeight;
  return entry;
}

export function addToolEntry(transcript, kind, label, argsOrText) {
  return addEntry(transcript, kind, label, code(argsOrText));
}

export function showThinking(transcript, step) {
  const entry = el("div", "entry thinking");
  entry.appendChild(el("div", "label", `Step ${step}`));
  const dots = el("div", "think");
  dots.append(el("span", "dot"), el("span", "dot"), el("span", "dot"));
  const wrap = el("div", "think-row");
  wrap.append(dots, el("span", "think-text", "Deputy is thinking\u2026"));
  entry.appendChild(wrap);
  transcript.appendChild(entry);
  transcript.scrollTop = transcript.scrollHeight;
  return entry;
}

// Renders the approval widget and resolves true/false when the operator decides.
export function requestApproval(transcript, request) {
  return new Promise((resolve) => {
    const entry = el("div", "entry approval");
    entry.appendChild(el("div", "label", "Approval needed"));
    entry.appendChild(code(`${request.tool}(${fmtArgs(request.args)})`));
    if (request.description) entry.appendChild(el("div", "desc", request.description));

    const actions = el("div", "actions");
    const approve = el("button", "btn primary", "Approve");
    const deny = el("button", "btn", "Deny");
    actions.append(approve, deny);
    entry.appendChild(actions);
    transcript.appendChild(entry);
    transcript.scrollTop = transcript.scrollHeight;

    const decide = (approved) => {
      approve.disabled = true;
      deny.disabled = true;
      actions.replaceChildren(el("span", "decision", approved ? "Approved" : "Denied"));
      resolve(approved);
    };
    approve.onclick = () => decide(true);
    deny.onclick = () => decide(false);
  });
}

export async function revealAnswer(node, text) {
  // Word-by-word reveal so a long answer streams in without feeling sluggish.
  const words = text.split(/(\s+)/);
  node.textContent = "";
  for (const word of words) {
    node.textContent += word;
    if (word.trim()) await sleep(18);
  }
}

function summarize(record) {
  const d = record.data || {};
  switch (record.kind) {
    case "plan":
      return d.final !== undefined ? `final answer` : `${d.tool}(${fmtArgs(d.args)})`;
    case "observe":
      return `${d.tool} \u2192 ${d.ok ? "ok" : "error"}: ${d.observation ?? ""}`;
    case "approval":
      return `${d.tool} ${d.approved ? "approved" : "denied"} \u2014 ${d.reason ?? ""}`;
    case "finish":
      return `${d.reason ?? ""}${d.answer ? `: ${d.answer}` : ""}`;
    default:
      return "";
  }
}

export function renderAudit(auditBody, runs) {
  clear(auditBody);
  if (!runs.length) {
    auditBody.appendChild(el("p", "muted", "No actions recorded yet. Run a demo to populate the log."));
    return;
  }

  for (const run of [...runs].reverse()) {
    const card = el("div", "run-card");
    const head = el("div", "run-head");
    head.appendChild(el("span", "run-id", run.runId));
    head.appendChild(el("span", "run-meta", `${run.records.length} events \u00b7 ${run.reason || "in progress"}`));
    card.appendChild(head);
    card.appendChild(el("div", "run-goal", run.goal));
    if (run.answer) card.appendChild(el("div", "run-answer", run.answer));

    const records = el("div", "records");
    for (const record of run.records) {
      const row = el("div", "record");
      row.appendChild(el("span", "rec-kind", record.kind));
      row.appendChild(el("span", "rec-detail", summarize(record)));
      row.appendChild(el("span", "rec-ts", record.ts));
      records.appendChild(row);
    }
    card.appendChild(records);
    auditBody.appendChild(card);
  }
}

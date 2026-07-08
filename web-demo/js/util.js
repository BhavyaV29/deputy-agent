export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function uid(prefix = "run") {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

export function nowStamp() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export class TimeoutError extends Error {
  constructor(message) {
    super(message);
    this.name = "TimeoutError";
  }
}

// Runs `run(signal)` but never waits longer than `ms`. On expiry it aborts the
// signal (so a cooperating callee can stop its own work) and rejects the race,
// so callers recover even if the callee ignores the abort and hangs forever.
export function withDeadline(ms, run) {
  const controller = new AbortController();
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      const err = new TimeoutError(`timed out after ${Math.round(ms / 1000)}s`);
      controller.abort(err);
      reject(err);
    }, ms);
  });
  const task = Promise.resolve().then(() => run(controller.signal));
  task.catch(() => {});
  return Promise.race([task, timeout]).finally(() => clearTimeout(timer));
}

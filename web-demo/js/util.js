export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function uid(prefix = "run") {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

export function nowStamp() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

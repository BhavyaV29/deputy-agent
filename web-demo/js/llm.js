// WebGPU detection and the on-device model wrapper. WebLLM is imported lazily
// from an ESM CDN only when the user chooses to load the model, so the fallback
// path never touches the network. The model satisfies the same `act(messages)`
// seam the loop expects, returning a single JSON action per turn.

// Pinned for reproducibility; drop the @version to always fetch the latest.
const WEBLLM_URL = "https://esm.run/@mlc-ai/web-llm@0.2.84";

const MAX_TOKENS = 512;

// Qwen2.5 instruct family from WebLLM's prebuilt list (all low-resource, q4f16_1).
// 0.5B is too weak for reliable JSON tool use, so the demo defaults to 1.5B —
// the smallest that completes the preset tasks — with 3B for the most capable.
export const MODELS = [
  {
    id: "Qwen2.5-0.5B-Instruct-q4f16_1-MLC",
    size: "0.5B",
    tier: "fastest",
    download: "~350 MB",
    note: "fastest download, but often loops on tool use",
  },
  {
    id: "Qwen2.5-1.5B-Instruct-q4f16_1-MLC",
    size: "1.5B",
    tier: "recommended",
    download: "~1 GB",
    note: "best balance of size and reliability",
  },
  {
    id: "Qwen2.5-3B-Instruct-q4f16_1-MLC",
    size: "3B",
    tier: "most capable",
    download: "~2 GB",
    note: "most reliable, largest download",
  },
];

export function modelLabel(model) {
  return `Qwen2.5-${model.size}-Instruct`;
}

export const DEFAULT_MODEL_ID = "Qwen2.5-1.5B-Instruct-q4f16_1-MLC";

export function modelById(id) {
  return MODELS.find((model) => model.id === id) || MODELS.find((model) => model.id === DEFAULT_MODEL_ID);
}

export function webgpuSupport() {
  if (typeof navigator === "undefined" || !("gpu" in navigator) || !navigator.gpu) {
    return { supported: false, reason: "This browser doesn't expose the WebGPU API (navigator.gpu)." };
  }
  return { supported: true, reason: "WebGPU API detected." };
}

// A present `navigator.gpu` doesn't guarantee a usable adapter (headless,
// blocklisted GPU, disabled flag), so confirm one can actually be acquired.
export async function probeAdapter() {
  try {
    const adapter = await navigator.gpu.requestAdapter();
    return Boolean(adapter);
  } catch {
    return false;
  }
}

export async function createWebLLMModel({ modelId = DEFAULT_MODEL_ID, onProgress } = {}) {
  const webllm = await import(/* @vite-ignore */ WEBLLM_URL);
  const engine = await webllm.CreateMLCEngine(modelId, { initProgressCallback: onProgress });
  return {
    kind: "webllm",
    engine,
    // Plain streamed generation, not grammar-constrained JSON mode: the
    // `response_format: json_object` grammar path stalls indefinitely on this
    // 0.5B model, so we prompt for JSON and parse tolerantly instead. Streaming
    // lets an external abort (a deadline) interrupt a stuck decode mid-flight.
    async act(messages, { signal } = {}) {
      if (signal?.aborted) throw abortReason(signal);
      console.debug("[deputy] inference start", { turns: messages.length });

      const stream = await engine.chat.completions.create({
        messages,
        temperature: 0,
        max_tokens: MAX_TOKENS,
        stream: true,
      });

      const stop = () => {
        try {
          engine.interruptGenerate();
        } catch {
          /* best effort */
        }
      };
      signal?.addEventListener("abort", stop, { once: true });

      let content = "";
      try {
        for await (const chunk of stream) {
          content += chunk.choices?.[0]?.delta?.content ?? "";
          if (signal?.aborted) break;
        }
      } finally {
        signal?.removeEventListener("abort", stop);
      }

      if (signal?.aborted) throw abortReason(signal);
      console.debug("[deputy] inference done", { chars: content.length });
      return content;
    },
    async dispose() {
      try {
        await engine.unload?.();
      } catch {
        /* best effort */
      }
    },
  };
}

function abortReason(signal) {
  const reason = signal?.reason;
  return reason instanceof Error ? reason : new Error("inference aborted");
}

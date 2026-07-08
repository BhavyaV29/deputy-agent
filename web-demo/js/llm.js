// WebGPU detection and the on-device model wrapper. WebLLM is imported lazily
// from an ESM CDN only when the user chooses to load the model, so the fallback
// path never touches the network. The model satisfies the same `act(messages)`
// seam the loop expects, returning a single JSON action per turn.

// Pinned for reproducibility; drop the @version to always fetch the latest.
const WEBLLM_URL = "https://esm.run/@mlc-ai/web-llm@0.2.84";

// Smallest genuinely useful instruct model in WebLLM's prebuilt list.
export const MODEL = {
  id: "Qwen2.5-0.5B-Instruct-q4f16_1-MLC",
  label: "Qwen2.5-0.5B-Instruct (q4f16_1)",
  download: "~300 MB of weights, downloaded once and cached by the browser",
  vram: "~0.95 GB of GPU memory at runtime",
};

// A slightly stronger 1B alternative — bigger download, still low-resource.
export const ALT_MODEL = {
  id: "Llama-3.2-1B-Instruct-q4f16_1-MLC",
  label: "Llama-3.2-1B-Instruct (q4f16_1)",
  download: "~880 MB of weights",
  vram: "~1.1 GB of GPU memory at runtime",
};

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

export async function createWebLLMModel({ modelId = MODEL.id, onProgress } = {}) {
  const webllm = await import(/* @vite-ignore */ WEBLLM_URL);
  const engine = await webllm.CreateMLCEngine(modelId, { initProgressCallback: onProgress });
  return {
    kind: "webllm",
    engine,
    async act(messages) {
      const response = await engine.chat.completions.create({
        messages,
        temperature: 0,
        max_tokens: 512,
        response_format: { type: "json_object" },
      });
      return response.choices?.[0]?.message?.content ?? "";
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

# Deputy

A private, on-device AI agent that works your own files and runs tasks — and asks before it acts.

Deputy runs a small local model (via [Ollama](https://ollama.com)) in a bounded agent loop, calls tools through MCP, retrieves from your own data on-device, and logs every action behind approval gates before anything is written. Nothing leaves your machine unless you opt in.

Status: early development.

# Deputy

A private, on-device assistant. It runs a small local model through a bounded
ReAct loop and reaches its tools over MCP, so the same loop can drive real
servers without knowing anything about them.

## Retrieval

Documents are chunked and embedded with nomic-embed-text, then stored in
sqlite-vec. The `search_docs` tool returns the closest passages together with
their source file paths, so an answer can always be traced back to where it
came from. When the embedder is offline a keyword search stands in.

## Safety

The files server is confined to one workspace root: any path that resolves
outside it — through `..`, an absolute path, or a symlink — is rejected rather
than served. Tools that write, like `add_note`, are tagged as mutating so a
later phase can require approval before they run.

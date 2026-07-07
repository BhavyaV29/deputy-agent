"""Built-in MCP servers Deputy ships with.

Each module is a self-contained stdio MCP server, launched as a subprocess by the
host. The tool logic lives in plain functions that take their roots as arguments,
so it can be unit-tested directly; the MCP wiring is a thin shell that reads the
configured location from the environment and calls in.
"""

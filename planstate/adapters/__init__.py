"""planstate.adapters — knowledge base adapters.

Each adapter reads/writes domain context from a different storage backend.
The adapter interface: load(domain) -> dict, save(domain, ctx) -> path.
"""

"""planstate.adapters.yaml_adapter — config YAML adapter.

The simplest KB adapter: reads/writes domain context as YAML files
in the PLANSTATE_CONTEXT_DIR.  This is the default for users who
don't use Obsidian or any other knowledge base.
"""

from planstate.context import load_context, save_context, list_contexts


class YamlAdapter:
    """Direct pass-through to planstate.context YAML files."""

    def load(self, domain):
        return load_context(domain)

    def save(self, ctx):
        return save_context(ctx)

    def list_domains(self):
        return list_contexts()

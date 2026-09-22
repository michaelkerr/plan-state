"""planstate.adapters.obsidian — Obsidian vault adapter.

Reads domain context from Obsidian notes with structured frontmatter.
Writes updates back as frontmatter changes.  Requires the vault path
to be set via PLANSTATE_OBSIDIAN_VAULT.

Expected note structure:
  ~/vault/domains/garden.md with YAML frontmatter containing the
  domain context schema fields.
"""

import os
import yaml

from planstate.context import validate_context


VAULT_PATH = os.environ.get("PLANSTATE_OBSIDIAN_VAULT", "")


class ObsidianAdapter:
    def __init__(self, vault_path=None):
        self.vault_path = vault_path or VAULT_PATH
        if not self.vault_path:
            raise ValueError("PLANSTATE_OBSIDIAN_VAULT not set")

    def load(self, domain):
        path = self._note_path(domain)
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"No Obsidian note for domain '{domain}' at {path}"
            )
        frontmatter, _body = _parse_frontmatter(path)
        if not frontmatter:
            raise ValueError(f"No frontmatter in {path}")

        ctx = frontmatter
        if "domain" not in ctx:
            ctx["domain"] = domain

        errors = validate_context(ctx)
        if errors:
            raise ValueError(
                f"Invalid context in {path}: " + "; ".join(errors)
            )
        return ctx

    def save(self, ctx):
        domain = ctx["domain"]
        path = self._note_path(domain)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # Preserve body content if the note already exists
        body = ""
        if os.path.isfile(path):
            _fm, body = _parse_frontmatter(path)

        from datetime import datetime
        ctx["updated_at"] = datetime.now().isoformat(timespec="seconds")

        content = "---\n"
        content += yaml.dump(ctx, default_flow_style=False, sort_keys=False)
        content += "---\n"
        if body:
            content += body

        with open(path, "w") as f:
            f.write(content)
        return path

    def list_domains(self):
        domains_dir = os.path.join(self.vault_path, "domains")
        if not os.path.isdir(domains_dir):
            return []
        results = []
        for entry in sorted(os.listdir(domains_dir)):
            if entry.endswith(".md"):
                domain = entry[:-3]
                try:
                    ctx = self.load(domain)
                    results.append({
                        "domain": ctx.get("domain", domain),
                        "display_name": ctx.get("display_name", domain),
                        "entity_count": len(ctx.get("entities", [])),
                    })
                except Exception:
                    pass
        return results

    def _note_path(self, domain):
        return os.path.join(self.vault_path, "domains", f"{domain}.md")


def _parse_frontmatter(path):
    with open(path) as f:
        content = f.read()

    if not content.startswith("---"):
        return None, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, content

    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None, content

    body = parts[2].lstrip("\n")
    return frontmatter, body

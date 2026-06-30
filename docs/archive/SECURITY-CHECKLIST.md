# Security Checklist

Verify all items before going live.

- [ ] Image tag pinned in .env (HERMES_VERSION, not :latest)
- [ ] Gateway port 8642 bound to 127.0.0.1 only
- [ ] Dashboard port 9119 bound to Tailscale IP only (DASHBOARD_BIND)
- [ ] .env has chmod 600
- [ ] GATEWAY_ALLOW_ALL_USERS is NOT set in .env
- [ ] Explicit user allowlists per platform (TELEGRAM_ALLOWED_USERS, etc.)
- [ ] GATEWAY_AUTH_TOKEN rotated (openssl rand -hex 32)
- [ ] Dashboard basic auth credentials set (not defaults)
- [ ] terminal.backend: docker in config.yaml
- [ ] docker_forward_env: [] in config.yaml (no secrets leak into sandbox)
- [ ] approvals.mode: manual in config.yaml (not "off")
- [ ] tool_loop_guardrails.hard_stop_enabled: true
- [ ] UFW active, deny incoming except SSH (no 80/443 needed)
- [ ] Tailscale ACLs restrict who can reach the server
- [ ] Container runs as non-root (default UID 10000)
- [ ] no-new-privileges security option set
- [ ] cap_drop: ALL with selective cap_add
- [ ] Backup procedure tested

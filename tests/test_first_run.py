"""First-run experience: doctor guidance, built-in scheduler, auto-init."""

import os
import threading

import pytest


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """A clean machine: no DB yet, no config in the environment."""
    db_path = str(tmp_path / "home" / "dispatch.db")
    monkeypatch.setenv("DISPATCH_DB", db_path)
    for var in ("OWM_API_KEY", "DISPATCH_LOCATION", "DISPATCH_PATHS_DIR",
                "DISPATCH_USER_PATHS_DIR", "DISPATCH_EVAL_MINUTES"):
        monkeypatch.delenv(var, raising=False)
    return db_path


class TestDoctor:
    def test_missing_db_says_run_init(self, fresh):
        from dispatch.doctor import run_doctor
        out = run_doctor()
        assert "✗ DB exists" in out
        assert "run `dispatch init`" in out
        assert "OWM_API_KEY: Not set" in out

    def test_fresh_db_lists_next_steps(self, fresh):
        from dispatch.doctor import run_doctor
        from dispatch.store import init_db
        init_db()
        out = run_doctor()
        assert "0 fail" in out
        assert "home.openweathermap.org" in out
        assert "DISPATCH_LOCATION: Not set" in out
        assert "3 built-in, 0 custom" in out
        assert "`dispatch instantiate`" in out
        assert "No eval has run yet" in out

    def test_configured(self, fresh, monkeypatch):
        from dispatch.doctor import run_doctor
        from dispatch.store import init_db
        init_db()
        monkeypatch.setenv("OWM_API_KEY", "x" * 32)
        monkeypatch.setenv("DISPATCH_LOCATION", "Nashville,TN,US")
        out = run_doctor()
        assert "✓ OWM_API_KEY" in out
        assert "✓ DISPATCH_LOCATION: Nashville,TN,US" in out


class TestEvalLoop:
    def test_minutes_parsing(self, fresh, monkeypatch):
        from dispatch.server import eval_minutes
        assert eval_minutes() == 0
        monkeypatch.setenv("DISPATCH_EVAL_MINUTES", "60")
        assert eval_minutes() == 60
        assert eval_minutes(15) == 15
        monkeypatch.setenv("DISPATCH_EVAL_MINUTES", "hourly")
        assert eval_minutes() == 0

    def test_disabled_without_minutes_or_location(self, fresh, monkeypatch):
        from dispatch.server import start_eval_loop
        assert start_eval_loop(0) is None
        assert start_eval_loop(60) is None

    def test_runs_eval_in_background(self, fresh, monkeypatch):
        import dispatch.eval
        from dispatch.server import start_eval_loop
        monkeypatch.setenv("DISPATCH_LOCATION", "Nashville,TN,US")
        ran = threading.Event()
        seen = []

        def fake_run_eval(location):
            seen.append(location)
            ran.set()
        monkeypatch.setattr(dispatch.eval, "run_eval", fake_run_eval)

        thread = start_eval_loop(60)
        assert thread is not None and thread.daemon
        assert ran.wait(5)
        assert seen == ["Nashville,TN,US"]


class TestAutoInit:
    def test_stdio_creates_db(self, fresh, monkeypatch):
        import asyncio
        import contextlib
        import dispatch.server as server

        @contextlib.asynccontextmanager
        async def fake_stdio():
            yield (None, None)

        async def fake_run(read, write, options):
            return None

        import mcp.server.stdio
        monkeypatch.setattr(mcp.server.stdio, "stdio_server", fake_stdio)
        monkeypatch.setattr(server.app, "run", fake_run)
        asyncio.run(server.run_stdio())
        assert os.path.exists(fresh)

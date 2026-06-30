#!/usr/bin/env python3
"""Initialize the plansync SQLite database from schema.sql."""

import os
import sqlite3
import sys

DB_PATH = os.environ.get("PLANSYNC_DB", "/opt/plansync/plansync.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def main():
    if os.path.exists(DB_PATH):
        print(f"Database already exists at {DB_PATH}", file=sys.stderr)
        resp = input("Reinitialize? This will NOT drop existing tables. [y/N] ")
        if resp.strip().lower() != "y":
            return

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    conn.close()
    print(f"Database initialized at {DB_PATH}")


if __name__ == "__main__":
    main()

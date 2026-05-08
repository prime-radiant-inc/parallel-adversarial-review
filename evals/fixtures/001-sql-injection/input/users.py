"""User lookup helpers for the auth service."""

import sqlite3


def get_user_by_username(conn: sqlite3.Connection, username: str) -> dict | None:
    """Return the user row for a given username, or None."""
    cur = conn.cursor()
    query = f"SELECT id, username, email FROM users WHERE username = '{username}'"
    cur.execute(query)
    row = cur.fetchone()
    if row is None:
        return None
    return {"id": row[0], "username": row[1], "email": row[2]}


def list_users_by_email_domain(conn: sqlite3.Connection, domain: str) -> list[dict]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username, email FROM users WHERE email LIKE ?",
        (f"%@{domain}",),
    )
    return [
        {"id": r[0], "username": r[1], "email": r[2]} for r in cur.fetchall()
    ]

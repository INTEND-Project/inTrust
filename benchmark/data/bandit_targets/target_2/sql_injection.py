"""Frozen benchmark input — SQL built by string interpolation (Bandit: B608)."""

import sqlite3


def find_user(username: str):
    conn = sqlite3.connect("users.db")
    # Query constructed with string formatting instead of parameters.
    query = "SELECT * FROM users WHERE name = '%s'" % username
    return conn.execute(query).fetchall()


def delete_user(user_id: str):
    conn = sqlite3.connect("users.db")
    conn.execute("DELETE FROM users WHERE id = " + user_id)
    conn.commit()

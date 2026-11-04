"""Bounded in-memory SQL runner for the synthetic-data prototype.

SQLite authorizer enforces an allowlist at query compilation; a VM progress
handler bounds work. This is defense in depth, not a production OS sandbox.
"""

import sqlite3
import time


class QueryRejected(ValueError):
    pass


class QueryRunner:
    FUNCTIONS = {"count", "sum", "min", "max", "avg", "coalesce", "ifnull", "nullif", "abs", "round"}

    def __init__(self, snapshot, *, timeout=3.0, max_steps=20000000, max_rows=100):
        from .inputs import validate_snapshot
        snapshot = validate_snapshot(snapshot)
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute("CREATE TABLE orders (order_id INTEGER, customer_id INTEGER, "
                                "order_date TEXT, status TEXT, kind TEXT, revenue_cents INTEGER)")
        self.connection.execute("CREATE TABLE customers (customer_id INTEGER, region TEXT)")
        self.connection.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", snapshot["orders"])
        self.connection.executemany("INSERT INTO customers VALUES (?, ?)", snapshot["customers"])
        self.connection.commit()
        self.connection.execute("PRAGMA query_only=ON")
        self.connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 100000)
        self.connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 10000)
        self.connection.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 50)
        self.connection.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 20)
        self.connection.set_authorizer(self._authorize)
        self.timeout, self.max_steps, self.max_rows = timeout, max_steps, max_rows

    def _authorize(self, action, arg1, arg2, database, trigger):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            # SQLite reports no database and an empty column for COUNT(*)'s
            # optimized table read. Permit only that special read of known tables.
            local_read = database == "main" or (database is None and arg2 == "")
            return (sqlite3.SQLITE_OK if local_read and arg1 in {"orders", "customers"}
                    else sqlite3.SQLITE_DENY)
        if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in self.FUNCTIONS:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def query(self, sql, *, max_rows=None):
        if not isinstance(sql, str) or not sql.strip() or len(sql) > 10000:
            raise QueryRejected("Provide one nonempty SELECT statement of at most 10,000 characters.")
        cap = self.max_rows if max_rows is None else min(max_rows, 50000)
        started = time.monotonic()
        steps = 0

        def progress():
            nonlocal steps
            steps += 100
            return int(steps >= self.max_steps or time.monotonic() - started >= self.timeout)

        self.connection.set_progress_handler(progress, 100)
        try:
            cursor = self.connection.execute(sql)
            if cursor.description is None:
                raise QueryRejected("Only read-only SELECT statements are accepted.")
            rows = cursor.fetchmany(cap + 1)
            return {"sql": sql, "columns": [c[0] for c in cursor.description],
                    "rows": [list(row) for row in rows[:cap]], "truncated": len(rows) > cap,
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2)}
        except sqlite3.Error as exc:
            raise QueryRejected(f"SQL rejected or interrupted: {exc}") from None
        finally:
            self.connection.set_progress_handler(None, 0)

    def close(self):
        self.connection.close()

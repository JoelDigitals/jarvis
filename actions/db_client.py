import json, os, sys, threading
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CFG_PATH = BASE / "config" / "db_config.json"

_connections = {}
_lock = threading.Lock()

def _get_connection(name):
    with _lock:
        return _connections.get(name)

def _set_connection(name, conn):
    with _lock:
        if conn is None:
            _connections.pop(name, None)
        else:
            _connections[name] = conn

def _connect_sqlite(path):
    import sqlite3
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def _connect_pg(host, port, database, user, password):
    import psycopg2
    conn = psycopg2.connect(host=host, port=port, dbname=database, user=user, password=password)
    conn.autocommit = True
    return conn

def _connect_mysql(host, port, database, user, password):
    import pymysql
    conn = pymysql.connect(host=host, port=port, db=database, user=user, password=password)
    return conn

def _query_to_text(cursor, limit=20):
    cols = [d[0] for d in cursor.description] if cursor.description else []
    rows = cursor.fetchmany(limit)
    if not rows:
        return "Keine Ergebnisse."
    widths = [len(c) for c in cols]
    for row in rows:
        for i, v in enumerate(row):
            widths[i] = max(widths[i], len(str(v)) if v is not None else 4)
    lines = [" | ".join(c.ljust(w) for c, w in zip(cols, widths))]
    lines.append("-+-".join("-" * w for w in widths))
    for row in rows:
        lines.append(" | ".join(
            (str(v) if v is not None else "NULL").ljust(w)
            for v, w in zip(row, widths)
        ))
    if cursor.rownumber > 0:
        lines.append(f"({cursor.rownumber} Zeilen, zeige {len(rows)})")
    return "\n".join(lines)

def db_action(parameters, response=None, player=None, session_memory=None):
    action = (parameters or {}).get("action", "").lower().strip()
    conn_name = (parameters or {}).get("name", "default")
    db_type = (parameters or {}).get("type", "sqlite")
    host = (parameters or {}).get("host", "localhost")
    port = (parameters or {}).get("port", 5432)
    database = (parameters or {}).get("database", "")
    user = (parameters or {}).get("user", "")
    password = (parameters or {}).get("password", "")
    sql = (parameters or {}).get("sql", "")
    path = (parameters or {}).get("path", "")

    try:
        if action == "connect":
            if db_type == "sqlite":
                if not path:
                    return "Für SQLite bitte path angeben."
                conn = _connect_sqlite(path)
            elif db_type == "postgresql":
                conn = _connect_pg(host, int(port) if port else 5432, database, user, password)
            elif db_type == "mysql":
                conn = _connect_mysql(host, int(port) if port else 3306, database, user, password)
            else:
                return f"Unbekannter DB-Typ: {db_type}. Verfügbar: sqlite, postgresql, mysql"
            _set_connection(conn_name, conn)
            return f"✅ Verbunden mit {db_type}:{database}"

        elif action == "disconnect":
            conn = _get_connection(conn_name)
            if conn:
                conn.close()
                _set_connection(conn_name, None)
            return "✅ Verbindung getrennt."

        elif action == "tables":
            conn = _get_connection(conn_name)
            if not conn:
                return "❌ Keine Verbindung. Erst connect verwenden."
            c = conn.cursor()
            if db_type == "sqlite":
                c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            elif db_type == "postgresql":
                c.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' ORDER BY tablename")
            elif db_type == "mysql":
                c.execute("SHOW TABLES")
            else:
                return "Unbekannter DB-Typ."
            tables = [row[0] for row in c.fetchall()]
            if not tables:
                return "Keine Tabellen gefunden."
            return "Tabellen:\n" + "\n".join(f"  - {t}" for t in tables)

        elif action == "query":
            conn = _get_connection(conn_name)
            if not conn:
                return "❌ Keine Verbindung. Erst connect verwenden."
            if not sql:
                return "Bitte sql angeben."
            c = conn.cursor()
            c.execute(sql)
            if sql.strip().upper().startswith(("SELECT", "WITH", "SHOW", "DESC", "EXPLAIN", "PRAGMA")):
                return _query_to_text(c)
            conn.commit()
            return f"✅ {c.rowcount} Zeilen betroffen."

        elif action == "schema":
            conn = _get_connection(conn_name)
            if not conn:
                return "❌ Keine Verbindung. Erst connect verwenden."
            table = (parameters or {}).get("table", "")
            if not table:
                return "Bitte table angeben."
            c = conn.cursor()
            if db_type == "sqlite":
                c.execute(f"PRAGMA table_info({table})")
            elif db_type == "postgresql":
                c.execute(f"""
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = '{table}'
                    ORDER BY ordinal_position
                """)
            elif db_type == "mysql":
                c.execute(f"DESCRIBE {table}")
            else:
                return "Unbekannter DB-Typ."
            return _query_to_text(c)

        else:
            return ("Verfügbare Aktionen: connect, disconnect, tables, query, schema. "
                    "Parameter: action, name, type (sqlite/postgresql/mysql), "
                    "host, port, database, user, password, path (für SQLite), sql, table")

    except Exception as e:
        return f"DB-Fehler: {e}"

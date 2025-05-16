import sqlite3
import threading
import json
import logging
from datetime import datetime


class StateStore:
    """
    Thread-safe SQLite-backed store for chat sessions, intents, and entities.
    """

    def __init__(self, db_path: str):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_msg TEXT NOT NULL,
                    bot_msg TEXT,
                    intent TEXT,
                    created_at TEXT NOT NULL
                )
            """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    session_id INTEGER,
                    name TEXT,
                    value TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            """
            )
            conn.commit()
        self.logger.debug("Initialized SQLite database and tables.")

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        return conn

    def create_session(self, user_msg: str) -> int:
        """Insert a new session row with the user message and return its ID."""
        timestamp = datetime.now().isoformat()
        with self.lock, self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO sessions (user_msg, created_at) VALUES (?, ?)", (user_msg, timestamp)
            )
            session_id = cur.lastrowid
            conn.commit()
        self.logger.debug(f"Created new session {session_id}.")
        return session_id

    def save_intent(self, session_id: int, intent: str):
        """Update the session row with the detected intent."""
        with self.lock, self._get_conn() as conn:
            conn.execute("UPDATE sessions SET intent = ? WHERE id = ?", (intent, session_id))
            conn.commit()
        self.logger.debug(f"Saved intent for session {session_id}: {intent}")

    def save_entities(self, session_id: int, entities: dict):
        """Insert all extracted entities for a session."""
        with self.lock, self._get_conn() as conn:
            cur = conn.cursor()
            for name, value in entities.items():
                cur.execute(
                    "INSERT INTO entities (session_id, name, value) VALUES (?, ?, ?)",
                    (session_id, name, json.dumps(value)),
                )
            conn.commit()
        self.logger.debug(f"Saved {len(entities)} entities for session {session_id}.")

    def parse_json(self, text: str) -> dict:
        """Helper to parse JSON, logging on failure."""
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            self.logger.error("JSON parsing error", exc_info=e)
            return {}

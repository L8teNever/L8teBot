# -*- coding: utf-8 -*-
import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from utils.config import GUILDS_DATA_DIR

class LogStorage:
    """Handles persistent audit log storage using SQLite."""

    def __init__(self):
        self.db_connections = {}

    def _get_db_path(self, guild_id: int) -> str:
        """Get the database file path for a guild."""
        guild_dir = os.path.join(GUILDS_DATA_DIR, str(guild_id))
        os.makedirs(guild_dir, exist_ok=True)
        return os.path.join(guild_dir, "logs.db")

    def _get_connection(self, guild_id: int) -> sqlite3.Connection:
        """Get or create a database connection for a guild."""
        db_path = self._get_db_path(guild_id)

        if guild_id not in self.db_connections:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self.db_connections[guild_id] = conn
            self._init_db(conn)

        return self.db_connections[guild_id]

    def _init_db(self, conn: sqlite3.Connection) -> None:
        """Initialize the database schema if it doesn't exist."""
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                user_id TEXT,
                user_name TEXT,
                channel_id TEXT,
                channel_name TEXT,
                target_id TEXT,
                target_name TEXT,
                action TEXT,
                before_value TEXT,
                after_value TEXT,
                reason TEXT,
                extra_data TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON audit_logs(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON audit_logs(event_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON audit_logs(user_id)")
        conn.commit()

    def save_log(self, guild_id: int, event_data: Dict[str, Any]) -> int:
        """
        Save a log entry to the database.

        Args:
            guild_id: The guild ID
            event_data: Dictionary containing log data:
                - event_type: str (required)
                - user_id: str
                - user_name: str
                - channel_id: str
                - channel_name: str
                - target_id: str
                - target_name: str
                - action: str
                - before_value: str
                - after_value: str
                - reason: str
                - extra_data: dict (will be JSON-serialized)

        Returns:
            The ID of the inserted log entry
        """
        conn = self._get_connection(guild_id)
        cursor = conn.cursor()

        # Prepare data
        timestamp = event_data.get('timestamp', datetime.utcnow().isoformat())
        extra_data = event_data.get('extra_data')
        if extra_data and isinstance(extra_data, dict):
            extra_data = json.dumps(extra_data)

        cursor.execute("""
            INSERT INTO audit_logs (
                timestamp, event_type, user_id, user_name, channel_id,
                channel_name, target_id, target_name, action, before_value,
                after_value, reason, extra_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            event_data.get('event_type'),
            event_data.get('user_id'),
            event_data.get('user_name'),
            event_data.get('channel_id'),
            event_data.get('channel_name'),
            event_data.get('target_id'),
            event_data.get('target_name'),
            event_data.get('action'),
            event_data.get('before_value'),
            event_data.get('after_value'),
            event_data.get('reason'),
            extra_data
        ))

        conn.commit()
        return cursor.lastrowid

    def get_logs(self, guild_id: int, filters: Optional[Dict[str, Any]] = None, limit: int = 100) -> List[Dict]:
        """
        Retrieve logs with optional filters.

        Args:
            guild_id: The guild ID
            filters: Optional filter dictionary:
                - event_type: str or list of str
                - user_id: str
                - channel_id: str
                - days: int (last N days)
            limit: Maximum number of logs to return

        Returns:
            List of log dictionaries
        """
        conn = self._get_connection(guild_id)
        cursor = conn.cursor()

        query = "SELECT * FROM audit_logs WHERE 1=1"
        params = []

        if filters:
            if 'event_type' in filters:
                event_types = filters['event_type']
                if isinstance(event_types, str):
                    query += " AND event_type = ?"
                    params.append(event_types)
                elif isinstance(event_types, list):
                    placeholders = ','.join('?' * len(event_types))
                    query += f" AND event_type IN ({placeholders})"
                    params.extend(event_types)

            if 'user_id' in filters:
                query += " AND user_id = ?"
                params.append(filters['user_id'])

            if 'channel_id' in filters:
                query += " AND channel_id = ?"
                params.append(filters['channel_id'])

            if 'days' in filters:
                cutoff_date = (datetime.utcnow() - timedelta(days=filters['days'])).isoformat()
                query += " AND timestamp > ?"
                params.append(cutoff_date)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    def delete_old_logs(self, guild_id: int, days: int) -> int:
        """
        Delete logs older than the specified number of days.

        Args:
            guild_id: The guild ID
            days: Number of days to keep

        Returns:
            Number of deleted rows
        """
        conn = self._get_connection(guild_id)
        cursor = conn.cursor()

        cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()
        cursor.execute("DELETE FROM audit_logs WHERE timestamp < ?", (cutoff_date,))
        conn.commit()

        return cursor.rowcount

    def get_stats(self, guild_id: int) -> Dict[str, Any]:
        """Get statistics about the logs for a guild."""
        conn = self._get_connection(guild_id)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM audit_logs")
        total = cursor.fetchone()['total']

        cursor.execute("""
            SELECT event_type, COUNT(*) as count
            FROM audit_logs
            GROUP BY event_type
            ORDER BY count DESC
        """)
        by_type = {row['event_type']: row['count'] for row in cursor.fetchall()}

        return {
            'total_logs': total,
            'by_event_type': by_type
        }

    def close_all_connections(self) -> None:
        """Close all database connections."""
        for conn in self.db_connections.values():
            conn.close()
        self.db_connections.clear()

import sqlite3
import os
import datetime
import logging  # 1. Import logging
from astrbot.api import logger  # Assuming this is the correct import for your logger

class QASystem:
    def __init__(self, db_path="data/qa.db", log_level=logging.INFO):  # Added log_level
        self.db_path = db_path
        self._conn = None
        self._cursor = None

        # 2. Initialize logger
        self.logger = logger

        # Ensure the directory for the database exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):  # 4. Create data directory
            try:
                os.makedirs(db_dir)
                self.logger.info(f"Created directory: {db_dir}")
            except OSError as e:
                self.logger.error(f"Error creating directory {db_dir}: {e}")
                # Decide if you want to raise an exception or try to continue
                # For now, we'll let it try to connect, which might fail if dir isn't writable

        self._connect()
        self._setup_database()

    def _connect(self):
        """Establishes a connection to the SQLite database."""
        try:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._cursor = self._conn.cursor()
            self._cursor.execute("PRAGMA foreign_keys = ON;")
            self._conn.commit()
            self.logger.debug(f"Successfully connected to database: {self.db_path}")
        except sqlite3.Error as e:
            self.logger.error(f"Error connecting to database {self.db_path}: {e}")
            # Depending on the desired behavior, you might want to re-raise the exception
            # or handle it in a way that the application can gracefully fail.
            raise

    def _get_current_timestamp_str(self):
        """Returns current timestamp in SQLite compatible format with milliseconds."""
        return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    def _setup_database(self):
        """Creates tables if they don't exist."""
        try:
            # Table: qa_entries
            self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS qa_entries (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_identifier TEXT NOT NULL,
                keyword TEXT NOT NULL,
                match_type TEXT CHECK(match_type IN ('EXACT', 'FUZZY', 'REGEX')) DEFAULT 'EXACT' NOT NULL,
                status TEXT CHECK(status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')) DEFAULT 'ACTIVE' NOT NULL,
                priority INTEGER DEFAULT 0 NOT NULL,
                created_at TEXT DEFAULT (STRFTIME('%Y-%m-%d %H:%M:%S', 'NOW', 'localtime')) NOT NULL,
                updated_at TEXT DEFAULT (STRFTIME('%Y-%m-%d %H:%M:%S', 'NOW', 'localtime')) NOT NULL
            );
            """)

            # Indexes for qa_entries
            self._cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_qa_entries_group_keyword 
            ON qa_entries (group_identifier, keyword, status, priority);
            """)
            self._cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_qa_entries_group_identifier 
            ON qa_entries (group_identifier);
            """)
            self._cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_qa_entries_keyword 
            ON qa_entries (keyword);
            """)

            # Table: qa_values
            self._cursor.execute("""
            CREATE TABLE IF NOT EXISTS qa_values (
                value_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                value_type TEXT CHECK(value_type IN ('TEXT', 'IMAGE_URL', 'FILE_URL', 'MARKDOWN')) DEFAULT 'TEXT' NOT NULL,
                value_content TEXT NOT NULL,
                order_num INTEGER DEFAULT 0 NOT NULL,
                created_at TEXT DEFAULT (STRFTIME('%Y-%m-%d %H:%M:%S', 'NOW', 'localtime')) NOT NULL,
                updated_at TEXT DEFAULT (STRFTIME('%Y-%m-%d %H:%M:%S', 'NOW', 'localtime')) NOT NULL,
                FOREIGN KEY (entry_id) REFERENCES qa_entries (entry_id) ON DELETE CASCADE
            );
            """)

            # Index for qa_values
            self._cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_qa_values_entry_id 
            ON qa_values (entry_id);
            """)

            # Trigger: Auto update qa_entries.updated_at
            self._cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_qa_entries_update_timestamp
            AFTER UPDATE ON qa_entries
            FOR EACH ROW
            WHEN OLD.updated_at = NEW.updated_at OR NEW.updated_at IS NULL OR NEW.updated_at = (STRFTIME('%Y-%m-%d %H:%M:%S', 'NOW', 'localtime'))
            BEGIN
                UPDATE qa_entries
                SET updated_at = (STRFTIME('%Y-%m-%d %H:%M:%S', 'NOW', 'localtime'))
                WHERE entry_id = OLD.entry_id;
            END;
            """)

            # Trigger: Auto update qa_values.updated_at
            self._cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_qa_values_update_timestamp
            AFTER UPDATE ON qa_values
            FOR EACH ROW
            WHEN OLD.updated_at = NEW.updated_at OR NEW.updated_at IS NULL OR NEW.updated_at = (STRFTIME('%Y-%m-%d %H:%M:%S', 'NOW', 'localtime'))
            BEGIN
                UPDATE qa_values
                SET updated_at = (STRFTIME('%Y-%m-%d %H:%M:%S', 'NOW', 'localtime'))
                WHERE value_id = OLD.value_id;
            END;
            """)
            self._conn.commit()
            self.logger.debug("Database setup/check complete.")
        except sqlite3.Error as e:
            self.logger.error(f"Error during database setup: {e}")
            self._conn.rollback()  # Rollback any partial DDL changes if error occurs
            raise

    def add_qa(self, group_identifier, keyword, values, match_type='EXACT', status='ACTIVE', priority=0):
        """
        Adds a new Q&A entry.
        'values' should be a list of dictionaries, e.g.,
        [{'type': 'TEXT', 'content': 'Hello!'}, {'type': 'IMAGE_URL', 'content': 'path/to/img.png'}]
        """
        if not isinstance(values, list) or not values:
            self.logger.error("Values must be a non-empty list of dictionaries.")
            raise ValueError("Values must be a non-empty list of dictionaries.")
        for v_item in values:
            if not isinstance(v_item, dict) or 'content' not in v_item:
                self.logger.error("Each value item must be a dictionary with at least a 'content' key.")
                raise ValueError("Each value item must be a dictionary with at least a 'content' key.")

        current_time = self._get_current_timestamp_str()
        try:
            self._cursor.execute("""
            INSERT INTO qa_entries (group_identifier, keyword, match_type, status, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (group_identifier, keyword, match_type, status, priority, current_time, current_time))
            entry_id = self._cursor.lastrowid

            for i, value_item in enumerate(values):
                value_type = value_item.get('type', 'TEXT')
                value_content = value_item['content']
                order_num = value_item.get('order', i)

                self._cursor.execute("""
                INSERT INTO qa_values (entry_id, value_type, value_content, order_num, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (entry_id, value_type, value_content, order_num, current_time, current_time))

            self._conn.commit()
            self.logger.info(
                f"Added Q&A for keyword '{keyword}' in group '{group_identifier}' with entry_id {entry_id}.")
            return entry_id
        except sqlite3.Error as e:
            self._conn.rollback()
            self.logger.error(f"Error adding Q&A for keyword '{keyword}', group '{group_identifier}': {e}")
            return None

    def get_qa(self, group_identifier, keyword):
        """
        Retrieves Q&A values for a given group and keyword.
        Returns a list of dictionaries, each representing a value, ordered by priority and value order.
        Returns an empty list if no match is found.
        """
        try:
            self._cursor.execute("""
            SELECT
                v.value_type,
                v.value_content,
                e.priority,
                v.order_num,
                e.entry_id -- Fetch entry_id for better logging if needed
            FROM
                qa_entries e
            JOIN
                qa_values v ON e.entry_id = v.entry_id
            WHERE
                e.group_identifier = ?
                AND e.keyword = ?
                AND e.status = 'ACTIVE'
            ORDER BY
                e.priority DESC, 
                v.order_num ASC;
            """, (group_identifier, keyword))

            results = self._cursor.fetchall()

            if not results:
                self.logger.debug(f"No active Q&A found for group '{group_identifier}', keyword '{keyword}'.")
                return []

            self.logger.debug(
                f"Found {len(results)} raw value rows for group '{group_identifier}', keyword '{keyword}'.")

            top_priority = results[0]['priority']
            final_values = []
            processed_entry_id = results[0]['entry_id']  # For logging the entry we are using

            for row in results:
                if row['priority'] == top_priority:
                    final_values.append(
                        {'type': row['value_type'], 'content': row['value_content'], 'order': row['order_num']})
                else:
                    # We've moved to a lower priority entry, so stop.
                    break

            # Sort again by original order_num within the top priority entry (already done by SQL for the top priority, but good for clarity if logic changes)
            final_values.sort(key=lambda x: x['order'])
            self.logger.info(
                f"Retrieved {len(final_values)} values for group '{group_identifier}', keyword '{keyword}' from entry_id {processed_entry_id} with priority {top_priority}.")
            return final_values
        except sqlite3.Error as e:
            self.logger.error(f"Error getting Q&A for group '{group_identifier}', keyword '{keyword}': {e}")
            return []

    def get_qa_by_group(self, group_identifier):
        """Retrieves all Q&A entries for a given group."""
        try:
            self._cursor.execute("""
            SELECT
                e.keyword,
                v.value_type,
                v.value_content,
                e.priority,
                v.order_num
            FROM
                qa_entries e
            JOIN
                qa_values v ON e.entry_id = v.entry_id
            WHERE
                e.group_identifier = ?
                AND e.status = 'ACTIVE'
            ORDER BY
                e.priority DESC, 
                v.order_num ASC;
            """, (group_identifier,))

            results = self._cursor.fetchall()

            if not results:
                self.logger.debug(f"No active Q&A found for group '{group_identifier}'.")
                return []

            self.logger.debug(f"Found {len(results)} raw value rows for group '{group_identifier}'.")

            final_values = {}
            for row in results:
                keyword = row['keyword']
                if keyword not in final_values:
                    final_values[keyword] = []
                final_values[keyword].append(
                    {'type': row['value_type'], 'content': row['value_content'], 'order': row['order_num']})

            # Sort each keyword's values by order_num
            for keyword in final_values:
                final_values[keyword].sort(key=lambda x: x['order'])

            self.logger.info(f"Retrieved {len(final_values)} keywords for group '{group_identifier}'.")
            return final_values
        except sqlite3.Error as e:
            self.logger.error(f"Error getting Q&A for group '{group_identifier}': {e}")
            return []

    def delete_qa(self, group_identifier, keyword):
        """Deletes Q&A entries for a given group and keyword."""
        try:
            self._cursor.execute("""
            DELETE FROM qa_entries
            WHERE group_identifier = ? AND keyword = ?
            """, (group_identifier, keyword))
            self._conn.commit()
            if self._cursor.rowcount > 0:
                self.logger.info(f"Deleted Q&A for keyword '{keyword}' in group '{group_identifier}'.")
                return "删除关键词成功"
            else:
                self.logger.info(f"No Q&A found for deletion with keyword '{keyword}' in group '{group_identifier}'.")
                return "没有找到要删除的关键词"
        except sqlite3.Error as e:
            self._conn.rollback()
            self.logger.error(f"Error deleting Q&A for keyword '{keyword}', group '{group_identifier}': {e}")
            return "删除关键词失败"


    def close(self):
        """Closes the database connection."""
        if self._conn:
            try:
                self._conn.close()
                self.logger.info("Database connection closed.")
            except sqlite3.Error as e:
                self.logger.error(f"Error closing database connection: {e}")
        self._conn = None
        self._cursor = None
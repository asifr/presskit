"""SQLite data source implementation."""

import aiosqlite
import logging
from pathlib import Path
import typing as t
from typing import Any, Dict, List

from jinja2 import Environment, TemplateError

from presskit.sources.base import QueryableSource, ConnectionError, QueryError

logger = logging.getLogger(__name__)


class SQLiteSource(QueryableSource):
    """SQLite data source with async support."""

    def __init__(self, config, site_dir=None):
        super().__init__(config, site_dir)
        self._connection: t.Optional[aiosqlite.Connection] = None

    @classmethod
    def get_required_dependencies(cls) -> List[str]:
        """SQLite is built into Python, but we use aiosqlite for async support."""
        return ["aiosqlite"]

    async def connect(self) -> None:
        """
        Connect to SQLite database.

        Raises:
            ConnectionError: If connection fails
        """
        if self._is_connected:
            return

        if not self.config.path:
            raise ConnectionError("SQLite source requires 'path' configuration")

        try:
            # Resolve path relative to site directory if needed
            if self.site_dir:
                db_path = self.config.get_resolved_path(Path(self.site_dir))
                if not db_path:
                    raise ConnectionError("SQLite source requires 'path' configuration")
            else:
                db_path = Path(self.config.path)

            if not db_path.exists():
                raise ConnectionError(f"SQLite database not found: {db_path}")

            # Connect with options from config
            connect_kwargs = {"database": str(db_path), **self.config.options}

            self._connection = await aiosqlite.connect(**connect_kwargs)

            # Enable row factory for dict-like access
            self._connection.row_factory = aiosqlite.Row

            # Enable foreign keys by default
            await self._connection.execute("PRAGMA foreign_keys = ON")

            self._is_connected = True
            logger.debug(f"Connected to SQLite database: {db_path}")

        except Exception as e:
            raise ConnectionError(f"Failed to connect to SQLite database: {e}")

    async def disconnect(self) -> None:
        """Close the SQLite connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            self._is_connected = False
            logger.debug("Disconnected from SQLite database")

    async def execute_query(self, query: str, variables: t.Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute SQL query and return results.

        Args:
            query: SQL query string (supports Jinja2 templating)
            variables: Variables for template substitution

        Returns:
            List of result dictionaries

        Raises:
            ConnectionError: If not connected to database
            QueryError: If query execution fails
        """
        if not self._is_connected or not self._connection:
            raise ConnectionError("Not connected to SQLite database")

        try:
            # Process query as Jinja2 template if variables provided
            processed_query = query
            if variables:
                processed_query = self._process_query_template(query, variables)

            logger.debug(f"Executing SQLite query: {processed_query[:100]}...")

            # Execute query
            async with self._connection.execute(processed_query) as cursor:
                rows = await cursor.fetchall()

                # Convert sqlite3.Row objects to dictionaries
                results = [dict(row) for row in rows]

            logger.debug(f"SQLite query returned {len(results)} rows")
            return results

        except aiosqlite.Error as e:
            raise QueryError(f"SQLite query failed: {e}")
        except TemplateError as e:
            raise QueryError(f"Query template processing failed: {e}")
        except Exception as e:
            raise QueryError(f"Unexpected error during query execution: {e}")

    def _process_query_template(self, query: str, variables: Dict[str, Any]) -> str:
        """
        Process SQL query as Jinja2 template.

        Args:
            query: SQL query template
            variables: Variables for substitution

        Returns:
            Processed SQL query

        Raises:
            TemplateError: If template processing fails
        """
        try:
            env = Environment()
            template = env.from_string(query)
            return template.render(**variables)
        except Exception as e:
            raise TemplateError(f"Failed to process query template: {e}")

    def validate_query(self, query: str) -> bool:
        """
        Basic SQL query validation.

        Args:
            query: SQL query to validate

        Returns:
            True if query appears to be valid SQL
        """
        # Basic validation - check for SQL keywords
        query_upper = query.strip().upper()

        # Allow SELECT, INSERT, UPDATE, DELETE, WITH, PRAGMA
        valid_starts = ["SELECT", "INSERT", "UPDATE", "DELETE", "WITH", "PRAGMA"]

        for start in valid_starts:
            if query_upper.startswith(start):
                return True

        return False

    async def get_table_info(self, table_name: str) -> List[Dict[str, Any]]:
        """
        Get information about a table's columns.

        Args:
            table_name: Name of the table

        Returns:
            List of column information dictionaries
        """
        query = f"PRAGMA table_info({table_name})"
        return await self.execute_query(query)

    async def list_tables(self) -> List[str]:
        """
        List all tables in the database.

        Returns:
            List of table names
        """
        query = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        results = await self.execute_query(query)
        return [row["name"] for row in results]

    async def get_schema(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get the complete database schema.

        Returns:
            Dictionary mapping table names to column information
        """
        tables = await self.list_tables()
        schema = {}

        for table in tables:
            schema[table] = await self.get_table_info(table)

        return schema

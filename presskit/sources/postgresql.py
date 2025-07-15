"""PostgreSQL data source implementation."""

import logging
from contextlib import asynccontextmanager
import typing as t
from typing import Any, Dict, List

from jinja2 import Environment, TemplateError

from presskit.sources.base import DatabaseSource, ConnectionError, QueryError

logger = logging.getLogger(__name__)


class PostgreSQLSource(DatabaseSource):
    """PostgreSQL data source with async connection pooling."""

    @classmethod
    def get_required_dependencies(cls) -> List[str]:
        """PostgreSQL requires asyncpg for async support."""
        return ["asyncpg"]

    async def create_pool(self) -> Any:
        """
        Create asyncpg connection pool.

        Returns:
            asyncpg connection pool

        Raises:
            ConnectionError: If pool creation fails
        """
        try:
            import asyncpg

            # Build connection parameters
            connect_kwargs = {}

            if self.config.connection_string:
                # Use connection string if provided
                connect_kwargs["dsn"] = self.config.connection_string
            else:
                # Build from individual parameters
                if self.config.host:
                    connect_kwargs["host"] = self.config.host
                if self.config.port:
                    connect_kwargs["port"] = self.config.port
                if self.config.database:
                    connect_kwargs["database"] = self.config.database
                if self.config.username:
                    connect_kwargs["user"] = self.config.username
                if self.config.password:
                    connect_kwargs["password"] = self.config.password

            # Add additional options
            connect_kwargs.update(self.config.options)

            # Set default pool parameters if not specified
            pool_kwargs = {
                "min_size": 1,
                "max_size": 10,
                "command_timeout": 60,
                **{
                    k: v
                    for k, v in connect_kwargs.items()
                    if k.startswith("pool_") or k in ["min_size", "max_size", "command_timeout"]
                },
            }

            # Remove pool-specific keys from connection kwargs
            for key in list(connect_kwargs.keys()):
                if key.startswith("pool_") or key in ["min_size", "max_size", "command_timeout"]:
                    pool_kwargs[key.replace("pool_", "")] = connect_kwargs.pop(key)

            # Create connection pool
            pool = await asyncpg.create_pool(**connect_kwargs, **pool_kwargs)

            logger.debug(
                f"Created PostgreSQL connection pool to {self.config.host}:{self.config.port}/{self.config.database}"
            )
            return pool

        except ImportError:
            raise ConnectionError(
                "asyncpg package is required for PostgreSQL support. Install with: pip install asyncpg"
            )
        except Exception as e:
            raise ConnectionError(f"Failed to create PostgreSQL connection pool: {e}")

    async def close_pool(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            logger.debug("Closed PostgreSQL connection pool")

    @asynccontextmanager
    async def get_connection(self):
        """
        Get a connection from the pool.

        Returns:
            Async context manager for database connection

        Raises:
            ConnectionError: If not connected or pool is unavailable
        """
        if not self._is_connected or not self._pool:
            raise ConnectionError("Database source is not connected")

        async with self._pool.acquire() as connection:
            yield connection

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
        if not self._is_connected or not self._pool:
            raise ConnectionError("Not connected to PostgreSQL database")

        try:
            # Process query as Jinja2 template if variables provided
            processed_query = query
            if variables:
                processed_query = self._process_query_template(query, variables)

            logger.debug(f"Executing PostgreSQL query: {processed_query[:100]}...")

            # Execute query using connection from pool
            async with self.get_connection() as conn:
                rows = await conn.fetch(processed_query)

                # Convert asyncpg Record objects to dictionaries
                results = [dict(row) for row in rows]

            logger.debug(f"PostgreSQL query returned {len(results)} rows")
            return results

        except Exception as e:
            if "template" in str(e).lower():
                raise QueryError(f"Query template processing failed: {e}")
            else:
                raise QueryError(f"PostgreSQL query failed: {e}")

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
        query_upper = query.strip().upper()

        # PostgreSQL supports more advanced queries
        valid_starts = [
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "WITH",
            "CREATE",
            "ALTER",
            "DROP",
            "TRUNCATE",
            "COPY",
            "EXPLAIN",
            "ANALYZE",
            "SET",
            "SHOW",
            "BEGIN",
            "COMMIT",
            "ROLLBACK",
        ]

        for start in valid_starts:
            if query_upper.startswith(start):
                return True

        return False

    async def execute_prepared(self, query: str, *args) -> List[Dict[str, Any]]:
        """
        Execute prepared statement with parameters.

        Args:
            query: SQL query with $1, $2, etc. placeholders
            *args: Query parameters

        Returns:
            List of result dictionaries
        """
        if not self._is_connected or not self._pool:
            raise ConnectionError("Not connected to PostgreSQL database")

        try:
            async with self.get_connection() as conn:
                rows = await conn.fetch(query, *args)
                return [dict(row) for row in rows]
        except Exception as e:
            raise QueryError(f"PostgreSQL prepared query failed: {e}")

    async def get_table_info(self, table_name: str, schema: str = "public") -> List[Dict[str, Any]]:
        """
        Get information about a table's columns.

        Args:
            table_name: Name of the table
            schema: Schema name (default: public)

        Returns:
            List of column information dictionaries
        """
        query = """
        SELECT 
            column_name,
            data_type,
            is_nullable,
            column_default,
            character_maximum_length,
            numeric_precision,
            numeric_scale
        FROM information_schema.columns 
        WHERE table_name = $1 AND table_schema = $2
        ORDER BY ordinal_position
        """
        return await self.execute_prepared(query, table_name, schema)

    async def list_tables(self, schema: str = "public") -> List[str]:
        """
        List all tables in a schema.

        Args:
            schema: Schema name (default: public)

        Returns:
            List of table names
        """
        query = """
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = $1 AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
        results = await self.execute_prepared(query, schema)
        return [row["table_name"] for row in results]

    async def list_schemas(self) -> List[str]:
        """
        List all schemas in the database.

        Returns:
            List of schema names
        """
        query = """
        SELECT schema_name 
        FROM information_schema.schemata 
        WHERE schema_name NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
        ORDER BY schema_name
        """
        results = await self.execute_query(query)
        return [row["schema_name"] for row in results]

    async def get_schema(self, schema: str = "public") -> Dict[str, List[Dict[str, Any]]]:
        """
        Get the complete database schema for a specific schema.

        Args:
            schema: Schema name (default: public)

        Returns:
            Dictionary mapping table names to column information
        """
        tables = await self.list_tables(schema)
        schema_info = {}

        for table in tables:
            schema_info[table] = await self.get_table_info(table, schema)

        return schema_info

    async def test_connection(self) -> bool:
        """
        Test the database connection.

        Returns:
            True if connection is working
        """
        try:
            await self.execute_query("SELECT 1 as test")
            return True
        except Exception:
            return False

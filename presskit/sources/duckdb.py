"""DuckDB data source implementation."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from jinja2 import Environment, TemplateError
from presskit.sources.base import QueryableSource, ConnectionError, QueryError

logger = logging.getLogger(__name__)


class DuckDBSource(QueryableSource):
    """DuckDB data source with async support."""

    def __init__(self, config, site_dir=None):
        super().__init__(config, site_dir)
        self._connection: Optional[Any] = None

    @classmethod
    def get_required_dependencies(cls) -> List[str]:
        """DuckDB requires the duckdb package."""
        return ["duckdb"]

    async def connect(self) -> None:
        """
        Connect to DuckDB database.

        Raises:
            ConnectionError: If connection fails
        """
        if self._is_connected:
            return

        try:
            import duckdb

            # DuckDB connection parameters
            if self.config.path:
                # File-based database
                # Resolve path relative to site directory if needed
                if self.site_dir:
                    db_path = self.config.get_resolved_path(Path(self.site_dir))
                    if not db_path:
                        raise ConnectionError("DuckDB source requires 'path' configuration")
                else:
                    db_path = Path(self.config.path)
                connect_kwargs = {"database": str(db_path), **self.config.options}
            else:
                # In-memory database
                connect_kwargs = {"database": ":memory:", **self.config.options}

            self._connection = duckdb.connect(**connect_kwargs)

            # Configure DuckDB settings from options
            for key, value in self.config.options.items():
                if key.startswith("setting_"):
                    setting_name = key[8:]  # Remove "setting_" prefix
                    self._connection.execute(f"SET {setting_name} = ?", [value])

            self._is_connected = True
            logger.debug(f"Connected to DuckDB database: {self.config.path or ':memory:'}")

        except ImportError:
            raise ConnectionError("duckdb package is required for DuckDB support. Install with: pip install duckdb")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to DuckDB database: {e}")

    async def disconnect(self) -> None:
        """Close the DuckDB connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
            self._is_connected = False
            logger.debug("Disconnected from DuckDB database")

    async def execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
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
            raise ConnectionError("Not connected to DuckDB database")

        try:
            # Process query as Jinja2 template if variables provided
            processed_query = query
            if variables:
                processed_query = self._process_query_template(query, variables)

            logger.debug(f"Executing DuckDB query: {processed_query[:100]}...")

            # Execute query and fetch all results
            result = self._connection.execute(processed_query)
            rows = result.fetchall()

            # Get column names
            columns = [desc[0] for desc in result.description] if result.description else []

            # Convert to list of dictionaries
            results = [dict(zip(columns, row)) for row in rows]

            logger.debug(f"DuckDB query returned {len(results)} rows")
            return results

        except Exception as e:
            if "template" in str(e).lower():
                raise QueryError(f"Query template processing failed: {e}")
            else:
                raise QueryError(f"DuckDB query failed: {e}")

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
        Basic SQL query validation for DuckDB.

        Args:
            query: SQL query to validate

        Returns:
            True if query appears to be valid SQL
        """
        query_upper = query.strip().upper()

        # DuckDB supports standard SQL plus extensions
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
            "DESCRIBE",
            "SHOW",
            "SET",
            "PRAGMA",
            "INSTALL",
            "LOAD",
            "EXPORT",
            "IMPORT",
        ]

        for start in valid_starts:
            if query_upper.startswith(start):
                return True

        return False

    async def install_extension(self, extension_name: str) -> None:
        """
        Install a DuckDB extension.

        Args:
            extension_name: Name of the extension to install
        """
        if not self._is_connected or not self._connection:
            raise ConnectionError("Not connected to DuckDB database")

        try:
            self._connection.execute(f"INSTALL {extension_name}")
            self._connection.execute(f"LOAD {extension_name}")
            logger.debug(f"Installed and loaded DuckDB extension: {extension_name}")
        except Exception as e:
            raise QueryError(f"Failed to install extension '{extension_name}': {e}")

    async def load_csv(self, file_path: str, table_name: str, **options) -> None:
        """
        Load CSV file into DuckDB table.

        Args:
            file_path: Path to CSV file
            table_name: Name of table to create
            **options: CSV loading options (header, delimiter, etc.)
        """
        if not self._is_connected or not self._connection:
            raise ConnectionError("Not connected to DuckDB database")

        try:
            # Build CREATE TABLE AS SELECT statement
            csv_options = []
            for key, value in options.items():
                if isinstance(value, bool):
                    csv_options.append(f"{key}={str(value).lower()}")
                elif isinstance(value, str):
                    csv_options.append(f"{key}='{value}'")
                else:
                    csv_options.append(f"{key}={value}")

            options_str = ", ".join(csv_options) if csv_options else ""
            query = f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{file_path}'{', ' + options_str if options_str else ''})"

            self._connection.execute(query)
            logger.debug(f"Loaded CSV '{file_path}' into table '{table_name}'")

        except Exception as e:
            raise QueryError(f"Failed to load CSV: {e}")

    async def load_parquet(self, file_path: str, table_name: str) -> None:
        """
        Load Parquet file into DuckDB table.

        Args:
            file_path: Path to Parquet file
            table_name: Name of table to create
        """
        if not self._is_connected or not self._connection:
            raise ConnectionError("Not connected to DuckDB database")

        try:
            query = f"CREATE TABLE {table_name} AS SELECT * FROM read_parquet('{file_path}')"
            self._connection.execute(query)
            logger.debug(f"Loaded Parquet '{file_path}' into table '{table_name}'")
        except Exception as e:
            raise QueryError(f"Failed to load Parquet: {e}")

    async def get_table_info(self, table_name: str) -> List[Dict[str, Any]]:
        """
        Get information about a table's columns.

        Args:
            table_name: Name of the table

        Returns:
            List of column information dictionaries
        """
        query = f"DESCRIBE {table_name}"
        return await self.execute_query(query)

    async def list_tables(self) -> List[str]:
        """
        List all tables in the database.

        Returns:
            List of table names
        """
        query = "SHOW TABLES"
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

    async def execute_script(self, script_path: str) -> None:
        """
        Execute a SQL script file.

        Args:
            script_path: Path to SQL script file
        """
        if not self._is_connected or not self._connection:
            raise ConnectionError("Not connected to DuckDB database")

        try:
            script_file = Path(script_path)
            if not script_file.exists():
                raise QueryError(f"Script file not found: {script_path}")

            with open(script_file, "r") as f:
                script_content = f.read()

            # Split by semicolons and execute each statement
            statements = [stmt.strip() for stmt in script_content.split(";") if stmt.strip()]

            for statement in statements:
                self._connection.execute(statement)

            logger.debug(f"Executed SQL script: {script_path}")

        except Exception as e:
            raise QueryError(f"Failed to execute script: {e}")

    async def export_to_csv(self, query: str, output_path: str, **options) -> None:
        """
        Export query results to CSV file.

        Args:
            query: SQL query to execute
            output_path: Path to output CSV file
            **options: CSV export options
        """
        if not self._is_connected or not self._connection:
            raise ConnectionError("Not connected to DuckDB database")

        try:
            csv_options = []
            for key, value in options.items():
                if isinstance(value, bool):
                    csv_options.append(f"{key}={str(value).lower()}")
                elif isinstance(value, str):
                    csv_options.append(f"{key}='{value}'")
                else:
                    csv_options.append(f"{key}={value}")

            options_str = ", ".join(csv_options) if csv_options else ""
            copy_query = (
                f"COPY ({query}) TO '{output_path}' WITH (FORMAT CSV{', ' + options_str if options_str else ''})"
            )

            self._connection.execute(copy_query)
            logger.debug(f"Exported query results to: {output_path}")

        except Exception as e:
            raise QueryError(f"Failed to export to CSV: {e}")

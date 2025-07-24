"""DuckDB data source plugin for Presskit."""

from presskit.hookspecs import hookimpl
from presskit.sources.duckdb import DuckDBSource


@hookimpl
def register_data_sources(context):
    """Register DuckDB data source."""
    del context  # Unused parameter required by hook interface
    return {"duckdb": DuckDBSource}

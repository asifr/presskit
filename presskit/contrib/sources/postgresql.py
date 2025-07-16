"""PostgreSQL data source plugin for Presskit."""

from presskit.hookspecs import hookimpl
from presskit.sources.postgresql import PostgreSQLSource


@hookimpl
def register_data_sources(context):
    """Register PostgreSQL data source."""
    del context  # Unused parameter required by hook interface
    return {"postgresql": PostgreSQLSource}
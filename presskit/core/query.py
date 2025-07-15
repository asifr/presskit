"""Async query processing engine."""

import asyncio
import datetime
import logging
from typing import Dict, List, Any

from presskit.config.models import SiteConfig, QueryDefinition, QueryCache
from presskit.sources.registry import get_registry
from presskit.sources.base import DataSource, FileSource

logger = logging.getLogger(__name__)


class QueryProcessor:
    """Async query processor with connection management."""

    def __init__(self):
        self.registry = get_registry()
        self._sources: Dict[str, DataSource] = {}

    async def process_all_queries(self, config: SiteConfig) -> QueryCache:
        """
        Process all queries in the configuration and return cached results.

        Args:
            config: Site configuration containing sources and queries

        Returns:
            QueryCache with all processed results
        """
        logger.info("Starting query processing...")

        try:
            # Initialize all data sources
            await self._initialize_sources(config)

            # Create cache structure
            cache_data = QueryCache(
                metadata={
                    "generated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sources": {
                        source_config.name: str(source_config.get_resolved_path(config.site_dir))
                        if source_config.path
                        else f"{source_config.type}://{source_config.host or 'memory'}"
                        for source_config in config.sources
                    },
                },
                queries={},
                generators={},
                data={},
            )

            # Process JSON/file sources first (these are loaded as static data)
            await self._process_file_sources(config, cache_data)

            # Process queries
            await self._process_queries(config, cache_data)

            logger.info(
                f"Query processing complete. Processed {len(cache_data.queries)} queries, {len(cache_data.generators)} generators"
            )
            return cache_data

        finally:
            # Clean up connections
            await self._cleanup_sources()

    async def _initialize_sources(self, config: SiteConfig) -> None:
        """Initialize and connect to all data sources."""
        logger.debug(f"Initializing {len(config.sources)} data sources...")

        connection_tasks = []
        for source_config in config.sources:
            task = self._initialize_source(source_config.name, source_config, config)
            connection_tasks.append(task)

        # Connect to all sources concurrently
        await asyncio.gather(*connection_tasks, return_exceptions=True)

        logger.debug(f"Initialized {len(self._sources)} sources successfully")

    async def _initialize_source(self, source_name: str, source_config, config: SiteConfig) -> None:
        """Initialize a single data source."""
        try:
            source = self.registry.create_source(source_config.type, source_config, config.site_dir)
            await source.connect()
            self._sources[source_name] = source
            logger.debug(f"Connected to source: {source_name} ({source_config.type})")
        except Exception as e:
            logger.error(f"Failed to initialize source '{source_name}': {e}")
            # Don't raise here - we want to continue with other sources

    async def _process_file_sources(self, config: SiteConfig, cache_data: QueryCache) -> None:
        """Process file-based sources (JSON, etc.) and load their data."""
        for source_config in config.sources:
            if source_config.type == "json" and source_config.name in self._sources:
                try:
                    source = self._sources[source_config.name]
                    if isinstance(source, FileSource):
                        data = await source.load_data()
                        cache_data.data[source_config.name] = data
                        logger.debug(f"Loaded data from JSON source: {source_config.name}")
                    else:
                        logger.warning(f"Source '{source_config.name}' is not a FileSource, cannot load data")
                except Exception as e:
                    logger.error(f"Failed to load data from source '{source_config.name}': {e}")

    async def _process_queries(self, config: SiteConfig, cache_data: QueryCache) -> None:
        """Process all queries concurrently."""
        # Separate parent and child queries
        parent_queries = [q for q in config.queries if "." not in q.name]
        child_queries = [q for q in config.queries if "." in q.name]

        # Process parent queries first
        parent_tasks = []
        for query in parent_queries:
            task = self._process_parent_query(query, config, cache_data)
            parent_tasks.append(task)

        await asyncio.gather(*parent_tasks, return_exceptions=True)

        # Process child queries (these depend on parent results)
        if child_queries:
            await self._process_child_queries(child_queries, config, cache_data)

    async def _process_parent_query(self, query: QueryDefinition, config: SiteConfig, cache_data: QueryCache) -> None:
        """Process a parent query."""
        try:
            logger.debug(f"Processing parent query: {query.name}")

            # Get source
            source_name = query.source or config.default_source
            if not source_name or source_name not in self._sources:
                logger.error(f"Source '{source_name}' not available for query '{query.name}'")
                return

            source = self._sources[source_name]

            # Prepare variables
            variables = {}
            if config.variables:
                variables.update(config.variables)
            if query.variables:
                variables.update(query.variables)

            # Execute query
            results = await source.execute_query(query.query, variables)

            # Store results
            if query.generator:
                cache_data.generators[query.name] = results
                logger.debug(f"Stored generator results for '{query.name}': {len(results)} rows")
            else:
                cache_data.queries[query.name] = results
                logger.debug(f"Stored query results for '{query.name}': {len(results)} rows")

        except Exception as e:
            logger.error(f"Failed to process query '{query.name}': {e}")

    async def _process_child_queries(
        self, child_queries: List[QueryDefinition], config: SiteConfig, cache_data: QueryCache
    ) -> None:
        """Process child queries that depend on parent results."""
        # Group child queries by parent
        children_by_parent = {}
        for query in child_queries:
            parent_name = query.name.split(".", 1)[0]
            if parent_name not in children_by_parent:
                children_by_parent[parent_name] = []
            children_by_parent[parent_name].append(query)

        # Process each parent's children
        for parent_name, children in children_by_parent.items():
            await self._process_parent_children(parent_name, children, config, cache_data)

    async def _process_parent_children(
        self, parent_name: str, child_queries: List[QueryDefinition], config: SiteConfig, cache_data: QueryCache
    ) -> None:
        """Process child queries for a specific parent."""
        # Get parent results (check both queries and generators)
        parent_results = cache_data.queries.get(parent_name, [])
        if not parent_results:
            parent_results = cache_data.generators.get(parent_name, [])

        if not parent_results:
            logger.warning(f"No parent results found for children of '{parent_name}'")
            return

        # Process children for each parent row
        for parent_row in parent_results:
            for child_query in child_queries:
                await self._process_child_query(child_query, parent_row, config)

    async def _process_child_query(
        self, child_query: QueryDefinition, parent_row: Dict[str, Any], config: SiteConfig
    ) -> None:
        """Process a single child query for a parent row."""
        try:
            child_name = child_query.name.split(".", 1)[1]

            # Get source
            source_name = child_query.source or config.default_source
            if not source_name or source_name not in self._sources:
                logger.error(f"Source '{source_name}' not available for child query '{child_query.name}'")
                return

            source = self._sources[source_name]

            # Prepare variables (parent row data + query variables)
            variables = dict(parent_row)
            if config.variables:
                variables.update(config.variables)
            if child_query.variables:
                variables.update(child_query.variables)

            # Execute child query
            child_results = await source.execute_query(child_query.query, variables)

            # Add results to parent row
            parent_row[child_name] = child_results

            logger.debug(f"Processed child query '{child_name}': {len(child_results)} rows")

        except Exception as e:
            logger.error(f"Failed to process child query '{child_query.name}': {e}")
            # Add empty results to prevent template errors
            parent_row[child_query.name.split(".", 1)[1]] = []

    async def process_markdown_queries(
        self, queries: Dict[str, Any], template_vars: Dict[str, Any], config: SiteConfig
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Process queries defined in markdown files.

        Args:
            queries: Query definitions from markdown frontmatter
            template_vars: Template variables for query substitution
            config: Site configuration

        Returns:
            Dictionary of query results
        """
        if not queries:
            return {}

        logger.debug(f"Processing {len(queries)} markdown queries...")

        try:
            # Ensure sources are initialized
            if not self._sources:
                await self._initialize_sources(config)

            results = {}

            # Process each query
            for query_name, query_def in queries.items():
                try:
                    # Get source
                    source_name = query_def.get("source", config.default_source)
                    if not source_name or source_name not in self._sources:
                        logger.error(f"Source '{source_name}' not available for markdown query '{query_name}'")
                        results[query_name] = []
                        continue

                    source = self._sources[source_name]
                    query_string = query_def.get("query", "")

                    # Execute query with template variables
                    query_results = await source.execute_query(query_string, template_vars)
                    results[query_name] = query_results

                    logger.debug(f"Processed markdown query '{query_name}': {len(query_results)} rows")

                except Exception as e:
                    logger.error(f"Failed to process markdown query '{query_name}': {e}")
                    results[query_name] = []

            return results

        except Exception as e:
            logger.error(f"Failed to process markdown queries: {e}")
            return {}

    async def _cleanup_sources(self) -> None:
        """Clean up all source connections."""
        logger.debug("Cleaning up source connections...")

        cleanup_tasks = []
        for source_name, source in self._sources.items():
            try:
                task = source.disconnect()
                cleanup_tasks.append(task)
            except Exception as e:
                logger.warning(f"Error during cleanup of source '{source_name}': {e}")

        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        self._sources.clear()
        logger.debug("Source cleanup complete")

    async def get_available_sources(self) -> Dict[str, Dict[str, Any]]:
        """
        Get information about available data sources.

        Returns:
            Dictionary mapping source types to their information
        """
        available_sources = {}

        for source_type in self.registry.list_sources():
            try:
                source_info = self.registry.get_source_info(source_type)
                available_sources[source_type] = source_info
            except Exception as e:
                logger.warning(f"Failed to get info for source '{source_type}': {e}")

        return available_sources

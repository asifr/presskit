"""Source registry and discovery system."""

import logging
import importlib
import importlib.metadata
from pathlib import Path
from typing import Dict, List, Type, Any, Optional

from presskit.sources.base import DataSource, SourceError

logger = logging.getLogger(__name__)


class SourceRegistry:
    """Registry for data source plugins with auto-discovery."""

    def __init__(self):
        self._sources: Dict[str, Type[DataSource]] = {}
        self._discovered = False

    def register_source(self, name: str, source_class: Type[DataSource]) -> None:
        """
        Manually register a data source.

        Args:
            name: Source type name
            source_class: DataSource subclass

        Raises:
            SourceError: If source name is already registered
        """
        if name in self._sources:
            raise SourceError(f"Source '{name}' is already registered")

        if not issubclass(source_class, DataSource):
            raise SourceError("Source class must be a subclass of DataSource")

        self._sources[name] = source_class
        logger.debug(f"Registered source: {name} -> {source_class.__name__}")

    def get_source(self, source_type: str) -> Type[DataSource]:
        """
        Get a data source class by type.

        Args:
            source_type: Type of source to retrieve

        Returns:
            DataSource subclass

        Raises:
            SourceError: If source type is not found
        """
        if not self._discovered:
            self.discover_sources()

        if source_type not in self._sources:
            available = list(self._sources.keys())
            raise SourceError(f"Source type '{source_type}' not found. Available: {available}")

        return self._sources[source_type]

    def list_sources(self) -> List[str]:
        """
        List all registered source types.

        Returns:
            List of source type names
        """
        if not self._discovered:
            self.discover_sources()
        return list(self._sources.keys())

    def list_available_sources(self) -> List[str]:
        """
        List source types that have all required dependencies installed.

        Returns:
            List of available source type names
        """
        if not self._discovered:
            self.discover_sources()

        available = []
        for name, source_class in self._sources.items():
            if source_class.is_available():
                available.append(name)
        return available

    def list_unavailable_sources(self) -> Dict[str, List[str]]:
        """
        List source types that are missing dependencies.

        Returns:
            Dictionary mapping source names to missing dependencies
        """
        if not self._discovered:
            self.discover_sources()

        unavailable = {}
        for name, source_class in self._sources.items():
            missing = source_class.get_missing_dependencies()
            if missing:
                unavailable[name] = missing
        return unavailable

    def discover_sources(self) -> None:
        """
        Auto-discover sources using entry points and built-in sources.
        """
        if self._discovered:
            return

        # Register built-in sources first
        self._register_builtin_sources()

        # Discover sources from entry points
        self._discover_entry_point_sources()

        self._discovered = True
        logger.info(f"Discovered {len(self._sources)} data sources")

    def _register_builtin_sources(self) -> None:
        """Register built-in data sources."""
        builtin_sources = [
            ("sqlite", "presskit.sources.sqlite", "SQLiteSource"),
            ("json", "presskit.sources.json", "JSONSource"),
        ]

        for name, module_name, class_name in builtin_sources:
            try:
                module = importlib.import_module(module_name)
                source_class = getattr(module, class_name)
                self._sources[name] = source_class
                logger.debug(f"Registered built-in source: {name}")
            except (ImportError, AttributeError) as e:
                logger.warning(f"Failed to register built-in source '{name}': {e}")

    def _discover_entry_point_sources(self) -> None:
        """Discover sources from entry points."""
        try:
            entry_points = importlib.metadata.entry_points().select(group="presskit.sources")

            for entry_point in entry_points:
                try:
                    source_class = entry_point.load()
                    if issubclass(source_class, DataSource):
                        self._sources[entry_point.name] = source_class
                        logger.debug(f"Discovered source from entry point: {entry_point.name}")
                    else:
                        logger.warning(f"Entry point '{entry_point.name}' is not a DataSource subclass")
                except Exception as e:
                    logger.warning(f"Failed to load source from entry point '{entry_point.name}': {e}")

        except Exception as e:
            logger.warning(f"Failed to discover entry point sources: {e}")

    def create_source(self, source_type: str, config, site_dir=None) -> DataSource:
        """
        Create a data source instance.

        Args:
            source_type: Type of source to create
            config: Source configuration
            site_dir: Site directory for resolving relative paths

        Returns:
            Configured DataSource instance

        Raises:
            SourceError: If source type is not found or cannot be created
        """
        source_class = self.get_source(source_type)

        # Check if source is available
        if not source_class.is_available():
            missing = source_class.get_missing_dependencies()
            raise SourceError(
                f"Source '{source_type}' is missing required dependencies: {missing}. "
                f"Install with: pip install {' '.join(missing)}"
            )

        try:
            return source_class(config, site_dir)
        except Exception as e:
            raise SourceError(f"Failed to create source '{source_type}': {e}")

    def get_source_info(self, source_type: str) -> Dict[str, Any]:
        """
        Get information about a source type.

        Args:
            source_type: Source type to get info for

        Returns:
            Dictionary with source information
        """
        source_class = self.get_source(source_type)

        return {
            "name": source_type,
            "class": source_class.__name__,
            "module": source_class.__module__,
            "available": source_class.is_available(),
            "required_dependencies": source_class.get_required_dependencies(),
            "missing_dependencies": source_class.get_missing_dependencies(),
            "docstring": source_class.__doc__,
        }


# Global registry instance
_registry: Optional[SourceRegistry] = None


def get_registry() -> SourceRegistry:
    """
    Get the global source registry instance.

    Returns:
        Global SourceRegistry instance
    """
    global _registry
    if _registry is None:
        _registry = SourceRegistry()

        # Call plugin hooks to register custom data sources
        try:
            from presskit.plugins import call_hook
            from presskit.hookspecs import PressskitContext

            # Create a minimal context for data source registration
            context = PressskitContext(config={}, build_dir=Path("."), content_dir=Path("."), template_dir=Path("."))

            # Call register_data_sources hook
            for result in call_hook("register_data_sources", context=context):
                if isinstance(result, dict):
                    for source_name, source_class in result.items():
                        try:
                            _registry.register_source(source_name, source_class)
                        except Exception as e:
                            logger.warning(f"Failed to register data source {source_name}: {e}")
        except ImportError:
            # Plugin system not available
            pass
        except Exception as e:
            logger.warning(f"Error loading plugin data sources: {e}")

    return _registry


def register_source(name: str, source_class: Type[DataSource]) -> None:
    """
    Register a source in the global registry.

    Args:
        name: Source type name
        source_class: DataSource subclass
    """
    get_registry().register_source(name, source_class)


def create_source(source_type: str, config, site_dir=None) -> DataSource:
    """
    Create a source instance using the global registry.

    Args:
        source_type: Type of source to create
        config: Source configuration
        site_dir: Site directory for resolving relative paths

    Returns:
        Configured DataSource instance
    """
    return get_registry().create_source(source_type, config, site_dir)

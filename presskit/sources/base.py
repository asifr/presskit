"""Abstract base classes for data sources."""

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
import typing as t
from typing import Any, Dict, List

from presskit.config.models import SourceDefinition


class SourceError(Exception):
    """Base exception for data source errors."""

    pass


class ConnectionError(SourceError):
    """Exception raised when connection to data source fails."""

    pass


class QueryError(SourceError):
    """Exception raised when query execution fails."""

    pass


class DataSource(ABC):
    """Abstract base class for all data sources."""

    def __init__(self, config: SourceDefinition, site_dir=None):
        """
        Initialize the data source.

        Args:
            config: Source configuration
            site_dir: Site directory for resolving relative paths
        """
        self.config = config
        self.site_dir = site_dir
        self._connection: t.Optional[Any] = None
        self._is_connected = False

    @abstractmethod
    async def connect(self) -> None:
        """
        Establish connection to the data source.

        Raises:
            ConnectionError: If connection fails
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Close the connection to the data source.
        """
        pass

    @abstractmethod
    async def execute_query(self, query: str, variables: t.Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute a query and return results.

        Args:
            query: Query string to execute
            variables: Variables to substitute in the query

        Returns:
            List of result dictionaries

        Raises:
            QueryError: If query execution fails
            ConnectionError: If not connected to data source
        """
        pass

    @classmethod
    @abstractmethod
    def get_required_dependencies(cls) -> List[str]:
        """
        Return list of required Python packages.

        Returns:
            List of package names required for this source
        """
        pass

    @classmethod
    def is_available(cls) -> bool:
        """
        Check if all required dependencies are installed.

        Returns:
            True if source can be used, False otherwise
        """
        try:
            for dep in cls.get_required_dependencies():
                __import__(dep)
            return True
        except ImportError:
            return False

    @classmethod
    def get_missing_dependencies(cls) -> List[str]:
        """
        Get list of missing dependencies.

        Returns:
            List of missing package names
        """
        missing = []
        for dep in cls.get_required_dependencies():
            try:
                __import__(dep)
            except ImportError:
                missing.append(dep)
        return missing

    @asynccontextmanager
    async def connection(self):
        """
        Async context manager for automatic connection management.

        Usage:
            async with source.connection():
                results = await source.execute_query("SELECT * FROM table")
        """
        await self.connect()
        try:
            yield self
        finally:
            await self.disconnect()

    async def __aenter__(self):
        """Support for async with statement."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Support for async with statement."""
        await self.disconnect()

    def __repr__(self) -> str:
        """String representation of the data source."""
        return f"{self.__class__.__name__}(type={self.config.type}, connected={self._is_connected})"


class QueryableSource(DataSource):
    """Abstract base class for sources that support query operations."""

    def validate_query(self, query: str) -> bool:
        """
        Validate query syntax (optional implementation).

        Args:
            query: Query string to validate

        Returns:
            True if query is valid, False otherwise
        """
        return True

    @abstractmethod
    async def execute_query(self, query: str, variables: t.Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Execute a query and return results as list of dictionaries."""
        pass


class FileSource(DataSource):
    """Abstract base class for file-based data sources."""

    @abstractmethod
    async def load_data(self) -> Any:
        """
        Load data from the file.

        Returns:
            Loaded data in appropriate format

        Raises:
            ConnectionError: If file cannot be read
        """
        pass

    async def connect(self) -> None:
        """File sources don't maintain persistent connections."""
        self._is_connected = True

    async def disconnect(self) -> None:
        """File sources don't maintain persistent connections."""
        self._is_connected = False


class DatabaseSource(QueryableSource):
    """Abstract base class for database sources with connection pooling."""

    def __init__(self, config: SourceDefinition):
        super().__init__(config)
        self._pool: t.Optional[Any] = None

    @abstractmethod
    async def create_pool(self) -> Any:
        """
        Create connection pool for database.

        Returns:
            Connection pool object
        """
        pass

    @abstractmethod
    async def close_pool(self) -> None:
        """Close the connection pool."""
        pass

    async def connect(self) -> None:
        """Establish connection pool."""
        if not self._is_connected:
            self._pool = await self.create_pool()
            self._is_connected = True

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._is_connected and self._pool:
            await self.close_pool()
            self._pool = None
            self._is_connected = False

    @abstractmethod
    def get_connection(self):
        """
        Get a connection from the pool.

        Returns:
            Async context manager for database connection

        Raises:
            ConnectionError: If not connected or pool is unavailable
        """
        pass

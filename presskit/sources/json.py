"""JSON data source implementation."""

import json
import logging
from pathlib import Path
import typing as t
from typing import Any, Dict, List

import jsonpath_ng

from presskit.sources.base import FileSource, ConnectionError, QueryError

logger = logging.getLogger(__name__)


class JSONSource(FileSource):
    """JSON file data source with JSONPath query support."""

    def __init__(self, config, site_dir=None):
        super().__init__(config, site_dir)
        self._data: t.Optional[Any] = None

    @classmethod
    def get_required_dependencies(cls) -> List[str]:
        """JSON is built into Python, but we use jsonpath-ng for querying."""
        return ["jsonpath_ng"]

    async def connect(self) -> None:
        """
        Load JSON data from file.

        Raises:
            ConnectionError: If file cannot be loaded
        """
        if self._is_connected:
            return

        if not self.config.path:
            raise ConnectionError("JSON source requires 'path' configuration")

        try:
            # Resolve path relative to site directory if needed
            if self.site_dir:
                json_path = self.config.get_resolved_path(Path(self.site_dir))
                if not json_path:
                    raise ConnectionError("JSON source requires 'path' configuration")
            else:
                json_path = Path(self.config.path)

            if not json_path.exists():
                raise ConnectionError(f"JSON file not found: {json_path}")

            with open(json_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

            self._is_connected = True
            logger.debug(f"Loaded JSON data from: {json_path}")

        except json.JSONDecodeError as e:
            raise ConnectionError(f"Invalid JSON in file {json_path}: {e}")
        except Exception as e:
            raise ConnectionError(f"Failed to load JSON file: {e}")

    async def disconnect(self) -> None:
        """Clear loaded data."""
        self._data = None
        self._is_connected = False
        logger.debug("Disconnected from JSON source")

    async def load_data(self) -> Any:
        """
        Load the complete JSON data.

        Returns:
            Complete JSON data structure

        Raises:
            ConnectionError: If not connected
        """
        if not self._is_connected:
            raise ConnectionError("Not connected to JSON source")
        return self._data

    async def execute_query(self, query: str, variables: t.Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute JSONPath query on the data.

        Args:
            query: JSONPath expression
            variables: Variables for query (not used in basic implementation)

        Returns:
            List of matching data items (converted to dictionaries where possible)

        Raises:
            ConnectionError: If not connected
            QueryError: If query execution fails
        """
        if not self._is_connected:
            raise ConnectionError("Not connected to JSON source")

        try:
            # Parse JSONPath expression
            jsonpath_expr = jsonpath_ng.parse(query)

            # Execute query
            matches = jsonpath_expr.find(self._data)

            # Convert results to list of dictionaries
            results = []
            for match in matches:
                value = match.value

                # Convert to dictionary if possible
                if isinstance(value, dict):
                    results.append(value)
                elif isinstance(value, list):
                    # If it's a list of dicts, extend results
                    for item in value:
                        if isinstance(item, dict):
                            results.append(item)
                        else:
                            # Wrap primitive values in a dictionary
                            results.append({"value": item})
                else:
                    # Wrap primitive values in a dictionary
                    results.append({"value": value})

            logger.debug(f"JSONPath query '{query}' returned {len(results)} items")
            return results

        except Exception as e:
            raise QueryError(f"JSONPath query failed: {e}")

    async def execute_simple_query(self, path: str) -> Any:
        """
        Execute a simple dot-notation path query.

        Args:
            path: Dot-separated path (e.g., "users.0.name")

        Returns:
            Value at the specified path

        Raises:
            QueryError: If path is invalid
        """
        if not self._is_connected:
            raise ConnectionError("Not connected to JSON source")

        try:
            current = self._data

            for key in path.split("."):
                if isinstance(current, dict):
                    current = current[key]
                elif isinstance(current, list):
                    current = current[int(key)]
                else:
                    raise KeyError(f"Cannot access '{key}' on {type(current)}")

            return current

        except (KeyError, IndexError, ValueError) as e:
            raise QueryError(f"Invalid path '{path}': {e}")

    def validate_query(self, query: str) -> bool:
        """
        Validate JSONPath query syntax.

        Args:
            query: JSONPath expression to validate

        Returns:
            True if query is valid JSONPath
        """
        try:
            jsonpath_ng.parse(query)
            return True
        except Exception:
            return False

    async def get_keys(self, path: str = "") -> List[str]:
        """
        Get available keys at a given path.

        Args:
            path: Path to get keys for (empty for root)

        Returns:
            List of available keys
        """
        if not self._is_connected:
            raise ConnectionError("Not connected to JSON source")

        try:
            current = self._data

            if path:
                for key in path.split("."):
                    if isinstance(current, dict):
                        current = current[key]
                    elif isinstance(current, list):
                        current = current[int(key)]
                    else:
                        return []

            if isinstance(current, dict):
                return list(current.keys())
            elif isinstance(current, list):
                return [str(i) for i in range(len(current))]
            else:
                return []

        except (KeyError, IndexError, ValueError):
            return []

    async def get_schema(self) -> Dict[str, Any]:
        """
        Analyze JSON structure and return schema information.

        Returns:
            Dictionary describing the JSON structure
        """
        if not self._is_connected:
            raise ConnectionError("Not connected to JSON source")

        def analyze_structure(obj: Any, path: str = "") -> Dict[str, Any]:
            """Recursively analyze JSON structure."""
            if isinstance(obj, dict):
                return {
                    "type": "object",
                    "path": path,
                    "keys": list(obj.keys()),
                    "properties": {
                        key: analyze_structure(value, f"{path}.{key}" if path else key) for key, value in obj.items()
                    },
                }
            elif isinstance(obj, list):
                if obj:
                    # Analyze first item as representative
                    item_schema = analyze_structure(obj[0], f"{path}[0]")
                    return {"type": "array", "path": path, "length": len(obj), "item_type": item_schema}
                else:
                    return {"type": "array", "path": path, "length": 0, "item_type": None}
            else:
                return {
                    "type": type(obj).__name__,
                    "path": path,
                    "value": obj if isinstance(obj, (str, int, float, bool)) else str(obj),
                }

        return analyze_structure(self._data)

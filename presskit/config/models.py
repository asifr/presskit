"""Configuration models for presskit."""

import datetime
import multiprocessing
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from presskit.config.loader import EnvironmentLoader
from pydantic import BaseModel, Field, model_validator


def get_num_workers() -> int:
    """Get the number of worker threads based on CPU cores."""
    return min(multiprocessing.cpu_count(), 8)


class SourceDefinition(BaseModel):
    """Definition of a data source with environment variable support."""

    name: str = Field(..., description="Name of the data source")
    type: str = Field(..., description="Type of the data source")

    # Connection parameters
    host: Optional[str] = Field(None, description="Database host")
    port: Optional[int] = Field(None, description="Database port")
    database: Optional[str] = Field(None, description="Database name")
    username: Optional[str] = Field(None, description="Username")
    password: Optional[str] = Field(None, description="Password")
    path: Optional[str] = Field(None, description="File path for file-based sources")
    connection_string: Optional[str] = Field(None, description="Full connection string")

    # Source-specific options
    options: Dict[str, Any] = Field(default_factory=dict, description="Source-specific configuration")

    @model_validator(mode="after")
    def process_env_vars(self) -> "SourceDefinition":
        """Process environment variables in all string fields."""
        # Process direct fields
        for field_name in ["name", "host", "database", "username", "password", "path", "connection_string"]:
            value = getattr(self, field_name)
            if value is not None:
                setattr(self, field_name, EnvironmentLoader.load_env_value(value))

        # Process port (could be env var as string)
        if isinstance(self.port, str):
            port_value = EnvironmentLoader.load_env_value(self.port)
            self.port = int(port_value) if port_value else None

        # Process nested options
        self.options = EnvironmentLoader.process_config(self.options)

        return self

    def get_resolved_path(self, base_dir: Path) -> Optional[Path]:
        """Get resolved path for file-based sources."""
        if not self.path:
            return None

        path_str = EnvironmentLoader.resolve_path_env_vars(self.path)
        path_obj = Path(path_str)

        if not path_obj.is_absolute():
            return base_dir / path_obj
        return path_obj


class PluginConfig(BaseModel):
    """Plugin configuration."""

    name: str = Field(..., description="Plugin name or import path")
    enabled: bool = Field(True, description="Whether the plugin is enabled")
    options: Dict[str, Any] = Field(default_factory=dict, description="Plugin-specific options")

    @model_validator(mode="after")
    def process_env_vars(self) -> "PluginConfig":
        """Process environment variables in plugin configuration."""
        self.name = EnvironmentLoader.load_env_value(self.name)
        self.options = EnvironmentLoader.process_config(self.options)
        return self


class QueryDefinition(BaseModel):
    """Defines a query to execute against a data source."""

    name: str = Field(..., description="Name of the query")
    source: str = Field(..., description="Name of the source to query")
    query: str = Field(..., description="Query string (SQL, JSONPath, etc.)")
    variables: Optional[Dict[str, Any]] = Field(None, description="Variables for the query")
    generator: bool = Field(False, description="Whether this is a generator query that creates multiple pages")
    template: Optional[str] = Field(None, description="Template to use for the generated pages")
    output_path: Optional[str] = Field(None, description="Output path for the generated pages")

    @model_validator(mode="after")
    def process_env_vars(self) -> "QueryDefinition":
        """Process environment variables in query and variables."""
        # Process query string
        self.query = EnvironmentLoader.load_env_value(self.query)

        # Process variables
        if self.variables:
            self.variables = EnvironmentLoader.process_config(self.variables)

        # Process template and output_path
        if self.template:
            self.template = EnvironmentLoader.load_env_value(self.template)
        if self.output_path:
            self.output_path = EnvironmentLoader.load_env_value(self.output_path)

        return self


class SiteConfig(BaseModel):
    """Overall site configuration with environment variable support."""

    # General configuration
    title: str = Field(default="Presskit", description="Name of the site")
    description: Optional[str] = Field(default=None, description="Description of the site")
    author: Optional[str] = Field(default=None, description="Author of the site")
    url: Optional[str] = Field(default=None, description="Base URL of the site")
    version: Optional[Union[str, int, float]] = Field(default=None, description="Version of the site")
    language: str = Field(default="en-US", description="Language of the site")

    # Directory configuration
    site_dir: Path = Field(default=Path("."), description="Base site directory")
    content_dir: Path = Field(default=Path("content"), description="Content directory")
    templates_dir: Path = Field(default=Path("templates"), description="Templates directory")
    output_dir: Path = Field(default=Path("public"), description="Output directory")
    cache_dir: Path = Field(default=Path(".cache"), description="Cache directory")

    # Site settings
    default_template: str = Field(default="page", description="Default template name")
    markdown_extension: str = Field(default="md", description="Markdown file extension")

    # Build settings
    workers: int = Field(default_factory=get_num_workers, description="Number of worker threads")

    # Server settings
    server_host: str = Field(default="0.0.0.0", description="Development server host")
    server_port: int = Field(default=8000, description="Development server port")

    # Data configuration
    sources: List[SourceDefinition] = Field(default_factory=list, description="Data sources")
    queries: List[QueryDefinition] = Field(default_factory=list, description="Query definitions")
    variables: Optional[Dict[str, Any]] = Field(None, description="Global variables")
    default_source: Optional[str] = Field(None, description="Default data source")

    # Plugin configuration
    plugins: List[PluginConfig] = Field(default_factory=list, description="Plugin configurations")
    plugin_directories: List[str] = Field(default_factory=list, description="Directories to search for plugins")

    @model_validator(mode="after")
    def process_env_vars_and_resolve_paths(self) -> "SiteConfig":
        """Process environment variables and resolve paths."""
        # Process string fields for environment variables
        for field_name in [
            "title",
            "description",
            "author",
            "url",
            "language",
            "default_template",
            "markdown_extension",
            "server_host",
            "default_source",
        ]:
            value = getattr(self, field_name)
            if value is not None:
                setattr(self, field_name, EnvironmentLoader.load_env_value(value))

        # Process version (could be env var)
        if isinstance(self.version, str):
            self.version = EnvironmentLoader.load_env_value(self.version)

        # Process server_port (could be env var as string)
        if isinstance(self.server_port, str):
            port_value = EnvironmentLoader.load_env_value(self.server_port)
            self.server_port = int(port_value) if port_value else 8000

        # Process workers (could be env var as string)
        if isinstance(self.workers, str):
            workers_value = EnvironmentLoader.load_env_value(self.workers)
            self.workers = int(workers_value) if workers_value else get_num_workers()

        # Process global variables
        if self.variables:
            self.variables = EnvironmentLoader.process_config(self.variables)

        return self

    def resolve_paths(self, config_path: Path) -> None:
        """Resolve all relative paths based on config file location."""
        config_dir = config_path.parent

        # Resolve main directories
        if not self.site_dir.is_absolute():
            self.site_dir = config_dir / self.site_dir
        if not self.content_dir.is_absolute():
            self.content_dir = self.site_dir / self.content_dir
        if not self.templates_dir.is_absolute():
            self.templates_dir = self.site_dir / self.templates_dir
        if not self.output_dir.is_absolute():
            self.output_dir = self.site_dir / self.output_dir
        if not self.cache_dir.is_absolute():
            self.cache_dir = self.site_dir / self.cache_dir


def write_json_schema(output_path: Path) -> None:
    """Write the JSON schema for SiteConfig to the specified output path."""
    import json

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        schema = SiteConfig.model_json_schema()
        json.dump(schema, f, indent=2, ensure_ascii=False)


# Template Context Models (keeping existing structure)
class SiteContext(BaseModel):
    """Site-wide configuration and metadata available in all templates."""

    title: str = Field(description="Site title")
    description: Optional[str] = Field(default=None, description="Site description")
    author: Optional[str] = Field(default=None, description="Site author")
    url: Optional[str] = Field(default=None, description="Base site URL")
    version: Optional[Union[str, int, float]] = Field(default=None, description="Site version")
    language: str = Field(default="en-US", description="Site language")


class BuildContext(BaseModel):
    """Build-time information available in all templates."""

    date: str = Field(description="Build date (YYYY-MM-DD)")
    year: str = Field(description="Build year")
    timestamp: datetime.datetime = Field(description="Full build timestamp")
    iso_date: str = Field(description="Build date in ISO format")


class PageContext(BaseModel):
    """Page-specific information available in templates."""

    filename: str = Field(description="Page filename without extension")
    filepath: str = Field(description="Full file path")
    path: str = Field(description="Clean URL path")
    content: Optional[str] = Field(default=None, description="Processed HTML content")
    layout: str = Field(description="Template layout name")
    title: Optional[str] = Field(default=None, description="Page title from front matter")
    description: Optional[str] = Field(default=None, description="Page description from front matter")


class DataContext(BaseModel):
    """Data available in templates from queries and sources."""

    queries: Dict[str, Any] = Field(default_factory=dict, description="Results from named queries")
    sources: Dict[str, Any] = Field(default_factory=dict, description="JSON data sources")
    page_queries: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=dict, description="Page-specific query results"
    )


class TemplateContext(BaseModel):
    """Complete template context combining all data sources."""

    site: SiteContext = Field(description="Site-wide configuration")
    build: BuildContext = Field(description="Build-time information")
    page: PageContext = Field(description="Page-specific information")
    data: DataContext = Field(description="Data from queries and sources")
    extras: Dict[str, Any] = Field(default_factory=dict, description="Extra variables from front matter")

    def to_template_vars(self) -> Dict[str, Any]:
        """Convert to flat dictionary for template rendering."""
        template_vars = {
            "site": self.site.model_dump(),
            "build": self.build.model_dump(),
            "page": self.page.model_dump(),
            "data": self.data.model_dump(),
        }

        # Add extras at top level
        template_vars.update(self.extras)

        return template_vars


class QueryCache(BaseModel):
    """Structure for cached query results."""

    metadata: Dict[str, Any] = Field(default_factory=dict, description="Cache metadata")
    queries: Dict[str, Any] = Field(default_factory=dict, description="Regular query results")
    generators: Dict[str, Any] = Field(default_factory=dict, description="Generator query results")
    data: Dict[str, Any] = Field(default_factory=dict, description="JSON data sources")

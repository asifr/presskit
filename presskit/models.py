import datetime
import multiprocessing
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal


def get_num_workers() -> int:
    """Get the number of worker threads based on CPU cores."""
    return min(multiprocessing.cpu_count(), 8)  # Default to 8 or number of CPU cores, whichever is lower


class SourceDefinition(BaseModel):
    """Definition of a data source."""

    type: Literal["sqlite", "json"] = Field(..., description="Type of the data source")
    path: Path = Field(..., description="Path to the data source file")


class QueryDefinition(BaseModel):
    """Defines a query to execute against a data source."""

    name: str = Field(..., description="Name of the query")
    source: str = Field(..., description="Name of the source to query")
    query: str = Field(..., description="SQL query string")
    variables: Optional[Dict[str, Any]] = Field(None, description="Variables for the SQL query")
    generator: bool = Field(False, description="Whether this is a generator query that creates multiple pages")
    template: Optional[str] = Field(None, description="Template to use for the generated pages")
    output_path: Optional[str] = Field(None, description="Output path for the generated pages")


class SiteConfig(BaseModel):
    """Overall site configuration."""

    # General configuration
    title: str = Field(default="Presskit", description="Name of the site")
    description: Optional[str] = Field(default=None, description="Description of the site")
    author: Optional[str] = Field(default=None, description="Author of the site")
    url: Optional[str] = Field(default=None, description="Base URL of the site")
    version: Optional[str | int | float] = Field(default=None, description="Version of the site")
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
    sources: Dict[str, SourceDefinition] = Field(default_factory=dict, description="Data sources")
    queries: List[QueryDefinition] = Field(default_factory=list, description="Query definitions")
    variables: Optional[Dict[str, Any]] = Field(None, description="Global variables")
    default_source: Optional[str] = Field(None, description="Default data source")

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

        # Resolve source paths
        for source in self.sources.values():
            if not source.path.is_absolute():
                source.path = self.site_dir / source.path


# Template Context Models
class SiteContext(BaseModel):
    """Site-wide configuration and metadata available in all templates."""

    title: str = Field(description="Site title")
    description: Optional[str] = Field(default=None, description="Site description")
    author: Optional[str] = Field(default=None, description="Site author")
    url: Optional[str] = Field(default=None, description="Base site URL")
    version: Optional[str | int | float] = Field(default=None, description="Site version")
    language: str = Field(default="en-US", description="Site language")


class BuildContext(BaseModel):
    """Build-time information available in all templates."""

    date: str = Field(description="Build date in YYYY-MM-DD format")
    year: str = Field(description="Build year")
    timestamp: datetime.datetime = Field(description="Full build timestamp")
    iso_date: str = Field(description="Build date in ISO format")


class PageContext(BaseModel):
    """Page-specific context for individual files."""

    filename: str = Field(description="Page filename without extension")
    filepath: str = Field(description="Full file path")
    path: str = Field(description="Clean URL path (no extension, relative to content)")
    layout: str = Field(description="Template layout to use")
    content: Optional[str] = Field(None, description="Processed HTML content")
    title: Optional[str] = Field(None, description="Page title from front matter")
    description: Optional[str] = Field(None, description="Page description from front matter")


class DataContext(BaseModel):
    """Data from queries and sources."""

    queries: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict, description="Named query results")
    sources: Dict[str, Any] = Field(default_factory=dict, description="JSON data sources")
    page_queries: Dict[str, List[Dict[str, Any]]] = Field(
        default_factory=dict, description="Page-specific query results"
    )


class TemplateContext(BaseModel):
    """Complete template context combining all variable categories."""

    site: SiteContext = Field(description="Site-wide configuration and metadata")
    build: BuildContext = Field(description="Build-time information")
    page: PageContext = Field(description="Page-specific context")
    data: DataContext = Field(description="Data from queries and sources")
    extras: Dict[str, Any] = Field(default_factory=dict, description="Additional front matter variables")

    def to_template_vars(self) -> Dict[str, Any]:
        """Convert to dictionary for Jinja2 template rendering."""
        result = {
            "site": self.site.model_dump(),
            "build": self.build.model_dump(),
            "page": self.page.model_dump(),
            "data": self.data.model_dump(),
        }

        # Add front matter variables at top level for convenience
        result.update(self.extras)

        return result


class QueryCache(BaseModel):
    """Structure for caching query results."""

    metadata: Dict[str, Any]
    queries: Dict[str, List[Dict[str, Any]]]
    generators: Dict[str, List[Dict[str, Any]]]
    data: Dict[str, Any]

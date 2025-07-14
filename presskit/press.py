"""
presskit - A static site generator for creating websites from markdown files and Jinja templates.
"""

import re
import sys
import json
import yaml
import asyncio
import argparse
import markdown
import datetime
import multiprocessing
from pathlib import Path
from markupsafe import Markup
from functools import partial
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
from jinja2.exceptions import TemplateError
from typing import Dict, List, Optional, Any, TypeVar
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Environment, FileSystemLoader, select_autoescape
from watchfiles import watch
from presskit.utils import print_error, print_warning, print_success, print_info, print_progress
from presskit.config.models import (
    SiteConfig,
    SiteContext,
    BuildContext,
    PageContext,
    DataContext,
    TemplateContext,
)
from presskit.core.query import QueryProcessor
from presskit.sources.registry import get_registry
from presskit.config.loader import EnvironmentLoader, ConfigError

T = TypeVar("T")  # Type variables for generic functions


# Context Builder Functions
def build_site_context(config: SiteConfig) -> SiteContext:
    """Build site context from configuration."""
    return SiteContext(
        title=config.title,
        description=config.description,
        author=config.author,
        url=config.url,
        version=config.version,
        language=config.language,
    )


def build_build_context() -> BuildContext:
    """Build context with build-time information."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return BuildContext(
        date=now.strftime("%Y-%m-%d"),
        year=now.strftime("%Y"),
        timestamp=now,
        iso_date=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def build_page_context(file_path: Path, config: SiteConfig, front_matter: Dict[str, Any]) -> PageContext:
    """Build page context for a specific file."""
    file_name = file_path.stem
    file_path_clean = str(file_path.resolve().relative_to(config.content_dir)).replace(
        f".{config.markdown_extension}", ""
    )

    return PageContext(
        filename=file_name,
        filepath=str(file_path),
        path=file_path_clean,
        content=None,
        layout=front_matter.get("layout", config.default_template),
        title=front_matter.get("title"),
        description=front_matter.get("description"),
    )


def build_data_context(
    query_cache: Optional[Dict[str, Any]], page_queries: Dict[str, List[Dict[str, Any]]]
) -> DataContext:
    """Build data context from cache and page queries."""
    return DataContext(
        queries=query_cache.get("queries", {}) if query_cache else {},
        sources=query_cache.get("data", {}) if query_cache else {},
        page_queries=page_queries,
    )


@dataclass(frozen=True)
class CommandArgs:
    """Simplified command arguments - only config file path."""

    config: Path


def find_config_file(config_arg: Optional[str] = None) -> Path:
    """
    Find the configuration file.

    Args:
        config_arg: Optional config file path from command line

    Returns:
        Path to the configuration file

    Raises:
        FileNotFoundError: If config file not found
    """
    if config_arg:
        config_path = Path(config_arg).resolve()
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        return config_path

    # Look for config in current directory
    default_config = Path.cwd() / "presskit.json"
    if not default_config.exists():
        raise FileNotFoundError(
            f"Config file not found: {default_config}. Create a presskit.json file or specify one with --config."
        )

    return default_config


def load_site_config(config_path: Path) -> SiteConfig:
    """
    Load and validate site configuration from presskit.json with environment variable support.

    Args:
        config_path: Path to the configuration file

    Returns:
        Validated SiteConfig object

    Raises:
        ConfigError: If the configuration couldn't be loaded or is invalid
    """
    try:
        with open(config_path, "r") as f:
            data = json.load(f)

        # Process environment variables
        processed_data = EnvironmentLoader.process_config(data)

        config = SiteConfig(**processed_data)
        config.resolve_paths(config_path)
        return config

    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise ConfigError(f"Error loading configuration file {config_path}: {e}")
    except ValueError as e:
        raise ConfigError(f"Invalid configuration in {config_path}: {e}")
    except Exception as e:
        raise ConfigError(f"Error processing configuration: {e}")


class BuildError(Exception):
    """Exception raised for errors in the build process."""

    pass


class TemplateRenderingError(Exception):
    """Exception raised for errors in template rendering."""

    pass


def get_cwd() -> Path:
    """Get the current working directory."""
    return Path.cwd()


def cwd_relpath(path: str) -> Path:
    """Convert a relative path to an absolute path based on the current working directory."""
    return get_cwd() / path


@dataclass(frozen=True)
class BuildCommandArgs:
    """Arguments for build command."""

    sitedir: Path = field(default_factory=get_cwd)
    """Site directory."""
    outdir: Path = field(default_factory=lambda: cwd_relpath("./public"))
    """Output directory for generated HTML files."""
    config: Path = field(default_factory=lambda: cwd_relpath("./presskit.json"))
    """Config JSON file."""
    workers: int = 8
    """Number of worker threads, default is 8 or CPU cores, whichever is lower."""
    file: Optional[str] = None
    """Optional specific file to build."""

    def __post_init__(self):
        # Ensure that site directory exists
        if not self.sitedir.exists():
            self.sitedir.mkdir(parents=True, exist_ok=True)

        # Ensure that output directory exists
        if not self.outdir.exists():
            self.outdir.mkdir(parents=True, exist_ok=True)

        # Only check for config file if it's not the default path
        # This allows for optional config files
        if self.config != cwd_relpath("./presskit.json") and not self.config.exists():
            raise FileNotFoundError(f"Config file not found: {self.config}")


@dataclass(frozen=True)
class ServerCommandArgs:
    """Arguments for server command."""

    outdir: Path = field(default_factory=lambda: cwd_relpath("./public"))
    """Directory to serve HTML files."""
    host: str = "0.0.0.0"
    """Host to bind the server to."""
    port: int = 8000
    """Port to run the server on."""

    def __post_init__(self):
        # Create output directory if it doesn't exist
        if not self.outdir.exists():
            self.outdir.mkdir(parents=True, exist_ok=True)

        # Ensure that output directory is a directory
        if not self.outdir.is_dir():
            raise NotADirectoryError(f"Output path is not a directory: {self.outdir}")


class SitePaths(BaseModel):
    """Standard site directory paths."""

    content_dir: Path = Field(..., description="Content directory path")
    templates_dir: Path = Field(..., description="Templates directory path")
    cache_dir: Path = Field(..., description="Cache directory path")
    config_file: Path = Field(..., description="Configuration file path")
    query_cache_file: Path = Field(..., description="Query cache file path")


def get_site_paths(sitedir: Path) -> SitePaths:
    """
    Get standard site directory paths.

    Args:
        sitedir: Base site directory

    Returns:
        SitePaths object with all standard paths
    """
    content_dir = sitedir / "content"
    templates_dir = sitedir / "templates"
    cache_dir = sitedir / ".cache"
    config_file = sitedir / "presskit.json"
    query_cache_file = cache_dir / "queries.json"

    return SitePaths(
        content_dir=content_dir,
        templates_dir=templates_dir,
        cache_dir=cache_dir,
        config_file=config_file,
        query_cache_file=query_cache_file,
    )


def ensure_directories(config: SiteConfig) -> None:
    """
    Ensure required directories exist.

    Args:
        config: Site configuration
    """
    # Create directories if they don't exist
    config.content_dir.mkdir(exist_ok=True, parents=True)
    config.templates_dir.mkdir(exist_ok=True, parents=True)
    config.cache_dir.mkdir(exist_ok=True, parents=True)
    config.output_dir.mkdir(exist_ok=True, parents=True)


def get_query_cache_file(config: SiteConfig) -> Path:
    """Get the query cache file path."""
    return config.cache_dir / "queries.json"


def check_query_cache(config: SiteConfig) -> bool:
    """
    Check if query cache exists and is valid.

    Args:
        config: Site configuration

    Returns:
        True if cache exists and is valid, False otherwise
    """
    query_cache_file = get_query_cache_file(config)

    if not query_cache_file.exists():
        return False

    # Attempt to load cache to validate it
    cache_data = load_json(query_cache_file)
    if not cache_data:
        return False

    # Check for required sections
    if not all(k in cache_data for k in ["metadata", "queries", "generators"]):
        print_warning("Cache file exists but is missing required sections.")
        return False

    return True


async def process_queries(config: SiteConfig) -> bool:
    """
    Process all queries in presskit.json and cache results using new async system.

    Args:
        config: Site configuration

    Returns:
        True if successful, False otherwise
    """
    print("Processing queries from presskit.json...")

    try:
        query_cache_file = get_query_cache_file(config)

        # Use new async query processor
        processor = QueryProcessor()
        cache_data = await processor.process_all_queries(config)

        # Save cache to file
        if save_json(cache_data, query_cache_file):
            print_success("Query processing complete.")
            print_info(f"Cached to: {query_cache_file}")
            return True
        else:
            print_error(f"Failed to save cache to {query_cache_file}")
            return False

    except Exception as e:
        print_error(f"Error processing queries: {e}")
        return False


# Legacy query processing functions removed - using new async QueryProcessor


# Legacy data source loading functions removed - using new modular source system


def build_file(file_path: Path, query_cache: Optional[Dict[str, Any]], config: SiteConfig) -> bool:
    """
    Build a single markdown file with structured template context.

    Args:
        file_path: Path to the markdown file
        query_cache: Query cache data
        config: Site configuration

    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"Building: {file_path}")

        # Read file content
        with open(file_path, "r") as f:
            content = f.read()

        # Extract front matter, content, and queries
        front_matter, md_content, md_queries = extract_front_matter(content)

        # Process markdown file's queries if any
        page_query_results = {}
        if md_queries:
            # Build temporary context for processing queries
            temp_context = TemplateContext(
                site=build_site_context(config),
                build=build_build_context(),
                page=build_page_context(file_path, config, front_matter),
                data=build_data_context(query_cache, {}),
            )
            # Use async query processor for markdown queries
            processor = QueryProcessor()
            page_query_results = asyncio.run(
                processor.process_markdown_queries(md_queries, temp_context.to_template_vars(), config)
            )

        # Build structured context
        site_ctx = build_site_context(config)
        build_ctx = build_build_context()
        page_ctx = build_page_context(file_path, config, front_matter)
        data_ctx = build_data_context(query_cache, page_query_results)

        # Create complete template context
        template_context = TemplateContext(
            site=site_ctx, build=build_ctx, page=page_ctx, data=data_ctx, extras=front_matter
        )

        # Process markdown content with context
        html_content = process_markdown(md_content, template_context.to_template_vars(), config.content_dir)

        # Update page context with processed content
        template_context.page.content = html_content

        # Process HTML template
        output_html = process_template(
            template_context.page.layout, template_context.to_template_vars(), config.templates_dir
        )

        # Determine output path
        relative_path = file_path.resolve().relative_to(config.content_dir.resolve())
        output_dir = config.output_dir / relative_path.parent
        output_dir.mkdir(exist_ok=True, parents=True)
        output_file = output_dir / f"{template_context.page.filename}.html"

        # Write output file
        with open(output_file, "w") as f:
            f.write(output_html)

        print_success(f"Built: {output_file}")
        return True
    except (FileNotFoundError, IOError) as e:
        print_error(f"File error processing {file_path}: {e}")
        return False
    except TemplateError as e:
        print_error(f"Template error processing {file_path}: {e}")
        return False
    except Exception as e:
        print_error(f"Unexpected error processing {file_path}: {e}")
        return False


def build_parallel(files: List[Path], query_cache: Optional[Dict[str, Any]], config: SiteConfig) -> bool:
    """
    Build multiple files in parallel with progress tracking.

    Args:
        files: List of files to build
        query_cache: Query cache data
        config: Site configuration

    Returns:
        True if all files built successfully, False otherwise
    """
    max_workers = min(config.workers, multiprocessing.cpu_count())
    total_files = len(files)
    print_info(f"Building {total_files} files using {max_workers} workers...")

    # Track progress
    completed = 0
    failed = 0
    success_paths: List[Path] = []
    failed_paths: List[Path] = []

    # Use ThreadPoolExecutor for IO-bound operations
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_file = {executor.submit(build_file, file, query_cache, config): file for file in files}

        # Print initial progress
        print_progress(completed, total_files)

        # Process as they complete
        for future in as_completed(future_to_file):
            file = future_to_file[future]
            try:
                result = future.result()
                if result:
                    success_paths.append(file)
                else:
                    failed += 1
                    failed_paths.append(file)
            except Exception as e:
                failed += 1
                failed_paths.append(file)
                print_error(f"Error building {file}: {e}")

            completed += 1
            # Update progress every 5% or for every file if few files
            if completed % max(1, total_files // 20) == 0 or completed == total_files:
                print_progress(completed, total_files)

    # Final status
    if failed == 0:
        print_success(f"Successfully built all {total_files} files")
        return True
    else:
        print_error(f"Built {completed - failed} files successfully, {failed} files failed")
        # Print failed files if there aren't too many
        if failed <= 10:
            print_error("Failed files:")
            for path in failed_paths:
                print_error(f"  - {path}")
        return False


def process_generators(config: SiteConfig) -> bool:
    """
    Process generator queries and create pages with structured context.

    Args:
        config: Site configuration

    Returns:
        True if successful, False otherwise
    """
    print("Processing generator queries...")

    query_cache_file = get_query_cache_file(config)

    # Load query cache
    cache_data = load_json(query_cache_file)
    if not cache_data:
        return False

    # Get generator queries
    generators = cache_data.get("generators", {})
    if not generators:
        print_warning("No generator queries found in cache.")
        return False

    # Track progress
    total_generators = len(generators)
    total_pages = sum(len(results) for results in generators.values())
    generated_pages = 0
    failed_pages = 0

    print_info(f"Found {total_generators} generators with {total_pages} total pages to generate")

    # Process each generator
    for query_name, results in generators.items():
        print(f"Processing generator: {query_name} ({len(results)} pages)")

        # Find the query definition
        query_def = next((q for q in config.queries if q.name == query_name), None)
        if not query_def:
            print_warning(f"Query definition not found for: {query_name}")
            continue

        # Get template name
        template_name = query_def.template or "page"
        template_file = config.templates_dir / f"{template_name}.html"

        if not template_file.exists():
            print_error(f"Template not found: {template_file}")
            continue

        # Get output path pattern
        output_path = query_def.output_path
        if not output_path:
            print_warning(f"No output_path defined for generator: {query_name}")
            continue

        # Process each row in the results
        for row in results:
            try:
                # Replace placeholders in the output path
                actual_path = replace_path_placeholders(output_path, row)

                # Create necessary directories
                output_dir = config.output_dir / Path(actual_path).parent
                output_dir.mkdir(exist_ok=True, parents=True)

                # Build structured context for generator page
                site_ctx = build_site_context(config)
                build_ctx = build_build_context()

                # Create page context for generated page
                page_ctx = PageContext(
                    filename=Path(actual_path).stem,
                    filepath=actual_path,
                    path=actual_path,
                    content=None,
                    layout=template_name,
                    title=row.get("title"),
                    description=row.get("description"),
                )

                data_ctx = build_data_context(cache_data, {})

                # Create template context with row data as front matter
                template_context = TemplateContext(
                    site=site_ctx, build=build_ctx, page=page_ctx, data=data_ctx, extras=row
                )

                # Process the template
                output_html = process_template(template_name, template_context.to_template_vars(), config.templates_dir)

                # Write output file
                output_file = config.output_dir / f"{actual_path}.html"
                with open(output_file, "w") as f:
                    f.write(output_html)

                generated_pages += 1
                # Periodically show progress
                if generated_pages % max(1, total_pages // 10) == 0:
                    print_progress(generated_pages + failed_pages, total_pages, "Generator progress")

            except Exception as e:
                failed_pages += 1
                print_error(f"Error generating page {actual_path}: {e}")

    # Final progress update
    print_progress(generated_pages + failed_pages, total_pages, "Generator progress")

    if failed_pages == 0:
        print_success(f"Successfully generated {generated_pages} pages from {total_generators} generators")
        return True
    else:
        print_warning(f"Generated {generated_pages} pages with {failed_pages} failures")
        return generated_pages > 0


def load_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Load JSON from a file with proper error handling.

    Args:
        file_path: Path to the JSON file

    Returns:
        Parsed JSON data as dictionary or None if file not found or invalid
    """
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print_error(f"File not found: {file_path}")
        return None
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON in {file_path}: {e}")
        return None


def save_json(data: Dict[str, Any] | BaseModel, file_path: Path) -> bool:
    """
    Save data as JSON to a file.

    Args:
        data: Data to save
        file_path: Path where the JSON file will be saved

    Returns:
        True if successful, False otherwise
    """
    try:
        if isinstance(data, BaseModel):
            # Convert Pydantic model to dict
            data = data.model_dump()
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except (IOError, TypeError) as e:
        print_error(f"Error saving JSON to {file_path}: {e}")
        return False


def sanitize_value(value: Any) -> str:
    """
    Sanitize a value for use in a file path.

    Args:
        value: The value to sanitize

    Returns:
        Sanitized string suitable for use in a file path
    """
    if value is None:
        return "uncategorized"
    # Convert to string, replace spaces with hyphens, and remove special chars
    return re.sub(r"[^a-zA-Z0-9\-_]", "", str(value).replace(" ", "-"))


def replace_path_placeholders(path_template: str, row: Dict[str, Any]) -> str:
    """
    Replace placeholders in a path template with values from a row.

    Args:
        path_template: Template string with placeholders like #{FieldName}
        row: Dictionary with values to use for replacement

    Returns:
        Path with placeholders replaced by actual values
    """
    # Find all placeholders in the format #{FieldName}
    placeholders = re.findall(r"#{([A-Za-z0-9_\.]*)}", path_template)
    result = path_template

    for field_name in placeholders:
        # Handle nested fields (with dots)
        if "." in field_name:
            parent, child = field_name.split(".", 1)
            if parent in row and row[parent] and len(row[parent]) > 0:
                field_value = row[parent][0].get(child, "")
            else:
                field_value = ""
        else:
            # Get value from row
            field_value = row.get(field_name, "")

        # Sanitize value for filesystem use
        sanitized_value = sanitize_value(field_value)

        # Replace placeholder in path
        result = result.replace(f"#{{{field_name}}}", sanitized_value)

    return result


def data_status(config: SiteConfig) -> None:
    """
    Display query cache status.

    Args:
        config: Site configuration
    """
    site_paths = get_site_paths(config.site_dir)

    print("Query cache status:")

    if check_query_cache(config):
        print_success(f"Cache exists: {site_paths.query_cache_file}")

        # Load cache data
        cache_data = load_json(site_paths.query_cache_file)
        if not cache_data:
            return

        # Display metadata
        print("Cache metadata:")
        print(json.dumps(cache_data.get("metadata", {}), indent=2))

        # Display available queries
        print("Regular queries:")
        print(json.dumps(list(cache_data.get("queries", {}).keys()), indent=2))

        # Display available generators
        print("Generator queries:")
        print(json.dumps(list(cache_data.get("generators", {}).keys()), indent=2))

        # Display available data sources
        print("JSON data sources:")
        print(json.dumps(list(cache_data.get("data", {}).keys()), indent=2))
    else:
        print_warning("No cache found or cache is invalid.")
        print("Run 'presskit data' to execute queries and create cache.")


def extract_front_matter(content: str) -> tuple[Dict[str, Any], str, Dict[str, Any]]:
    """
    Extract YAML front matter from a markdown file.

    Args:
        content: File content with optional YAML front matter

    Returns:
        Tuple of (front_matter, content_without_fm, queries)
    """
    front_matter: Dict[str, Any] = {}
    queries: Dict[str, Any] = {}
    content_without_fm = content

    # Check for front matter
    fm_match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if fm_match:
        try:
            front_matter = yaml.safe_load(fm_match.group(1))
            content_without_fm = fm_match.group(2)

            # Extract queries if they exist in front matter
            if "queries" in front_matter:
                queries = front_matter.pop("queries")
        except yaml.YAMLError as e:
            print_error(f"Error parsing front matter: {e}")

    return front_matter, content_without_fm, queries


def date_format(value: str, format: str) -> str:
    """
    Jinja filter to format date strings from YYYY-MM-DD to any format.

    Args:
        value: Date string in YYYY-MM-DD format
        format: Desired output format
    """
    try:
        date_obj = datetime.datetime.strptime(str(value), "%Y-%m-%d")
        return date_obj.strftime(format)
    except ValueError:
        print_error(f"Invalid date format: {value}")
        return value


JINJA_FILTERS = {
    "date_format": date_format,
}


def process_sql_template(sql_query: str, variables: Dict[str, Any]) -> str:
    """
    Process SQL query with Jinja2 templating.

    Args:
        sql_query: SQL query template
        variables: Variables to substitute in the template

    Returns:
        Processed SQL query with variables substituted

    Raises:
        TemplateRenderingError: If template processing fails
    """
    try:
        env = Environment()
        env.filters.update(JINJA_FILTERS)
        template = env.from_string(sql_query)
        processed_sql = template.render(**variables)
        return processed_sql
    except TemplateError as e:
        raise TemplateRenderingError(f"Error processing SQL template: {e}")


def process_markdown(md_content: str, variables: Dict[str, Any], content_dir: Path) -> str:
    """
    Process markdown content with Jinja2 templating and convert to HTML.

    Args:
        md_content: Markdown content with optional Jinja2 templating
        variables: Variables to substitute in the template
        content_dir: Content directory for template loading

    Returns:
        HTML content

    Raises:
        TemplateRenderingError: If template processing fails
    """
    try:
        # Create Jinja2 environment
        env = Environment(
            loader=FileSystemLoader(content_dir),
            autoescape=select_autoescape(["html", "xml"]),
            extensions=["jinja2.ext.debug"],
        )
        env.filters.update(JINJA_FILTERS)

        # Create template from string
        template = env.from_string(md_content)

        # Render template with variables
        processed_md = template.render(**variables)

        # Convert markdown to HTML
        html_content = markdown.markdown(
            processed_md,
            extensions=[
                "tables",
                "fenced_code",
                "toc",
                "meta",
                "md_in_html",
                "codehilite",
                "attr_list",
                "pymdownx.arithmatex",
                "pymdownx.blocks.caption",
                "pymdownx.blocks.admonition",
                "pymdownx.inlinehilite",
            ],
            extension_configs={
                "codehilite": {"css_class": "highlight"},
                "pymdownx.arithmatex": {"generic": True},
            },
        )

        return html_content
    except TemplateError as e:
        raise TemplateRenderingError(f"Error processing markdown template: {e}")


# Legacy markdown query processing removed - using new async QueryProcessor.process_markdown_queries


def process_template(template_name: str, variables: Dict[str, Any], templates_dir: Path) -> str:
    """
    Process an HTML template with Jinja2.

    Args:
        template_name: Name of the template (without extension)
        variables: Variables to substitute in the template
        templates_dir: Templates directory

    Returns:
        Rendered HTML

    Raises:
        TemplateError: If template processing fails
    """
    try:
        # Create Jinja2 environment
        env = Environment(
            loader=FileSystemLoader(templates_dir),
            autoescape=select_autoescape(["html", "xml"]),
            extensions=["jinja2.ext.debug"],
        )
        env.filters.update(JINJA_FILTERS)

        # Mark content variable as safe HTML if it exists
        if "page" in variables and "content" in variables["page"]:
            variables["page"]["content"] = Markup(variables["page"]["content"])

        # Remove the extension from the template name
        if template_name.endswith(".html"):
            template_name = template_name[:-5]

        # Check if template exists, otherwise use default
        template_path = templates_dir / f"{template_name}.html"
        if not template_path.exists():
            print_warning(f"Template '{template_name}.html' not found. Using page.html instead.")
            template_name = "page"

        # Get template
        template = env.get_template(f"{template_name}.html")

        # Render template with variables
        return template.render(**variables)
    except TemplateError as e:
        raise TemplateRenderingError(f"Error processing template {template_name}: {e}")


def cmd_data(config: SiteConfig) -> bool:
    """
    Execute all queries and cache results using new async system.

    Args:
        config: Site configuration

    Returns:
        True if successful, False otherwise
    """
    print("Refreshing query cache...")
    ensure_directories(config)
    return asyncio.run(process_queries(config))


def cmd_data_status(config: SiteConfig) -> bool:
    """
    Show query cache status.

    Args:
        config: Site configuration

    Returns:
        True if successful, False otherwise
    """
    query_cache_file = get_query_cache_file(config)

    print("Query cache status:")

    if check_query_cache(config):
        print_success(f"Cache exists: {query_cache_file}")

        # Load cache data
        cache_data = load_json(query_cache_file)
        if not cache_data:
            return True

        # Display metadata
        print("Cache metadata:")
        print(json.dumps(cache_data.get("metadata", {}), indent=2))

        # Display available queries
        print("Regular queries:")
        print(json.dumps(list(cache_data.get("queries", {}).keys()), indent=2))

        # Display available generators
        print("Generator queries:")
        print(json.dumps(list(cache_data.get("generators", {}).keys()), indent=2))

        # Display available data sources
        print("JSON data sources:")
        print(json.dumps(list(cache_data.get("data", {}).keys()), indent=2))
    else:
        print_warning("No cache found or cache is invalid.")
        print("Run 'presskit data' to execute queries and create cache.")

    return True


def cmd_generate(config: SiteConfig) -> bool:
    """
    Generate pages from generator queries.

    Args:
        config: Site configuration

    Returns:
        True if successful, False otherwise
    """
    print("Generating pages from queries...")

    if not check_query_cache(config):
        print_warning("No cache found or cache is invalid.")
        print("Run 'presskit data' first to execute queries and create cache.")
        return False

    return process_generators(config)


def cmd_build(config: SiteConfig, file: Optional[str] = None, reload: bool = False) -> bool:
    """
    Build the site.

    Args:
        config: Site configuration
        file: Optional specific file to build
        reload: Whether to watch for changes and rebuild automatically

    Returns:
        True if successful, False otherwise
    """
    if reload:
        print("Building with auto-reload enabled...")
        print("Watching for changes in content/, templates/, and data directories...")
        print("Press Ctrl+C to stop.")

        def do_build():
            """Perform the actual build process."""
            print("\n" + "=" * 50)
            print(f"Building at {datetime.datetime.now().strftime('%H:%M:%S')}...")

            # Ensure directories exist
            ensure_directories(config)

            # Check if query cache exists when there are sources/queries configured
            if config.sources and not check_query_cache(config):
                print_warning("Query cache not found but sources are configured.")
                print("Run 'presskit data' first to execute queries and create cache.")
                return False

            # Load query cache if available
            query_cache_file = get_query_cache_file(config)
            query_cache = load_json(query_cache_file) if check_query_cache(config) else None

            # Check if a specific file should be built
            if file:
                file_path = Path(file)
                if not file_path.exists():
                    print_error(f"File not found: {file_path}")
                    return False
                files = [file_path]
            else:
                # Build all markdown files
                files = list(config.content_dir.glob(f"**/*.{config.markdown_extension}"))

            if not files:
                print_error("No files to process!")
                return False

            print_info(f"Found {len(files)} files to process")

            # Build files - use parallel for multiple files
            build_success = False
            if len(files) == 1 or config.workers == 1:
                # Build sequentially for a single file or if workers=1
                success_count = 0
                for file_path in files:
                    if build_file(file_path, query_cache, config):
                        success_count += 1
                build_success = success_count == len(files)
            else:
                # Build in parallel for multiple files
                build_success = build_parallel(files, query_cache, config)

            # Process generator queries if available and not building a specific file
            if not file and query_cache and "generators" in query_cache:
                process_generators(config)

            if build_success:
                print_success("Build complete!")
            else:
                print_warning("Build completed with some errors.")

            return build_success

        # Initial build
        do_build()

        # Set up file watching
        watch_paths = [config.content_dir, config.templates_dir]

        # Add data directory if it exists (for JSON sources)
        data_dir = config.site_dir / "data"
        if data_dir.exists():
            watch_paths.append(data_dir)

        try:
            for changes in watch(*watch_paths):
                print(
                    f"\nDetected changes: {[str(Path(change[1]).relative_to(config.site_dir)) for change in changes]}"
                )
                do_build()
        except KeyboardInterrupt:
            print("\nStopping file watcher.")
            return True

    print("Building...")

    # Ensure directories exist
    ensure_directories(config)

    # Check if query cache exists when there are sources/queries configured
    if config.sources and not check_query_cache(config):
        print_warning("Query cache not found but sources are configured.")
        print("Run 'presskit data' first to execute queries and create cache.")
        return False

    # Load query cache if available
    query_cache_file = get_query_cache_file(config)
    query_cache = load_json(query_cache_file) if check_query_cache(config) else None

    # Check if a specific file should be built
    if file:
        file_path = Path(file)
        if not file_path.exists():
            print_error(f"File not found: {file_path}")
            return False
        files = [file_path]
    else:
        # Build all markdown files
        files = list(config.content_dir.glob(f"**/*.{config.markdown_extension}"))

    if not files:
        print_error("No files to process!")
        return False

    print_info(f"Found {len(files)} files to process")
    if len(files) <= 5:
        for f in files:
            print(f"  - {f}")

    # Build files - use parallel for multiple files
    build_success = False
    if len(files) == 1 or config.workers == 1:
        # Build sequentially for a single file or if workers=1
        success_count = 0
        for file_path in files:
            if build_file(file_path, query_cache, config):
                success_count += 1
        build_success = success_count == len(files)
    else:
        # Build in parallel for multiple files
        build_success = build_parallel(files, query_cache, config)

    # Process generator queries if available and not building a specific file
    if not file and query_cache and "generators" in query_cache:
        process_generators(config)

    if build_success:
        print_success("Build complete!")
    else:
        print_warning("Build completed with some errors.")

    return build_success


def cmd_server(config: SiteConfig, reload: bool = False) -> bool:
    """
    Start a development server.

    Args:
        config: Site configuration
        reload: Whether to watch for changes and rebuild automatically
    """
    import http.server
    import threading

    if reload:
        print("Starting server with auto-reload enabled...")
        print("Watching for changes in content/, templates/, and data directories...")
    else:
        print("Starting server...")

    # If public directory is empty, suggest building first
    if not list(config.output_dir.glob("*")):
        print_warning("Output directory is empty. Run 'presskit build' first.")

    # Set up server
    host = config.server_host
    port = config.server_port
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(config.output_dir))

    # Create server
    server = http.server.ThreadingHTTPServer((host, port), handler)

    print_success(f"Server running at http://{host}:{port}/")
    print("Press Ctrl+C to stop.")

    if reload:

        def do_build():
            """Perform the actual build process."""
            print("\n" + "=" * 50)
            print(f"Rebuilding at {datetime.datetime.now().strftime('%H:%M:%S')}...")

            # Ensure directories exist
            ensure_directories(config)

            # Check if query cache exists when there are sources/queries configured
            if config.sources and not check_query_cache(config):
                print_warning("Query cache not found but sources are configured.")
                print("Run 'presskit data' first to execute queries and create cache.")
                return False

            # Load query cache if available
            query_cache_file = get_query_cache_file(config)
            query_cache = load_json(query_cache_file) if check_query_cache(config) else None

            # Build all markdown files
            files = list(config.content_dir.glob(f"**/*.{config.markdown_extension}"))

            if not files:
                print_error("No files to process!")
                return False

            print_info(f"Found {len(files)} files to process")

            # Build files - use parallel for multiple files
            build_success = False
            if len(files) == 1 or config.workers == 1:
                # Build sequentially for a single file or if workers=1
                success_count = 0
                for file_path in files:
                    if build_file(file_path, query_cache, config):
                        success_count += 1
                build_success = success_count == len(files)
            else:
                # Build in parallel for multiple files
                build_success = build_parallel(files, query_cache, config)

            # Process generator queries if available
            if query_cache and "generators" in query_cache:
                process_generators(config)

            if build_success:
                print_success("Rebuild complete!")
            else:
                print_warning("Rebuild completed with some errors.")

            return build_success

        # Set up file watching in a separate thread
        watch_paths = [config.content_dir, config.templates_dir]

        # Add data directory if it exists (for JSON sources)
        data_dir = config.site_dir / "data"
        if data_dir.exists():
            watch_paths.append(data_dir)

        def file_watcher():
            """Watch for file changes and rebuild when needed."""
            try:
                for changes in watch(*watch_paths):
                    print(
                        f"\nDetected changes: {[str(Path(change[1]).relative_to(config.site_dir)) for change in changes]}"
                    )
                    do_build()
            except Exception as e:
                print_error(f"File watcher error: {e}")

        # Start file watcher in background thread
        watcher_thread = threading.Thread(target=file_watcher, daemon=True)
        watcher_thread.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")

    return True


def cmd_clean(config: SiteConfig) -> bool:
    """
    Clean build artifacts.

    Args:
        config: Site configuration

    Returns:
        True if successful, False otherwise
    """
    import shutil

    print("Cleaning build artifacts...")

    if config.cache_dir.exists():
        print(f"Removing contents of {config.cache_dir}...")
        # Preserve the directory but remove contents
        for item in config.cache_dir.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        print_success(f"Cleared {config.cache_dir}")

    print_success("Clean complete!")
    return True


def cmd_sources() -> bool:
    """
    List available data sources and their status.

    Returns:
        True if successful, False otherwise
    """
    print("Available data sources:")
    print()

    try:
        registry = get_registry()
        available_sources = registry.list_available_sources()
        unavailable_sources = registry.list_unavailable_sources()

        # Show available sources
        if available_sources:
            print_success("✓ Available sources:")
            for source_type in available_sources:
                try:
                    info = registry.get_source_info(source_type)
                    print(f"  • {source_type:<12} - {info.get('docstring', 'No description available').split('.')[0]}")
                except Exception:
                    print(f"  • {source_type}")
            print()

        # Show unavailable sources
        if unavailable_sources:
            print_warning("⚠ Unavailable sources (missing dependencies):")
            for source_type, missing_deps in unavailable_sources.items():
                deps_str = ", ".join(missing_deps)
                print(f"  • {source_type:<12} - Missing: {deps_str}")
                print(f"{'':16}Install with: pip install {' '.join(missing_deps)}")
            print()

        # Show installation examples
        print("Installation examples:")
        print("  pip install presskit[postgresql]  # PostgreSQL support")
        print("  pip install presskit[duckdb]      # DuckDB support")
        print("  pip install presskit[all-databases]  # All database sources")

        return True

    except Exception as e:
        print_error(f"Error listing sources: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Static site generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Global config argument
    parser.add_argument(
        "--config",
        type=str,
        help="Path to presskit.json config file (default: ./presskit.json)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Build command
    build_parser = subparsers.add_parser("build", help="Build the site")
    build_parser.add_argument("file", nargs="?", help="Specific file to build (optional)")
    build_parser.add_argument("--reload", action="store_true", help="Watch for changes and rebuild automatically")

    # Data command
    subparsers.add_parser("data", help="Execute all SQL queries and cache results")

    # Status command
    subparsers.add_parser("status", help="Show query cache status")

    # Generate command
    subparsers.add_parser("generate", help="Generate pages from generator queries")

    # Server command
    server_parser = subparsers.add_parser("server", help="Start a development server")
    server_parser.add_argument("--reload", action="store_true", help="Watch for changes and rebuild automatically")

    # Clean command
    subparsers.add_parser("clean", help="Clean build artifacts and cache")

    # Sources command
    subparsers.add_parser("sources", help="List available data sources")

    # Parse arguments
    args = parser.parse_args()

    # Find and load configuration
    try:
        config_path = find_config_file(args.config)
        config = load_site_config(config_path)
        print_info(f"Using config: {config_path}")
    except (FileNotFoundError, ConfigError) as e:
        print_error(str(e))
        sys.exit(1)

    # Route to appropriate command
    try:
        if args.command == "build":
            return cmd_build(config, getattr(args, "file", None), getattr(args, "reload", False))
        elif args.command == "data":
            return cmd_data(config)
        elif args.command == "status":
            return cmd_data_status(config)
        elif args.command == "generate":
            return cmd_generate(config)
        elif args.command == "server":
            return cmd_server(config, getattr(args, "reload", False))
        elif args.command == "clean":
            return cmd_clean(config)
        elif args.command == "sources":
            return cmd_sources()
        else:
            parser.print_help()
            sys.exit(1)
    except KeyboardInterrupt:
        print_error("Process interrupted by user")
        sys.exit(1)
    except FileNotFoundError as e:
        print_error(f"File or directory not found: {e}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

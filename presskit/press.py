"""
presskit - A static site generator for creating websites from markdown files and Jinja templates.
"""

import re
import json
import yaml
import string
import random
import asyncio
import markdown
import datetime
import unicodedata
import multiprocessing
from pathlib import Path
from watchfiles import watch
from markupsafe import Markup
from functools import partial
from pydantic import BaseModel, Field
from dataclasses import dataclass, field
from jinja2.exceptions import TemplateError
from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Environment, FileSystemLoader, select_autoescape, pass_context
from typing import Dict, List, Optional, Any, TypeVar, Union, Mapping, Sequence
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
from presskit.reload import SmartReloader, Dependencies
from presskit.plugins import call_hook
from presskit.hookspecs import PressskitContext, FileContext, ContentContext, BuildContext as PluginBuildContext

T = TypeVar("T")  # Type variables for generic functions
_alphabet = string.ascii_lowercase + string.digits
CLEANR = re.compile("<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});")


# Plugin Context Helpers
def create_presskit_context(config: SiteConfig) -> PressskitContext:
    """Create a PressskitContext from site configuration."""
    return PressskitContext(
        config=config.model_dump(),
        build_dir=config.output_dir,
        content_dir=config.content_dir,
        template_dir=config.templates_dir,
    )


def create_file_context(file_path: Path, config: SiteConfig, file_type: str = "content") -> FileContext:
    """Create a FileContext for file processing."""
    presskit_context = create_presskit_context(config)
    relative_path = file_path.relative_to(config.content_dir if file_type == "content" else config.site_dir)

    return FileContext(file_path=file_path, relative_path=relative_path, file_type=file_type, presskit=presskit_context)


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


def build_file_with_tracking(
    file_path: Path,
    query_cache: Optional[Dict[str, Any]],
    config: SiteConfig,
    smart_reloader: Optional[SmartReloader] = None,
) -> bool:
    """Build a single markdown file with dependency tracking."""
    result = build_file(file_path, query_cache, config)

    # Track dependencies if smart reloader is enabled
    if result and smart_reloader:
        try:
            # Read front matter to extract template and query dependencies
            with open(file_path, "r") as f:
                content = f.read()

            front_matter, _, md_queries, _ = extract_front_matter(content)

            # Create dependencies
            deps = Dependencies(
                templates={front_matter.get("layout", config.default_template)},
                data_sources=set(),
                queries=set(md_queries.keys()) if md_queries else set(),
            )

            # Track template usage and dependencies
            smart_reloader.update_file_state(file_path, deps)

        except Exception as e:
            print_warning(f"Failed to track dependencies for {file_path}: {e}")

    return result


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

        # Call pre_process_file hook
        file_context = create_file_context(file_path, config, "content")
        call_hook("pre_process_file", context=file_context)

        # Read file content
        with open(file_path, "r") as f:
            content = f.read()

        # Extract front matter, content, and queries
        front_matter, md_content, md_queries, md_sources = extract_front_matter(content)

        # Call plugin hooks for frontmatter processing
        content_context = ContentContext(content=md_content, frontmatter=front_matter, file_context=file_context)

        # Call process_frontmatter hook
        for result in call_hook("process_frontmatter", context=content_context):
            if result is not None:
                front_matter = result

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

        # Call extra_template_vars hook
        from presskit.hookspecs import TemplateContext as PluginTemplateContext

        plugin_template_context = PluginTemplateContext(
            template_path=None,
            template_vars=template_context.to_template_vars(),
            presskit=create_presskit_context(config),
        )

        extra_vars = {}
        for result in call_hook("extra_template_vars", context=plugin_template_context):
            if isinstance(result, dict):
                extra_vars.update(result)

        # Add extra template variables
        if extra_vars:
            template_context.extras.update(extra_vars)

        # Process markdown content with context
        html_content = process_markdown(
            md_content, template_context.to_template_vars(), config.content_dir, config, file_path
        )

        # Update page context with processed content
        template_context.page.content = html_content

        # Call prepare_page_context hook
        from presskit.hookspecs import PageContext as PluginPageContext

        plugin_page_context = PluginPageContext(
            page_data=template_context.page.__dict__,
            template_vars=template_context.to_template_vars(),
            file_context=file_context,
        )
        call_hook("prepare_page_context", context=plugin_page_context)

        # Process HTML template
        output_html = process_template(
            template_context.page.layout, template_context.to_template_vars(), config.templates_dir, config
        )

        # Determine output path
        relative_path = file_path.resolve().relative_to(config.content_dir.resolve())
        output_dir = config.output_dir / relative_path.parent
        output_dir.mkdir(exist_ok=True, parents=True)
        output_file = output_dir / f"{template_context.page.filename}.html"

        # Write output file
        with open(output_file, "w") as f:
            f.write(output_html)

        # Call post_process_file hook
        call_hook("post_process_file", context=file_context, output_path=output_file)

        print_success(f"Built: {output_file}")
        return True
    except (FileNotFoundError, IOError) as e:
        print_error(f"File error processing {file_path}: {e}")
        return False
    except TemplateError as e:
        # Call handle_template_error hook
        from presskit.hookspecs import ErrorContext

        error_context = ErrorContext(
            error=e,
            file_path=file_path,
            template_path=None,
            context_data={"message": str(e)},
            presskit=create_presskit_context(config),
        )

        # Check if any plugin handled the error
        handled = False
        for result in call_hook("handle_template_error", context=error_context):
            if result is True:
                handled = True
                break

        if not handled:
            print_error(f"Template error processing {file_path}: {e}")
        return False
    except Exception as e:
        # Call handle_build_error hook
        from presskit.hookspecs import ErrorContext

        error_context = ErrorContext(
            error=e,
            file_path=file_path,
            template_path=None,
            context_data={"message": str(e)},
            presskit=create_presskit_context(config),
        )

        # Check if any plugin handled the error
        handled = False
        for result in call_hook("handle_build_error", context=error_context):
            if result is True:
                handled = True
                break

        if not handled:
            print_error(f"Unexpected error processing {file_path}: {e}")
        return False


def build_parallel_with_tracking(
    files: List[Path],
    query_cache: Optional[Dict[str, Any]],
    config: SiteConfig,
    smart_reloader: Optional[SmartReloader] = None,
) -> bool:
    """Build multiple files in parallel with dependency tracking."""
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
        future_to_file = {
            executor.submit(build_file_with_tracking, file, query_cache, config, smart_reloader): file for file in files
        }

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


def process_generators_with_tracking(config: SiteConfig, smart_reloader: Optional[SmartReloader] = None) -> bool:
    """Process generator queries with dependency tracking."""
    result = process_generators(config)

    # Track generator states if smart reloader is enabled
    if result and smart_reloader:
        try:
            for query_def in config.queries:
                if query_def.generator:
                    smart_reloader.update_generator_state(query_def.name, query_def)
        except Exception as e:
            print_warning(f"Failed to track generator states: {e}")

    return result


def process_specific_generators(
    config: SiteConfig, generator_names: List[str], smart_reloader: Optional[SmartReloader] = None
) -> bool:
    """Process only specific generator queries."""
    print(f"Processing {len(generator_names)} specific generators...")

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

    # Filter to only requested generators
    filtered_generators = {name: results for name, results in generators.items() if name in generator_names}

    if not filtered_generators:
        print_warning(f"None of the requested generators found: {generator_names}")
        return False

    # Process each requested generator
    generated_pages = 0
    failed_pages = 0

    for query_name, results in filtered_generators.items():
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
                output_html = process_template(
                    template_name, template_context.to_template_vars(), config.templates_dir, config
                )

                # Write output file
                output_file = config.output_dir / f"{actual_path}.html"
                with open(output_file, "w") as f:
                    f.write(output_html)

                generated_pages += 1

            except Exception as e:
                failed_pages += 1
                print_error(f"Error generating page {actual_path}: {e}")

        # Track generator state if smart reloader is enabled
        if smart_reloader:
            smart_reloader.update_generator_state(query_name, query_def)

    if failed_pages == 0:
        print_success(f"Successfully generated {generated_pages} pages from {len(filtered_generators)} generators")
        return True
    else:
        print_warning(f"Generated {generated_pages} pages with {failed_pages} failures")
        return generated_pages > 0


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
                output_html = process_template(
                    template_name, template_context.to_template_vars(), config.templates_dir, config
                )

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
        sanitized_value = slugify(sanitize_value(field_value))

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


def extract_front_matter(content: str) -> tuple[Dict[str, Any], str, Dict[str, Any], Dict[str, Any]]:
    """
    Extract YAML front matter from a markdown or HTML file.

    Args:
        content: File content with optional YAML front matter

    Returns:
        Tuple of (front_matter, content_without_fm, queries, sources)
    """
    front_matter: Dict[str, Any] = {}
    queries: Dict[str, Any] = {}
    sources: Dict[str, Any] = {}
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
            
            # Extract sources if they exist in front matter
            if "sources" in front_matter:
                sources = front_matter.pop("sources")
        except yaml.YAMLError as e:
            print_error(f"Error parsing front matter: {e}")

    return front_matter, content_without_fm, queries, sources


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


def flatten(lst: List[Any]) -> List[Any]:
    """Flatten a list of lists."""
    if lst is None:
        return []
    if isinstance(lst, str):
        return [lst]
    result = []
    for item in lst:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            if item is not None:
                result.append(item)
    return result


def stringify(value: Any, sep: str = " ") -> str:
    """Turn a value or list of values into a string."""
    if isinstance(value, list):
        return sep.join(str(v) for v in flatten(value))
    return str(value)


def is_truthy(value: Any) -> bool:
    """Return True if the value is truthy."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.lower() in ["true", "yes", "1"]

    return bool(value)


def slugify(value: str, allow_unicode: bool = False, sep: str = "-"):
    """
    Convert a string to a slug. Spaces are replaced with hyphens and special characters are removed.

    Args:
        value (str): The string to slugify.
        allow_unicode (bool): Whether to allow unicode characters. Defaults to False.
        sep (str): The separator to use. Defaults to "-".

    Returns:
        str: The slugified string.

    Example:
        Convert a string to a slug.

        ```python
        slugify("Hello World")  # "hello-world"
        ```
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", sep, value)


def plainify(raw_html: str) -> str:
    """Returns a string with all HTML tags removed."""
    if not isinstance(raw_html, str) or not raw_html:
        return ""
    cleantext = re.sub(CLEANR, "", raw_html)
    return cleantext


def jsonify(obj: Union[Mapping, Sequence], **kwargs) -> str:
    """Convert an object to a JSON string. Keyword arguments are passed to json.dumps."""
    # Check if obj is a Pydantic model with a model_dump method
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()  # type: ignore
    kw = dict(
        ensure_ascii=False,
        allow_nan=False,
        indent=None,
        separators=(",", ":"),
        default=str,
        sort_keys=True,
    )
    kw.update(kwargs)
    return json.dumps(obj, **kw)  # type: ignore


def humanize(num: Union[int, float]) -> str:
    """Convert a number to a human-readable string."""
    num = float("{:.3g}".format(num))
    magnitude = 0
    while abs(num) >= 1000:
        magnitude += 1
        num /= 1000.0
    return "{}{}".format("{:f}".format(num).rstrip("0").rstrip("."), ["", "K", "M", "B", "T"][magnitude])


def short_random_id(prefix: str = "", k: int = 8, seed: Optional[int] = None) -> str:
    """Generate a random ID up to `k` chars with an optional `prefix`."""
    rng = random.Random(seed)
    choices = rng.choices(_alphabet, k=k)
    return prefix + "".join(choices)


def _template_debug_impl(context):
    """
    Generate a nicely formatted HTML display of all variables available to the template.

    This function is intended for debugging Jinja2 templates by showing all available
    variables in a collapsible, formatted HTML structure.

    Returns:
        HTML string containing formatted variable information
    """
    import html
    from datetime import datetime, date
    from markupsafe import Markup

    def format_value(value, max_length=100):
        """Format a value for display, truncating if too long."""
        if value is None:
            return '<span class="null">null</span>'
        elif isinstance(value, bool):
            return f'<span class="boolean">{str(value).lower()}</span>'
        elif isinstance(value, (int, float)):
            return f'<span class="number">{value}</span>'
        elif isinstance(value, str):
            if len(value) > max_length:
                truncated = html.escape(value[:max_length])
                return f'<span class="string">"{truncated}..." <small>({len(value)} chars)</small></span>'
            else:
                return f'<span class="string">"{html.escape(value)}"</span>'
        elif isinstance(value, (list, tuple)):
            if len(value) > 10:
                # Show first 5 and last 5 items for large lists
                first_items = [format_value(item, 50) for item in value[:5]]
                last_items = [format_value(item, 50) for item in value[-5:]]
                return f'<span class="array">[{", ".join(first_items)}, ... ({len(value) - 10} more) ..., {", ".join(last_items)}]</span>'
            elif len(value) > 5:
                items = [format_value(item, 50) for item in value[:5]]
                return f'<span class="array">[{", ".join(items)}, ... ({len(value) - 5} more)]</span>'
            else:
                items = [format_value(item, 50) for item in value]
                return f'<span class="array">[{", ".join(items)}]</span>'
        elif isinstance(value, dict):
            if len(value) > 10:
                # Show first 5 and last 5 keys for large dictionaries
                items_list = list(value.items())
                first_items = [f'"{k}": {format_value(v, 50)}' for k, v in items_list[:5]]
                last_items = [f'"{k}": {format_value(v, 50)}' for k, v in items_list[-5:]]
                return f'<span class="object">{{ {", ".join(first_items)}, ... ({len(value) - 10} more) ..., {", ".join(last_items)} }}</span>'
            elif len(value) > 5:
                items = [f'"{k}": {format_value(v, 50)}' for k, v in list(value.items())[:5]]
                return f'<span class="object">{{ {", ".join(items)}, ... ({len(value) - 5} more) }}</span>'
            else:
                items = [f'"{k}": {format_value(v, 50)}' for k, v in value.items()]
                return f'<span class="object">{{ {", ".join(items)} }}</span>'
        elif isinstance(value, (datetime, date)):
            return f'<span class="date">{value.isoformat()}</span>'
        else:
            return f'<span class="other">{html.escape(str(type(value).__name__))}</span>'

    def format_section(name, data, is_nested=False):
        """Format a section of variables."""
        if not data:
            return ""

        indent = "  " if is_nested else ""
        html_parts = []

        # Limit the number of items to prevent overwhelming output
        sorted_items = sorted(data.items())

        if len(sorted_items) > 20:
            # Show first 10 and last 10 items for very large sections
            items_to_show = sorted_items[:10] + sorted_items[-10:]
            html_parts.append(f"{indent}<div><em>Showing first 10 and last 10 of {len(sorted_items)} items</em></div>")

            for i, (key, value) in enumerate(items_to_show):
                if i == 10:
                    html_parts.append(f"{indent}<div><em>... ({len(sorted_items) - 20} items omitted) ...</em></div>")
        elif len(sorted_items) > 10:
            # Show first 10 items for moderately large sections
            items_to_show = sorted_items[:10]
            html_parts.append(f"{indent}<div><em>Showing first 10 of {len(sorted_items)} items</em></div>")
        else:
            items_to_show = sorted_items

        for key, value in items_to_show:
            if isinstance(value, dict) and len(value) > 0:
                # Nested object - use details/summary
                nested_content = format_section(f"{name}.{key}", value, True)
                html_parts.append(f"""
                {indent}<details>
                {indent}  <summary><strong>{key}</strong> <span class="object">{{ {len(value)} keys }}</span></summary>
                {indent}  <div class="nested">
                {nested_content}
                {indent}  </div>
                {indent}</details>
                """)
            else:
                # Regular value
                formatted_value = format_value(value)
                html_parts.append(f"{indent}<div><strong>{key}:</strong> {formatted_value}</div>")

        return "\n".join(html_parts)

    # Get all template variables from the provided context
    jinja_builtins = {
        "range",
        "dict",
        "list",
        "namespace",
        "cycler",
        "joiner",
        "lipsum",
        "template_debug",
        "short_random_id",
    }
    template_vars = {k: v for k, v in context.items() if k not in jinja_builtins}

    # Group variables by category
    categories = {"site": {}, "build": {}, "page": {}, "data": {}, "other": {}}

    for key, value in template_vars.items():
        if key.startswith("site"):
            categories["site"][key] = value
        elif key.startswith("build"):
            categories["build"][key] = value
        elif key.startswith("page"):
            categories["page"][key] = value
        elif key.startswith("data"):
            categories["data"][key] = value
        else:
            categories["other"][key] = value

    # Generate HTML
    html_parts = [
        """
    <div class="template-debug" style="
        background: #F5F5F5;
        border: 2px solid #dee2e6;
        border-radius: 8px;
        padding: 10px;
        margin: 20px 0;
        font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        font-size: 12px;
        line-height: 1.25;
        color: #333;
        max-width: 100%;
        overflow-x: auto;
    ">
        <h3 style="margin-top: 0; color: #495057; border-bottom: 2px solid #dee2e6; padding-bottom: 10px;">
            Template Debug
        </h3>
        
        <style>
            .template-debug .string { color: #198754; }
            .template-debug .number { color: #0d6efd; }
            .template-debug .boolean { color: #6610f2; }
            .template-debug .null { color: #495057; font-style: italic; }
            .template-debug .array { color: #fd7e14; }
            .template-debug .object { color: rgba(0, 125, 33, 1); }
            .template-debug .date { color: #d63384; }
            .template-debug .other { color: #495057; }
            .template-debug .nested { 
                margin-left: 20px; 
                border-left: 2px solid #dee2e6; 
                padding-left: 15px; 
                margin-top: 10px;
            }
            .template-debug details { margin: 5px 0; }
            .template-debug summary { 
                cursor: pointer; 
                padding: 5px;
                background: rgba(207, 207, 207, 1);
                color: #000;
                border-radius: 4px;
                margin-bottom: 5px;
            }
            .template-debug summary:hover { background: rgba(193, 193, 193, 1); }
            .template-debug div { margin: 3px 0; }
        </style>
    """
    ]

    # Add each category
    for category_name, category_data in categories.items():
        if category_data:
            html_parts.append(f"""
            <details open>
                <summary><h4 style="margin: 0; display: inline;">{category_name.title()} Variables</h4></summary>
                <div class="nested">
                    {format_section(category_name, category_data)}
                </div>
            </details>
            """)

    html_parts.append("</div>")

    return Markup("\n".join(html_parts))


@pass_context
def template_debug(context):
    """
    Context-aware template debug function that can be called from Jinja2 templates.
    """
    return _template_debug_impl(context)


JINJA_FILTERS = {
    "date_format": date_format,
    "flatten": flatten,
    "stringify": stringify,
    "is_truthy": is_truthy,
    "slugify": slugify,
    "plainify": plainify,
    "jsonify": jsonify,
    "humanize": humanize,
}

JINJA_GLOBALS = {
    "short_random_id": short_random_id,
    "template_debug": template_debug,
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
        env.globals.update(JINJA_GLOBALS)
        template = env.from_string(sql_query)
        processed_sql = template.render(**variables)
        return processed_sql
    except TemplateError as e:
        raise TemplateRenderingError(f"Error processing SQL template: {e}")


def process_markdown(
    md_content: str,
    variables: Dict[str, Any],
    content_dir: Path,
    config: Optional[SiteConfig] = None,
    file_path: Optional[Path] = None,
) -> str:
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
        env.globals.update(JINJA_GLOBALS)

        # Create template from string
        template = env.from_string(md_content)

        # Render template with variables
        processed_md = template.render(**variables)

        # Call plugin hooks for markdown processing
        if config and file_path:
            file_context = create_file_context(file_path, config, "content")
            content_context = ContentContext(
                content=processed_md, frontmatter=variables.get("page", {}), file_context=file_context
            )

            # Call process_markdown hook
            for result in call_hook("process_markdown", context=content_context):
                if result is not None:
                    processed_md = result

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


def process_template(
    template_name: str, variables: Dict[str, Any], templates_dir: Path, config: Optional[SiteConfig] = None
) -> str:
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
        env.globals.update(JINJA_GLOBALS)

        # Call plugin hooks for Jinja2 environment preparation
        if config:
            presskit_context = create_presskit_context(config)
            call_hook("prepare_jinja2_environment", env=env, context=presskit_context)

            # Get custom filters and functions from plugins
            custom_filters = {}
            custom_functions = {}
            for result in call_hook("custom_jinja_filters", context=presskit_context):
                if isinstance(result, dict):
                    custom_filters.update(result)

            for result in call_hook("custom_jinja_functions", context=presskit_context):
                if isinstance(result, dict):
                    custom_functions.update(result)

            env.filters.update(custom_filters)
            env.globals.update(custom_functions)

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


def cmd_build(config: SiteConfig, file: Optional[str] = None, reload: bool = False, smart_reload: bool = True) -> bool:
    """
    Build the site.

    Args:
        config: Site configuration
        file: Optional specific file to build
        reload: Whether to watch for changes and rebuild automatically
        smart_reload: Whether to use smart reload optimization

    Returns:
        True if successful, False otherwise
    """
    # Call pre-build hooks
    presskit_context = create_presskit_context(config)
    call_hook("pre_build", context=presskit_context)
    if reload:
        smart_reloader = SmartReloader(config, enabled=smart_reload)
        print("Building with auto-reload enabled...")
        if smart_reload:
            print("Smart reload optimization enabled (use --disable-smart-reload to disable)")
        else:
            print("Smart reload optimization disabled")
        print("Watching for changes in content/, templates/, and data directories...")
        print("Press Ctrl+C to stop.")

        def do_build(rebuild_plan=None):
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

            # Determine what to build
            if file:
                # Build specific file
                file_path = Path(file)
                if not file_path.exists():
                    print_error(f"File not found: {file_path}")
                    return False
                files = [file_path]
                generators_to_build = []
            elif rebuild_plan and not rebuild_plan.full_rebuild:
                # Use smart rebuild plan
                files = rebuild_plan.content_files
                generators_to_build = rebuild_plan.generators
                print_info(f"Smart rebuild: {rebuild_plan.reason}")
                print_info(f"Building {len(files)} files and {len(generators_to_build)} generators")
            else:
                # Build all markdown files
                files = list(config.content_dir.glob(f"**/*.{config.markdown_extension}"))
                generators_to_build = []

            if not files and not generators_to_build:
                print_info("No files to process!")
                return True

            if files:
                print_info(f"Found {len(files)} files to process")

                # Build files - use parallel for multiple files
                build_success = False
                if len(files) == 1 or config.workers == 1:
                    # Build sequentially for a single file or if workers=1
                    success_count = 0
                    for file_path in files:
                        if build_file_with_tracking(file_path, query_cache, config, smart_reloader):
                            success_count += 1
                    build_success = success_count == len(files)
                else:
                    # Build in parallel for multiple files
                    build_success = build_parallel_with_tracking(files, query_cache, config, smart_reloader)

                if not build_success:
                    print_warning("Build completed with some errors.")
                    return False

            # Process generator queries if available and not building a specific file
            if not file and query_cache and "generators" in query_cache:
                if generators_to_build:
                    # Build only specific generators
                    process_specific_generators(config, generators_to_build, smart_reloader)
                elif rebuild_plan and not rebuild_plan.full_rebuild:
                    # Smart rebuild with no generators to rebuild - skip generators
                    pass
                else:
                    # Build all generators (only for full rebuilds or initial builds)
                    process_generators_with_tracking(config, smart_reloader)

            print_success("Build complete!")
            return True

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
                rebuild_plan = smart_reloader.analyze_changes(changes)
                do_build(rebuild_plan)
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

    # Call post-build hooks
    build_context = PluginBuildContext(
        build_results={"success": build_success, "file_count": len(files) if "files" in locals() else 0},
        presskit=presskit_context,
    )
    call_hook("post_build", context=build_context)

    if build_success:
        print_success("Build complete!")
    else:
        print_warning("Build completed with some errors.")

    return build_success


def cmd_server(config: SiteConfig, reload: bool = False, smart_reload: bool = True) -> bool:
    """
    Start a development server.

    Args:
        config: Site configuration
        reload: Whether to watch for changes and rebuild automatically
        smart_reload: Whether to use smart reload optimization
    """
    import http.server
    import threading

    if reload:
        print("Starting server with auto-reload enabled...")
        if smart_reload:
            print("Smart reload optimization enabled (use --disable-smart-reload to disable)")
        else:
            print("Smart reload optimization disabled")
        print("Watching for changes in content/, templates/, and data directories...")
    else:
        print("Starting server...")

    # If public directory is empty and reload is enabled, run initial build
    if not list(config.output_dir.glob("*")):
        if reload:
            print_warning("Output directory is empty. Running initial build...")
            # Run initial build
            if not cmd_build(config, smart_reload=smart_reload):
                print_error("Initial build failed.")
                return False
        else:
            print_warning("Output directory is empty. Run 'presskit build' first.")

    # Set up server
    host = config.server_host
    port = config.server_port
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(config.output_dir))

    # Create server
    server = http.server.ThreadingHTTPServer((host, port), handler)

    # Call server_start hook
    from presskit.hookspecs import ServerContext

    presskit_context = create_presskit_context(config)
    server_context = ServerContext(
        host=host, port=port, reload=reload, smart_reload=smart_reload, presskit=presskit_context
    )
    call_hook("server_start", context=server_context)

    print_success(f"Server running at http://{host}:{port}/")
    print("Press Ctrl+C to stop.")

    if reload:
        smart_reloader = SmartReloader(config, enabled=smart_reload)

        def do_build(rebuild_plan=None):
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

            # Determine what to build
            if rebuild_plan and not rebuild_plan.full_rebuild:
                # Use smart rebuild plan
                files = rebuild_plan.content_files
                generators_to_build = rebuild_plan.generators
                print_info(f"Smart rebuild: {rebuild_plan.reason}")
                print_info(f"Building {len(files)} files and {len(generators_to_build)} generators")
            else:
                # Build all markdown files
                files = list(config.content_dir.glob(f"**/*.{config.markdown_extension}"))
                generators_to_build = []

            if not files and not generators_to_build:
                print_info("No files to process!")
                return True

            if files:
                print_info(f"Found {len(files)} files to process")

                # Build files - use parallel for multiple files
                build_success = False
                if len(files) == 1 or config.workers == 1:
                    # Build sequentially for a single file or if workers=1
                    success_count = 0
                    for file_path in files:
                        if build_file_with_tracking(file_path, query_cache, config, smart_reloader):
                            success_count += 1
                    build_success = success_count == len(files)
                else:
                    # Build in parallel for multiple files
                    build_success = build_parallel_with_tracking(files, query_cache, config, smart_reloader)

                if not build_success:
                    print_warning("Rebuild completed with some errors.")
                    return False

            # Process generator queries if available
            if query_cache and "generators" in query_cache:
                if generators_to_build:
                    # Build only specific generators
                    process_specific_generators(config, generators_to_build, smart_reloader)
                elif rebuild_plan and not rebuild_plan.full_rebuild:
                    # Smart rebuild with no generators to rebuild - skip generators
                    pass
                else:
                    # Build all generators (only for full rebuilds or initial builds)
                    process_generators_with_tracking(config, smart_reloader)

            print_success("Rebuild complete!")
            return True

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
                    rebuild_plan = smart_reloader.analyze_changes(changes)
                    do_build(rebuild_plan)
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

        return True

    except Exception as e:
        print_error(f"Error listing sources: {e}")
        return False


def cmd_compile(
    file_path: str,
    sources: List[str],
    template_override: Optional[str] = None,
    output_path: Optional[str] = None,
    config_file: Optional[str] = None,
    watch: bool = False,
) -> bool:
    """
    Compile a single Markdown or HTML file with Jinja templating.

    Args:
        file_path: Path to the file to compile
        sources: List of JSON data source files
        template_override: Optional template file to use instead of frontmatter layout
        output_path: Optional output path for the compiled HTML
        config_file: Optional config file path
        watch: Whether to watch for file changes and recompile automatically

    Returns:
        True if successful, False otherwise
    """
    def do_compile():
        """Perform the actual compilation."""
        try:
            print(f"Compiling: {file_path}")

            # Convert file path to Path object
            input_file = Path(file_path)
            if not input_file.exists():
                print_error(f"File not found: {input_file}")
                return False

            # Load configuration if available
            config = None
            if config_file:
                try:
                    config_path = find_config_file(config_file)
                    config = load_site_config(config_path)
                except (FileNotFoundError, ConfigError):
                    print_warning(f"Config file not found or invalid: {config_file}")
            else:
                # Try to find config in current directory or parent directories
                try:
                    config_path = find_config_file()
                    config = load_site_config(config_path)
                    print_info(f"Using config: {config_path}")
                except (FileNotFoundError, ConfigError):
                    print_info("No config file found, using minimal defaults")

            # Load JSON data sources
            json_data = {}
            for source_path in sources:
                source_file = Path(source_path)
                if not source_file.exists():
                    print_error(f"Source file not found: {source_file}")
                    return False

                try:
                    with open(source_file, "r") as f:
                        source_data = json.load(f)
                        # Use filename without extension as key
                        source_key = source_file.stem
                        json_data[source_key] = source_data
                        print_info(f"Loaded data source: {source_key}")
                except json.JSONDecodeError as e:
                    print_error(f"Invalid JSON in {source_file}: {e}")
                    return False

            # Determine file type and process accordingly
            file_extension = input_file.suffix.lower()

            if file_extension == ".md":
                return compile_markdown_file(input_file, json_data, template_override, output_path, config)
            elif file_extension == ".html":
                return compile_html_file(input_file, json_data, template_override, output_path, config)
            else:
                print_error(f"Unsupported file type: {file_extension}")
                print_info("Supported file types: .md, .html")
                return False

        except Exception as e:
            print_error(f"Error compiling file: {e}")
            return False

    # If watch mode is enabled
    if watch:
        print("Watch mode enabled...")
        print("Watching for changes and recompiling automatically...")
        print("Press Ctrl+C to stop.")

        # Initial compilation
        success = do_compile()
        if not success:
            return False

        # Determine paths to watch
        input_file = Path(file_path)
        watch_paths = [input_file.parent]  # Watch the directory containing the file

        # Add source file directories to watch paths
        for source_path in sources:
            source_file = Path(source_path)
            if source_file.exists() and source_file.parent not in watch_paths:
                watch_paths.append(source_file.parent)

        # Add config directory if available
        if config_file:
            config_path = Path(config_file)
            if config_path.exists() and config_path.parent not in watch_paths:
                watch_paths.append(config_path.parent)
        else:
            # Try to find and watch config directory
            try:
                config_path = find_config_file()
                if config_path.parent not in watch_paths:
                    watch_paths.append(config_path.parent)
            except (FileNotFoundError, ConfigError):
                pass

        print_info(f"Watching directories: {[str(p) for p in watch_paths]}")

        try:
            from watchfiles import watch as watch_files
            for changes in watch_files(*watch_paths):
                # Filter changes to only relevant files
                relevant_changes = []
                input_file_resolved = input_file.resolve()
                
                for change in changes:
                    change_path = Path(change[1]).resolve()
                    
                    # Check if it's the target file, a source file, or config file
                    is_target_file = change_path == input_file_resolved
                    is_source_file = any(Path(source).resolve() == change_path for source in sources)
                    is_config_file = change_path.name == "presskit.json"
                    
                    if is_target_file or is_source_file or is_config_file:
                        relevant_changes.append(change)

                if relevant_changes:
                    print(f"\nDetected changes: {[str(Path(change[1]).name) for change in relevant_changes]}")
                    print("⚡ Recompiling...")
                    success = do_compile()
                    if success:
                        print("✅ Compilation completed successfully")
                    else:
                        print("❌ Compilation failed")

        except KeyboardInterrupt:
            print("\nStopping file watcher.")
            return True
    else:
        # Single compilation
        return do_compile()


def compile_markdown_file(
    input_file: Path,
    json_data: Dict[str, Any],
    template_override: Optional[str],
    output_path: Optional[str],
    config: Optional[SiteConfig],
) -> bool:
    """
    Compile a Markdown file with Jinja templating.

    Args:
        input_file: Path to the markdown file
        json_data: Loaded JSON data sources
        template_override: Optional template override
        output_path: Optional output path
        config: Optional site configuration

    Returns:
        True if successful, False otherwise
    """
    try:
        # Read file content
        with open(input_file, "r") as f:
            content = f.read()

        # Extract front matter and content
        front_matter, md_content, md_queries, md_sources = extract_front_matter(content)

        # Create minimal config if none provided
        if not config:
            config = create_minimal_config(input_file.parent)

        # Load frontmatter sources if any
        frontmatter_sources = {}
        if md_sources:
            frontmatter_sources = load_frontmatter_sources(md_sources, input_file.parent)

        # Combine command-line sources with frontmatter sources
        combined_sources = {**json_data, **frontmatter_sources}

        # Build template context
        site_ctx = build_site_context(config)
        build_ctx = build_build_context()

        # Create page context
        page_ctx = PageContext(
            filename=input_file.stem,
            filepath=str(input_file),
            path=input_file.stem,
            content=None,  # Will be set after processing
            layout=template_override or front_matter.get("layout", config.default_template),
            title=front_matter.get("title"),
            description=front_matter.get("description"),
        )

        # Create data context with combined sources
        data_ctx = DataContext(
            queries={},
            sources=combined_sources,
            page_queries={},
        )

        # Create complete template context
        template_context = TemplateContext(
            site=site_ctx,
            build=build_ctx,
            page=page_ctx,
            data=data_ctx,
            extras=front_matter,
        )

        # Process markdown content
        html_content = process_markdown(
            md_content, template_context.to_template_vars(), config.content_dir, config, input_file
        )

        # Update page context with processed content
        template_context.page.content = html_content

        # Process template if specified
        if page_ctx.layout:
            # Look for template in templates directory or same directory as input file
            template_paths = []
            if config.templates_dir.exists():
                template_paths.append(config.templates_dir)
            template_paths.append(input_file.parent)

            template_found = False
            for template_dir in template_paths:
                template_file = template_dir / f"{page_ctx.layout}.html"
                if template_file.exists():
                    final_html = process_template(
                        page_ctx.layout, template_context.to_template_vars(), template_dir, config
                    )
                    template_found = True
                    break

            if not template_found and page_ctx.layout != "none":
                print_warning(f"Template '{page_ctx.layout}.html' not found, using content only")
                final_html = html_content
            else:
                final_html = html_content if page_ctx.layout == "none" else final_html
        else:
            final_html = html_content

        # Determine output path
        if output_path:
            output_file = Path(output_path)
        else:
            output_file = input_file.with_suffix(".html")

        # Create output directory if needed
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Write output file
        with open(output_file, "w") as f:
            f.write(final_html)

        print_success(f"Compiled to: {output_file}")
        return True

    except Exception as e:
        print_error(f"Error compiling markdown file: {e}")
        return False


def compile_html_file(
    input_file: Path,
    json_data: Dict[str, Any],
    template_override: Optional[str],
    output_path: Optional[str],
    config: Optional[SiteConfig],
) -> bool:
    """
    Compile an HTML file with Jinja templating and optional frontmatter.

    Args:
        input_file: Path to the HTML file
        json_data: Loaded JSON data sources
        template_override: Optional template override
        output_path: Optional output path
        config: Optional site configuration

    Returns:
        True if successful, False otherwise
    """
    try:
        # Read file content
        with open(input_file, "r") as f:
            content = f.read()

        # Extract front matter from HTML content
        front_matter, html_content, html_queries, html_sources = extract_front_matter(content)

        # Create minimal config if none provided
        if not config:
            config = create_minimal_config(input_file.parent)

        # Load frontmatter sources if any
        frontmatter_sources = {}
        if html_sources:
            frontmatter_sources = load_frontmatter_sources(html_sources, input_file.parent)

        # Combine command-line sources with frontmatter sources
        combined_sources = {**json_data, **frontmatter_sources}

        # Build template context
        site_ctx = build_site_context(config)
        build_ctx = build_build_context()

        # Create page context - use frontmatter values if available
        page_ctx = PageContext(
            filename=input_file.stem,
            filepath=str(input_file),
            path=input_file.stem,
            content=html_content,
            layout=template_override or front_matter.get("layout", "none"),
            title=front_matter.get("title"),
            description=front_matter.get("description"),
        )

        # Process HTML file's queries if any (similar to markdown)
        page_query_results = {}
        if html_queries:
            # Build temporary context for processing queries
            temp_context = TemplateContext(
                site=site_ctx,
                build=build_ctx,
                page=page_ctx,
                data=DataContext(queries={}, sources=combined_sources, page_queries={}),
                extras=front_matter,
            )
            # Use async query processor for HTML queries
            processor = QueryProcessor()
            page_query_results = asyncio.run(
                processor.process_markdown_queries(html_queries, temp_context.to_template_vars(), config)
            )

        # Create data context with combined sources and page queries
        data_ctx = DataContext(
            queries={},
            sources=combined_sources,
            page_queries=page_query_results,
        )

        # Create complete template context with frontmatter extras
        template_context = TemplateContext(
            site=site_ctx,
            build=build_ctx,
            page=page_ctx,
            data=data_ctx,
            extras=front_matter,
        )

        # Process HTML file as Jinja template
        template_vars = template_context.to_template_vars()

        # Process the HTML content with Jinja
        env = Environment(
            loader=FileSystemLoader(input_file.parent),
            autoescape=select_autoescape(["html", "xml"]),
        )
        env.filters.update(JINJA_FILTERS)
        env.globals.update(JINJA_GLOBALS)

        # Process as template
        template = env.from_string(html_content)
        final_html = template.render(**template_vars)

        # Apply template layout if specified (from frontmatter or override)
        if page_ctx.layout and page_ctx.layout != "none":
            # Look for template file
            template_paths = []
            if config and config.templates_dir.exists():
                template_paths.append(config.templates_dir)
            template_paths.append(input_file.parent)

            template_found = False
            for template_dir in template_paths:
                template_file = template_dir / page_ctx.layout
                if not page_ctx.layout.endswith(".html"):
                    template_file = template_dir / f"{page_ctx.layout}.html"

                if template_file.exists():
                    # Update page content with processed HTML
                    template_vars["page"]["content"] = Markup(final_html)

                    # Process with the layout template
                    final_html = process_template(page_ctx.layout, template_vars, template_dir, config)
                    template_found = True
                    break

            if not template_found:
                print_warning(f"Template '{page_ctx.layout}.html' not found, using content only")

        # Determine output path
        if output_path:
            output_file = Path(output_path)
        else:
            output_file = input_file.with_name(f"{input_file.stem}_compiled.html")

        # Create output directory if needed
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Write output file
        with open(output_file, "w") as f:
            f.write(final_html)

        print_success(f"Compiled to: {output_file}")
        return True

    except Exception as e:
        print_error(f"Error compiling HTML file: {e}")
        return False


def load_frontmatter_sources(
    sources_config: Dict[str, Any], 
    base_dir: Path
) -> Dict[str, Any]:
    """
    Load data sources defined in frontmatter.

    Args:
        sources_config: Sources configuration from frontmatter
        base_dir: Base directory for resolving relative paths

    Returns:
        Dictionary with loaded source data
    """
    loaded_sources = {}
    
    for source_name, source_config in sources_config.items():
        try:
            if isinstance(source_config, dict):
                source_type = source_config.get("type", "json")
                source_path = source_config.get("path")
                
                if not source_path:
                    print_warning(f"No path specified for source '{source_name}', skipping")
                    continue
                
                # Resolve path relative to base directory or working directory
                path_obj = Path(source_path)
                if not path_obj.is_absolute():
                    # Try relative to base directory first
                    file_path = base_dir / source_path
                    # If that doesn't exist, try relative to current working directory
                    if not file_path.exists():
                        cwd_path = Path.cwd() / source_path
                        if cwd_path.exists():
                            file_path = cwd_path
                else:
                    file_path = path_obj
                
                if not file_path.exists():
                    print_warning(f"Source file not found: {file_path}")
                    continue
                
                # Currently only support JSON sources in frontmatter
                if source_type == "json":
                    with open(file_path, "r") as f:
                        source_data = json.load(f)
                        loaded_sources[source_name] = source_data
                        print_info(f"Loaded frontmatter source: {source_name}")
                else:
                    print_warning(f"Unsupported source type '{source_type}' for source '{source_name}'")
            else:
                print_warning(f"Invalid source configuration for '{source_name}', expected dict")
                
        except json.JSONDecodeError as e:
            print_error(f"Invalid JSON in source '{source_name}': {e}")
        except Exception as e:
            print_error(f"Error loading source '{source_name}': {e}")
    
    return loaded_sources


def create_minimal_config(base_dir: Path) -> SiteConfig:
    """
    Create a minimal configuration for single file compilation.

    Args:
        base_dir: Base directory for relative paths

    Returns:
        Minimal SiteConfig object
    """
    return SiteConfig(
        title="Compiled Page",
        site_dir=base_dir,
        content_dir=base_dir,
        templates_dir=base_dir / "templates",
        output_dir=base_dir,
        cache_dir=base_dir / ".cache",
    )

"""Hook specifications for Presskit plugin system."""

import typing as t
from pathlib import Path
from pydantic import BaseModel
from pluggy import HookimplMarker, HookspecMarker

hookspec = HookspecMarker("presskit")
hookimpl = HookimplMarker("presskit")


# Context Models for Hook Parameters

class PressskitContext(BaseModel):
    """Base context for all Presskit operations."""
    config: t.Dict[str, t.Any]
    build_dir: Path
    content_dir: Path
    template_dir: Path


class FileContext(BaseModel):
    """Context for file processing operations."""
    file_path: Path
    relative_path: Path
    file_type: str
    presskit: PressskitContext


class ContentContext(BaseModel):
    """Context for content processing."""
    content: str
    frontmatter: t.Dict[str, t.Any]
    file_context: FileContext


class PageContext(BaseModel):
    """Context for page rendering."""
    page_data: t.Dict[str, t.Any]
    template_vars: t.Dict[str, t.Any]
    file_context: FileContext


class TemplateContext(BaseModel):
    """Context for template operations."""
    template_path: t.Optional[Path] = None
    template_vars: t.Dict[str, t.Any]
    presskit: PressskitContext


class BuildContext(BaseModel):
    """Context for build operations."""
    build_results: t.Dict[str, t.Any]
    start_time: t.Optional[float] = None
    end_time: t.Optional[float] = None
    presskit: PressskitContext


class ErrorContext(BaseModel):
    """Context for error handling."""
    model_config = {"arbitrary_types_allowed": True}
    
    error: Exception
    file_path: t.Optional[Path] = None
    template_path: t.Optional[Path] = None
    context_data: t.Dict[str, t.Any] = {}
    presskit: PressskitContext


# Configuration and Startup Hooks

@hookspec
def startup(context: PressskitContext):
    """Fires directly after Presskit starts running."""


# Content Processing Hooks

@hookspec
def process_markdown(context: ContentContext):
    """Process markdown content before rendering - return modified content or None."""


@hookspec
def process_frontmatter(context: ContentContext):
    """Process frontmatter data - return modified frontmatter dict or None."""


@hookspec
def prepare_page_context(context: PageContext):
    """Modify page context before template rendering."""


# Template System Hooks

@hookspec
def prepare_jinja2_environment(env: t.Any, context: PressskitContext):
    """Modify Jinja2 template environment - register custom filters, functions, etc."""


@hookspec
def extra_template_vars(context: TemplateContext):
    """Provide additional template variables - return dict of variables."""


@hookspec
def custom_jinja_filters(context: PressskitContext):
    """Register custom Jinja2 filters - return dict of {name: function}."""


@hookspec
def custom_jinja_functions(context: PressskitContext):
    """Register custom Jinja2 global functions - return dict of {name: function}."""


# Data Source Hooks

@hookspec
def register_data_sources(context: PressskitContext):
    """Register custom data source types - return dict of {type_name: source_class}."""


# Build Process Hooks

@hookspec
def pre_build(context: PressskitContext):
    """Execute before build process starts."""


@hookspec
def post_build(context: BuildContext):
    """Execute after build process completes."""


@hookspec
def pre_process_file(context: FileContext):
    """Execute before processing individual file."""


@hookspec
def post_process_file(context: FileContext, output_path: Path):
    """Execute after processing individual file."""


# CLI Extension Hooks

@hookspec
def register_commands(cli: t.Any):
    """Register additional CLI commands."""


# Error Handling Hooks

@hookspec
def handle_build_error(context: ErrorContext):
    """Handle build errors - return True if handled, None otherwise."""


@hookspec
def handle_template_error(context: ErrorContext):
    """Handle template rendering errors - return True if handled, None otherwise."""
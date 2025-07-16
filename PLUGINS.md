# Presskit Plugin System

Presskit includes a plugin system that allows you to extend its functionality through custom hooks. The plugin system is built on the widely used [Pluggy](https://pluggy.readthedocs.io/en/latest/) library, and provides strongly-typed interfaces for all operations.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Plugin Configuration](#plugin-configuration)
- [Available Hooks](#available-hooks)
- [Plugin Development](#plugin-development)
- [Context Models](#context-models)
- [Examples](#examples)
- [Debugging](#debugging)
- [Distribution](#distribution)

## Overview

The plugin system allows you to hook into various stages of Presskit's operation:

- **Content Processing**: Modify markdown content and frontmatter
- **Template System**: Add custom Jinja2 filters and functions
- **Build Process**: Execute code before/after builds
- **Data Sources**: Register custom data source types
- **CLI Extensions**: Add new CLI commands
- **Error Handling**: Custom error processing

## Quick Start

### 1. Create a Simple Plugin

Create a file called `my_plugin.py`:

```python
from presskit.hookspecs import hookimpl

@hookimpl
def startup(context):
    """Called when Presskit starts up."""
    print("🔌 My plugin loaded!")

@hookimpl
def custom_jinja_filters(context):
    """Add custom Jinja2 filters."""
    def shout(text):
        return str(text).upper() + "!"
    
    return {"shout": shout}

@hookimpl
def register_commands(cli):
    """Register custom CLI commands."""
    import typer
    
    @cli.command()
    def hello(name: str = typer.Argument("World")):
        """Say hello from the plugin."""
        print(f"🔌 Hello {name} from my plugin!")
        
    @cli.command()
    def status():
        """Show plugin status."""
        print("🔌 My plugin is active and working!")
```

### 2. Configure the Plugin

Add to your `presskit.json`:

```json
{
  "plugins": [
    {
      "name": "my_plugin.py",
      "enabled": true
    }
  ]
}
```

### 3. Use in Templates

Now you can use the filter in your templates:

```html
<h1>{{ "hello world" | shout }}</h1>
<!-- Outputs: <h1>HELLO WORLD!</h1> -->
```

### 4. Test the Plugin

Your plugin commands will now appear in the CLI:

```bash
$ presskit --help
Commands:
  hello         Say hello from the plugin.
  status        Show plugin status.
  init          Initialize a new Presskit project.
  build         Build the site.
  # ... other commands

$ presskit hello "Developer"
🔌 Hello Developer from my plugin!

$ presskit status
🔌 My plugin is active and working!
```

## Plugin Configuration

### Configuration in presskit.json

```json
{
  "plugins": [
    {
      "name": "path/to/plugin.py",
      "enabled": true,
      "options": {
        "setting1": "value1",
        "setting2": 42
      }
    }
  ],
  "plugin_directories": [
    "plugins/",
    "custom_plugins/"
  ]
}
```

### Plugin Loading Methods

1. **File Path**: Direct path to a Python file
2. **Directory Scanning**: All `.py` files in specified directories
3. **Entry Points**: Installed packages with `presskit` entry points

### Environment Variables

- `PRESSKIT_TRACE_PLUGINS`: Enable debug tracing of plugin calls (e.g., `export PRESSKIT_TRACE_PLUGINS=1`)
- `PRESSKIT_LOAD_PLUGINS`: Comma-separated list of plugin packages to load (e.g., `export PRESSKIT_LOAD_PLUGINS=my_plugin,another_plugin`)

## Available Hooks

### Configuration and Startup

```python
@hookimpl
def startup(context: PressskitContext):
    """Fires when Presskit starts up."""
    print("Plugin loaded!")
```

### Content Processing

```python
@hookimpl
def process_markdown(context: ContentContext):
    """Process markdown content before rendering."""
    # Modify context.content and return it, or return None
    if "TODO" in context.content:
        return context.content.replace("TODO", "✅ DONE")
    return None

@hookimpl
def process_frontmatter(context: ContentContext):
    """Process frontmatter data."""
    # Modify context.frontmatter and return it, or return None
    if "auto_date" in context.frontmatter:
        context.frontmatter["date"] = datetime.now().strftime("%Y-%m-%d")
        return context.frontmatter
    return None

@hookimpl
def prepare_page_context(context: PageContext):
    """Modify page context before template rendering."""
    print(f"Preparing page: {context.file_context.relative_path}")
```

### Template System

```python
@hookimpl
def prepare_jinja2_environment(env, context: PressskitContext):
    """Modify Jinja2 environment directly."""
    env.globals['site_name'] = context.config.get("title", "My Site")

@hookimpl
def custom_jinja_filters(context: PressskitContext):
    """Register custom Jinja2 filters."""
    return {
        "reverse": lambda text: str(text)[::-1],
        "truncate": lambda text, length=50: str(text)[:length],
        "upper": lambda text: str(text).upper()
    }

@hookimpl
def custom_jinja_functions(context: PressskitContext):
    """Register custom Jinja2 global functions."""
    return {
        "current_year": lambda: datetime.now().year,
        "build_timestamp": lambda: datetime.now().isoformat()
    }

@hookimpl
def extra_template_vars(context: TemplateContext):
    """Provide additional template variables."""
    return {
        "plugin_version": "1.0.0",
        "build_id": str(uuid.uuid4())[:8]
    }
```

### Build Process

```python
@hookimpl
def pre_build(context: PressskitContext):
    """Execute before build process starts."""
    print("🚀 Starting build process...")

@hookimpl
def post_build(context: BuildContext):
    """Execute after build process completes."""
    success = context.build_results.get("success", False)
    file_count = context.build_results.get("file_count", 0)
    print(f"✅ Build {'succeeded' if success else 'failed'} - {file_count} files processed")

@hookimpl
def pre_process_file(context: FileContext):
    """Execute before processing individual file."""
    print(f"📝 Processing {context.relative_path}")

@hookimpl
def post_process_file(context: FileContext, output_path: Path):
    """Execute after processing individual file."""
    print(f"✅ Generated {output_path}")
```

### Data Sources

```python
@hookimpl
def register_data_sources(context: PressskitContext):
    """Register custom data source types."""
    return {
        "redis": RedisDataSource,
        "api": APIDataSource,
        "csv": CSVDataSource
    }
```

### CLI Extensions

The `register_commands` hook allows plugins to add custom CLI commands that appear alongside built-in Presskit commands.

```python
@hookimpl
def register_commands(cli):
    """Register additional CLI commands."""
    import typer
    from pathlib import Path
    
    @cli.command()
    def validate():
        """Validate all markdown files in the content directory."""
        content_dir = Path("content")
        if not content_dir.exists():
            print("❌ Content directory not found")
            return
        
        md_files = list(content_dir.glob("**/*.md"))
        print(f"🔍 Validating {len(md_files)} markdown files...")
        
        for file in md_files:
            # Custom validation logic
            if file.stat().st_size == 0:
                print(f"⚠️  Empty file: {file}")
            else:
                print(f"✅ Valid: {file}")
    
    @cli.command()
    def optimize_images(
        input_dir: str = typer.Argument("assets/images", help="Input directory"),
        output_dir: str = typer.Option("public/images", help="Output directory"),
        quality: int = typer.Option(85, help="JPEG quality (1-100)")
    ):
        """Optimize images for web."""
        print(f"🖼️  Optimizing images from {input_dir} to {output_dir}")
        print(f"Quality: {quality}%")
        # Custom image optimization logic here
        
    @cli.command()
    def theme_info():
        """Display theme information."""
        print("🎨 Current Theme Information")
        print("Name: Custom Theme")
        print("Version: 1.0.0")
        print("Author: Plugin Developer")
```

**Command Registration Notes:**

- Commands are registered when plugins are loaded at CLI startup
- Use standard Typer syntax for arguments, options, and help text
- Commands appear in the main `presskit --help` output
- Commands work exactly like built-in Presskit commands

**CLI Command Best Practices:**

1. **Use Descriptive Names**: Choose clear, descriptive command names that don't conflict with built-in commands
2. **Include Help Text**: Always provide helpful docstrings for commands and arguments
3. **Handle Errors Gracefully**: Use try-catch blocks and provide meaningful error messages
4. **Access Plugin Configuration**: Use `load_config_with_plugins()` to access site config and plugin options
5. **Follow CLI Conventions**: Use consistent output formatting and exit codes

```python
@hookimpl
def register_commands(cli):
    """Register commands with proper error handling."""
    import typer
    from presskit.cli import load_config_with_plugins
    from presskit.utils import print_error, print_success
    
    @cli.command()
    def my_command():
        """Well-documented command with error handling."""
        try:
            config = load_config_with_plugins()
            # Access plugin options
            plugin_options = {}
            for plugin in config.plugins:
                if plugin.name == "my_plugin":
                    plugin_options = plugin.options
                    break
            
            # Command logic here
            print_success("Command completed successfully!")
            
        except Exception as e:
            print_error(f"Command failed: {e}")
            raise typer.Exit(1)
```

### Error Handling

```python
@hookimpl
def handle_build_error(context: ErrorContext):
    """Handle build errors."""
    print(f"Build error in {context.file_path}: {context.error}")
    # Return True if handled, None otherwise
    return True

@hookimpl
def handle_template_error(context: ErrorContext):
    """Handle template rendering errors."""
    # Custom error handling logic
    return True
```

## Plugin Development

### Project Structure

```
presskit-analytics/
├── pyproject.toml
├── presskit_analytics/
│   ├── __init__.py
│   └── plugin.py
└── README.md
```

### Plugin Implementation

```python
# presskit_analytics/plugin.py
from presskit.hookspecs import hookimpl
import datetime

@hookimpl
def startup(context):
    print("Presskit Analytics Plugin loaded!")

@hookimpl
def custom_jinja_filters(context):
    def format_date(date_str, format="%Y-%m-%d"):
        try:
            date_obj = datetime.datetime.fromisoformat(date_str)
            return date_obj.strftime(format)
        except:
            return date_str
    
    return {
        "format_date": format_date
    }

@hookimpl
def pre_build(context):
    # Custom pre-build logic
    ensure_assets_directory(context.config["output_dir"])

@hookimpl
def process_markdown(context):
    # Add custom markdown processing
    if "[TOC]" in context.content:
        # Generate table of contents
        toc = generate_toc(context.content)
        return context.content.replace("[TOC]", toc)
    return None
```

### Distribution Setup

**Package Naming Convention**: Follow the `presskit-` prefix for plugin packages (e.g., `presskit-analytics`, `presskit-seo`, `presskit-themes`) to make them easily discoverable in package repositories.

#### Using pyproject.toml (Recommended)

```toml
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "presskit-analytics"
version = "1.0.0"
description = "Analytics plugin for Presskit"
authors = [
    {name = "Your Name", email = "your.email@example.com"}
]
dependencies = [
    "presskit>=0.1.0"
]
requires-python = ">=3.11"

[project.entry-points.presskit]
analytics = "presskit_analytics.plugin"
```

#### Using setup.py (Legacy)

```python
from setuptools import setup, find_packages

setup(
    name="presskit-analytics",
    version="1.0.0",
    packages=find_packages(),
    entry_points={
        "presskit": [
            "analytics = presskit_analytics.plugin"
        ]
    },
    install_requires=[
        "presskit>=0.1.0"
    ]
)
```

## Context Models

All hooks receive strongly-typed context objects:

### PressskitContext

```python
class PressskitContext:
    config: Dict[str, Any]        # Site configuration
    build_dir: Path               # Build/output directory
    content_dir: Path             # Content directory
    template_dir: Path            # Template directory
```

### FileContext

```python
class FileContext:
    file_path: Path               # Absolute file path
    relative_path: Path           # Relative to content dir
    file_type: str               # File type (content, static, etc.)
    presskit: PressskitContext   # Parent context
```

### ContentContext

```python
class ContentContext:
    content: str                  # Markdown content
    frontmatter: Dict[str, Any]   # YAML frontmatter
    file_context: FileContext     # File information
```

### PageContext

```python
class PageContext:
    page_data: Dict[str, Any]     # Page data
    template_vars: Dict[str, Any] # Template variables
    file_context: FileContext     # File information
```

### TemplateContext

```python
class TemplateContext:
    template_path: Optional[Path] # Template file path
    template_vars: Dict[str, Any] # Template variables
    presskit: PressskitContext    # Parent context
```

### BuildContext

```python
class BuildContext:
    build_results: Dict[str, Any] # Build results
    start_time: Optional[float]   # Build start time
    end_time: Optional[float]     # Build end time
    presskit: PressskitContext    # Parent context
```

### ErrorContext

```python
class ErrorContext:
    error: Exception              # The error that occurred
    file_path: Optional[Path]     # File being processed
    template_path: Optional[Path] # Template being processed
    context_data: Dict[str, Any]  # Additional context
    presskit: PressskitContext    # Parent context
```

## Examples

### SEO Plugin

```python
from presskit.hookspecs import hookimpl
from urllib.parse import urljoin

@hookimpl
def extra_template_vars(context):
    """Add SEO-related template variables."""
    site_url = context.presskit.config.get("url", "")
    
    return {
        "canonical_url": urljoin(site_url, context.template_vars.get("page", {}).get("path", "")),
        "og_image": urljoin(site_url, "/assets/og-image.png"),
        "twitter_card": "summary_large_image"
    }

@hookimpl
def process_frontmatter(context):
    """Add default SEO metadata."""
    if "description" not in context.frontmatter:
        # Generate description from content
        content_preview = context.content[:150].strip()
        context.frontmatter["description"] = content_preview
    
    return context.frontmatter
```

### Analytics Plugin

```python
from presskit.hookspecs import hookimpl
import json
import typer
from pathlib import Path

@hookimpl
def post_build(context):
    """Generate build analytics."""
    analytics = {
        "build_time": context.end_time - context.start_time if context.start_time else 0,
        "success": context.build_results.get("success", False),
        "file_count": context.build_results.get("file_count", 0),
        "timestamp": context.end_time
    }
    
    analytics_file = context.presskit.build_dir / "analytics.json"
    with open(analytics_file, "w") as f:
        json.dump(analytics, f, indent=2)


@hookimpl
def register_commands(cli):
    """Register analytics commands."""
    
    @cli.command()
    def analytics():
        """Display build analytics."""
        analytics_file = Path("public/analytics.json")
        if not analytics_file.exists():
            print("❌ No analytics data found. Run 'presskit build' first.")
            return
        
        with open(analytics_file) as f:
            data = json.load(f)
        
        print("📊 Build Analytics")
        print(f"Last build time: {data['build_time']:.2f}s")
        print(f"Files processed: {data['file_count']}")
        print(f"Status: {'✅ Success' if data['success'] else '❌ Failed'}")
        
    @cli.command()
    def benchmark(
        runs: int = typer.Option(5, help="Number of build runs"),
        clean: bool = typer.Option(False, help="Clean before each run")
    ):
        """Benchmark build performance."""
        print(f"🏃 Running {runs} build benchmarks...")
        # Benchmark logic here
```


## Debugging

### Enable Plugin Tracing

```bash
export PRESSKIT_TRACE_PLUGINS=1
presskit build
```

This will output detailed information about plugin hook calls.

### List Loaded Plugins

```bash
presskit plugins
```

### Plugin Development Tips

1. **Use Type Hints**: All context models are typed for better IDE support
2. **Handle Errors Gracefully**: Wrap plugin logic in try-catch blocks
3. **Return Appropriate Values**: Follow hook specifications for return values
4. **Test Thoroughly**: Test plugins with various content types and configurations
5. **Document Hooks**: Include docstrings for all hook implementations

### CLI Command Troubleshooting

**Commands Not Appearing in Help:**
- Ensure your plugin is properly configured in `presskit.json`
- Check that the plugin file exists and is readable
- Verify the `register_commands` hook is implemented correctly
- Commands are loaded when the CLI module is imported

**Plugin Loading Issues:**
```bash
# Enable plugin tracing to debug loading issues
export PRESSKIT_TRACE_PLUGINS=1
presskit --help

# Check what plugins are loaded
presskit plugins
```

**Command Execution Errors:**
- Use proper error handling with try-catch blocks
- Import required modules inside the hook function
- Access configuration through `load_config_with_plugins()` if needed
- Use `print_error()` and `print_success()` for consistent output formatting

## Best Practices

1. **Namespace Your Hooks**: Use descriptive names for custom functions and filters
2. **Check Context**: Always validate context data before using it
3. **Performance**: Be mindful of performance in hooks called frequently
4. **Documentation**: Document your plugin's hooks and configuration options
5. **Testing**: Include tests for your plugin functionality
6. **Versioning**: Use semantic versioning for plugin releases
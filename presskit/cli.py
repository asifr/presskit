"""
CLI interface for presskit using click.
"""

import json
import click
import typing as t
from pathlib import Path

from presskit import __version__
from presskit.press import (
    find_config_file,
    load_site_config,
    cmd_build,
    cmd_data,
    cmd_data_status,
    cmd_generate,
    cmd_server,
    cmd_clean,
    cmd_sources,
    cmd_compile,
)
from presskit.config.loader import ConfigError
from presskit.utils import print_error, print_info, print_success
from presskit.plugins import call_hook, load_plugins_from_directory, load_plugin_from_path, get_plugins
from presskit.press import create_presskit_context


@click.group()
@click.version_option(version=__version__, prog_name="presskit")
@click.pass_context
def app(ctx):
    """Presskit - A powerful static site generator.

    Combines Markdown content with Jinja2 templating and database-driven page generation.
    It allows building dynamic static sites by connecting content to SQLite databases and JSON data sources.
    """
    ctx.ensure_object(dict)


# Load plugins at import time for command registration
def _load_plugins_for_commands():
    """Load plugins for command registration at import time."""
    try:
        config_path = find_config_file()
        if config_path.exists():
            config = load_site_config(config_path)

            # Load plugins from directories
            for plugin_dir in config.plugin_directories:
                resolved_dir = config.site_dir / plugin_dir if not Path(plugin_dir).is_absolute() else Path(plugin_dir)
                load_plugins_from_directory(str(resolved_dir))

            # Load configured plugins
            for plugin_config in config.plugins:
                if plugin_config.enabled:
                    try:
                        plugin_path = Path(plugin_config.name)
                        if plugin_path.exists():
                            load_plugin_from_path(str(plugin_path))
                    except Exception:
                        pass

            # Register plugin commands
            call_hook("register_commands", cli=app)
    except Exception:
        # Silently ignore errors during plugin loading for command registration
        pass


# Load plugins for command registration
_load_plugins_for_commands()


def load_config_with_plugins(config_file: t.Optional[str] = None):
    """Load site configuration and call startup hooks."""
    try:
        config_path = find_config_file(config_file)
        config = load_site_config(config_path)

        # Load plugins from directories
        for plugin_dir in config.plugin_directories:
            resolved_dir = config.site_dir / plugin_dir if not Path(plugin_dir).is_absolute() else Path(plugin_dir)
            load_plugins_from_directory(str(resolved_dir))

        # Load configured plugins
        for plugin_config in config.plugins:
            if plugin_config.enabled:
                try:
                    # Try to load as a file path first, then as a module
                    plugin_path = Path(plugin_config.name)
                    if plugin_path.exists():
                        load_plugin_from_path(str(plugin_path))
                    else:
                        # Load as a module (will be handled by setuptools entry points)
                        pass
                except Exception as e:
                    print_error(f"Failed to load plugin {plugin_config.name}: {e}")

        # Call startup hooks
        presskit_context = create_presskit_context(config)
        call_hook("startup", context=presskit_context)

        # Register plugin commands after plugins are loaded
        call_hook("register_commands", cli=app)

        return config
    except ConfigError as e:
        print_error(f"Configuration error: {e}")
        raise click.Abort()


@app.command()
@click.argument("directory", required=False)
def init(directory: t.Optional[str] = None):
    """Initialize a new Presskit project."""
    if directory:
        target_dir = Path(directory).resolve()
        # Create the directory if it doesn't exist
        target_dir.mkdir(parents=True, exist_ok=True)
        current_dir = target_dir
    else:
        current_dir = Path.cwd()

    # Create directories if they don't exist
    templates_dir = current_dir / "templates"
    content_dir = current_dir / "content"

    for dir_path in [templates_dir, content_dir]:
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            print_success(f"Created directory: {dir_path}")
        else:
            print_info(f"Directory already exists: {dir_path}")

    # Create presskit.json if it doesn't exist
    config_file = current_dir / "presskit.json"
    if not config_file.exists():
        default_config = {
            "title": "My Presskit Site",
            "description": "A static site built with Presskit",
            "author": "Your Name",
            "url": "https://example.com",
            "version": "1.0.0",
            "language": "en",
            "content_dir": "./content",
            "templates_dir": "./templates",
            "output_dir": "./public",
            "cache_dir": "./.cache",
            "markdown_extension": "md",
            "default_template": "page",
            "workers": 8,
            "server_host": "0.0.0.0",
            "server_port": 8000,
            "sources": [],
            "queries": [],
        }

        with open(config_file, "w") as f:
            json.dump(default_config, f, indent=2)
        print_success(f"Created configuration file: {config_file}")
    else:
        print_info(f"Configuration file already exists: {config_file}")

    # Create base.html template if it doesn't exist
    base_template = templates_dir / "base.html"
    if not base_template.exists():
        base_content = """<!DOCTYPE html>
<html lang="{{ site.language }}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{{ page.title or site.title }}{% endblock %}</title>
    <meta name="description" content="{% block description %}{{ page.description or site.description }}{% endblock %}">
    <meta name="author" content="{{ site.author }}">
    {% block head %}{% endblock %}
</head>
<body>
    {% block content %}{% endblock %}
    {% block scripts %}{% endblock %}
</body>
</html>"""

        with open(base_template, "w") as f:
            f.write(base_content)
        print_success(f"Created base template: {base_template}")
    else:
        print_info(f"Base template already exists: {base_template}")

    # Create page.html template if it doesn't exist
    page_template = templates_dir / "page.html"
    if not page_template.exists():
        page_content = """{% extends "base.html" %}

{% block content %}
{{ page.content }}
{% endblock %}"""

        with open(page_template, "w") as f:
            f.write(page_content)
        print_success(f"Created page template: {page_template}")
    else:
        print_info(f"Page template already exists: {page_template}")

    # Create sample content file if content directory is empty
    sample_content = content_dir / "index.md"
    if not sample_content.exists() and not any(content_dir.glob("*.md")):
        sample_md = """---
title: Welcome to Presskit
description: This is a sample page created by Presskit init
layout: page
---

# Welcome to Presskit

This is a sample page created when you ran `presskit init`. 

Presskit is a powerful static site generator that combines:

- **Markdown content** with YAML frontmatter
- **Jinja2 templating** for dynamic content
- **Database-driven page generation** from SQL queries
- **JSON data sources** for structured content

## Getting Started

1. Edit this file (`content/index.md`) to create your homepage
2. Add more markdown files to the `content/` directory
3. Customize the templates in `templates/`
4. Run `presskit build` to generate your site
5. Use `presskit server` to preview your site locally

## Next Steps

- Explore the [Presskit documentation](https://github.com/asifr/presskit)
- Add data sources and queries to `presskit.json`
- Create additional templates and layouts
- Customize the styling and structure

Happy building! 🚀
"""

        with open(sample_content, "w") as f:
            f.write(sample_md)
        print_success(f"Created sample content: {sample_content}")
    else:
        if sample_content.exists():
            print_info(f"Sample content already exists: {sample_content}")
        else:
            print_info("Content directory contains files, skipping sample content creation")

    print()
    print_success("✨ Presskit project initialized successfully!")
    print()
    print("Next steps:")
    print("  1. Edit presskit.json to configure your site")
    print("  2. Add content files to the content/ directory")
    print("  3. Customize templates in the templates/ directory")
    print("  4. Run 'presskit build' to generate your site")
    print("  5. Run 'presskit server' to preview your site")


@app.command()
@click.argument("file", required=False)
@click.option("--reload", is_flag=True, help="Watch for changes and rebuild automatically")
@click.option("--disable-smart-reload", is_flag=True, help="Rebuild everything on change")
@click.option("--config", help="Path to presskit.json config file")
def build(
    file: t.Optional[str] = None,
    reload: bool = False,
    disable_smart_reload: bool = False,
    config: t.Optional[str] = None,
):
    """Build the site."""
    try:
        site_config = load_config_with_plugins(config)
        print_info(f"Using config: {find_config_file(config)}")

        success = cmd_build(site_config, file, reload, smart_reload=not disable_smart_reload)
        if not success:
            raise click.Abort()
    except (FileNotFoundError, ConfigError) as e:
        print_error(str(e))
        raise click.Abort()
    except KeyboardInterrupt:
        print_error("Process interrupted by user")
        raise click.Abort()
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        raise click.Abort()


@app.command()
@click.option("--config", help="Path to presskit.json config file")
def data(config: t.Optional[str] = None):
    """Execute all SQL queries and cache results."""
    try:
        config_path = find_config_file(config)
        site_config = load_site_config(config_path)
        print_info(f"Using config: {config_path}")

        success = cmd_data(site_config)
        if not success:
            raise click.Abort()
    except (FileNotFoundError, ConfigError) as e:
        print_error(str(e))
        raise click.Abort()
    except KeyboardInterrupt:
        print_error("Process interrupted by user")
        raise click.Abort()
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        raise click.Abort()


@app.command()
@click.option("--config", help="Path to presskit.json config file")
def status(config: t.Optional[str] = None):
    """Show query cache status."""
    try:
        config_path = find_config_file(config)
        site_config = load_site_config(config_path)
        print_info(f"Using config: {config_path}")

        success = cmd_data_status(site_config)
        if not success:
            raise click.Abort()
    except (FileNotFoundError, ConfigError) as e:
        print_error(str(e))
        raise click.Abort()
    except KeyboardInterrupt:
        print_error("Process interrupted by user")
        raise click.Abort()
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        raise click.Abort()


@app.command()
@click.option("--config", help="Path to presskit.json config file")
def generate(config: t.Optional[str] = None):
    """Generate pages from generator queries."""
    try:
        config_path = find_config_file(config)
        site_config = load_site_config(config_path)
        print_info(f"Using config: {config_path}")

        success = cmd_generate(site_config)
        if not success:
            raise click.Abort()
    except (FileNotFoundError, ConfigError) as e:
        print_error(str(e))
        raise click.Abort()
    except KeyboardInterrupt:
        print_error("Process interrupted by user")
        raise click.Abort()
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        raise click.Abort()


@app.command()
@click.option("--reload", is_flag=True, help="Watch for changes and rebuild automatically")
@click.option("--disable-smart-reload", is_flag=True, help="Rebuild everything on change")
@click.option("--config", help="Path to presskit.json config file")
def server(reload: bool = False, disable_smart_reload: bool = False, config: t.Optional[str] = None):
    """Start a development server."""
    try:
        config_path = find_config_file(config)
        site_config = load_site_config(config_path)
        print_info(f"Using config: {config_path}")

        success = cmd_server(site_config, reload, smart_reload=not disable_smart_reload)
        if not success:
            raise click.Abort()
    except (FileNotFoundError, ConfigError) as e:
        print_error(str(e))
        raise click.Abort()
    except KeyboardInterrupt:
        print_error("Process interrupted by user")
        raise click.Abort()
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        raise click.Abort()


@app.command()
@click.option("--config", help="Path to presskit.json config file")
def clean(config: t.Optional[str] = None):
    """Clean build artifacts and cache."""
    try:
        config_path = find_config_file(config)
        site_config = load_site_config(config_path)
        print_info(f"Using config: {config_path}")

        success = cmd_clean(site_config)
        if not success:
            raise click.Abort()
    except (FileNotFoundError, ConfigError) as e:
        print_error(str(e))
        raise click.Abort()
    except KeyboardInterrupt:
        print_error("Process interrupted by user")
        raise click.Abort()
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        raise click.Abort()


@app.command()
def sources():
    """List available data sources."""
    try:
        success = cmd_sources()
        if not success:
            raise click.Abort()
    except KeyboardInterrupt:
        print_error("Process interrupted by user")
        raise click.Abort()
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        raise click.Abort()


@app.command()
@click.argument("file", required=False)
@click.option("--source", multiple=True, help="JSON data source files")
@click.option("--template", help="Template file to use (default: use file's layout from frontmatter)")
@click.option("--output", help="Output HTML file path")
@click.option("--config", help="Path to presskit.json config file (optional)")
@click.option("--watch", is_flag=True, help="Watch for changes and recompile automatically")
@click.option("--type", "file_type", type=click.Choice(["md", "html"]), help="File type when reading from stdin")
@click.pass_context
def compile(
    ctx,
    file: t.Optional[str],
    source: t.Tuple[str, ...],
    template: t.Optional[str] = None,
    output: t.Optional[str] = None,
    config: t.Optional[str] = None,
    watch: bool = False,
    file_type: t.Optional[str] = None,
):
    """Compile a single Markdown or HTML file with Jinja templating.

    Supports compiling individual files with custom data sources and templates.
    If no file is provided or file is '-', reads from stdin.

    \b
    presskit compile page.md
    presskit compile page.html --template base.html --output out.html
    presskit compile page.md --source data.json --source users.json
    presskit compile --type md < input.md
    echo "# Hello" | presskit compile --type md
    """
    try:
        # Handle stdin input
        if file is None or file == "-":
            if not file_type:
                print_error("--type option is required when reading from stdin")
                print_error("Use --type md for Markdown or --type html for HTML content")
                ctx.exit(1)
            import sys

            stdin_content = sys.stdin.read()
            if not stdin_content.strip():
                print_error("No content provided from stdin")
                raise click.Abort()
        else:
            stdin_content = None

        success = cmd_compile(
            file_path=file,
            sources=list(source),
            template_override=template,
            output_path=output,
            config_file=config,
            watch=watch,
            stdin_content=stdin_content,
            file_type=file_type,
        )
        if not success:
            raise click.Abort()
    except click.exceptions.Exit:
        raise  # Re-raise Exit exceptions to let Click handle them cleanly
    except (FileNotFoundError, ConfigError) as e:
        print_error(str(e))
        raise click.Abort()
    except KeyboardInterrupt:
        print_error("Process interrupted by user")
        raise click.Abort()
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        raise click.Abort()


@app.command()
@click.option("--config", help="Path to presskit.json config file")
def plugins(config: t.Optional[str] = None):
    """List loaded plugins."""
    try:
        load_config_with_plugins(config)
        plugins_list = get_plugins()

        if not plugins_list:
            print_info("No plugins loaded.")
            return

        print_success(f"Loaded {len(plugins_list)} plugin(s):")
        for plugin in plugins_list:
            print(f"  - {plugin['name']}")
            if plugin.get("version"):
                print(f"    Version: {plugin['version']}")
            if plugin.get("hooks"):
                print(f"    Hooks: {', '.join(plugin['hooks'])}")
            if plugin.get("static_path"):
                print(f"    Static path: {plugin['static_path']}")
            if plugin.get("templates_path"):
                print(f"    Templates path: {plugin['templates_path']}")
            print()

    except (FileNotFoundError, ConfigError) as e:
        print_error(str(e))
        raise click.Abort()


def main_cli():
    """Main entry point for the CLI."""
    app()

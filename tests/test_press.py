"""Tests for presskit press.py module."""

import json
import pytest
import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

from presskit.press import (
    find_config_file,
    load_site_config,
    build_site_context,
    build_build_context,
    build_page_context,
    build_data_context,
    extract_front_matter,
    sanitize_value,
    replace_path_placeholders,
    load_json,
    save_json,
    process_sql_template,
    process_markdown,
    process_template,
    get_site_paths,
    ensure_directories,
    check_query_cache,
    cmd_compile,
    compile_markdown_file,
    compile_markdown_content,
    compile_html_file,
    compile_html_content,
    load_frontmatter_sources,
    create_minimal_config,
)
from presskit.config.loader import ConfigError
from presskit.config.models import (
    SiteConfig,
    SiteContext,
)


class TestConfigFunctions:
    """Test configuration loading and validation functions."""

    def test_find_config_file_with_arg(self, tmp_path: Path) -> None:
        """Test find_config_file when config arg is provided."""
        config_file = tmp_path / "myconfig.json"
        config_file.write_text("{}")
        
        result = find_config_file(str(config_file))
        assert result == config_file
    
    def test_find_config_file_not_found(self) -> None:
        """Test find_config_file raises error when file not found."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            find_config_file("/nonexistent/path.json")
    
    @patch("presskit.press.Path.cwd")
    def test_find_config_file_default(self, mock_cwd: MagicMock, tmp_path: Path) -> None:
        """Test find_config_file looks for default presskit.json."""
        mock_cwd.return_value = tmp_path
        config_file = tmp_path / "presskit.json"
        config_file.write_text("{}")
        
        result = find_config_file()
        assert result == config_file
    
    def test_load_site_config_valid(self, tmp_path: Path) -> None:
        """Test loading valid site configuration."""
        config_data = {
            "title": "Test Site",
            "description": "A test site",
            "author": "Test Author"
        }
        config_file = tmp_path / "presskit.json"
        config_file.write_text(json.dumps(config_data))
        
        config = load_site_config(config_file)
        assert config.title == "Test Site"
        assert config.description == "A test site"
        assert config.author == "Test Author"
    
    def test_load_site_config_invalid_json(self, tmp_path: Path) -> None:
        """Test loading invalid JSON raises ConfigError."""
        config_file = tmp_path / "presskit.json"
        config_file.write_text("{invalid json}")
        
        with pytest.raises(ConfigError, match="Error loading configuration file"):
            load_site_config(config_file)
    
    def test_load_site_config_resolves_paths(self, tmp_path: Path) -> None:
        """Test that load_site_config resolves relative paths."""
        config_data = {
            "title": "Test Site",
            "content_dir": "content",
            "sources": [
                {
                    "name": "db",
                    "type": "sqlite",
                    "path": "data/test.db"
                }
            ]
        }
        config_file = tmp_path / "presskit.json"
        config_file.write_text(json.dumps(config_data))
        
        config = load_site_config(config_file)
        assert config.content_dir.is_absolute()
        resolved_path = next(s for s in config.sources if s.name == "db").get_resolved_path(config.site_dir)
        assert resolved_path is not None and resolved_path.is_absolute()


class TestContextBuilders:
    """Test context builder functions."""

    def test_build_site_context(self) -> None:
        """Test building site context from config."""
        config = SiteConfig(
            title="My Site",
            description="Test description",
            author="John Doe",
            url="https://example.com",
            version="1.0.0",
            language="en-GB"
        )
        
        context = build_site_context(config)
        assert context.title == "My Site"
        assert context.description == "Test description"
        assert context.author == "John Doe"
        assert context.url == "https://example.com"
        assert context.version == "1.0.0"
        assert context.language == "en-GB"
    
    @patch("presskit.press.datetime")
    def test_build_build_context(self, mock_datetime: MagicMock) -> None:
        """Test building build context with mocked time."""
        mock_now = datetime.datetime(2024, 6, 11, 12, 30, 45, tzinfo=datetime.timezone.utc)
        mock_datetime.datetime.now.return_value = mock_now
        
        context = build_build_context()
        assert context.date == "2024-06-11"
        assert context.year == "2024"
        assert context.timestamp == mock_now
        assert context.iso_date == "2024-06-11T12:30:45Z"
    
    def test_build_page_context(self, tmp_path: Path) -> None:
        """Test building page context for a file."""
        config = SiteConfig(
            content_dir=tmp_path / "content",
            markdown_extension="md"
        )
        file_path = tmp_path / "content" / "blog" / "post.md"
        file_path.parent.mkdir(parents=True)
        file_path.touch()
        
        front_matter = {
            "title": "My Post",
            "description": "A blog post",
            "layout": "blog"
        }
        
        context = build_page_context(file_path, config, front_matter)
        assert context.filename == "post"
        assert context.filepath == str(file_path)
        assert context.path == "blog/post"
        assert context.layout == "blog"
        assert context.title == "My Post"
        assert context.description == "A blog post"
    
    def test_build_data_context(self) -> None:
        """Test building data context from cache and page queries."""
        query_cache = {
            "queries": {
                "posts": [{"id": 1, "title": "Post 1"}],
                "categories": [{"id": 1, "name": "Tech"}]
            },
            "data": {
                "config": {"theme": "dark"}
            }
        }
        page_queries = {
            "recent": [{"id": 2, "title": "Recent Post"}]
        }
        
        context = build_data_context(query_cache, page_queries)
        assert context.queries["posts"] == [{"id": 1, "title": "Post 1"}]
        assert context.queries["categories"] == [{"id": 1, "name": "Tech"}]
        assert context.sources["config"] == {"theme": "dark"}
        assert context.page_queries["recent"] == [{"id": 2, "title": "Recent Post"}]


class TestMarkdownProcessing:
    """Test markdown and front matter processing."""

    def test_extract_front_matter_with_yaml(self) -> None:
        """Test extracting YAML front matter from markdown."""
        content = """---
title: Test Page
layout: custom
queries:
  posts:
    source: db
    query: SELECT * FROM posts
---

# Hello World

This is content."""
        
        front_matter, md_content, queries, sources = extract_front_matter(content)
        assert front_matter == {"title": "Test Page", "layout": "custom"}
        assert queries == {"posts": {"source": "db", "query": "SELECT * FROM posts"}}
        assert md_content.strip() == "# Hello World\n\nThis is content."
    
    def test_extract_front_matter_no_yaml(self) -> None:
        """Test extracting from content without front matter."""
        content = "# Just Markdown\n\nNo front matter here."
        
        front_matter, md_content, queries, sources = extract_front_matter(content)
        assert front_matter == {}
        assert queries == {}
        assert md_content == content
    
    def test_extract_front_matter_invalid_yaml(self) -> None:
        """Test handling invalid YAML gracefully."""
        content = """---
title: Test
invalid yaml here: [
---

Content here."""
        
        front_matter, md_content, queries, sources = extract_front_matter(content)
        assert front_matter == {}
        assert queries == {}
        assert md_content == content


class TestUtilityFunctions:
    """Test utility functions."""

    def test_sanitize_value(self) -> None:
        """Test sanitizing values for file paths."""
        assert sanitize_value("Hello World") == "Hello-World"
        assert sanitize_value("Test@#$%123") == "Test123"
        assert sanitize_value(None) == "uncategorized"
        assert sanitize_value("under_score-dash") == "under_score-dash"
    
    def test_replace_path_placeholders(self) -> None:
        """Test replacing placeholders in path templates."""
        template = "posts/#{category}/#{slug}"
        row = {"category": "tech", "slug": "my-post"}
        
        result = replace_path_placeholders(template, row)
        assert result == "posts/tech/my-post"
    
    def test_replace_path_placeholders_nested(self) -> None:
        """Test replacing nested placeholders."""
        template = "authors/#{author.slug}/posts"
        row = {"author": [{"slug": "john-doe"}]}
        
        result = replace_path_placeholders(template, row)
        assert result == "authors/john-doe/posts"
    
    def test_replace_path_placeholders_missing_value(self) -> None:
        """Test replacing placeholders with missing values."""
        template = "posts/#{category}/#{slug}"
        row = {"slug": "my-post"}
        
        result = replace_path_placeholders(template, row)
        assert result == "posts//my-post"  # Empty string for missing values
    
    def test_load_json_valid(self, tmp_path: Path) -> None:
        """Test loading valid JSON file."""
        json_file = tmp_path / "test.json"
        data = {"key": "value", "list": [1, 2, 3]}
        json_file.write_text(json.dumps(data))
        
        result = load_json(json_file)
        assert result == data
    
    def test_load_json_not_found(self, tmp_path: Path) -> None:
        """Test loading non-existent JSON file."""
        result = load_json(tmp_path / "nonexistent.json")
        assert result is None
    
    def test_load_json_invalid(self, tmp_path: Path) -> None:
        """Test loading invalid JSON file."""
        json_file = tmp_path / "invalid.json"
        json_file.write_text("{invalid json}")
        
        result = load_json(json_file)
        assert result is None
    
    def test_save_json_dict(self, tmp_path: Path) -> None:
        """Test saving dictionary as JSON."""
        json_file = tmp_path / "output.json"
        data = {"key": "value", "number": 42}
        
        result = save_json(data, json_file)
        assert result is True
        
        loaded = json.loads(json_file.read_text())
        assert loaded == data
    
    def test_save_json_basemodel(self, tmp_path: Path) -> None:
        """Test saving Pydantic model as JSON."""
        json_file = tmp_path / "model.json"
        context = SiteContext(title="Test", language="en")
        
        result = save_json(context, json_file)
        assert result is True
        
        loaded = json.loads(json_file.read_text())
        assert loaded["title"] == "Test"
        assert loaded["language"] == "en"


class TestTemplateProcessing:
    """Test template processing functions."""

    def test_process_sql_template(self) -> None:
        """Test processing SQL with Jinja2 variables."""
        sql = "SELECT * FROM posts WHERE author_id = {{ author_id }} AND status = '{{ status }}'"
        variables = {"author_id": 123, "status": "published"}
        
        result = process_sql_template(sql, variables)
        assert result == "SELECT * FROM posts WHERE author_id = 123 AND status = 'published'"
    
    def test_process_sql_template_with_filter(self) -> None:
        """Test SQL template with custom filter."""
        sql = "SELECT * FROM posts WHERE date >= '{{ start_date | date_format('%Y-%m-%d') }}'"
        variables = {"start_date": "2024-06-11"}
        
        result = process_sql_template(sql, variables)
        assert result == "SELECT * FROM posts WHERE date >= '2024-06-11'"
    
    def test_process_markdown_basic(self, tmp_path: Path) -> None:
        """Test basic markdown to HTML conversion."""
        md_content = "# Hello\n\nThis is **bold** text."
        variables = {}
        
        html = process_markdown(md_content, variables, tmp_path)
        assert '<h1 id="hello">Hello</h1>' in html
        assert "<strong>bold</strong>" in html
    
    def test_process_markdown_with_jinja(self, tmp_path: Path) -> None:
        """Test markdown with Jinja2 templating."""
        md_content = "# {{ title }}\n\nAuthor: {{ author }}"
        variables = {"title": "My Post", "author": "John Doe"}
        
        html = process_markdown(md_content, variables, tmp_path)
        assert '<h1 id="my-post">My Post</h1>' in html
        assert "Author: John Doe" in html
    
    def test_process_template(self, tmp_path: Path) -> None:
        """Test HTML template processing."""
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        
        template_file = template_dir / "page.html"
        template_file.write_text("""
<!DOCTYPE html>
<html>
<head><title>{{ page.title }}</title></head>
<body>
    <h1>{{ site.title }}</h1>
    {{ page.content }}
</body>
</html>
        """)
        
        variables = {
            "site": {"title": "My Site"},
            "page": {"title": "Page Title", "content": "<p>Content here</p>"}
        }
        
        html = process_template("page", variables, template_dir)
        assert "<title>Page Title</title>" in html
        assert "<h1>My Site</h1>" in html
        assert "<p>Content here</p>" in html


class TestFileOperations:
    """Test file and directory operations."""

    def test_get_site_paths(self, tmp_path: Path) -> None:
        """Test getting standard site paths."""
        paths = get_site_paths(tmp_path)
        
        assert paths.content_dir == tmp_path / "content"
        assert paths.templates_dir == tmp_path / "templates"
        assert paths.cache_dir == tmp_path / ".cache"
        assert paths.config_file == tmp_path / "presskit.json"
        assert paths.query_cache_file == tmp_path / ".cache" / "queries.json"
    
    def test_ensure_directories(self, tmp_path: Path) -> None:
        """Test ensuring required directories exist."""
        config = SiteConfig(
            content_dir=tmp_path / "content",
            templates_dir=tmp_path / "templates",
            cache_dir=tmp_path / ".cache",
            output_dir=tmp_path / "public"
        )
        
        ensure_directories(config)
        
        assert config.content_dir.exists()
        assert config.templates_dir.exists()
        assert config.cache_dir.exists()
        assert config.output_dir.exists()
    
    def test_check_query_cache_exists(self, tmp_path: Path) -> None:
        """Test checking valid query cache."""
        config = SiteConfig(cache_dir=tmp_path / ".cache")
        config.cache_dir.mkdir()
        
        cache_file = config.cache_dir / "queries.json"
        cache_data = {
            "metadata": {"generated": "2024-06-11"},
            "queries": {},
            "generators": {}
        }
        cache_file.write_text(json.dumps(cache_data))
        
        assert check_query_cache(config) is True
    
    def test_check_query_cache_not_exists(self, tmp_path: Path) -> None:
        """Test checking when cache doesn't exist."""
        config = SiteConfig(cache_dir=tmp_path / ".cache")
        assert check_query_cache(config) is False
    
    def test_check_query_cache_invalid(self, tmp_path: Path) -> None:
        """Test checking invalid cache file."""
        config = SiteConfig(cache_dir=tmp_path / ".cache")
        config.cache_dir.mkdir()
        
        cache_file = config.cache_dir / "queries.json"
        cache_file.write_text(json.dumps({"incomplete": "data"}))
        
        assert check_query_cache(config) is False


# Query execution tests have been moved to source-specific test files
# since execute_query is now part of the individual data source implementations


class TestDateFilter:
    """Test the date_format filter function."""

    def test_date_format_valid(self) -> None:
        """Test formatting valid date string."""
        from presskit.press import date_format
        
        result = date_format("2024-06-11", "%B %d, %Y")
        assert result == "June 11, 2024"
        
        result = date_format("2024-01-01", "%Y/%m/%d")
        assert result == "2024/01/01"
    
    def test_date_format_invalid(self) -> None:
        """Test formatting invalid date string."""
        from presskit.press import date_format
        
        result = date_format("invalid-date", "%B %d, %Y")
        assert result == "invalid-date"  # Returns original value on error


class TestCompileFunctionality:
    """Test compile functionality."""

    def test_cmd_compile_markdown_file(self, tmp_path: Path) -> None:
        """Test compiling a simple markdown file."""
        
        # Create a markdown file
        md_file = tmp_path / "test.md"
        md_content = """---
title: Test Page
layout: none
---

# Hello World

This is a **test** page.
"""
        md_file.write_text(md_content)
        
        # Compile the file
        result = cmd_compile(
            file_path=str(md_file),
            sources=[],
            template_override=None,
            output_path=None,
            watch=False
        )
        
        assert result is True
        
        # Check output file exists
        output_file = tmp_path / "test.html"
        assert output_file.exists()
        
        # Check content
        html_content = output_file.read_text()
        assert '<h1 id="hello-world">Hello World</h1>' in html_content
        assert '<strong>test</strong>' in html_content

    def test_cmd_compile_markdown_with_template(self, tmp_path: Path) -> None:
        """Test compiling markdown with custom template."""
        
        # Create template
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        template_file = template_dir / "custom.html"
        template_file.write_text("""
<!DOCTYPE html>
<html>
<head><title>{{ page.title }}</title></head>
<body>
    <header>{{ site.title }}</header>
    <main>{{ page.content }}</main>
</body>
</html>
        """)
        
        # Create content directory (needed for config path resolution)
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        
        # Create config file
        config_file = tmp_path / "presskit.json"
        config_data = {
            "title": "My Site",
            "templates_dir": "./templates",
            "content_dir": "./content"
        }
        config_file.write_text(json.dumps(config_data))
        
        # Create markdown file in content directory
        md_file = content_dir / "test.md"
        md_content = """---
title: Custom Template Test
layout: custom
---

# Content Here
"""
        md_file.write_text(md_content)
        
        result = cmd_compile(
            file_path=str(md_file),
            sources=[],
            template_override=None,
            output_path=None,
            config_file=str(config_file),
            watch=False
        )
        
        assert result is True
        
        output_file = content_dir / "test.html"
        html_content = output_file.read_text()
        assert "<title>Custom Template Test</title>" in html_content
        assert "<header>My Site</header>" in html_content
        assert '<h1 id="content-here">Content Here</h1>' in html_content

    def test_cmd_compile_with_json_source(self, tmp_path: Path) -> None:
        """Test compiling with JSON data source."""
        
        # Create JSON data source
        data_file = tmp_path / "data.json"
        data = {"users": [{"name": "John", "age": 30}, {"name": "Jane", "age": 25}]}
        data_file.write_text(json.dumps(data))
        
        # Create markdown file
        md_file = tmp_path / "test.md"
        md_content = """---
title: Users List
layout: none
---

# Users

{% for user in data.sources.data.users %}
- {{ user.name }} ({{ user.age }} years old)
{% endfor %}
"""
        md_file.write_text(md_content)
        
        result = cmd_compile(
            file_path=str(md_file),
            sources=[str(data_file)],
            watch=False
        )
        
        assert result is True
        
        output_file = tmp_path / "test.html"
        html_content = output_file.read_text()
        assert "John (30 years old)" in html_content
        assert "Jane (25 years old)" in html_content

    def test_cmd_compile_stdin_markdown(self) -> None:
        """Test compiling markdown from stdin."""
        
        stdin_content = """---
title: Stdin Test
---

# From Stdin

This came from **stdin**.
"""
        
        result = cmd_compile(
            file_path=None,
            sources=[],
            stdin_content=stdin_content,
            file_type="md",
            watch=False
        )
        
        assert result is True

    def test_cmd_compile_html_file(self, tmp_path: Path) -> None:
        """Test compiling HTML file with Jinja templating."""
        
        # Create HTML file with template variables
        html_file = tmp_path / "test.html"
        html_content = """---
title: HTML Template Test
---

<h1>{{ page.title }}</h1>
<p>Generated at: {{ build.date }}</p>
"""
        html_file.write_text(html_content)
        
        result = cmd_compile(
            file_path=str(html_file),
            sources=[],
            watch=False
        )
        
        assert result is True
        
        output_file = tmp_path / "test_compiled.html"
        assert output_file.exists()
        
        compiled_content = output_file.read_text()
        assert "<h1>HTML Template Test</h1>" in compiled_content
        assert "Generated at:" in compiled_content

    def test_cmd_compile_nonexistent_file(self) -> None:
        """Test compiling nonexistent file returns False."""
        
        result = cmd_compile(
            file_path="/nonexistent/file.md",
            sources=[],
            watch=False
        )
        
        assert result is False

    def test_cmd_compile_stdin_without_file_type(self) -> None:
        """Test compiling from stdin without file type fails."""
        
        result = cmd_compile(
            file_path=None,
            sources=[],
            stdin_content="# Test",
            file_type=None,
            watch=False
        )
        
        assert result is False

    def test_compile_markdown_file(self, tmp_path: Path) -> None:
        """Test compile_markdown_file function directly."""
        
        # Create markdown file with frontmatter
        md_file = tmp_path / "article.md"
        md_content = """---
title: Direct Test
description: Testing compile_markdown_file directly
layout: none
---

# Article Title

This is the article content with **formatting**.
"""
        md_file.write_text(md_content)
        
        result = compile_markdown_file(
            input_file=md_file,
            json_data={},
            template_override=None,
            output_path=None,
            config=None
        )
        
        assert result is True
        
        output_file = tmp_path / "article.html"
        assert output_file.exists()
        
        html_content = output_file.read_text()
        assert '<h1 id="article-title">Article Title</h1>' in html_content
        assert '<strong>formatting</strong>' in html_content

    def test_compile_markdown_content(self) -> None:
        """Test compile_markdown_content function with string input."""
        
        md_content = """---
title: String Content Test
---

# From String

This is **markdown** from a string.
"""
        
        result = compile_markdown_content(
            content=md_content,
            json_data={},
            template_override=None,
            output_path=None,
            config=None
        )
        
        assert result is True

    def test_compile_html_file(self, tmp_path: Path) -> None:
        """Test compile_html_file function directly."""
        
        # Create HTML file
        html_file = tmp_path / "template.html"
        html_content = """---
title: HTML File Test
layout: none
---

<div class="content">
    <h2>{{ page.title }}</h2>
    <p>Current year: {{ build.year }}</p>
</div>
"""
        html_file.write_text(html_content)
        
        result = compile_html_file(
            input_file=html_file,
            json_data={},
            template_override=None,
            output_path=None,
            config=None
        )
        
        assert result is True
        
        output_file = tmp_path / "template_compiled.html"
        assert output_file.exists()
        
        compiled_content = output_file.read_text()
        assert "<h2>HTML File Test</h2>" in compiled_content
        assert "Current year:" in compiled_content

    def test_compile_html_content(self) -> None:
        """Test compile_html_content function with string input."""
        
        html_content = """---
title: HTML String Test
---

<section>
    <h1>{{ page.title }}</h1>
    <time>{{ build.iso_date }}</time>
</section>
"""
        
        result = compile_html_content(
            content=html_content,
            json_data={},
            template_override=None,
            output_path=None,
            config=None
        )
        
        assert result is True

    def test_load_frontmatter_sources(self, tmp_path: Path) -> None:
        """Test load_frontmatter_sources function."""
        
        # Create JSON source files
        users_file = tmp_path / "users.json"
        users_data = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        users_file.write_text(json.dumps(users_data))
        
        config_file = tmp_path / "config.json"
        config_data = {"theme": "dark", "version": "2.0"}
        config_file.write_text(json.dumps(config_data))
        
        # Define sources configuration
        sources_config = {
            "users": {
                "type": "json",
                "path": "users.json"
            },
            "site_config": {
                "type": "json", 
                "path": "config.json"
            }
        }
        
        result = load_frontmatter_sources(sources_config, tmp_path)
        
        assert "users" in result
        assert "site_config" in result
        assert result["users"] == users_data
        assert result["site_config"] == config_data

    def test_load_frontmatter_sources_missing_file(self, tmp_path: Path) -> None:
        """Test load_frontmatter_sources with missing file."""
        
        sources_config = {
            "missing": {
                "type": "json",
                "path": "nonexistent.json"
            }
        }
        
        result = load_frontmatter_sources(sources_config, tmp_path)
        
        assert result == {}

    def test_load_frontmatter_sources_invalid_json(self, tmp_path: Path) -> None:
        """Test load_frontmatter_sources with invalid JSON."""
        
        # Create invalid JSON file
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json content")
        
        sources_config = {
            "bad_data": {
                "type": "json",
                "path": "bad.json"
            }
        }
        
        result = load_frontmatter_sources(sources_config, tmp_path)
        
        assert result == {}

    def test_create_minimal_config(self, tmp_path: Path) -> None:
        """Test create_minimal_config function."""
        
        config = create_minimal_config(tmp_path)
        
        assert config.title == "Compiled Page"
        assert config.site_dir == tmp_path
        assert config.content_dir == tmp_path
        assert config.templates_dir == tmp_path / "templates"
        assert config.output_dir == tmp_path
        assert config.cache_dir == tmp_path / ".cache"

    def test_cmd_compile_with_custom_output_path(self, tmp_path: Path) -> None:
        """Test compiling with custom output path."""
        
        # Create markdown file
        md_file = tmp_path / "input.md"
        md_content = "# Custom Output Path Test"
        md_file.write_text(md_content)
        
        # Custom output path
        output_path = tmp_path / "custom" / "output.html"
        
        result = cmd_compile(
            file_path=str(md_file),
            sources=[],
            output_path=str(output_path),
            watch=False
        )
        
        assert result is True
        assert output_path.exists()
        
        html_content = output_path.read_text()
        assert '<h1 id="custom-output-path-test">Custom Output Path Test</h1>' in html_content

    def test_cmd_compile_with_template_override(self, tmp_path: Path) -> None:
        """Test compiling with template override."""
        
        # Create template
        template_file = tmp_path / "override.html"
        template_file.write_text("""
<html>
<head><title>Override: {{ page.title }}</title></head>
<body>{{ page.content }}</body>
</html>
        """)
        
        # Create markdown file
        md_file = tmp_path / "test.md"
        md_content = """---
title: Override Test
layout: default
---

# Overridden Template
"""
        md_file.write_text(md_content)
        
        result = cmd_compile(
            file_path=str(md_file),
            sources=[],
            template_override="override",
            watch=False
        )
        
        assert result is True
        
        output_file = tmp_path / "test.html"
        html_content = output_file.read_text()
        assert "<title>Override: Override Test</title>" in html_content

    def test_cmd_compile_unsupported_file_type(self, tmp_path: Path) -> None:
        """Test compiling unsupported file type returns False."""
        
        # Create unsupported file
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Plain text file")
        
        result = cmd_compile(
            file_path=str(txt_file),
            sources=[],
            watch=False
        )
        
        assert result is False

    def test_cmd_compile_invalid_json_source(self, tmp_path: Path) -> None:
        """Test compiling with invalid JSON source fails."""
        
        # Create invalid JSON file
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{invalid json")
        
        # Create markdown file
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test")
        
        result = cmd_compile(
            file_path=str(md_file),
            sources=[str(bad_json)],
            watch=False
        )
        
        assert result is False

    def test_cmd_compile_missing_json_source(self, tmp_path: Path) -> None:
        """Test compiling with missing JSON source fails."""
        
        # Create markdown file
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test")
        
        result = cmd_compile(
            file_path=str(md_file),
            sources=["/nonexistent/data.json"],
            watch=False
        )
        
        assert result is False

    def test_cmd_compile_with_frontmatter_sources(self, tmp_path: Path) -> None:
        """Test compiling with sources defined in frontmatter."""
        
        # Create JSON data source
        data_file = tmp_path / "posts.json"
        posts_data = [{"title": "Post 1", "content": "Content 1"}]
        data_file.write_text(json.dumps(posts_data))
        
        # Create markdown file with frontmatter sources
        md_file = tmp_path / "test.md"
        md_content = """---
title: Frontmatter Sources Test
layout: none
sources:
  posts:
    type: json
    path: posts.json
---

# Posts

{% for post in data.sources.posts %}
- {{ post.title }}: {{ post.content }}
{% endfor %}
"""
        md_file.write_text(md_content)
        
        result = cmd_compile(
            file_path=str(md_file),
            sources=[],
            watch=False
        )
        
        assert result is True
        
        output_file = tmp_path / "test.html"
        html_content = output_file.read_text()
        assert "Post 1: Content 1" in html_content

    def test_compile_markdown_with_invalid_template(self, tmp_path: Path) -> None:
        """Test compiling with invalid template gracefully handles error."""
        
        # Create markdown file requesting non-existent template
        md_file = tmp_path / "test.md"
        md_content = """---
title: Missing Template Test
layout: nonexistent
---

# Content
"""
        md_file.write_text(md_content)
        
        result = compile_markdown_file(
            input_file=md_file,
            json_data={},
            template_override=None,
            output_path=None,
            config=None
        )
        
        # Should still succeed but with warning about missing template
        assert result is True
        
        output_file = tmp_path / "test.html"
        assert output_file.exists()

    def test_cmd_compile_with_absolute_output_path(self, tmp_path: Path) -> None:
        """Test compiling with absolute output path."""
        
        # Create markdown file
        md_file = tmp_path / "input.md"
        md_content = "# Absolute Path Test"
        md_file.write_text(md_content)
        
        # Create separate output directory
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_path = output_dir / "result.html"
        
        result = cmd_compile(
            file_path=str(md_file),
            sources=[],
            output_path=str(output_path),
            watch=False
        )
        
        assert result is True
        assert output_path.exists()

    def test_compile_html_with_template_layout(self, tmp_path: Path) -> None:
        """Test compiling HTML file with template layout."""
        
        # Create base template
        base_template = tmp_path / "base.html"
        base_template.write_text("""
<!DOCTYPE html>
<html>
<head><title>Base: {{ page.title }}</title></head>
<body>
    <nav>Navigation</nav>
    {{ page.content }}
    <footer>Footer</footer>
</body>
</html>
        """)
        
        # Create HTML file with layout
        html_file = tmp_path / "content.html"
        html_content = """---
title: Layout Test
layout: base
---

<main>
    <h1>{{ page.title }}</h1>
    <p>This content uses a layout template.</p>
</main>
"""
        html_file.write_text(html_content)
        
        result = compile_html_file(
            input_file=html_file,
            json_data={},
            template_override=None,
            output_path=None,
            config=None
        )
        
        assert result is True
        
        output_file = tmp_path / "content_compiled.html"
        compiled_content = output_file.read_text()
        assert "<title>Base: Layout Test</title>" in compiled_content
        assert "<nav>Navigation</nav>" in compiled_content
        assert "<footer>Footer</footer>" in compiled_content
        assert "<h1>Layout Test</h1>" in compiled_content

    def test_cmd_compile_stdin_html(self) -> None:
        """Test compiling HTML from stdin."""
        
        stdin_content = """---
title: HTML from Stdin
---

<div class="container">
    <h1>{{ page.title }}</h1>
    <p>Generated on {{ build.date }}</p>
</div>
"""
        
        result = cmd_compile(
            file_path=None,
            sources=[],
            stdin_content=stdin_content,
            file_type="html",
            watch=False
        )
        
        assert result is True

    def test_load_frontmatter_sources_with_absolute_path(self, tmp_path: Path) -> None:
        """Test load_frontmatter_sources with absolute paths."""
        
        # Create JSON file in different directory
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        json_file = data_dir / "absolute.json"
        json_data = {"key": "absolute value"}
        json_file.write_text(json.dumps(json_data))
        
        # Use absolute path in sources config
        sources_config = {
            "absolute_data": {
                "type": "json",
                "path": str(json_file)  # Absolute path
            }
        }
        
        result = load_frontmatter_sources(sources_config, tmp_path)
        
        assert "absolute_data" in result
        assert result["absolute_data"] == json_data

    def test_load_frontmatter_sources_invalid_config(self, tmp_path: Path) -> None:
        """Test load_frontmatter_sources with invalid configuration."""
        
        # Invalid config - not a dict
        sources_config = {
            "invalid": "not a dict"
        }
        
        result = load_frontmatter_sources(sources_config, tmp_path)
        
        assert result == {}

    def test_load_frontmatter_sources_missing_path(self, tmp_path: Path) -> None:
        """Test load_frontmatter_sources with missing path key."""
        
        sources_config = {
            "no_path": {
                "type": "json"
                # Missing "path" key
            }
        }
        
        result = load_frontmatter_sources(sources_config, tmp_path)
        
        assert result == {}
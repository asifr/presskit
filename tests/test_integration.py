"""Integration tests for presskit workflow."""

import json
import sqlite3
import typing as t
from pathlib import Path

from presskit.press import (
    load_site_config,
    cmd_data,
    cmd_build,
    cmd_clean,
    build_file,
    process_queries,
)


class TestFullWorkflow:
    """Test complete presskit workflow from config to build."""

    def setup_test_site(self, tmp_path: Path) -> Path:
        """Set up a test site with all required files."""
        # Create directory structure
        (tmp_path / "content").mkdir()
        (tmp_path / "templates").mkdir()
        (tmp_path / "data").mkdir()
        
        # Create config file
        config_data = {
            "title": "Test Blog",
            "description": "A test blog site",
            "author": "Test Author",
            "url": "https://testblog.com",
            "version": "1.0.0",
            "sources": {
                "blog_db": {
                    "type": "sqlite",
                    "path": "data/blog.db"
                },
                "site_config": {
                    "type": "json",
                    "path": "data/config.json"
                }
            },
            "default_source": "blog_db",
            "queries": [
                {
                    "name": "recent_posts",
                    "source": "blog_db",
                    "query": "SELECT id, title, slug, content, date FROM posts ORDER BY date DESC LIMIT 5"
                },
                {
                    "name": "all_posts",
                    "source": "blog_db",
                    "query": "SELECT id, title, slug, content, date, author FROM posts",
                    "generator": True,
                    "template": "post",
                    "output_path": "posts/#{slug}"
                },
                {
                    "name": "categories",
                    "source": "blog_db",
                    "query": "SELECT id, name, slug FROM categories"
                },
                {
                    "name": "categories.posts",
                    "source": "blog_db",
                    "query": "SELECT p.id, p.title, p.slug FROM posts p WHERE p.category_id = {{ id }}"
                }
            ]
        }
        
        config_file = tmp_path / "presskit.json"
        config_file.write_text(json.dumps(config_data, indent=2))
        
        # Create SQLite database
        db_path = tmp_path / "data" / "blog.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create tables
        cursor.execute("""
            CREATE TABLE categories (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL,
                slug TEXT NOT NULL,
                content TEXT NOT NULL,
                date TEXT NOT NULL,
                author TEXT NOT NULL,
                category_id INTEGER,
                FOREIGN KEY (category_id) REFERENCES categories (id)
            )
        """)
        
        # Insert test data
        categories = [
            (1, "Technology", "technology"),
            (2, "Travel", "travel"),
            (3, "Food", "food")
        ]
        cursor.executemany("INSERT INTO categories VALUES (?, ?, ?)", categories)
        
        posts = [
            (1, "Getting Started with Python", "python-intro", "Learn Python basics...", "2024-06-01", "John Doe", 1),
            (2, "Advanced Python Tips", "python-advanced", "Advanced techniques...", "2024-06-05", "Jane Smith", 1),
            (3, "Best Travel Destinations", "travel-destinations", "Top places to visit...", "2024-06-08", "John Doe", 2),
            (4, "Cooking Italian Food", "italian-cooking", "Authentic recipes...", "2024-06-10", "Chef Mario", 3),
            (5, "Web Development Trends", "web-trends", "Latest in web dev...", "2024-06-11", "Jane Smith", 1)
        ]
        cursor.executemany(
            "INSERT INTO posts VALUES (?, ?, ?, ?, ?, ?, ?)",
            posts
        )
        
        conn.commit()
        conn.close()
        
        # Create JSON data source
        json_data = {
            "site_theme": "dark",
            "social_links": {
                "twitter": "https://twitter.com/testblog",
                "github": "https://github.com/testblog"
            }
        }
        json_file = tmp_path / "data" / "config.json"
        json_file.write_text(json.dumps(json_data, indent=2))
        
        # Create templates
        base_template = """<!DOCTYPE html>
<html lang="{{ site.language }}">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}{{ page.title or site.title }}{% endblock %}</title>
</head>
<body>
    <header>
        <h1>{{ site.title }}</h1>
        <p>{{ site.description }}</p>
    </header>
    
    <main>
        {% block content %}{% endblock %}
    </main>
    
    <footer>
        <p>&copy; {{ build.year }} {{ site.author }}</p>
    </footer>
</body>
</html>"""
        
        page_template = """{% extends "base.html" %}

{% block content %}
{{ page.content }}
{% endblock %}"""
        
        post_template = """{% extends "base.html" %}

{% block title %}{{ title }} - {{ site.title }}{% endblock %}

{% block content %}
<article>
    <h1>{{ title }}</h1>
    <time>{{ date | date_format('%B %d, %Y') }}</time>
    <p>By {{ author }}</p>
    
    <div class="content">
        {{ content }}
    </div>
    
    <a href="/">← Back to Home</a>
</article>
{% endblock %}"""
        
        (tmp_path / "templates" / "base.html").write_text(base_template)
        (tmp_path / "templates" / "page.html").write_text(page_template)
        (tmp_path / "templates" / "post.html").write_text(post_template)
        
        # Create content files
        index_md = """---
title: Welcome to Test Blog
layout: page
---

# Welcome to {{ site.title }}

This is a test blog built with Presskit.

## Recent Posts

{% for post in data.queries.recent_posts %}
- [{{ post.title }}](/posts/{{ post.slug }}.html) - {{ post.date | date_format('%Y-%m-%d') }}
{% endfor %}

## Categories

{% for category in data.queries.categories %}
### {{ category.name }}

{% if category.posts %}
{% for post in category.posts %}
- [{{ post.title }}](/posts/{{ post.slug }}.html)
{% endfor %}
{% else %}
No posts in this category yet.
{% endif %}
{% endfor %}

Theme: {{ data.sources.site_config.site_theme }}"""
        
        about_md = """---
title: About Us
description: Learn more about our blog
queries:
    author_posts:
        source: blog_db
        query: "SELECT title, slug FROM posts WHERE author = '{{ author_name }}' ORDER BY date DESC"
variables:
    author_name: "John Doe"
---

# About {{ site.title }}

Written by {{ site.author }}.

## Posts by John Doe

{% for post in data.page_queries.author_posts %}
- [{{ post.title }}](/posts/{{ post.slug }}.html)
{% endfor %}"""
        
        (tmp_path / "content" / "index.md").write_text(index_md)
        (tmp_path / "content" / "about.md").write_text(about_md)
        
        return tmp_path
    
    def test_complete_workflow(self, tmp_path: Path) -> None:
        """Test the complete presskit workflow."""
        # Setup test site
        site_dir = self.setup_test_site(tmp_path)
        
        # Load configuration
        config_path = site_dir / "presskit.json"
        config = load_site_config(config_path)
        
        # Step 1: Process queries
        assert cmd_data(config) is True
        
        # Verify cache was created
        cache_file = config.cache_dir / "queries.json"
        assert cache_file.exists()
        
        cache_data = json.loads(cache_file.read_text())
        assert "recent_posts" in cache_data["queries"]
        assert len(cache_data["queries"]["recent_posts"]) == 5
        assert "categories" in cache_data["queries"]
        assert "all_posts" in cache_data["generators"]
        assert "site_config" in cache_data["data"]
        
        # Step 2: Build static pages
        assert cmd_build(config) is True
        
        # Verify index page was built
        index_html = config.output_dir / "index.html"
        assert index_html.exists()
        
        index_content = index_html.read_text()
        assert "Welcome to Test Blog" in index_content
        assert "Getting Started with Python" in index_content
        assert "Technology" in index_content
        
        # Verify about page was built
        about_html = config.output_dir / "about.html"
        assert about_html.exists()
        
        about_content = about_html.read_text()
        assert "About Test Blog" in about_content
        assert "Posts by John Doe" in about_content
        
        # Step 3: Verify generator pages were created
        assert (config.output_dir / "posts" / "python-intro.html").exists()
        assert (config.output_dir / "posts" / "web-trends.html").exists()
        
        # Check generated page content
        post_html = config.output_dir / "posts" / "python-intro.html"
        post_content = post_html.read_text()
        assert "Getting Started with Python" in post_content
        assert "June 01, 2024" in post_content
        assert "By John Doe" in post_content
    
    def test_build_single_file(self, tmp_path: Path) -> None:
        """Test building a single file."""
        site_dir = self.setup_test_site(tmp_path)
        config_path = site_dir / "presskit.json"
        config = load_site_config(config_path)
        
        # Process queries first
        cmd_data(config)
        
        # Build only the about page
        about_file = config.content_dir / "about.md"
        assert cmd_build(config, str(about_file)) is True
        
        # Verify only about page was built
        assert (config.output_dir / "about.html").exists()
        assert not (config.output_dir / "index.html").exists()
    
    def test_clean_command(self, tmp_path: Path) -> None:
        """Test cleaning build artifacts."""
        site_dir = self.setup_test_site(tmp_path)
        config_path = site_dir / "presskit.json"
        config = load_site_config(config_path)
        
        # Create some cache files
        config.cache_dir.mkdir(exist_ok=True)
        (config.cache_dir / "queries.json").write_text("{}")
        (config.cache_dir / "temp.txt").write_text("temp")
        
        # Clean
        assert cmd_clean(config) is True
        
        # Verify cache was cleaned but directory exists
        assert config.cache_dir.exists()
        assert not (config.cache_dir / "queries.json").exists()
        assert not (config.cache_dir / "temp.txt").exists()


class TestErrorHandling:
    """Test error handling in various scenarios."""

    def test_build_without_queries(self, tmp_path: Path) -> None:
        """Test building when queries are configured but not cached."""
        # Create minimal site
        (tmp_path / "content").mkdir()
        (tmp_path / "templates").mkdir()
        
        config_data = {
            "title": "Test Site",
            "sources": {
                "db": {
                    "type": "sqlite",
                    "path": "data/test.db"
                }
            },
            "queries": [
                {
                    "name": "test",
                    "source": "db",
                    "query": "SELECT * FROM test"
                }
            ]
        }
        
        config_file = tmp_path / "presskit.json"
        config_file.write_text(json.dumps(config_data))
        
        config = load_site_config(config_file)
        
        # Try to build without running queries first
        assert cmd_build(config) is False
    
    def test_missing_template(self, tmp_path: Path) -> None:
        """Test handling missing template gracefully."""
        # Setup minimal site
        (tmp_path / "content").mkdir()
        (tmp_path / "templates").mkdir()
        
        config_data = {"title": "Test Site"}
        config_file = tmp_path / "presskit.json"
        config_file.write_text(json.dumps(config_data))
        
        # Create content that references missing template
        content = """---
title: Test
layout: missing_template
---

Test content"""
        (tmp_path / "content" / "test.md").write_text(content)
        
        # Create default page template
        (tmp_path / "templates" / "page.html").write_text(
            "<html><body>{{ page.content }}</body></html>"
        )
        
        config = load_site_config(config_file)
        
        # Should fall back to page.html
        cache_data: t.Optional[t.Dict[str, t.Any]] = None
        result = build_file(
            tmp_path / "content" / "test.md",
            cache_data,
            config
        )
        assert result is True
        assert (config.output_dir / "test.html").exists()
    
    def test_invalid_query_syntax(self, tmp_path: Path) -> None:
        """Test handling invalid SQL query."""
        # Setup site with database
        (tmp_path / "data").mkdir()
        
        config_data = {
            "title": "Test Site",
            "sources": {
                "db": {
                    "type": "sqlite",
                    "path": "data/test.db"
                }
            },
            "queries": [
                {
                    "name": "bad_query",
                    "source": "db",
                    "query": "INVALID SQL SYNTAX"
                }
            ]
        }
        
        config_file = tmp_path / "presskit.json"
        config_file.write_text(json.dumps(config_data))
        
        # Create empty database
        db_path = tmp_path / "data" / "test.db"
        conn = sqlite3.connect(db_path)
        conn.close()
        
        config = load_site_config(config_file)
        
        # Should handle error gracefully
        result = process_queries(config)
        assert result is False  # Should fail due to invalid SQL
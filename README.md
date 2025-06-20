# Presskit

A powerful static site generator that combines Markdown content with Jinja2 templating and database-driven page generation. Presskit lets you build dynamic static sites by connecting your content to SQLite databases and JSON data sources.

## Key Features

- **Jinja2 Templating**: Use Jinja2 variables and logic in both Markdown content and HTML layouts
- **Database Integration**: Load data from SQLite databases and JSON files
- **Dynamic Page Generation**: Generate multiple pages automatically from SQLite query results
- **Structured Context**: Access site metadata, build information, and data through a clean template context

## Installation

```bash
pip install presskit
```

Or you can use [Astral's uv](https://docs.astral.sh/uv/) Python package manager to install Presskit as a self-contained tool so it can be run from the command line without needing to activate a virtual environment:

```bash
uv tool install presskit
```

## Quick Start

1. Create a new site directory:
```bash
mkdir my-site
cd my-site
```

2. Create the basic structure:
```
my-site/
├── presskit.json      # Configuration file
├── content/           # Markdown files
├── templates/         # HTML templates
└── public/            # Generated output (created automatically)
```

3. Build your site:
```bash
presskit build
```

## Basic Usage

### Writing Markdown Content

Create Markdown files in the `content/` directory. Each file can include YAML front matter for metadata:

```
---
title: "Welcome to My Site"
description: "A brief introduction"
layout: page
---

# Welcome

This is my **awesome** site built with Presskit!
```

### Creating HTML Templates

Templates go in the `templates/` directory. Here's a basic `page.html` template:

```html
<!DOCTYPE html>
<html lang="{{ site.language }}">
<head>
    <meta charset="UTF-8">
    <title>{{ page.title or site.title }}</title>
    <meta name="description" content="{{ page.description or site.description }}">
</head>
<body>
    <header>
        <h1>{{ site.title }}</h1>
    </header>
    
    <main>
        {{ page.content }}
    </main>
    
    <footer>
        <p>&copy; {{ build.year }} {{ site.author }}</p>
    </footer>
</body>
</html>
```

### Configuration

Create a `presskit.json` file to configure your site:

```json
{
    "title": "My Awesome Site",
    "description": "A site built with Presskit",
    "author": "Your Name",
    "url": "https://mysite.com",
    "language": "en-US"
}
```

## Template Variables

Presskit provides a structured context with the following variables available in all templates:

### Site Variables (`site.*`)
- `site.title` - Site title
- `site.description` - Site description  
- `site.author` - Site author
- `site.url` - Base site URL
- `site.version` - Site version
- `site.language` - Site language

### Build Variables (`build.*`)
- `build.date` - Build date (YYYY-MM-DD)
- `build.year` - Build year
- `build.timestamp` - Full build timestamp
- `build.iso_date` - Build date in ISO format

### Page Variables (`page.*`)
- `page.filename` - Page filename without extension
- `page.filepath` - Full file path
- `page.path` - Clean URL path
- `page.layout` - Template layout name
- `page.content` - Processed HTML content (in templates)
- `page.title` - Page title from front matter
- `page.description` - Page description from front matter

### Data Variables (`data.*`)
- `data.queries` - Results from named queries
- `data.sources` - JSON data sources
- `data.page_queries` - Page-specific query results

Plus any custom variables from your front matter are available at the top level.

## Using Variables in Markdown

You can use Jinja2 templating directly in your Markdown content:

```
---
title: About
category: personal
---

# About {{ site.author }}

This site was built on {{ build.date }} and is currently version {{ site.version }}.

{% if category == "personal" %}
This is a personal page about {{ site.author }}.
{% endif %}
```

## Data Sources and Queries

Presskit's data integration feature allows you to connect your static site to data sources, enabling content generation while maintaining the performance benefits of static sites. This powerful feature bridges the gap between static and dynamic websites.

This enables data-driven pages that display statistics, reports, or any structured data. Ideal for portfolios showcasing project metrics, business dashboards, or documentation sites pulling from APIs.

This encourages separation of concerns where you keep your content in databases where it can be easily edited, queried, and managed, while your site structure remains in version control.

### Configuring Data Sources

Add data sources to your `presskit.json`:

```json
{
    "title": "My Blog",
    "sources": {
        "blog_db": {
            "type": "sqlite",
            "path": "data/blog.db"
        },
        "config": {
            "type": "json", 
            "path": "data/site-config.json"
        }
    },
    "default_source": "blog_db"
}
```

### Adding Queries

Define queries to load data from your sources:

```json
{
    "sources": {
        "blog_db": {
            "type": "sqlite",
            "path": "data/blog.db"
        }
    },
    "queries": [
        {
            "name": "recent_posts",
            "source": "blog_db",
            "query": "SELECT title, slug, date, excerpt FROM posts ORDER BY date DESC LIMIT 5"
        },
        {
            "name": "categories",
            "source": "blog_db", 
            "query": "SELECT name, slug, COUNT(*) as post_count FROM categories JOIN posts ON categories.id = posts.category_id GROUP BY categories.id"
        }
    ]
}
```

### Using Query Data in Templates

Access query results through the `data.queries` object:

```html
<section class="recent-posts">
    <h2>Recent Posts</h2>
    {% for post in data.queries.recent_posts %}
    <article>
        <h3><a href="/posts/{{ post.slug }}">{{ post.title }}</a></h3>
        <time>{{ post.date | date_format('%B %d, %Y') }}</time>
        <p>{{ post.excerpt }}</p>
    </article>
    {% endfor %}
</section>

<aside class="categories">
    <h3>Categories</h3>
    <ul>
    {% for category in data.queries.categories %}
        <li><a href="/category/{{ category.slug }}">{{ category.name }} ({{ category.post_count }})</a></li>
    {% endfor %}
    </ul>
</aside>
```

### Page-Level Queries

You can also define queries in individual Markdown files:

```markdown
---
title: "Author Profile"
queries:
    author_posts:
        source: "blog_db"
        query: "SELECT title, slug, date FROM posts WHERE author_id = {{ author_id }} ORDER BY date DESC"
variables:
    author_id: 123
---

# {{ author.name }}

## Recent Posts by This Author

{% for post in data.page_queries.author_posts %}
- [{{ post.title }}](/posts/{{ post.slug }}) - {{ post.date | date_format('%Y-%m-%d') }}
{% endfor %}
```

The above example shows how to define a query that fetches posts by a specific author using the `author_id` variable.

## Generating Pages

The most powerful feature of Presskit is generating multiple pages from database queries.

### Generator Queries

Mark a query as a generator to create multiple pages:

```json
{
    "queries": [
        {
            "name": "blog_posts",
            "source": "blog_db",
            "query": "SELECT title, slug, content, date, author FROM posts WHERE published = 1",
            "generator": true,
            "template": "post",
            "output_path": "posts/#{slug}"
        }
    ]
}
```

### Generator Configuration

- `generator: true` - Marks this as a page generator
- `template` - Template to use for generated pages
- `output_path` - Path pattern with placeholders like `#{field_name}`

### Creating Generator Templates

Create a template for your generated pages (`templates/post.html`):

```html
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }} | {{ site.title }}</title>
</head>
<body>
    <article>
        <h1>{{ title }}</h1>
        <time>{{ date | date_format('%B %d, %Y') }}</time>
        <div class="content">
            {{ content | safe }}
        </div>
        <p>By {{ author }}</p>
    </article>
    
    <nav>
        <a href="/">← Back to Home</a>
    </nav>
</body>
</html>
```

### Nested Queries

You can create parent-child query relationships:

```json
{
    "queries": [
        {
            "name": "authors",
            "source": "blog_db", 
            "query": "SELECT id, name, bio, slug FROM authors"
        },
        {
            "name": "authors.posts",
            "source": "blog_db",
            "query": "SELECT title, slug, date FROM posts WHERE author_id = {{ id }} ORDER BY date DESC"
        }
    ]
}
```

Access nested data in templates:

```html
{% for author in data.queries.authors %}
<div class="author">
    <h2>{{ author.name }}</h2>
    <p>{{ author.bio }}</p>
    
    <h3>Posts by {{ author.name }}</h3>
    {% for post in author.posts %}
    <p><a href="/posts/{{ post.slug }}">{{ post.title }}</a> - {{ post.date }}</p>
    {% endfor %}
</div>
{% endfor %}
```

## Commands

### Build Commands

```bash
# Build entire site
presskit build

# Build specific file
presskit build content/about.md

# Execute queries and cache results
presskit data

# Generate pages from generator queries  
presskit generate

# Check query cache status
presskit status
```

### Development

```bash
# Start development server
presskit server

# Clean build artifacts
presskit clean
```

## Advanced Configuration

### Full Configuration Example

```json
{
    "title": "My Blog",
    "description": "A blog about web development",
    "author": "Jane Developer", 
    "url": "https://myblog.dev",
    "version": "2.1.0",
    "language": "en-US",
    
    "content_dir": "content",
    "templates_dir": "templates", 
    "output_dir": "public",
    "cache_dir": ".cache",
    
    "default_template": "page",
    "markdown_extension": "md",
    "workers": 8,
    
    "server_host": "0.0.0.0",
    "server_port": 8000,
    
    "sources": {
        "blog_db": {
            "type": "sqlite",
            "path": "data/blog.sqlite3" 
        },
        "config": {
            "type": "json",
            "path": "data/config.json"
        }
    },
    
    "default_source": "blog_db",
    
    "variables": {
        "environment": "production",
        "analytics_id": "GA-XXXXX"
    },
    
    "queries": [
        {
            "name": "posts",
            "source": "blog_db",
            "query": "SELECT * FROM posts WHERE status = 'published' ORDER BY date DESC",
            "generator": true,
            "template": "post", 
            "output_path": "blog/#{slug}"
        },
        {
            "name": "recent_posts",
            "source": "blog_db",
            "query": "SELECT title, slug, excerpt, date FROM posts WHERE status = 'published' ORDER BY date DESC LIMIT 5"
        }
    ]
}
```

### Custom Filters

Presskit includes useful Jinja2 filters:

- `date_format(format)` - Format dates (e.g., `{{ date | date_format('%B %d, %Y') }}`)

## Changes

- 0.0.1 - Initial version with site configuration, markdown processing, and Jinja templating
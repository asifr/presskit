# Presskit

A powerful static site generator that combines Markdown content with Jinja2 templating and database-driven page generation. Presskit lets you build dynamic static sites by connecting your content to SQLite databases and JSON data sources.

## Key Features

- **Jinja2 Templating**: Use Jinja2 variables and logic in both Markdown content and HTML layouts
- **Multiple Data Sources**: Connect to SQLite, PostgreSQL, DuckDB databases, and JSON files with JSONPath querying
- **Dynamic Page Generation**: Generate multiple pages automatically from database query results
- **Structured Context**: Access site metadata, build information, and data through a clean template context

## Installation

```bash
pip install presskit
```

Or you can use [Astral's uv](https://docs.astral.sh/uv/) Python package manager to install Presskit as a self-contained tool so it can be run from the command line without needing to activate a virtual environment:

```bash
uv tool install presskit
```

### Database Dependencies

Presskit supports different data sources. Install additional dependencies based on your needs:

```bash
# For PostgreSQL support
pip install presskit[postgresql]

# For DuckDB support  
pip install presskit[duckdb]
```

## Quick Start

1. Initialize a new Presskit project:
```bash
mkdir my-site
cd my-site
presskit init
```

This creates the basic structure and sample files:
```
my-site/
├── presskit.json      # Configuration file
├── content/           # Markdown files
│   └── index.md       # Sample homepage
├── templates/         # HTML templates
│   ├── base.html      # Base template
│   └── page.html      # Page template
└── public/            # Generated output (created automatically)
```

2. Build your site:
```bash
presskit build
```

## Basic Usage

### Writing Content with Frontmatter

Create Markdown files in the `content/` directory. Each file can include YAML front matter for metadata:

```markdown
---
title: "Welcome to My Site"
description: "A brief introduction"
layout: page
---

# Welcome

This is my **awesome** site built with Presskit!
```

HTML files also support YAML frontmatter:

```html
---
title: "My HTML Page"
description: "A page with frontmatter"
layout: custom
---
<div class="content">
    <h1>{{ title }}</h1>
    <p>{{ description }}</p>
</div>
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

Presskit supports multiple data source types. Add them to your `presskit.json`:

#### SQLite

```json
{
    "sources": {
        "blog_db": {
            "type": "sqlite",
            "path": "data/blog.db"
        }
    }
}
```

#### PostgreSQL

```json
{
    "sources": {
        "postgres_db": {
            "type": "postgresql", 
            "host": "localhost",
            "port": 5432,
            "database": "mydb",
            "username": "user",
            "password": "env:DB_PASSWORD"
        }
    }
}
```

#### DuckDB

```json
{
    "sources": {
        "analytics_db": {
            "type": "duckdb",
            "path": "data/analytics.duckdb"
        }
    }
}
```

#### JSON Files

```json
{
    "sources": {
        "config": {
            "type": "json",
            "path": "data/site-config.json"
        }
    }
}
```

JSON sources support both basic data loading and advanced JSONPath querying for extracting specific data from complex JSON structures.

#### Connection Strings

You can also use connection strings for database sources:

```json
{
    "sources": {
        "prod_db": {
            "type": "postgresql",
            "connection_string": "env:DATABASE_URL"
        }
    }
}
```

### JSON Data Querying

JSON sources support powerful JSONPath expressions for extracting data from complex JSON structures. JSONPath is a query language for JSON, similar to XPath for XML.

#### JSONPath Query Examples

Given a JSON file `data/users.json`:
```json
{
    "users": [
        {"id": 1, "name": "Alice", "role": "admin", "posts": 25},
        {"id": 2, "name": "Bob", "role": "editor", "posts": 12},
        {"id": 3, "name": "Carol", "role": "admin", "posts": 8}
    ],
    "settings": {
        "theme": "dark",
        "features": ["comments", "analytics"]
    }
}
```

You can query this data using JSONPath expressions:

```json
{
    "sources": {
        "users_data": {
            "type": "json",
            "path": "data/users.json"
        }
    },
    "queries": [
        {
            "name": "all_users",
            "source": "users_data",
            "query": "$.users[*]"
        },
        {
            "name": "admin_users",
            "source": "users_data", 
            "query": "$.users[?(@.role == 'admin')]"
        },
        {
            "name": "user_names",
            "source": "users_data",
            "query": "$.users[*].name"
        },
        {
            "name": "active_users",
            "source": "users_data",
            "query": "$.users[?(@.posts > 10)]"
        }
    ]
}
```

#### JSONPath Syntax Reference

- `$` - Root element
- `.` - Child element
- `[*]` - All array elements
- `[0]` - First array element
- `[?(@.field == 'value')]` - Filter expression
- `..field` - Recursive descent (find field anywhere)
- `[start:end]` - Array slice

#### Simple Dot Notation

For basic access, you can also use simple dot notation:

```json
{
    "name": "theme_setting",
    "source": "users_data",
    "query": "settings.theme"
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

Access query results through the `data.queries` object. This works for both SQL and JSON query results:

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

#### Using JSON Query Results

For JSON data queries, access the results similarly:

```html
<section class="users">
    <h2>Admin Users</h2>
    {% for user in data.queries.admin_users %}
    <div class="user-card">
        <h3>{{ user.name }}</h3>
        <p>Role: {{ user.role }}</p>
        <p>Posts: {{ user.posts }}</p>
    </div>
    {% endfor %}
</section>

<div class="site-theme">
    Current theme: {{ data.queries.theme_setting.value }}
</div>
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

The `authors.posts` query will automatically run for each row returned by the `authors` query. The query has access to the parent row's data (e.g. `{{ id }}` column), allowing you to create nested structures.

Access nested data in templates:

```html
{% for author in data.queries.authors %}
<div class="author">
    <h2>{{ author.name }}</h2>
    <p>{{ author.bio }}</p>
    
    <h3>Posts by {{ author.name }}</h3>
    <!-- Nested data: Loop through posts for this author -->
    {% for post in author.posts %}
    <p><a href="/posts/{{ post.slug }}">{{ post.title }}</a> - {{ post.date }}</p>
    {% endfor %}
</div>
{% endfor %}
```

## Frontmatter Data Sources

In addition to configuring data sources in `presskit.json`, you can define data sources directly in the YAML frontmatter of individual files. This is particularly useful for standalone files or page-specific data.

### Frontmatter Sources Syntax

```markdown
---
title: My Page
description: A page with embedded data sources
sources:
    users:
        type: json
        path: data/users.json
    books:
        type: json
        path: books.json
---

# {{ title }}

## Users
{% for user in data.sources.users %}
- {{ user.name }} ({{ user.email }})
{% endfor %}

## Books  
{% for book in data.sources.books %}
- **{{ book.title }}** by {{ book.author }}
{% endfor %}
```

### Path Resolution

Frontmatter source paths are resolved in the following order:

1. **Relative to the input file's directory** (primary)
2. **Relative to current working directory** (fallback)
3. **Absolute paths** (if specified)

This means if you have a file at `content/posts/article.md` with a frontmatter source path `data.json`, it will look for:
1. `content/posts/data.json` first
2. `./data.json` (current working directory) if the first doesn't exist

### Combining Sources

Frontmatter sources work alongside:
- Sources defined in `presskit.json` (for full site builds)
- Command-line sources via `--source` flag (for standalone compilation)
- All sources are merged and available in templates via `data.sources.*`

### Supported Source Types

Currently, frontmatter sources support:
- **JSON files** (`type: json`) - Load JSON data from files

## Commands

### Project Setup

```bash
# Initialize a new Presskit project
presskit init
```

Creates the basic project structure with sample files including:
- `presskit.json` configuration file
- `content/` directory with sample `index.md`
- `templates/` directory with `base.html` and `page.html`

### Build Commands

```bash
# Execute queries and cache results
presskit data

# Build entire site
presskit build

# Build specific file
presskit build content/about.md

# Build with auto-reload (watches for file changes)
presskit build --reload

# Generate pages from generator queries  
presskit generate

# Check query cache status
presskit status
```

Run `data` command before `build` or `generate` to ensure all queries are executed and data is cached.

### Development

```bash
# Start development server
presskit server

# Start development server with auto-reload
# (automatically builds if output directory is empty)
presskit server --reload

# Clean build artifacts and cache
presskit clean

# List available data sources
presskit sources
```

### Standalone Compilation

The `compile` command allows you to compile individual Markdown or HTML files without requiring a full Presskit project setup. This is perfect for creating standalone pages, documentation, or one-off content.

```bash
# Compile a single Markdown file
presskit compile page.md

# Compile HTML file with custom output path
presskit compile page.html --output result.html

# Compile with JSON data sources
presskit compile article.md --source users.json --source products.json

# Compile with custom template and config
presskit compile page.md --template custom.html --config site.json

# Compile HTML with frontmatter sources (sources defined in the file itself)
presskit compile standalone.html
```

#### Compile Command Options

- `--source` - JSON data source files (can be used multiple times)
- `--template` - Template file to use (overrides frontmatter layout)
- `--output` - Custom output HTML file path
- `--config` - Path to presskit.json config file (optional)

#### How Compilation Works

1. **File Processing**:
   - Markdown files: Process frontmatter → Jinja2 → Markdown → HTML → Template
   - HTML files: Process frontmatter → Jinja2 → Template (optional)

2. **Data Sources**:
   - Command-line sources (`--source file.json`)
   - Frontmatter sources (defined in YAML frontmatter)
   - All sources available via `data.sources.*` in templates

3. **Template Resolution**:
   - Uses `layout` from frontmatter or `--template` override
   - Searches in `templates/` directory (if config exists) or same directory as input file
   - Falls back to content-only if template not found

4. **Context Available**:
   - All standard Presskit template variables (`site.*`, `build.*`, `page.*`, `data.*`)
   - Frontmatter variables available at top level
   - Minimal defaults used when no config file present

#### Standalone Examples

**Simple Markdown with data:**
```bash
# users.json contains: [{"name": "Alice", "email": "alice@example.com"}]
presskit compile article.md --source users.json
```

**HTML with frontmatter sources:**
```html
---
title: Product Showcase
sources:
    products:
        type: json
        path: products.json
---
<h1>{{ title }}</h1>
{% for product in data.sources.products %}
<div>{{ product.name }}: ${{ product.price }}</div>
{% endfor %}
```

**Using custom templates:**
```bash
presskit compile content.md --template newsletter.html --output newsletter.html
```

## Environment Variables

Presskit supports environment variables throughout your configuration using the `env:` prefix. This is essential for keeping sensitive data like database passwords out of your configuration files.

### Using Environment Variables

Any string value in your `presskit.json` can reference an environment variable:

```json
{
    "title": "env:SITE_TITLE",
    "url": "env:SITE_URL",
    "sources": {
        "database": {
            "type": "postgresql",
            "host": "env:DB_HOST",
            "port": "env:DB_PORT", 
            "database": "env:DB_NAME",
            "username": "env:DB_USER",
            "password": "env:DB_PASSWORD"
        }
    },
    "queries": [
        {
            "name": "posts",
            "source": "database",
            "query": "env:POSTS_QUERY"
        }
    ]
}
```

### Path Variables

Environment variables in paths support both `${VAR}` and `$VAR` syntax:

```json
{
    "sources": {
        "data": {
            "type": "sqlite",
            "path": "${HOME}/data/blog.db"
        }
    }
}
```

### Setting Environment Variables

```bash
# In your shell or .env file
export DB_PASSWORD="your-secure-password"
export SITE_URL="https://yoursite.com"
export DB_HOST="localhost"

# Run presskit
presskit build
```

## Advanced Configuration

### Full Configuration Example

```json
{
    "title": "My Blog",
    "description": "A blog about web development",
    "author": "Jane Developer", 
    "url": "env:SITE_URL",
    "version": "2.1.0",
    "language": "en-US",
    
    "content_dir": "content",
    "templates_dir": "templates", 
    "output_dir": "public",
    "cache_dir": ".cache",
    
    "default_template": "page",
    "markdown_extension": "md",
    "workers": "env:BUILD_WORKERS",
    
    "server_host": "0.0.0.0",
    "server_port": "env:PORT",
    
    "sources": {
        "blog_db": {
            "type": "postgresql",
            "host": "env:DB_HOST",
            "port": 5432,
            "database": "env:DB_NAME",
            "username": "env:DB_USER",
            "password": "env:DB_PASSWORD",
            "options": {
                "pool_min_size": 2,
                "pool_max_size": 10
            }
        },
        "analytics": {
            "type": "duckdb",
            "path": "data/analytics.duckdb"
        },
        "config": {
            "type": "json",
            "path": "${CONFIG_DIR}/site-config.json"
        }
    },
    
    "default_source": "blog_db",
    
    "variables": {
        "environment": "env:ENVIRONMENT",
        "analytics_id": "env:ANALYTICS_ID"
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
        },
        {
            "name": "page_views",
            "source": "analytics",
            "query": "SELECT page, views FROM page_stats WHERE date >= current_date - interval '30 days'"
        }
    ]
}
```

### Custom Filters and Functions

Presskit includes useful Jinja2 filters and functions:

#### Filters

- `date_format(format)` - Format dates from YYYY-MM-DD to any format
  ```html
  {{ "2024-01-15" | date_format('%B %d, %Y') }}
  <!-- Output: January 15, 2024 -->
  ```

- `flatten` - Flatten a list of lists into a single list
  ```html
  {{ [[1, 2], [3, 4]] | flatten }}
  <!-- Output: [1, 2, 3, 4] -->
  ```

- `stringify(sep=" ")` - Convert a value or list of values into a string
  ```html
  {{ ["apple", "banana", "cherry"] | stringify(", ") }}
  <!-- Output: apple, banana, cherry -->
  ```

- `is_truthy` - Check if a value is truthy
  ```html
  {% if post.featured | is_truthy %}
  <span class="featured">Featured</span>
  {% endif %}
  ```

- `slugify(allow_unicode=False, sep="-")` - Convert a string to a URL-friendly slug
  ```html
  {{ "Hello World!" | slugify }}
  <!-- Output: hello-world -->
  ```

- `plainify` - Remove all HTML tags from a string
  ```html
  {{ "<p>Hello <strong>world</strong></p>" | plainify }}
  <!-- Output: Hello world -->
  ```

- `jsonify(**kwargs)` - Convert an object to a JSON string
  ```html
  {{ {"name": "John", "age": 30} | jsonify }}
  <!-- Output: {"name": "John", "age": 30} -->
  ```

- `humanize` - Convert a number to a human-readable string
  ```html
  {{ 1234567 | humanize }}
  <!-- Output: 1.23M -->
  ```

#### Functions

- `short_random_id(prefix="", k=8, seed=None)` - Generate a random ID with optional prefix
  ```html
  <div id="{{ short_random_id() }}">Random ID</div>
  <!-- Output: <div id="a7b2c4d8">Random ID</div> -->
  
  <button id="{{ short_random_id('btn-') }}">Click me</button>
  <!-- Output: <button id="btn-x9y4z2w1">Click me</button> -->
  
  <input id="{{ short_random_id('input-', 12) }}">
  <!-- Output: <input id="input-m5n8p3q7r2s6"> -->
  ```

- `template_debug()` - Display all available template variables in a formatted, collapsible HTML structure
  ```html
  <!-- Add this anywhere in your template for debugging -->
  {{ template_debug() }}
  ```
  
  This function generates a nicely formatted HTML panel showing all template variables organized by category (site, build, page, data, other). Perfect for debugging template issues or exploring what data is available in your templates.

## Changes

- Unreleased - New plugin system using pluggy, livereload plugin for automatic browser refresh, CLI migrated to click, init command accepts an optional directory argument, new `compile` command for standalone file compilation, frontmatter support for HTML files, frontmatter data sources support
- 0.0.6 - CLI upgrades, sources are now defined as a list in the config, smart reload only builds changed files
- 0.0.5 - Filters and functions for Jinja2 templates, new `template_debug()` function for debugging templates
- 0.0.4 - Bug fix for DuckDB data source to read relative paths correctly, DuckDB read-only mode, `--version` flag for CLI
- 0.0.3 - `--reload` flag on build and server commands to watch for file changes and rebuild automatically
- 0.0.2 - Extensible modular data sources, DuckDB, PostgreSQL, environment variables in configuration
- 0.0.1 - Initial version with site configuration, markdown processing, and Jinja templating
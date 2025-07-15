"""Tests for presskit models module."""

import json
from pathlib import Path

from presskit.config.models import (
    SiteConfig,
    SiteContext,
    BuildContext,
    PageContext,
    DataContext,
    TemplateContext,
    QueryCache,
    SourceDefinition,
    QueryDefinition,
    get_num_workers,
)


class TestHelperFunctions:
    """Test helper functions in models module."""

    def test_get_num_workers(self) -> None:
        """Test get_num_workers returns reasonable value."""
        workers = get_num_workers()
        assert 1 <= workers <= 8
        assert isinstance(workers, int)


class TestSourceDefinition:
    """Test SourceDefinition model."""

    def test_sqlite_source(self) -> None:
        """Test creating SQLite source definition."""
        source = SourceDefinition(
            name="testdb",
            type="sqlite",
            path="data/test.db"
        )
        assert source.type == "sqlite"
        assert source.path == "data/test.db"
    
    def test_json_source(self) -> None:
        """Test creating JSON source definition."""
        source = SourceDefinition(
            name="config",
            type="json",
            path="data/config.json"
        )
        assert source.type == "json"
        assert source.path == "data/config.json"


class TestQueryDefinition:
    """Test QueryDefinition model."""

    def test_basic_query(self) -> None:
        """Test creating basic query definition."""
        query = QueryDefinition(
            name="posts",
            source="blog_db",
            query="SELECT * FROM posts"
        )
        assert query.name == "posts"
        assert query.source == "blog_db"
        assert query.query == "SELECT * FROM posts"
        assert query.generator is False
        assert query.template is None
        assert query.output_path is None
        assert query.variables is None
    
    def test_generator_query(self) -> None:
        """Test creating generator query definition."""
        query = QueryDefinition(
            name="all_posts",
            source="blog_db",
            query="SELECT * FROM posts",
            generator=True,
            template="post",
            output_path="posts/#{slug}",
            variables={"status": "published"}
        )
        assert query.generator is True
        assert query.template == "post"
        assert query.output_path == "posts/#{slug}"
        assert query.variables == {"status": "published"}


class TestSiteConfig:
    """Test SiteConfig model."""

    def test_minimal_config(self) -> None:
        """Test creating minimal site config."""
        config = SiteConfig()
        assert config.title == "Presskit"
        assert config.description is None
        assert config.author is None
        assert config.url is None
        assert config.version is None
        assert config.language == "en-US"
        assert config.default_template == "page"
        assert config.markdown_extension == "md"
        assert config.server_host == "0.0.0.0"
        assert config.server_port == 8000
    
    def test_full_config(self) -> None:
        """Test creating full site config."""
        config = SiteConfig(
            title="My Blog",
            description="A tech blog",
            author="John Doe",
            url="https://myblog.com",
            version="2.0.0",
            language="en-GB",
            default_template="blog",
            markdown_extension="markdown",
            workers=4,
            server_host="localhost",
            server_port=3000,
            sources=[
                SourceDefinition(
                    name="db",
                    type="sqlite",
                    path="data/blog.db"
                )
            ],
            queries=[
                {
                    "name": "posts",
                    "source": "db",
                    "query": "SELECT * FROM posts"
                }
            ],
            variables={"theme": "dark"},
            default_source="db"
        )
        assert config.title == "My Blog"
        assert config.workers == 4
        assert any(source.name == "db" for source in config.sources)
        assert len(config.queries) == 1
        assert config.variables is not None and config.variables["theme"] == "dark"
        assert config.default_source == "db"
    
    def test_resolve_paths(self, tmp_path: Path) -> None:
        """Test path resolution in config."""
        config_file = tmp_path / "presskit.json"
        config = SiteConfig(
            site_dir=Path("."),
            content_dir=Path("content"),
            templates_dir=Path("templates"),
            output_dir=Path("public"),
            cache_dir=Path(".cache"),
            sources=[
                SourceDefinition(
                    name="db",
                    type="sqlite",
                    path="data/test.db"
                )
            ]
        )
        
        # Resolve paths relative to config file
        config.resolve_paths(config_file)
        
        # Check all paths are absolute
        assert config.site_dir.is_absolute()
        assert config.content_dir.is_absolute()
        assert config.templates_dir.is_absolute()
        assert config.output_dir.is_absolute()
        assert config.cache_dir.is_absolute()
        # Check that source definition has resolved path when accessed through EnvironmentLoader
        source_def = next(s for s in config.sources if s.name == "db")
        if hasattr(source_def, 'get_resolved_path'):
            resolved_path = source_def.get_resolved_path(config.site_dir)
            assert resolved_path is not None and resolved_path.is_absolute()
        else:
            # For dict sources, check the path value directly after resolution
            assert isinstance(source_def.path, Path) and source_def.path.is_absolute()


class TestContextModels:
    """Test context models."""

    def test_site_context(self) -> None:
        """Test SiteContext model."""
        context = SiteContext(
            title="Test Site",
            description="A test site",
            author="Test Author",
            url="https://test.com",
            version="1.0.0",
            language="fr-FR"
        )
        assert context.title == "Test Site"
        assert context.language == "fr-FR"
    
    def test_build_context(self) -> None:
        """Test BuildContext model."""
        import datetime
        
        now = datetime.datetime.now(datetime.timezone.utc)
        context = BuildContext(
            date="2024-06-11",
            year="2024",
            timestamp=now,
            iso_date="2024-06-11T12:00:00Z"
        )
        assert context.date == "2024-06-11"
        assert context.year == "2024"
        assert context.timestamp == now
    
    def test_page_context(self) -> None:
        """Test PageContext model."""
        context = PageContext(
            filename="about",
            filepath="/path/to/about.md",
            path="about",
            layout="page",
            content="<p>About us</p>",
            title="About",
            description="About our company"
        )
        assert context.filename == "about"
        assert context.content == "<p>About us</p>"
    
    def test_data_context(self) -> None:
        """Test DataContext model."""
        context = DataContext(
            queries={
                "posts": [{"id": 1, "title": "Post 1"}]
            },
            sources={
                "config": {"theme": "dark"}
            },
            page_queries={
                "recent": [{"id": 2, "title": "Recent"}]
            }
        )
        assert len(context.queries["posts"]) == 1
        assert context.sources["config"]["theme"] == "dark"


class TestTemplateContext:
    """Test TemplateContext model."""

    def test_template_context_basic(self) -> None:
        """Test basic TemplateContext creation."""
        import datetime
        
        site = SiteContext(title="Test", language="en")
        build = BuildContext(
            date="2024-06-11",
            year="2024",
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            iso_date="2024-06-11T12:00:00Z"
        )
        page = PageContext(
            filename="index",
            filepath="index.md",
            path="index",
            layout="page",
            content=None,
            title=None,
            description=None
        )
        data = DataContext()
        
        context = TemplateContext(
            site=site,
            build=build,
            page=page,
            data=data
        )
        
        assert context.site.title == "Test"
        assert context.page.filename == "index"
    
    def test_template_context_to_vars(self) -> None:
        """Test converting TemplateContext to template variables."""
        import datetime
        
        site = SiteContext(title="Test Site", author="John")
        build = BuildContext(
            date="2024-06-11",
            year="2024",
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            iso_date="2024-06-11T12:00:00Z"
        )
        page = PageContext(
            filename="about",
            filepath="about.md",
            path="about",
            layout="page",
            content=None,
            title="About Us",
            description=None
        )
        data = DataContext(
            queries={"posts": [{"id": 1}]}
        )
        extras = {"custom_var": "value"}
        
        context = TemplateContext(
            site=site,
            build=build,
            page=page,
            data=data,
            extras=extras
        )
        
        vars_dict = context.to_template_vars()
        
        # Check structure
        assert "site" in vars_dict
        assert "build" in vars_dict
        assert "page" in vars_dict
        assert "data" in vars_dict
        assert "custom_var" in vars_dict
        
        # Check values
        assert vars_dict["site"]["title"] == "Test Site"
        assert vars_dict["page"]["title"] == "About Us"
        assert vars_dict["custom_var"] == "value"
        assert len(vars_dict["data"]["queries"]["posts"]) == 1


class TestQueryCache:
    """Test QueryCache model."""

    def test_query_cache(self) -> None:
        """Test QueryCache model."""
        cache = QueryCache(
            metadata={
                "generated": "2024-06-11T12:00:00Z",
                "sources": {
                    "db": "/path/to/db.sqlite"
                }
            },
            queries={
                "posts": [{"id": 1, "title": "Post"}]
            },
            generators={
                "all_posts": [{"id": 1, "slug": "post-1"}]
            },
            data={
                "config": {"theme": "dark"}
            }
        )
        
        assert cache.metadata["generated"] == "2024-06-11T12:00:00Z"
        assert "posts" in cache.queries
        assert "all_posts" in cache.generators
        assert cache.data["config"]["theme"] == "dark"
    
    def test_query_cache_json_serialization(self) -> None:
        """Test QueryCache can be serialized to JSON."""
        cache = QueryCache(
            metadata={"version": "1.0"},
            queries={"test": [{"id": 1}]},
            generators={},
            data={}
        )
        
        # Convert to dict and JSON
        cache_dict = cache.model_dump()
        json_str = json.dumps(cache_dict)
        
        # Should serialize without errors
        assert "metadata" in json_str
        assert "queries" in json_str
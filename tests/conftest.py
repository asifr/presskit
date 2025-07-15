"""Pytest configuration and shared fixtures."""

import pytest
import typing as t
from pathlib import Path


@pytest.fixture
def sample_config() -> t.Dict[str, t.Any]:
    """Provide a sample configuration dictionary."""
    return {
        "title": "Test Site",
        "description": "A test site",
        "author": "Test Author",
        "url": "https://testsite.com",
        "version": "1.0.0",
        "language": "en-US",
        "sources": [],
        "queries": [],
        "variables": {},
        "default_source": None
    }


@pytest.fixture
def sample_site_structure(tmp_path: Path) -> Path:
    """Create a basic site structure with directories."""
    (tmp_path / "content").mkdir()
    (tmp_path / "templates").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "public").mkdir()
    
    # Create basic templates
    (tmp_path / "templates" / "base.html").write_text("""
<!DOCTYPE html>
<html>
<head><title>{{ site.title }}</title></head>
<body>{% block content %}{% endblock %}</body>
</html>
    """)
    
    (tmp_path / "templates" / "page.html").write_text("""
{% extends "base.html" %}
{% block content %}{{ page.content }}{% endblock %}
    """)
    
    return tmp_path
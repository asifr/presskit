# Presskit Tests

This directory contains comprehensive tests for the presskit static site generator.

## Test Structure

- `test_press.py` - Unit tests for core functions in press.py
- `test_models.py` - Tests for Pydantic models  
- `test_utils.py` - Tests for utility functions
- `test_integration.py` - End-to-end integration tests
- `conftest.py` - Shared pytest fixtures

## Running Tests

### Setup
```bash
./dev setup
```

### Run all tests
```bash
./dev test
```

### Run tests with coverage
```bash
./dev cov
```

### Run specific test file
```bash
source .venv/bin/activate
pytest tests/test_press.py -v
```

### Run specific test
```bash
source .venv/bin/activate
pytest tests/test_press.py::TestConfigFunctions::test_find_config_file_with_arg -v
```

## Test Coverage

The tests cover:
- Configuration loading and validation
- Context building (site, build, page, data)
- Markdown and front matter processing
- Template processing with Jinja2
- Query execution and caching
- File operations and path handling
- Colored output utilities
- Full build workflows
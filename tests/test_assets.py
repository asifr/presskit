"""Tests for asset management functionality."""

import tempfile
import shutil
from pathlib import Path
import pytest
from presskit.utils import (
    get_asset_files,
    should_copy_asset,
    copy_single_asset,
    copy_all_assets,
    copy_changed_assets,
    copy_static_assets,
)
from presskit.config.models import SiteConfig, AssetConfig


class TestAssetHelpers:
    """Test helper functions for asset management."""

    def test_get_asset_files_no_directory(self):
        """Test getting asset files when directory doesn't exist."""
        non_existent = Path("/non/existent/path")
        files = get_asset_files(non_existent, ["**/*"], [])
        assert files == []

    def test_get_asset_files_basic(self):
        """Test getting asset files with basic patterns."""
        with tempfile.TemporaryDirectory() as temp_dir:
            static_dir = Path(temp_dir) / "static"
            static_dir.mkdir()
            
            # Create test files
            (static_dir / "style.css").write_text("body { color: red; }")
            (static_dir / "script.js").write_text("console.log('hello');")
            (static_dir / "image.png").write_bytes(b"fake png data")
            
            # Create subdirectory with files
            css_dir = static_dir / "css"
            css_dir.mkdir()
            (css_dir / "main.css").write_text("h1 { font-size: 2em; }")
            
            files = get_asset_files(static_dir, ["**/*"], [])
            file_names = [f.name for f in files]
            
            assert "style.css" in file_names
            assert "script.js" in file_names
            assert "image.png" in file_names
            assert "main.css" in file_names
            assert len(files) == 4

    def test_get_asset_files_with_exclude_patterns(self):
        """Test getting asset files with ignore patterns."""
        with tempfile.TemporaryDirectory() as temp_dir:
            static_dir = Path(temp_dir) / "static"
            static_dir.mkdir()
            
            # Create test files including ones to ignore
            (static_dir / "style.css").write_text("body { color: red; }")
            (static_dir / ".DS_Store").write_bytes(b"mac metadata")
            (static_dir / "temp.tmp").write_text("temporary file")
            (static_dir / "backup.swp").write_text("vim swap file")
            (static_dir / "Thumbs.db").write_bytes(b"windows thumbnail db")
            
            files = get_asset_files(static_dir, ["**/*"], [".DS_Store", "*.tmp", "*.swp", "Thumbs.db"])
            file_names = [f.name for f in files]
            
            assert "style.css" in file_names
            assert ".DS_Store" not in file_names
            assert "temp.tmp" not in file_names
            assert "backup.swp" not in file_names
            assert "Thumbs.db" not in file_names
            assert len(files) == 1

    def test_get_asset_files_specific_patterns(self):
        """Test getting asset files with specific glob patterns."""
        with tempfile.TemporaryDirectory() as temp_dir:
            static_dir = Path(temp_dir) / "static"
            static_dir.mkdir()
            
            # Create test files
            (static_dir / "style.css").write_text("body { color: red; }")
            (static_dir / "script.js").write_text("console.log('hello');")
            (static_dir / "image.png").write_bytes(b"fake png data")
            (static_dir / "readme.txt").write_text("readme content")
            
            # Test CSS files only
            css_files = get_asset_files(static_dir, ["*.css"], [])
            assert len(css_files) == 1
            assert css_files[0].name == "style.css"
            
            # Test multiple patterns
            web_files = get_asset_files(static_dir, ["*.css", "*.js"], [])
            web_file_names = [f.name for f in web_files]
            assert "style.css" in web_file_names
            assert "script.js" in web_file_names
            assert "image.png" not in web_file_names
            assert len(web_files) == 2

    def test_should_copy_asset_new_file(self):
        """Test should_copy_asset when destination doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "src.txt"
            dest = Path(temp_dir) / "dest.txt"
            
            src.write_text("content")
            
            assert should_copy_asset(src, dest) is True

    def test_should_copy_asset_newer_source(self):
        """Test should_copy_asset when source is newer."""
        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "src.txt"
            dest = Path(temp_dir) / "dest.txt"
            
            # Create dest first, then src (so src is newer)
            dest.write_text("old content")
            import time
            time.sleep(0.01)  # Ensure different timestamps
            src.write_text("new content")
            
            assert should_copy_asset(src, dest) is True

    def test_should_copy_asset_older_source(self):
        """Test should_copy_asset when source is older."""
        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "src.txt"
            dest = Path(temp_dir) / "dest.txt"
            
            # Create src first, then dest (so src is older)
            src.write_text("old content")
            import time
            time.sleep(0.01)  # Ensure different timestamps
            dest.write_text("new content")
            
            assert should_copy_asset(src, dest) is False

    def test_copy_single_asset_success(self):
        """Test copying a single asset successfully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "src.txt"
            dest = Path(temp_dir) / "subdir" / "dest.txt"
            
            src.write_text("test content")
            
            success, error = copy_single_asset(src, dest)
            
            assert success is True
            assert error == ""
            assert dest.exists()
            assert dest.read_text() == "test content"
            assert dest.parent.exists()  # Directory was created

    def test_copy_single_asset_preserves_metadata(self):
        """Test that copy_single_asset preserves file metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            src = Path(temp_dir) / "src.txt"
            dest = Path(temp_dir) / "dest.txt"
            
            src.write_text("test content")
            original_stat = src.stat()
            
            success, error = copy_single_asset(src, dest)
            
            assert success is True
            dest_stat = dest.stat()
            # shutil.copy2 should preserve modification time
            assert abs(dest_stat.st_mtime - original_stat.st_mtime) < 1


class TestAssetConfig:
    """Test AssetConfig model."""

    def test_asset_config_defaults(self):
        """Test AssetConfig with default values."""
        config = AssetConfig()
        
        assert config.include_patterns == ["**/*"]
        assert ".DS_Store" in config.exclude_patterns
        assert "*.tmp" in config.exclude_patterns
        assert "*.swp" in config.exclude_patterns
        assert "Thumbs.db" in config.exclude_patterns
        assert config.clean_destination is False

    def test_asset_config_custom(self):
        """Test AssetConfig with custom values."""
        config = AssetConfig(
            include_patterns=["*.css", "*.js"],
            exclude_patterns=["*.backup"],
            clean_destination=True
        )
        
        assert config.include_patterns == ["*.css", "*.js"]
        assert config.exclude_patterns == ["*.backup"]
        assert config.clean_destination is True


class TestSiteConfigAssets:
    """Test SiteConfig with asset configuration."""

    def test_site_config_default_assets(self):
        """Test SiteConfig with default asset configuration."""
        config = SiteConfig()
        
        assert config.static_dir == Path("static")
        assert isinstance(config.assets, AssetConfig)
        assert config.assets.include_patterns == ["**/*"]

    def test_site_config_resolve_static_path(self):
        """Test that static_dir is resolved correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "presskit.json"
            config_file.touch()
            
            config = SiteConfig(static_dir=Path("assets"))
            config.resolve_paths(config_file)
            
            expected_static = Path(temp_dir) / "assets"
            assert config.static_dir == expected_static

    def test_site_config_absolute_static_path(self):
        """Test that absolute static_dir paths are preserved."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "presskit.json"
            config_file.touch()
            
            absolute_static = Path(temp_dir) / "absolute_static"
            config = SiteConfig(static_dir=absolute_static)
            config.resolve_paths(config_file)
            
            assert config.static_dir == absolute_static


class TestAssetCopying:
    """Test high-level asset copying functions."""

    def create_test_site(self, temp_dir):
        """Create a test site structure."""
        site_dir = Path(temp_dir)
        static_dir = site_dir / "static"
        output_dir = site_dir / "public"
        
        static_dir.mkdir()
        output_dir.mkdir()
        
        # Create test assets
        (static_dir / "style.css").write_text("body { color: red; }")
        (static_dir / "script.js").write_text("console.log('hello');")
        
        css_dir = static_dir / "css"
        css_dir.mkdir()
        (css_dir / "main.css").write_text("h1 { font-size: 2em; }")
        
        images_dir = static_dir / "images"
        images_dir.mkdir()
        (images_dir / "logo.png").write_bytes(b"fake png data")
        
        # Create some files to ignore
        (static_dir / ".DS_Store").write_bytes(b"mac metadata")
        (static_dir / "temp.tmp").write_text("temporary")
        
        config = SiteConfig(
            site_dir=site_dir,
            static_dir=static_dir,
            output_dir=output_dir,
            workers=1  # Use single worker for predictable testing
        )
        
        return config

    def test_copy_all_assets_success(self):
        """Test copying all assets successfully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.create_test_site(temp_dir)
            
            result = copy_all_assets(config)
            
            assert result is True
            
            # Check that files were copied
            assert (config.output_dir / "style.css").exists()
            assert (config.output_dir / "script.js").exists()
            assert (config.output_dir / "css" / "main.css").exists()
            assert (config.output_dir / "images" / "logo.png").exists()
            
            # Check that ignored files were not copied
            assert not (config.output_dir / ".DS_Store").exists()
            assert not (config.output_dir / "temp.tmp").exists()
            
            # Verify content
            assert (config.output_dir / "style.css").read_text() == "body { color: red; }"

    def test_copy_all_assets_no_static_dir(self):
        """Test copy_all_assets when static directory doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = SiteConfig(
                site_dir=Path(temp_dir),
                static_dir=Path(temp_dir) / "nonexistent",
                output_dir=Path(temp_dir) / "public"
            )
            config.output_dir.mkdir()
            
            result = copy_all_assets(config)
            
            assert result is True  # Should succeed even with no static dir

    def test_copy_changed_assets(self):
        """Test copying only changed assets."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.create_test_site(temp_dir)
            
            # First, copy all assets
            copy_all_assets(config)
            
            # Modify one file
            import time
            time.sleep(0.01)  # Ensure different timestamp
            (config.static_dir / "style.css").write_text("body { color: blue; }")
            
            # Copy changed assets
            result = copy_changed_assets(config, [])
            
            assert result is True
            
            # Check that modified file was updated
            assert (config.output_dir / "style.css").read_text() == "body { color: blue; }"

    def test_copy_static_assets_no_reloader(self):
        """Test copy_static_assets without smart reloader (full copy)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.create_test_site(temp_dir)
            
            result = copy_static_assets(config)
            
            assert result is True
            assert (config.output_dir / "style.css").exists()
            assert (config.output_dir / "script.js").exists()

    def test_copy_static_assets_with_reloader(self):
        """Test copy_static_assets with smart reloader (incremental copy)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = self.create_test_site(temp_dir)
            
            # Mock smart reloader
            class MockSmartReloader:
                pass
            
            smart_reloader = MockSmartReloader()
            
            result = copy_static_assets(config, smart_reloader)
            
            assert result is True
            assert (config.output_dir / "style.css").exists()


class TestAssetIntegration:
    """Test asset management integration with build process."""

    def test_assets_in_site_config_schema(self):
        """Test that asset configuration is properly included in site config."""
        config_data = {
            "title": "Test Site",
            "static_dir": "assets",
            "assets": {
                "include_patterns": ["*.css", "*.js"],
                "exclude_patterns": ["*.bak"],
                "clean_destination": True
            }
        }
        
        config = SiteConfig(**config_data)
        
        assert config.static_dir == Path("assets")
        assert config.assets.include_patterns == ["*.css", "*.js"]
        assert config.assets.exclude_patterns == ["*.bak"]
        assert config.assets.clean_destination is True

    def test_minimal_asset_config(self):
        """Test that asset config works with minimal configuration."""
        config = SiteConfig(title="Test Site")
        
        # Should have sensible defaults
        assert config.static_dir == Path("static")
        assert isinstance(config.assets, AssetConfig)
        assert config.assets.include_patterns == ["**/*"]
        assert ".DS_Store" in config.assets.exclude_patterns
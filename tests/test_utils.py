"""Tests for presskit utils module."""

import io
import os
import tempfile
from unittest.mock import patch
import pytest

from presskit.utils import (
    print_error,
    print_warning,
    print_success,
    print_info,
    print_progress,
    setup_logging,
    Colors,
)


class TestColoredOutput:
    """Test colored output functions."""

    def test_print_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test error message printing."""
        print_error("This is an error")
        captured = capsys.readouterr()
        assert "This is an error" in captured.out
        assert "\033[0;31m" in captured.out  # Red color code
    
    def test_print_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test warning message printing."""
        print_warning("This is a warning")
        captured = capsys.readouterr()
        assert "This is a warning" in captured.out
        assert "\033[0;33m" in captured.out  # Yellow color code
    
    def test_print_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test success message printing."""
        print_success("Operation successful")
        captured = capsys.readouterr()
        assert "Operation successful" in captured.out
        assert "\033[0;32m" in captured.out  # Green color code
    
    def test_print_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test info message printing."""
        print_info("Information message")
        captured = capsys.readouterr()
        assert "Information message" in captured.out
        assert "\033[0;34m" in captured.out  # Blue color code
    
    def test_print_progress(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test progress message printing."""
        print_progress(50, 100)
        captured = capsys.readouterr()
        assert "Progress: 50/100 (50.0%)" in captured.out
    
    def test_print_progress_with_label(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test progress message with custom label."""
        print_progress(25, 100, "Processing files")
        captured = capsys.readouterr()
        assert "Processing files: 25/100 (25.0%)" in captured.out
    
    def test_print_progress_zero_total(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test progress with zero total (edge case)."""
        print_progress(0, 0)
        captured = capsys.readouterr()
        assert "Progress: 0/0 (0.0%)" in captured.out
        # Should handle division by zero gracefully
    
    def test_print_progress_complete(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test progress at 100%."""
        print_progress(100, 100)
        captured = capsys.readouterr()
        assert "Progress: 100/100 (100.0%)" in captured.out


class TestOutputRedirection:
    """Test output functions with redirected stdout."""

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_print_functions_with_redirected_stdout(self, mock_stdout: io.StringIO) -> None:
        """Test that print functions work with redirected stdout."""
        print_error("Error")
        print_warning("Warning")
        print_success("Success")
        print_info("Info")
        print_progress(1, 2)
        
        output = mock_stdout.getvalue()
        assert "Error" in output
        assert "Warning" in output
        assert "Success" in output
        assert "Info" in output
        assert "Progress: 1/2 (50.0%)" in output


class TestColors:
    """Test Colors constants."""

    def test_color_codes(self) -> None:
        """Test that color codes are defined correctly."""
        assert Colors.ERROR == "\033[0;31m"
        assert Colors.SUCCESS == "\033[0;32m"
        assert Colors.WARNING == "\033[0;33m"
        assert Colors.INFO == "\033[0;34m"
        assert Colors.CODE == "\033[0;36m"
        assert Colors.NC == "\033[0m"


class TestLogging:
    """Test logging setup function."""

    def test_setup_logging_default(self) -> None:
        """Test default logging setup."""
        import logging
        
        # Clear existing handlers
        logger = logging.getLogger()
        logger.handlers = []
        
        setup_logging()
        
        # Should have one StreamHandler
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)
    
    def test_setup_logging_with_file(self) -> None:
        """Test logging setup with file output."""
        import logging
        
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = os.path.join(tmpdir, "logs", "test.log")
            
            # Clear existing handlers
            logger = logging.getLogger()
            logger.handlers = []
            
            setup_logging(file=log_file)
            
            # Should have two handlers: StreamHandler and FileHandler
            assert len(logger.handlers) == 2
            handler_types = [type(h).__name__ for h in logger.handlers]
            assert "StreamHandler" in handler_types
            assert "FileHandler" in handler_types
            
            # Log directory should be created
            assert os.path.exists(os.path.dirname(log_file))
    
    def test_setup_logging_disabled_stdout(self) -> None:
        """Test logging setup with stdout disabled."""
        import logging
        
        # Clear existing handlers
        logger = logging.getLogger()
        logger.handlers = []
        
        setup_logging(disable_stdout=True)
        
        # Should have no handlers
        assert len(logger.handlers) == 0
    
    def test_setup_logging_with_level(self) -> None:
        """Test logging setup with custom level."""
        import logging
        
        # Clear existing handlers
        logger = logging.getLogger()
        logger.handlers = []
        
        setup_logging(level=logging.DEBUG)
        assert logger.level == logging.DEBUG
        
        # Test with string level
        logger.handlers = []
        setup_logging(level="WARNING")
        assert logger.level == logging.WARNING
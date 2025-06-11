import os
import logging
import typing as t


def setup_logging(level: t.Optional[int] = None, file: t.Optional[str] = None, disable_stdout: bool = False):
    """Setup logging."""
    if level is None:
        level = logging.INFO
    if isinstance(level, str):
        level = getattr(logging, level.upper())
    if file is None and disable_stdout:
        return
    handlers = []
    if not disable_stdout:
        handlers.append(logging.StreamHandler())
    if file is not None:
        os.makedirs(os.path.dirname(file), exist_ok=True)
        handlers.append(logging.FileHandler(file))
    logging.basicConfig(
        level=level,
        format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
        handlers=handlers,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class Colors:
    ERROR = "\033[0;31m"
    SUCCESS = "\033[0;32m"
    WARNING = "\033[0;33m"
    INFO = "\033[0;34m"
    CODE = "\033[0;36m"
    NC = "\033[0m"  # No Color


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"{Colors.SUCCESS}{message}{Colors.NC}")


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"{Colors.ERROR}{message}{Colors.NC}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"{Colors.WARNING}{message}{Colors.NC}")


def print_info(message: str) -> None:
    """Print an informational message."""
    print(f"{Colors.INFO}{message}{Colors.NC}")


def print_progress(current: int, total: int, prefix: str = "Progress") -> None:
    """Print a progress message."""
    percent = (current / total) * 100 if total > 0 else 0
    print(f"{prefix}: {current}/{total} ({percent:.1f}%)")

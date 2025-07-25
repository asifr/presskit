import os
import shutil
import logging
import fnmatch
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# Asset Management Functions
def get_asset_files(static_dir: Path, patterns: t.List[str], exclude_patterns: t.List[str]) -> t.List[Path]:
    """Get list of asset files matching patterns."""
    if not static_dir.exists():
        return []

    asset_files = []

    # Collect all files matching copy patterns
    for pattern in patterns:
        if pattern == "**/*":
            # Optimize for the common case
            for file_path in static_dir.rglob("*"):
                if file_path.is_file():
                    asset_files.append(file_path)
        else:
            for file_path in static_dir.glob(pattern):
                if file_path.is_file():
                    asset_files.append(file_path)

    # Filter out ignored patterns
    if exclude_patterns:
        filtered_files = []
        for file_path in asset_files:
            relative_path = file_path.relative_to(static_dir)
            should_ignore = False

            for ignore_pattern in exclude_patterns:
                if fnmatch.fnmatch(str(relative_path), ignore_pattern) or fnmatch.fnmatch(
                    file_path.name, ignore_pattern
                ):
                    should_ignore = True
                    break

            if not should_ignore:
                filtered_files.append(file_path)

        asset_files = filtered_files

    return list(set(asset_files))  # Remove duplicates


def should_copy_asset(src_path: Path, dest_path: Path) -> bool:
    """Check if asset needs copying based on modification time."""
    if not dest_path.exists():
        return True

    try:
        src_mtime = src_path.stat().st_mtime
        dest_mtime = dest_path.stat().st_mtime
        return src_mtime > dest_mtime
    except (OSError, FileNotFoundError):
        return True


def copy_single_asset(src_path: Path, dest_path: Path) -> t.Tuple[bool, str]:
    """Copy a single asset file."""
    try:
        # Create destination directory if it doesn't exist
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy the file
        shutil.copy2(src_path, dest_path)
        return True, ""
    except Exception as e:
        return False, str(e)


def copy_all_assets(config, static_dir: t.Optional[Path] = None) -> bool:
    """Full asset copy for regular builds."""
    if static_dir is None:
        static_dir = config.static_dir

    if not static_dir.exists():
        return True

    print_info("Copying static assets...")

    # Get all asset files
    asset_files = get_asset_files(static_dir, config.assets.include_patterns, config.assets.exclude_patterns)

    if not asset_files:
        print_info("No assets to copy")
        return True

    success_count = 0
    failed_files = []

    # Use parallel copying for large numbers of files
    if len(asset_files) > 10 and hasattr(config, "workers"):
        max_workers = getattr(config, "workers", 4)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all copy tasks
            future_to_file = {}
            for src_path in asset_files:
                relative_path = src_path.relative_to(static_dir)
                dest_path = config.output_dir / relative_path

                future = executor.submit(copy_single_asset, src_path, dest_path)
                future_to_file[future] = (src_path, dest_path)

            # Process results
            for future in as_completed(future_to_file):
                src_path, dest_path = future_to_file[future]
                success, error = future.result()

                if success:
                    success_count += 1
                else:
                    failed_files.append((src_path, error))

                # Show progress for large operations
                if len(asset_files) > 20:
                    print_progress(success_count + len(failed_files), len(asset_files), "Copying assets")
    else:
        # Sequential copying for small numbers of files
        for src_path in asset_files:
            relative_path = src_path.relative_to(static_dir)
            dest_path = config.output_dir / relative_path

            success, error = copy_single_asset(src_path, dest_path)

            if success:
                success_count += 1
            else:
                failed_files.append((src_path, error))

    # Report results
    if success_count > 0:
        print_success(f"Copied {success_count} assets successfully")

    if failed_files:
        print_warning(f"{len(failed_files)} assets failed to copy:")
        for src_path, error in failed_files[:5]:  # Show first 5 errors
            print_error(f"  - Failed: {src_path.relative_to(static_dir)} ({error})")
        if len(failed_files) > 5:
            print_warning(f"  - ... and {len(failed_files) - 5} more")

    return len(failed_files) == 0


def copy_changed_assets(config, changes: t.List, smart_reloader=None, static_dir: t.Optional[Path] = None) -> bool:
    """Smart incremental asset copying for watch mode."""
    if static_dir is None:
        static_dir = config.static_dir

    if not static_dir.exists():
        return True

    # Get all asset files and filter for changed ones
    asset_files = get_asset_files(static_dir, config.assets.include_patterns, config.assets.exclude_patterns)

    if not asset_files:
        return True

    changed_assets = []
    for src_path in asset_files:
        relative_path = src_path.relative_to(static_dir)
        dest_path = config.output_dir / relative_path

        if should_copy_asset(src_path, dest_path):
            changed_assets.append(src_path)

    if not changed_assets:
        return True

    print_info(f"Copying {len(changed_assets)} changed assets...")

    success_count = 0
    failed_files = []

    for src_path in changed_assets:
        relative_path = src_path.relative_to(static_dir)
        dest_path = config.output_dir / relative_path

        success, error = copy_single_asset(src_path, dest_path)

        if success:
            success_count += 1
        else:
            failed_files.append((src_path, error))

    # Report results
    if success_count > 0:
        print_success(f"Updated {success_count} assets")

    if failed_files:
        print_warning(f"{len(failed_files)} assets failed to copy")
        for src_path, error in failed_files:
            print_error(f"  - Failed: {src_path.relative_to(static_dir)} ({error})")

    return len(failed_files) == 0


def copy_static_assets(config, smart_reloader=None) -> bool:
    """Main asset copying function - dispatches to full or incremental."""
    # Check if static directory exists
    if not config.static_dir.exists():
        return True

    # Use incremental copying in watch mode when smart_reloader is available
    if smart_reloader is not None:
        return copy_changed_assets(config, [], smart_reloader)
    else:
        return copy_all_assets(config)

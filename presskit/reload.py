"""
Smart reload system for presskit with SQLite state tracking.

This module provides intelligent file change detection and targeted rebuilding
to improve development performance during auto-reload.
"""

import time
import json
import hashlib
import sqlite3
from enum import Enum
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, Any

from presskit.config.models import SiteConfig


class ChangeType(Enum):
    """Types of file changes that can trigger rebuilds."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class FileType(Enum):
    """Types of files that the system tracks."""

    CONTENT = "content"
    TEMPLATE = "template"
    CONFIG = "config"
    DATA = "data"
    UNKNOWN = "unknown"


@dataclass
class FileChange:
    """Represents a change to a file."""

    path: Path
    change_type: ChangeType
    file_type: FileType
    content_hash: Optional[str] = None
    mtime: Optional[float] = None


@dataclass
class FileState:
    """Represents the current state of a file."""

    path: Path
    mtime: float
    content_hash: str
    file_type: FileType
    last_built: Optional[float] = None


@dataclass
class Dependencies:
    """Represents dependencies for a file."""

    templates: Set[str]
    data_sources: Set[str]
    queries: Set[str]


@dataclass
class RebuildPlan:
    """Plan for what needs to be rebuilt."""

    content_files: List[Path]
    generators: List[str]
    full_rebuild: bool = False
    reason: str = ""


class StateDatabase:
    """SQLite database for tracking file states and dependencies."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Initialize the SQLite database with required tables."""
        # Ensure the parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    mtime REAL NOT NULL,
                    content_hash TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    last_built REAL,
                    UNIQUE(path)
                );
                
                CREATE TABLE IF NOT EXISTS dependencies (
                    source_file TEXT NOT NULL,
                    dependency_path TEXT NOT NULL,
                    dependency_type TEXT NOT NULL,
                    PRIMARY KEY (source_file, dependency_path, dependency_type)
                );
                
                CREATE TABLE IF NOT EXISTS template_usage (
                    template_name TEXT NOT NULL,
                    content_file TEXT NOT NULL,
                    PRIMARY KEY (template_name, content_file)
                );
                
                CREATE TABLE IF NOT EXISTS generators (
                    name TEXT PRIMARY KEY,
                    query_hash TEXT NOT NULL,
                    template_name TEXT,
                    data_sources TEXT,
                    last_rebuilt REAL
                );
                
                CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime);
                CREATE INDEX IF NOT EXISTS idx_files_type ON files(file_type);
                CREATE INDEX IF NOT EXISTS idx_deps_source ON dependencies(source_file);
                CREATE INDEX IF NOT EXISTS idx_deps_path ON dependencies(dependency_path);
                CREATE INDEX IF NOT EXISTS idx_template_usage_template ON template_usage(template_name);
            """)

    def update_file_state(self, file_path: Path, mtime: float, content_hash: str, file_type: FileType):
        """Update the state of a file in the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO files (path, mtime, content_hash, file_type, last_built)
                VALUES (?, ?, ?, ?, ?)
            """,
                (str(file_path), mtime, content_hash, file_type.value, time.time()),
            )

    def get_file_state(self, file_path: Path) -> Optional[FileState]:
        """Get the stored state of a file."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT path, mtime, content_hash, file_type, last_built
                FROM files WHERE path = ?
            """,
                (str(file_path),),
            ).fetchone()

            if row:
                return FileState(
                    path=Path(row[0]), mtime=row[1], content_hash=row[2], file_type=FileType(row[3]), last_built=row[4]
                )
        return None

    def get_all_files(self) -> Dict[Path, FileState]:
        """Get all files stored in the database."""
        result = {}
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT path, mtime, content_hash, file_type, last_built
                FROM files
            """).fetchall()

            for row in rows:
                path = Path(row[0])
                result[path] = FileState(
                    path=path, mtime=row[1], content_hash=row[2], file_type=FileType(row[3]), last_built=row[4]
                )
        return result

    def remove_file(self, file_path: Path):
        """Remove a file from the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM files WHERE path = ?", (str(file_path),))
            conn.execute("DELETE FROM dependencies WHERE source_file = ?", (str(file_path),))
            conn.execute("DELETE FROM template_usage WHERE content_file = ?", (str(file_path),))

    def update_dependencies(self, file_path: Path, deps: Dependencies):
        """Update dependencies for a file."""
        with sqlite3.connect(self.db_path) as conn:
            # Remove existing dependencies
            conn.execute("DELETE FROM dependencies WHERE source_file = ?", (str(file_path),))
            conn.execute("DELETE FROM template_usage WHERE content_file = ?", (str(file_path),))

            # Add template dependencies
            for template in deps.templates:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO dependencies (source_file, dependency_path, dependency_type)
                    VALUES (?, ?, ?)
                """,
                    (str(file_path), template, "template"),
                )

                conn.execute(
                    """
                    INSERT OR IGNORE INTO template_usage (template_name, content_file)
                    VALUES (?, ?)
                """,
                    (template, str(file_path)),
                )

            # Add data source dependencies
            for data_source in deps.data_sources:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO dependencies (source_file, dependency_path, dependency_type)
                    VALUES (?, ?, ?)
                """,
                    (str(file_path), data_source, "data_source"),
                )

            # Add query dependencies
            for query in deps.queries:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO dependencies (source_file, dependency_path, dependency_type)
                    VALUES (?, ?, ?)
                """,
                    (str(file_path), query, "query"),
                )

    def get_files_using_template(self, template_name: str) -> List[Path]:
        """Get all files that use a specific template."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT content_file FROM template_usage WHERE template_name = ?
            """,
                (template_name,),
            ).fetchall()

            return [Path(row[0]) for row in rows]

    def get_files_using_data_source(self, data_source: str) -> List[Path]:
        """Get all files that use a specific data source."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT source_file FROM dependencies 
                WHERE dependency_path = ? AND dependency_type = ?
            """,
                (data_source, "data_source"),
            ).fetchall()

            return [Path(row[0]) for row in rows]

    def update_generator_state(self, name: str, query_hash: str, template_name: Optional[str], data_sources: List[str]):
        """Update the state of a generator."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO generators (name, query_hash, template_name, data_sources, last_rebuilt)
                VALUES (?, ?, ?, ?, ?)
            """,
                (name, query_hash, template_name, json.dumps(data_sources), time.time()),
            )

    def get_generator_state(self, name: str) -> Optional[Tuple[str, Optional[str], List[str]]]:
        """Get the stored state of a generator."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT query_hash, template_name, data_sources
                FROM generators WHERE name = ?
            """,
                (name,),
            ).fetchone()

            if row:
                return (row[0], row[1], json.loads(row[2]))
        return None

    def get_generators_using_template(self, template_name: str) -> List[str]:
        """Get all generators that use a specific template."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT name FROM generators WHERE template_name = ?
            """,
                (template_name,),
            ).fetchall()

            return [row[0] for row in rows]


class SmartReloader:
    """Smart reload system that analyzes changes and creates targeted rebuild plans."""

    def __init__(self, config: SiteConfig, enabled: bool = True):
        self.config = config
        self.enabled = enabled
        self.state_db = StateDatabase(config.cache_dir / "build_state.db")

    def analyze_changes(self, watch_changes) -> RebuildPlan:
        """Analyze file changes and create a rebuild plan."""
        if not self.enabled:
            return RebuildPlan(
                content_files=list(self.config.content_dir.glob(f"**/*.{self.config.markdown_extension}")),
                generators=[],
                full_rebuild=True,
                reason="Smart reload disabled",
            )

        # Convert watch changes to our format
        changes = []
        for change_type, file_path in watch_changes:
            path = Path(file_path)
            file_type = self._classify_file(path)

            if file_type != FileType.UNKNOWN:
                # Map watchfiles change types to our change types
                if change_type == 1:  # Change.added
                    change_enum = ChangeType.ADDED
                elif change_type == 2:  # Change.modified
                    change_enum = ChangeType.MODIFIED
                elif change_type == 3:  # Change.deleted
                    change_enum = ChangeType.DELETED
                else:
                    change_enum = ChangeType.MODIFIED  # Default

                changes.append(
                    FileChange(
                        path=path,
                        change_type=change_enum,
                        file_type=file_type,
                        content_hash=self._get_content_hash(path) if path.exists() else None,
                        mtime=path.stat().st_mtime if path.exists() else None,
                    )
                )

        return self._create_rebuild_plan(changes)

    def scan_for_changes(self) -> RebuildPlan:
        """Scan the filesystem for changes and create a rebuild plan."""
        if not self.enabled:
            return RebuildPlan(
                content_files=list(self.config.content_dir.glob(f"**/*.{self.config.markdown_extension}")),
                generators=[],
                full_rebuild=True,
                reason="Smart reload disabled",
            )

        current_files = self._scan_filesystem()
        previous_files = self.state_db.get_all_files()

        changes = []

        # Check for new and modified files
        for file_path, current_state in current_files.items():
            previous_state = previous_files.get(file_path)

            if not previous_state:
                changes.append(
                    FileChange(
                        path=file_path,
                        change_type=ChangeType.ADDED,
                        file_type=current_state.file_type,
                        content_hash=current_state.content_hash,
                        mtime=current_state.mtime,
                    )
                )
            elif current_state.content_hash != previous_state.content_hash:
                changes.append(
                    FileChange(
                        path=file_path,
                        change_type=ChangeType.MODIFIED,
                        file_type=current_state.file_type,
                        content_hash=current_state.content_hash,
                        mtime=current_state.mtime,
                    )
                )

        # Check for deleted files
        for file_path in previous_files:
            if file_path not in current_files:
                changes.append(
                    FileChange(
                        path=file_path, change_type=ChangeType.DELETED, file_type=previous_files[file_path].file_type
                    )
                )

        return self._create_rebuild_plan(changes)

    def update_file_state(self, file_path: Path, deps: Optional[Dependencies] = None):
        """Update the state of a file after it's been built."""
        if not self.enabled:
            return

        if file_path.exists():
            file_type = self._classify_file(file_path)
            mtime = file_path.stat().st_mtime
            content_hash = self._get_content_hash(file_path)

            self.state_db.update_file_state(file_path, mtime, content_hash, file_type)

            if deps:
                self.state_db.update_dependencies(file_path, deps)

    def update_generator_state(self, name: str, query_def: Any):
        """Update the state of a generator after it's been built."""
        if not self.enabled:
            return

        query_hash = self._hash_query_definition(query_def)
        template_name = getattr(query_def, "template", None)
        data_sources = [getattr(query_def, "source", "")]

        self.state_db.update_generator_state(name, query_hash, template_name, data_sources)

    def _scan_filesystem(self) -> Dict[Path, FileState]:
        """Scan the filesystem for all tracked files."""
        result = {}

        # Scan content files
        for file_path in self.config.content_dir.glob(f"**/*.{self.config.markdown_extension}"):
            if file_path.is_file():
                result[file_path] = FileState(
                    path=file_path,
                    mtime=file_path.stat().st_mtime,
                    content_hash=self._get_content_hash(file_path),
                    file_type=FileType.CONTENT,
                )

        # Scan template files
        for file_path in self.config.templates_dir.glob("**/*.html"):
            if file_path.is_file():
                result[file_path] = FileState(
                    path=file_path,
                    mtime=file_path.stat().st_mtime,
                    content_hash=self._get_content_hash(file_path),
                    file_type=FileType.TEMPLATE,
                )

        # Scan config file
        config_file = self.config.site_dir / "presskit.json"
        if config_file.exists():
            result[config_file] = FileState(
                path=config_file,
                mtime=config_file.stat().st_mtime,
                content_hash=self._get_content_hash(config_file),
                file_type=FileType.CONFIG,
            )

        # Scan data files
        data_dir = self.config.site_dir / "data"
        if data_dir.exists():
            for file_path in data_dir.glob("**/*.json"):
                if file_path.is_file():
                    result[file_path] = FileState(
                        path=file_path,
                        mtime=file_path.stat().st_mtime,
                        content_hash=self._get_content_hash(file_path),
                        file_type=FileType.DATA,
                    )

        return result

    def _create_rebuild_plan(self, changes: List[FileChange]) -> RebuildPlan:
        """Create a rebuild plan based on file changes."""
        if not changes:
            return RebuildPlan(content_files=[], generators=[], reason="No changes detected")

        content_files = set()
        generators = set()
        full_rebuild = False
        reasons = []

        for change in changes:
            if change.file_type == FileType.CONFIG:
                # Config changes require full rebuild
                full_rebuild = True
                reasons.append(f"Config file changed: {change.path}")
                break

            elif change.file_type == FileType.CONTENT:
                # Content file changes only affect that file
                if change.change_type == ChangeType.DELETED:
                    self.state_db.remove_file(change.path)
                else:
                    content_files.add(change.path)
                    reasons.append(f"Content file {change.change_type.value}: {change.path}")

            elif change.file_type == FileType.TEMPLATE:
                # Template changes affect all files using that template
                template_name = change.path.stem

                if change.change_type == ChangeType.DELETED:
                    # Template deleted - might need full rebuild
                    full_rebuild = True
                    reasons.append(f"Template deleted: {template_name}")
                    break
                else:
                    # Find all files using this template
                    affected_files = self.state_db.get_files_using_template(template_name)
                    content_files.update(affected_files)

                    # Find all generators using this template
                    affected_generators = self.state_db.get_generators_using_template(template_name)
                    generators.update(affected_generators)

                    reasons.append(
                        f"Template {change.change_type.value}: {template_name} "
                        f"({len(affected_files)} files, {len(affected_generators)} generators)"
                    )

            elif change.file_type == FileType.DATA:
                # Data file changes affect files using that data source
                data_source = change.path.stem

                if change.change_type == ChangeType.DELETED:
                    self.state_db.remove_file(change.path)

                affected_files = self.state_db.get_files_using_data_source(data_source)
                content_files.update(affected_files)
                reasons.append(f"Data file {change.change_type.value}: {data_source} ({len(affected_files)} files)")

        if full_rebuild:
            return RebuildPlan(
                content_files=list(self.config.content_dir.glob(f"**/*.{self.config.markdown_extension}")),
                generators=list(generators),
                full_rebuild=True,
                reason="; ".join(reasons),
            )

        return RebuildPlan(
            content_files=list(content_files),
            generators=list(generators),
            full_rebuild=False,
            reason="; ".join(reasons),
        )

    def _classify_file(self, path: Path) -> FileType:
        """Classify a file based on its path and extension."""
        try:
            # Check if it's relative to content directory
            if path.is_relative_to(self.config.content_dir):
                if path.suffix == f".{self.config.markdown_extension}":
                    return FileType.CONTENT

            # Check if it's relative to templates directory
            if path.is_relative_to(self.config.templates_dir):
                if path.suffix == ".html":
                    return FileType.TEMPLATE

            # Check if it's the config file
            if path.name == "presskit.json":
                return FileType.CONFIG

            # Check if it's in data directory
            data_dir = self.config.site_dir / "data"
            if data_dir.exists() and path.is_relative_to(data_dir):
                if path.suffix == ".json":
                    return FileType.DATA

        except (ValueError, OSError):
            # is_relative_to can raise ValueError
            pass

        return FileType.UNKNOWN

    def _get_content_hash(self, path: Path) -> str:
        """Get the SHA-256 hash of a file's content."""
        try:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except (OSError, IOError):
            return ""

    def _hash_query_definition(self, query_def: Any) -> str:
        """Create a hash of a query definition."""
        # Create a deterministic representation of the query
        data = {
            "name": getattr(query_def, "name", ""),
            "source": getattr(query_def, "source", ""),
            "query": getattr(query_def, "query", ""),
            "variables": getattr(query_def, "variables", {}),
            "generator": getattr(query_def, "generator", False),
            "template": getattr(query_def, "template", None),
            "output_path": getattr(query_def, "output_path", None),
        }

        # Sort keys to ensure deterministic hash
        json_str = json.dumps(data, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()

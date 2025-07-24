"""Plugin management for Presskit."""

import os
import sys
import pluggy
import importlib
from pprint import pprint
from presskit import hookspecs
from typing import Dict, List, Any, Optional

if sys.version_info >= (3, 9):
    import importlib.resources as importlib_resources
else:
    import importlib_resources

if sys.version_info >= (3, 10):
    import importlib.metadata as importlib_metadata
else:
    import importlib_metadata


# Default built-in plugins that are always loaded
DEFAULT_PLUGINS = (
    "presskit.contrib.livereload",
    "presskit.contrib.sources.duckdb",
    "presskit.contrib.sources.postgresql",
)

# Create the plugin manager
pm = pluggy.PluginManager("presskit")
pm.add_hookspecs(hookspecs)

# Environment variable for plugin tracing/debugging
PRESSKIT_TRACE_PLUGINS = os.environ.get("PRESSKIT_TRACE_PLUGINS", None)


def before(hook_name, hook_impls, kwargs):
    """Debug hook called before hook execution."""
    print(file=sys.stderr)
    print(f"Presskit Hook: {hook_name}", file=sys.stderr)
    pprint(kwargs, width=40, indent=4, stream=sys.stderr)
    print("Hook implementations:", file=sys.stderr)
    pprint(hook_impls, width=40, indent=4, stream=sys.stderr)


def after(outcome, hook_name, hook_impls, kwargs):
    """Debug hook called after hook execution."""
    results = outcome.get_result()
    if not isinstance(results, list):
        results = [results]
    print("Hook Results:", file=sys.stderr)
    pprint(results, width=40, indent=4, stream=sys.stderr)


# Enable plugin tracing if environment variable is set
if PRESSKIT_TRACE_PLUGINS:
    pm.add_hookcall_monitoring(before, after)


# Environment variable for loading specific plugins
PRESSKIT_LOAD_PLUGINS = os.environ.get("PRESSKIT_LOAD_PLUGINS", None)

# Load plugins from setuptools entry points (unless in test mode)
if not hasattr(sys, "_called_from_test") and PRESSKIT_LOAD_PLUGINS is None:
    pm.load_setuptools_entrypoints("presskit")

# Load specific plugins if PRESSKIT_LOAD_PLUGINS is set
if PRESSKIT_LOAD_PLUGINS is not None:
    for package_name in [name for name in PRESSKIT_LOAD_PLUGINS.split(",") if name.strip()]:
        try:
            distribution = importlib_metadata.distribution(package_name)
            entry_points = distribution.entry_points
            for entry_point in entry_points:
                if entry_point.group == "presskit":
                    mod = entry_point.load()
                    pm.register(mod, name=entry_point.name)
                    # Ensure name can be found in plugin_to_distinfo later
                    pm._plugin_distinfo.append((mod, distribution))  # type: ignore
        except importlib_metadata.PackageNotFoundError:
            sys.stderr.write(f"Plugin {package_name} could not be found\n")


# Load default built-in plugins
for plugin in DEFAULT_PLUGINS:
    try:
        mod = importlib.import_module(plugin)
        pm.register(mod, plugin)
    except ImportError as e:
        # Built-in plugins are optional during development
        sys.stderr.write(f"Built-in plugin {plugin} could not be loaded: {e}\n")


def get_plugins() -> List[Dict[str, Any]]:
    """Get information about all loaded plugins."""
    plugins = []
    plugin_to_distinfo = dict(pm.list_plugin_distinfo())

    for plugin in pm.get_plugins():
        static_path = None
        templates_path = None

        # Check for static and template directories in external plugins
        if plugin.__name__ not in DEFAULT_PLUGINS:
            try:
                if (importlib_resources.files(plugin.__name__) / "static").is_dir():
                    static_path = str(importlib_resources.files(plugin.__name__) / "static")
                if (importlib_resources.files(plugin.__name__) / "templates").is_dir():
                    templates_path = str(importlib_resources.files(plugin.__name__) / "templates")
            except (TypeError, ModuleNotFoundError):
                # Plugins loaded from directories may not have importlib resources
                pass

        plugin_info = {
            "name": plugin.__name__,
            "static_path": static_path,
            "templates_path": templates_path,
            "hooks": [h.name for h in (pm.get_hookcallers(plugin) or [])],
        }

        # Add distribution info if available
        distinfo = plugin_to_distinfo.get(plugin)
        if distinfo:
            plugin_info["version"] = distinfo.version
            plugin_info["name"] = distinfo.name or distinfo.project_name

        plugins.append(plugin_info)

    return plugins


def load_plugin_from_path(plugin_path: str, plugin_name: Optional[str] = None) -> None:
    """Load a plugin from a file path."""
    import importlib.util

    if plugin_name is None:
        plugin_name = os.path.splitext(os.path.basename(plugin_path))[0]

    spec = importlib.util.spec_from_file_location(plugin_name, plugin_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[plugin_name] = module
        spec.loader.exec_module(module)
        pm.register(module, plugin_name)


def load_plugins_from_directory(plugins_dir: str) -> None:
    """Load all Python files from a plugins directory."""
    if not os.path.isdir(plugins_dir):
        return

    for filename in os.listdir(plugins_dir):
        if filename.endswith(".py") and not filename.startswith("_"):
            plugin_path = os.path.join(plugins_dir, filename)
            try:
                load_plugin_from_path(plugin_path)
            except Exception as e:
                sys.stderr.write(f"Failed to load plugin {filename}: {e}\n")


def register_plugin(plugin_module, name: Optional[str] = None) -> None:
    """Register a plugin module."""
    pm.register(plugin_module, name)


def get_plugin_manager() -> pluggy.PluginManager:
    """Get the plugin manager instance."""
    return pm


# Hook calling convenience functions
def call_hook(hook_name: str, **kwargs) -> List[Any]:
    """Call a hook by name with keyword arguments."""
    hook = getattr(pm.hook, hook_name, None)
    if hook:
        return hook(**kwargs)
    return []


def call_hook_first_result(hook_name: str, **kwargs) -> Any:
    """Call a hook and return the first non-None result."""
    hook = getattr(pm.hook, hook_name, None)
    if hook:
        results = hook(**kwargs)
        for result in results:
            if result is not None:
                return result
    return None


def has_hook_implementations(hook_name: str) -> bool:
    """Check if any plugins implement a specific hook."""
    hook = getattr(pm.hook, hook_name, None)
    return hook is not None and len(hook.get_hookimpls()) > 0

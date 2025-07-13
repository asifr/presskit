"""Environment variable loading utilities."""

import os
from typing import Any, Dict


class ConfigError(Exception):
    """Exception raised for configuration errors."""

    pass


class EnvironmentLoader:
    """Handles loading of environment variables with optional 'env:' prefix."""

    @staticmethod
    def load_env_value(value: Any) -> Any:
        """
        Load environment variable if value is a string starting with 'env:'.

        Args:
            value: The configuration value to process

        Returns:
            The environment variable value if prefixed with 'env:', otherwise the original value

        Raises:
            ConfigError: If environment variable is not found
        """
        if not isinstance(value, str):
            return value

        if value.startswith("env:"):
            env_var = value[4:]  # Remove 'env:' prefix
            env_value = os.getenv(env_var)
            if env_value is None:
                raise ConfigError(f"Environment variable '{env_var}' not found")
            return env_value

        return value

    @classmethod
    def process_config(cls, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively process configuration dictionary to load environment variables.

        Args:
            config_dict: Configuration dictionary to process

        Returns:
            Processed configuration with environment variables loaded
        """
        if not isinstance(config_dict, dict):
            return cls.load_env_value(config_dict)

        processed = {}
        for key, value in config_dict.items():
            if isinstance(value, dict):
                processed[key] = cls.process_config(value)
            elif isinstance(value, list):
                processed[key] = [
                    cls.process_config(item) if isinstance(item, dict) else cls.load_env_value(item) for item in value
                ]
            else:
                processed[key] = cls.load_env_value(value)

        return processed

    @staticmethod
    def resolve_path_env_vars(path_str: str) -> str:
        """
        Resolve environment variables in path strings.
        Supports both ${VAR} and $VAR syntax.

        Args:
            path_str: Path string that may contain environment variables

        Returns:
            Path with environment variables resolved
        """
        return os.path.expandvars(path_str)

"""Environment variable loading utilities."""

import os
from typing import Any, Dict


class ConfigError(Exception):
    """Exception raised for configuration errors."""

    pass


class EnvironmentLoader:
    """Handles loading of environment variables using standard shell expansion syntax."""

    @staticmethod
    def load_env_value(value: Any) -> Any:
        """
        Load environment variables using standard shell expansion syntax ${VAR} or $VAR.

        Args:
            value: The configuration value to process

        Returns:
            The value with environment variables expanded, or original value if not a string

        Raises:
            ConfigError: If environment variable is not found
        """
        if not isinstance(value, str):
            return value

        # Use standard shell expansion for ${VAR} and $VAR patterns
        expanded = os.path.expandvars(value)
        
        # Check if expansion failed (contains unexpanded variables)
        if '$' in expanded and expanded != value:
            # Find unexpanded variables for better error messages
            import re
            unexpanded = re.findall(r'\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)', expanded)
            for match in unexpanded:
                var_name = match[0] or match[1]
                if os.getenv(var_name) is None:
                    raise ConfigError(f"Environment variable '{var_name}' not found")
        
        return expanded

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
        return EnvironmentLoader.load_env_value(path_str)

import os
import json
from pathlib import Path
from typing import Any, Dict, Union

ENV_PREFIX = "CORE_ENGINE_"
NESTED_SEPARATOR = "__"

def _cast_value(value: str) -> Any:
    """Attempts to cast a string value to a more specific type."""
    val_lower = value.lower()
    if val_lower in ("true", "yes", "1"):
        return True
    if val_lower in ("false", "no", "0"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value

def _update_from_env(config: Dict[str, Any], prefix: str, separator: str) -> None:
    """
    Updates the configuration dictionary with values from environment variables.
    It only overrides keys that already exist in the base configuration.
    """
    for env_key, value in os.environ.items():
        if not env_key.startswith(prefix):
            continue

        # Remove prefix and convert to lowercase
        # e.g., CORE_ENGINE_DATABASE__HOST -> database__host
        config_path_str = env_key[len(prefix):].lower()
        
        # Split into path components
        # e.g., database__host -> ['database', 'host']
        keys = config_path_str.split(separator)

        # Traverse the config dict to find the target for update
        current_level = config
        for key in keys[:-1]:
            if not isinstance(current_level.get(key), dict):
                # If path does not exist in config, skip this env var
                current_level = None
                break
            current_level = current_level.get(key)
        
        if current_level is not None:
            final_key = keys[-1]
            # Only update if the key already exists at this level
            if final_key in current_level:
                current_level[final_key] = _cast_value(value)

def load_config(path: Union[str, Path]) -> Dict[str, Any]:
    """
    Loads a JSON configuration file and overrides values with environment variables.

    This function provides a hierarchical configuration system. It starts by loading
    a base configuration from a JSON file. It then overrides values in this
    configuration using environment variables that match existing keys.

    Environment variables must be prefixed with `CORE_ENGINE_`. Nested keys in the
    JSON can be targeted by using a double underscore `__` as a separator.

    For example, to override the `host` key within a `database` object,
    you would set the environment variable: `CORE_ENGINE_DATABASE__HOST=new.db.host.com`.

    Type Casting:
    - "true", "yes", "1" are cast to `True`.
    - "false", "no", "0" are cast to `False`.
    - Values that can be parsed as integers or floats are cast accordingly.
    - All other values remain strings.

    Args:
        path: The path to the JSON configuration file.

    Returns:
        A dictionary containing the final, merged configuration.

    Raises:
        FileNotFoundError: If the config file does not exist.
        json.JSONDecodeError: If the config file is not valid JSON.
    """
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found at: {config_path}")

    with config_path.open('r', encoding='utf-8') as f:
        config = json.load(f)

    _update_from_env(config, prefix=ENV_PREFIX, separator=NESTED_SEPARATOR)
    
    return config

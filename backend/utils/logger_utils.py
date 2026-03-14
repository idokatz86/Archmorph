import logging
from typing import Any

def sanitize_log(val: Any) -> Any:
    """Sanitize log inputs."""
    if not isinstance(val, str):
        return val
    return val.replace('\n', '').replace('\r', '')


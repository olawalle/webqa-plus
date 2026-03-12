"""Utility helpers for WebQA-Plus."""

import hashlib
import random
import string
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse


def generate_id(length: int = 8) -> str:
    """Generate a random alphanumeric ID."""
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def hash_url(url: str) -> str:
    """Generate a hash for a URL."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def normalize_url(url: str, base_url: str) -> str:
    """Normalize a URL relative to a base URL."""
    return urljoin(base_url, url)


def is_same_domain(url: str, base_url: str) -> bool:
    """Check if URL is in the same domain as base_url."""
    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)
    return parsed_url.netloc == parsed_base.netloc


def sanitize_filename(filename: str) -> str:
    """Sanitize a string for use as a filename."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, "_")
    return filename[:100]  # Limit length


def format_timestamp(dt: Optional[datetime] = None) -> str:
    """Format a datetime as ISO string."""
    if dt is None:
        dt = datetime.now()
    return dt.isoformat()


def truncate_text(text: str, max_length: int = 100) -> str:
    """Truncate text to max_length with ellipsis."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def calculate_coverage(visited: List[str], total: int) -> float:
    """Calculate coverage percentage."""
    if total == 0:
        return 0.0
    return (len(visited) / total) * 100


def merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def estimate_cost(tokens: int, cost_per_1k: float = 0.01) -> float:
    """Estimate API cost based on token count."""
    return (tokens / 1000) * cost_per_1k

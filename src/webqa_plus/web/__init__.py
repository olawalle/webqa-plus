"""Web interface for WebQA-Plus."""

__version__ = "1.0.0"

from .server import create_app, start_server

__all__ = ["create_app", "start_server"]

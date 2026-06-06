"""
FullMark — Convert ANY source format into a perfect Markdown file.
Full Marks — Every source, Perfect Markdown.
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "tmprabubiz"
__license__ = "MIT"


class FullMarkError(Exception):
    """Base exception for all FullMark errors."""


class AgentError(FullMarkError):
    """Raised by an agent when it cannot recover from a failure."""


class ConfigError(FullMarkError):
    """Raised when required configuration is missing or invalid."""

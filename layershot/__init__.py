"""Screenshot any Windows app window without bringing it to the front."""
from .core import WindowInfo, capture, find_window, list_windows

__all__ = ["WindowInfo", "capture", "find_window", "list_windows"]
__version__ = "0.1.0"

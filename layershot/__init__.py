"""Screenshot any Windows app window without bringing it to the front."""
from .core import WindowInfo, capture, find_window, list_windows
from .launch import bring_to_front, open_app

__all__ = ["WindowInfo", "bring_to_front", "capture", "find_window", "list_windows", "open_app"]
__version__ = "0.3.2"

"""Strip EXIF, GPS, XMP, IPTC and comments from JPEG, PNG and WebP images byte-exactly."""

from __future__ import annotations

import logging

from .core import ExifStripError, Removed, StripResult, inspect, strip
from .tiff import MetadataBlock

__all__ = [
    "ExifStripError",
    "MetadataBlock",
    "Removed",
    "StripResult",
    "__version__",
    "inspect",
    "strip",
]

__version__ = "0.1.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())

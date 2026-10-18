"""Compatibility import for firesight.services.mapview."""
import sys
from firesight.services import mapview as _implementation
sys.modules[__name__] = _implementation

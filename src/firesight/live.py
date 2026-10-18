"""Compatibility import for firesight.ingestion.live."""
import sys
from firesight.ingestion import live as _implementation
sys.modules[__name__] = _implementation

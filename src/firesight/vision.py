"""Compatibility import for firesight.analysis.vision."""
import sys
from firesight.analysis import vision as _implementation
sys.modules[__name__] = _implementation

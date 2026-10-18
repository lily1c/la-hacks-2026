"""Compatibility import for firesight.analysis.frame."""
import sys
from firesight.analysis import frame as _implementation
sys.modules[__name__] = _implementation

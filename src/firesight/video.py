"""Compatibility import for firesight.analysis.video."""
import sys
from firesight.analysis import video as _implementation
sys.modules[__name__] = _implementation

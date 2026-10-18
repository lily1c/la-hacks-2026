"""Compatibility import for firesight.analysis.detector."""
import sys
from firesight.analysis import detector as _implementation
sys.modules[__name__] = _implementation

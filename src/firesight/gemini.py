"""Compatibility import for firesight.analysis.gemini."""
import sys
from firesight.analysis import gemini as _implementation
sys.modules[__name__] = _implementation

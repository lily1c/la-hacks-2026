"""Compatibility import for firesight.contracts.alerts."""
import sys
from firesight.contracts import alerts as _implementation
sys.modules[__name__] = _implementation

"""Compatibility import for firesight.ingestion.push."""
import sys
from firesight.ingestion import push as _implementation
sys.modules[__name__] = _implementation

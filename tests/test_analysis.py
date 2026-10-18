import os
from pathlib import Path
import unittest
from unittest.mock import patch
from firesight.frame import analyze_frame
from firesight.gemini import GeminiRequestError
from firesight.services.mapview import render_map
import cv2
import numpy as np

class AnalysisTests(unittest.TestCase):
    def test_fallback_is_explicit(self):
        image=Path('wildfire.jpeg').read_bytes()
        with patch.dict(os.environ,{'FIRESIGHT_DETECTOR':'gemini','FIRESIGHT_GEMINI_FALLBACK':''}), patch('firesight.gemini.analyze_image_with_gemini',side_effect=GeminiRequestError('test failure')):
            with self.assertRaises(GeminiRequestError): analyze_frame(image,'image/jpeg')
            with patch.dict(os.environ,{'FIRESIGHT_GEMINI_FALLBACK':'opencv'}):
                self.assertIn('headline',analyze_frame(image,'image/jpeg'))

    def test_compatibility_and_map_dimensions(self):
        from firesight.analysis.frame import analyze_frame as moved
        self.assertIs(moved,analyze_frame)
        image=cv2.imdecode(np.frombuffer(render_map('test','upper-left'),np.uint8),cv2.IMREAD_GRAYSCALE)
        self.assertEqual(image.shape,(144,288))

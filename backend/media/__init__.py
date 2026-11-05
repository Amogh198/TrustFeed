"""Media forensics adapter (T1): explainable signals for images and videos.

Importing this package does not load torch, transformers or any model weights.
"""

from backend.media.analyzer import analyze_media
from backend.media.config import MediaConfig
from backend.media.heatmap import OcclusionHeatmap, occlusion_heatmap, render_png
from backend.media.models import MediaAnalysisResult

__all__ = ["MediaAnalysisResult", "MediaConfig", "OcclusionHeatmap", "analyze_media", "occlusion_heatmap", "render_png"]

"""
Processing Pipeline Package

Modular image processing pipeline with pluggable nodes.
"""
from .compositors import (
    BaseCompositor,
    LinearCompositor,
    PercentileCompositor,
    HistogramEqualizationCompositor,
    SingleBandCompositor,
    RGBCompositorFactory,
)

from .enhancement import (
    BaseEnhancer,
    GammaEnhancer,
    ContrastEnhancer,
    SharpeningEnhancer,
    DenoisingEnhancer,
    CLAHEEnhancer,
    NanHandlingEnhancer,
    EnhancementPipeline,
)

__all__ = [
    # Compositors
    'BaseCompositor',
    'LinearCompositor',
    'PercentileCompositor',
    'HistogramEqualizationCompositor',
    'SingleBandCompositor',
    'RGBCompositorFactory',
    # Enhancers
    'BaseEnhancer',
    'GammaEnhancer',
    'ContrastEnhancer',
    'SharpeningEnhancer',
    'DenoisingEnhancer',
    'CLAHEEnhancer',
    'NanHandlingEnhancer',
    'EnhancementPipeline',
]

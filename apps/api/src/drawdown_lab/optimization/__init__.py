"""Deterministic parameter search and out-of-sample scoring."""

from drawdown_lab.optimization.grid import generate_grid, generate_monotone_grid
from drawdown_lab.optimization.scoring import (
    AnalysisFrames,
    OptimizationRequest,
    OptimizationResult,
    optimize,
)

__all__ = [
    "AnalysisFrames",
    "OptimizationRequest",
    "OptimizationResult",
    "generate_grid",
    "generate_monotone_grid",
    "optimize",
]

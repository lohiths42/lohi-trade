"""Lohi-Research Ideas / Themes / Sectors — proactive research surface.

Extracts ``StockIdea``s from completed research briefs, clusters them into
``ThemeReport``s, and builds ``SectorCluster``s for the auto-discovery grid.

Modules
-------
classifier
    ``IdeaClassifier`` — extracts a ``StockIdea`` from a ``ResearchBrief``.
store
    ``IdeaStore`` — PostgreSQL CRUD for ideas, themes, sectors.
theme_generator
    ``ThemeGenerator`` — clusters ideas into cross-symbol editorial themes.
sector_analyzer
    ``SectorAnalyzer`` — builds per-sector AI-analyzed clusters.
"""

__all__ = [
    "IdeaClassifier",
    "IdeaStore",
    "SectorAnalyzer",
    "ThemeGenerator",
]


def __getattr__(name: str):
    """Lazy imports to avoid circular dependencies at import time."""
    if name == "IdeaClassifier":
        from src.research.ideas.classifier import IdeaClassifier
        return IdeaClassifier
    if name == "IdeaStore":
        from src.research.ideas.store import IdeaStore
        return IdeaStore
    if name == "ThemeGenerator":
        from src.research.ideas.theme_generator import ThemeGenerator
        return ThemeGenerator
    if name == "SectorAnalyzer":
        from src.research.ideas.sector_analyzer import SectorAnalyzer
        return SectorAnalyzer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

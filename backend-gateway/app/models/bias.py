"""Bias and news response models."""

from pydantic import BaseModel, Field
from datetime import datetime

from app.models.base import CamelModel


class BiasResponse(CamelModel):
    id: int
    ticker: str
    bias: str
    score: float
    confidence: float
    article_count: int
    created_at: datetime


class NewsResponse(CamelModel):
    id: int
    article_id: str
    ticker: str
    sentiment: str
    confidence: float
    raw_score: float
    boosted_score: float
    news_title: str = Field(alias="title")
    news_source: str = Field(alias="source")
    created_at: datetime

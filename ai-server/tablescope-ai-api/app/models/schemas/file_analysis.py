"""Schemas for the file-profile analysis endpoint."""

from pydantic import BaseModel


class AnalyzeFileRequest(BaseModel):
    """Request to analyze a file profile — no tenant context required."""
    prompt: str
    task: str = "file_analysis"
    response_format: str = "json"
    signature: str = ""
    timestamp: float = 0.0


class AnalyzeFileResponse(BaseModel):
    analysis: dict
    request_id: str
    model_used: str

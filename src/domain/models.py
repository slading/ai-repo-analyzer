from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, field_validator, model_validator


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AnalysisType(str, Enum):
    CODE_QUALITY = "code_quality"
    SECURITY = "security"
    SENTIMENT = "sentiment"
    PERFORMANCE = "performance"


class AnalysisRequest(BaseModel):
    model_config = {
        "protected_namespaces": ()
    }
    
    text: str = Field(..., min_length=5, max_length=100000, description="The content/code to analyze")
    analysis_type: AnalysisType = Field(default=AnalysisType.CODE_QUALITY, description="Type of analysis to perform")
    model_name: str = Field(default="llama-3.3-70b-versatile", description="Groq model name to use")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Additional analysis parameters")

    @field_validator("text")
    @classmethod
    def validate_text_not_only_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Text content must not be empty or whitespace-only")
        return v


class Finding(BaseModel):
    id: str = Field(..., description="Unique finding identifier, e.g., SEC-001")
    category: str = Field(..., min_length=2, description="Finding category (e.g., XSS, Style, Memory Leak)")
    severity: Severity = Field(..., description="Severity level of the finding")
    line_number: Optional[int] = Field(None, ge=1, description="Line number where the finding was identified")
    description: str = Field(..., min_length=5, description="Detailed explanation of the finding")
    suggestion: Optional[str] = Field(None, min_length=5, description="Actionable remediation advice")


class TokenUsage(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def compute_and_validate_total_tokens(self) -> "TokenUsage":
        calculated = self.prompt_tokens + self.completion_tokens
        if self.total_tokens == 0 and calculated > 0:
            self.total_tokens = calculated
        elif self.total_tokens != calculated and calculated > 0:
            # Sync total_tokens just in case
            self.total_tokens = calculated
        return self


class AnalysisSummary(BaseModel):
    score: float = Field(..., ge=0.0, le=100.0, description="Overall health score or index (0-100)")
    findings_count: Dict[Severity, int] = Field(default_factory=dict, description="Count of findings per severity")
    duration_ms: float = Field(..., ge=0.0, description="Total execution duration in milliseconds")


class AnalysisResult(BaseModel):
    model_config = {
        "protected_namespaces": ()
    }

    request_id: str = Field(..., description="Unique request identifier")
    status: str = Field(..., pattern="^(success|failed)$", description="Execution status")
    summary: Optional[AnalysisSummary] = Field(None, description="Aggregated summary metrics")
    findings: List[Finding] = Field(default_factory=list, description="Discovered findings")
    raw_output: Optional[str] = Field(None, description="Raw model response text")
    token_usage: TokenUsage = Field(default_factory=TokenUsage, description="Token consumption details")
    model_used: str = Field(..., description="Name of the model that executed the analysis")
    error: Optional[str] = Field(None, description="Error message if the execution failed")


class CircuitBreakerConfig(BaseModel):
    failure_threshold: int = Field(default=5, ge=1)
    recovery_timeout_seconds: float = Field(default=10.0, ge=1.0)


class RateLimiterConfig(BaseModel):
    requests_per_minute: int = Field(default=30, ge=1)
    tokens_per_minute: int = Field(default=40000, ge=1)

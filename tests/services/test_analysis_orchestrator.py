import pytest
from unittest.mock import MagicMock

from src.domain.models import AnalysisRequest, AnalysisType, Severity, TokenUsage
from src.services.llm_analyzer import LLMAnalyzer
from src.services.analysis_orchestrator import AnalysisOrchestrator


def test_orchestrator_single_stage():
    analyzer = LLMAnalyzer(api_key="mock")
    orchestrator = AnalysisOrchestrator(analyzer)

    req = AnalysisRequest(
        text="def double(n): return n * 2",
        analysis_type=AnalysisType.CODE_QUALITY
    )
    result = orchestrator.execute_analysis(req)

    assert result.status == "success"
    assert result.summary is not None
    assert result.summary.score == 90.0
    assert len(result.findings) == 1
    assert result.findings[0].category == "Code Quality"


def test_orchestrator_multi_stage_aggregation():
    analyzer = LLMAnalyzer(api_key="mock")
    orchestrator = AnalysisOrchestrator(analyzer)

    # Ask for extra types (SECURITY and PERFORMANCE)
    req = AnalysisRequest(
        text="SELECT id FROM products WHERE category = 'books'",
        analysis_type=AnalysisType.CODE_QUALITY,
        parameters={"extra_types": ["security", "performance"]}
    )
    result = orchestrator.execute_analysis(req)

    assert result.status == "success"
    # Average score of: Code Quality (90.0), Security (65.0), Performance (75.0) -> (90+65+75)/3 = 76.67
    assert result.summary.score == 76.67
    
    # 3 distinct findings should be aggregated (one from each of code_quality, security, performance)
    assert len(result.findings) == 3
    
    # Check severity count
    counts = result.summary.findings_count
    assert counts[Severity.LOW] == 1  # From Code Quality
    assert counts[Severity.HIGH] == 1  # From Security
    assert counts[Severity.MEDIUM] == 1  # From Performance

    # Check token sum
    assert result.token_usage.total_tokens > 0


def test_orchestrator_partial_failure():
    analyzer = LLMAnalyzer(api_key="mock")
    orchestrator = AnalysisOrchestrator(analyzer)

    # Mock the LLMAnalyzer's analyze method to fail only for performance type
    original_analyze = analyzer.analyze
    
    def mock_analyze(request, request_id):
        if request.analysis_type == AnalysisType.PERFORMANCE:
            raise RuntimeError("Performance module offline")
        return original_analyze(request, request_id)
        
    analyzer.analyze = mock_analyze

    req = AnalysisRequest(
        text="SELECT id FROM products WHERE category = 'books'",
        analysis_type=AnalysisType.CODE_QUALITY,
        parameters={"extra_types": ["performance"]}
    )
    result = orchestrator.execute_analysis(req)

    # Since Code Quality succeeded, status is success with an error string indicating performance failure
    assert result.status == "success"
    assert result.summary.score == 90.0  # only code quality score counts
    assert len(result.findings) == 1  # Only code quality finding
    assert "Performance module offline" in result.error

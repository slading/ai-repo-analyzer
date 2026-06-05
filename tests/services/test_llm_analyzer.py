import pytest
import time
from unittest.mock import MagicMock

from src.domain.models import AnalysisRequest, AnalysisType, Severity
from src.services.llm_analyzer import LLMAnalyzer, CircuitBreakerOpenError


def test_analyzer_mock_mode_code_quality():
    analyzer = LLMAnalyzer(api_key="mock")
    req = AnalysisRequest(
        text="def foo(x):\n    return x",
        analysis_type=AnalysisType.CODE_QUALITY,
        model_name="llama-3.1-8b-instant"
    )
    result = analyzer.analyze(req, "test-req-1")
    
    assert result.status == "success"
    assert result.request_id == "test-req-1"
    assert result.summary is not None
    assert result.summary.score == 90.0
    assert len(result.findings) == 1
    assert result.findings[0].severity == Severity.LOW
    assert result.findings[0].category == "Code Quality"
    assert result.model_used == "llama-3.1-8b-instant"
    assert result.token_usage.total_tokens > 0


def test_analyzer_mock_mode_security():
    analyzer = LLMAnalyzer(api_key="mock")
    req = AnalysisRequest(
        text="query = 'SELECT * FROM users WHERE name = ' + user_input",
        analysis_type=AnalysisType.SECURITY,
        model_name="llama-3.3-70b-versatile"
    )
    result = analyzer.analyze(req, "test-req-2")
    
    assert result.status == "success"
    assert result.summary.score == 65.0
    assert len(result.findings) == 1
    assert result.findings[0].severity == Severity.HIGH
    assert "SQL injection" in result.findings[0].description


def test_circuit_breaker_trip_and_fast_fail():
    # Set circuit breaker failure threshold to 2, recovery timeout to 1s
    analyzer = LLMAnalyzer(
        api_key="mock",
        cb_config=MagicMock(failure_threshold=2, recovery_timeout_seconds=1.0)
    )
    
    # Intentionally force a run-time failure inside _mock_groq_call to trigger failure handling
    analyzer._mock_groq_call = MagicMock(side_effect=RuntimeError("Simulated Groq Failure"))
    
    req = AnalysisRequest(text="Hello world test", analysis_type=AnalysisType.SENTIMENT)
    
    # First failure
    res1 = analyzer.analyze(req, "req-1")
    assert res1.status == "failed"
    assert "Simulated Groq Failure" in res1.error
    assert analyzer.cb_state == "CLOSED"
    
    # Second failure (should trip the circuit breaker)
    res2 = analyzer.analyze(req, "req-2")
    assert res2.status == "failed"
    assert "Simulated Groq Failure" in res2.error
    assert analyzer.cb_state == "OPEN"

    # Subsequent call must immediately fail with CircuitBreakerOpenError without running _mock_groq_call
    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        analyzer.analyze(req, "req-3")
    
    assert "Circuit breaker is OPEN" in str(exc_info.value)


def test_circuit_breaker_recovery_and_close():
    # Failure threshold 1, recovery timeout 0.1s
    analyzer = LLMAnalyzer(
        api_key="mock",
    )
    analyzer.cb_failure_threshold = 1
    analyzer.cb_recovery_timeout = 0.1
    
    # Force mock failure
    original_mock_call = analyzer._mock_groq_call
    analyzer._mock_groq_call = MagicMock(side_effect=RuntimeError("Transient Fail"))
    
    req = AnalysisRequest(text="Check circuit recovery", analysis_type=AnalysisType.CODE_QUALITY)
    
    # Call fails and trips circuit to OPEN
    analyzer.analyze(req, "req-fail")
    assert analyzer.cb_state == "OPEN"
    
    # Sleep to allow recovery timeout to pass
    time.sleep(0.15)
    
    # Restore normal mock behavior
    analyzer._mock_groq_call = original_mock_call
    
    # Next call should transition to HALF_OPEN and then to CLOSED upon success
    res = analyzer.analyze(req, "req-success")
    assert res.status == "success"
    assert analyzer.cb_state == "CLOSED"

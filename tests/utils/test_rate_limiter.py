import pytest
import time
from src.utils.rate_limiter import LLMRateLimiter, RateLimitExceededError


def test_rate_limiter_under_limits():
    limiter = LLMRateLimiter(requests_per_minute=5, tokens_per_minute=1000)
    
    # Check multiple fits
    allowed, wait_time = limiter.check_limit(100)
    assert allowed is True
    assert wait_time == 0.0

    allowed, wait_time = limiter.check_limit(200)
    assert allowed is True
    assert wait_time == 0.0


def test_rate_limiter_exceed_tpm():
    # Limit to 500 tokens
    limiter = LLMRateLimiter(requests_per_minute=10, tokens_per_minute=500)
    
    # Fits
    allowed, _ = limiter.check_limit(400)
    assert allowed is True

    # Exceeds cumulative limit (400 + 200 = 600 > 500)
    allowed, wait_time = limiter.check_limit(200)
    assert allowed is False
    assert wait_time > 0.0


def test_rate_limiter_exceed_rpm():
    # Limit to 2 requests
    limiter = LLMRateLimiter(requests_per_minute=2, tokens_per_minute=1000)
    
    allowed, _ = limiter.check_limit(10)
    assert allowed is True

    allowed, _ = limiter.check_limit(10)
    assert allowed is True

    # Third request within same minute is blocked due to RPM
    allowed, wait_time = limiter.check_limit(10)
    assert allowed is False
    assert wait_time > 0.0


def test_rate_limiter_acquire_non_blocking_raise():
    limiter = LLMRateLimiter(requests_per_minute=1, tokens_per_minute=100)
    
    # First request works
    assert limiter.acquire(50, block=False) is True

    # Second request raises RateLimitExceededError
    with pytest.raises(RateLimitExceededError):
        limiter.acquire(50, block=False)


def test_rate_limiter_acquire_timeout_raise():
    limiter = LLMRateLimiter(requests_per_minute=1, tokens_per_minute=100)
    assert limiter.acquire(50, block=False) is True

    # Expect timeout exception when waiting time (approx 60s) exceeds timeout (0.1s)
    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.acquire(50, block=True, timeout=0.1)
    
    assert "Timeout reached" in str(exc_info.value)

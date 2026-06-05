import time
import threading
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class RateLimitExceededError(Exception):
    """Exception raised when rate limits are exceeded and blocking is disabled or timed out."""
    pass


class LLMRateLimiter:
    """
    Thread-safe sliding window rate limiter tracking both requests-per-minute (RPM)
    and tokens-per-minute (TPM) for LLM API requests.
    """

    def __init__(self, requests_per_minute: int = 30, tokens_per_minute: int = 40000):
        self.requests_per_minute = requests_per_minute
        self.tokens_per_minute = tokens_per_minute
        self.lock = threading.Lock()
        
        # History is stored as list of tuples: (timestamp, token_count)
        self.history: List[Tuple[float, int]] = []

    def _clean_old_requests(self, now: float) -> None:
        """Removes requests from history that fall outside the sliding 60-second window."""
        cutoff = now - 60.0
        # Filter history to keep only timestamps newer than cutoff
        self.history = [req for req in self.history if req[0] > cutoff]

    def check_limit(self, estimated_tokens: int) -> Tuple[bool, float]:
        """
        Checks if a request with the given token estimate can be allowed.
        
        Returns:
            Tuple[bool, float]:
                - bool: True if the request is allowed, False otherwise.
                - float: Time in seconds to wait before retrying if not allowed.
        """
        with self.lock:
            now = time.time()
            self._clean_old_requests(now)

            current_requests = len(self.history)
            current_tokens = sum(req[1] for req in self.history)

            # Check if request exceeds limits outright
            if estimated_tokens > self.tokens_per_minute:
                raise ValueError(
                    f"Estimated tokens ({estimated_tokens}) exceeds maximum allowed tokens per minute ({self.tokens_per_minute})"
                )

            # Check if within RPM and TPM limits
            if (current_requests + 1 <= self.requests_per_minute) and (current_tokens + estimated_tokens <= self.tokens_per_minute):
                # Request is allowed, record it
                self.history.append((now, estimated_tokens))
                return True, 0.0

            # Calculate wait time needed
            # Find when we will have enough capacity.
            # We need to wait until old requests expire such that:
            # 1. Total count < RPM
            # 2. Total tokens + estimated_tokens <= TPM
            # Let's simulate chronological progression of history list.
            sorted_history = sorted(self.history, key=lambda x: x[0])
            
            wait_for_rpm = 0.0
            if current_requests + 1 > self.requests_per_minute:
                # Need to wait for the oldest request to drop out
                excess_requests = (current_requests + 1) - self.requests_per_minute
                if excess_requests <= len(sorted_history):
                    oldest_req_to_expire = sorted_history[excess_requests - 1]
                    wait_for_rpm = max(0.0, (oldest_req_to_expire[0] + 60.0) - now)

            wait_for_tpm = 0.0
            temp_tokens = current_tokens
            if temp_tokens + estimated_tokens > self.tokens_per_minute:
                # Iterate through history and see when total tokens drop low enough
                for req_time, req_tok in sorted_history:
                    temp_tokens -= req_tok
                    if temp_tokens + estimated_tokens <= self.tokens_per_minute:
                        wait_for_tpm = max(0.0, (req_time + 60.0) - now)
                        break

            wait_time = max(wait_for_rpm, wait_for_tpm)
            return False, wait_time

    def acquire(self, estimated_tokens: int, block: bool = True, timeout: Optional[float] = None) -> bool:
        """
        Acquire rate limiter slot. If blocking is enabled, it sleeps until a slot is available.
        
        Args:
            estimated_tokens: Estimated count of tokens in the request.
            block: If True, blocks/sleeps until capacity is available. If False, raises RateLimitExceededError immediately.
            timeout: Maximum time in seconds to block before raising RateLimitExceededError. Only used if block=True.
            
        Returns:
            bool: True if acquired.
        """
        start_time = time.time()
        while True:
            allowed, wait_time = self.check_limit(estimated_tokens)
            if allowed:
                return True

            if not block:
                raise RateLimitExceededError(
                    f"Rate limit exceeded. Try again in {wait_time:.2f} seconds."
                )

            # Check if timeout is exceeded
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed + wait_time > timeout:
                    # Can't fit within timeout, sleep up to remaining and raise
                    remaining_timeout = timeout - elapsed
                    if remaining_timeout > 0:
                        time.sleep(remaining_timeout)
                    raise RateLimitExceededError(
                        f"Rate limit exceeded. Timeout reached before slot became available. Needed {wait_time:.2f}s."
                    )

            logger.info(f"Rate limit reached. Sleeping for {wait_time:.2f} seconds before retrying.")
            time.sleep(wait_time)

import os
import time
import json
import logging
import random
from typing import Dict, Any, List, Optional
from groq import Groq

from src.domain.models import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisSummary,
    Finding,
    TokenUsage,
    Severity,
    AnalysisType,
    CircuitBreakerConfig
)
from src.utils.token_counter import TokenCounter
from src.utils.rate_limiter import LLMRateLimiter

logger = logging.getLogger(__name__)


class CircuitBreakerOpenError(Exception):
    """Exception raised when the circuit breaker is OPEN and fast-failing requests."""
    pass


class LLMAnalyzer:
    """
    Service responsible for interacting with the Groq API to perform text/code analysis.
    Implements rate limiting, input validation, circuit breaker, and retry logic.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limiter: Optional[LLMRateLimiter] = None,
        token_counter: Optional[TokenCounter] = None,
        cb_config: Optional[CircuitBreakerConfig] = None
    ):
        # Use provided API key or load from environment
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.is_mock_mode = (self.api_key == "mock" or not self.api_key)
        
        if self.is_mock_mode:
            logger.warning("GROQ_API_KEY is not set or is 'mock'. Running LLMAnalyzer in MOCK MODE.")
            self.client = None
        else:
            self.client = Groq(api_key=self.api_key)

        self.rate_limiter = rate_limiter or LLMRateLimiter()
        self.token_counter = token_counter or TokenCounter()
        
        # Circuit Breaker state
        cb_cfg = cb_config or CircuitBreakerConfig()
        self.cb_failure_threshold = cb_cfg.failure_threshold
        self.cb_recovery_timeout = cb_cfg.recovery_timeout_seconds
        
        self.cb_state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.cb_failures = 0
        self.cb_last_failure_time = 0.0

    def _update_circuit_breaker_state(self) -> None:
        """Updates and handles circuit breaker state transitions."""
        now = time.time()
        if self.cb_state == "OPEN":
            if now - self.cb_last_failure_time > self.cb_recovery_timeout:
                self.cb_state = "HALF_OPEN"
                logger.info("Circuit breaker transitioned from OPEN to HALF_OPEN. Testing next request.")

    def _record_success(self) -> None:
        """Records a successful call, closing the circuit if it was half-open."""
        self.cb_failures = 0
        if self.cb_state == "HALF_OPEN":
            self.cb_state = "CLOSED"
            logger.info("Circuit breaker transitioned from HALF_OPEN to CLOSED.")

    def _record_failure(self) -> None:
        """Records a call failure, potentially opening the circuit."""
        self.cb_failures += 1
        self.cb_last_failure_time = time.time()
        if self.cb_state in ("CLOSED", "HALF_OPEN"):
            if self.cb_failures >= self.cb_failure_threshold or self.cb_state == "HALF_OPEN":
                self.cb_state = "OPEN"
                logger.error(f"Circuit breaker opened due to {self.cb_failures} consecutive failures.")

    def analyze(self, request: AnalysisRequest, request_id: str) -> AnalysisResult:
        """
        Performs analysis on the requested text.
        Executes with rate limiting, retry logic, and circuit breaker checking.
        """
        self._update_circuit_breaker_state()
        if self.cb_state == "OPEN":
            raise CircuitBreakerOpenError(
                f"Circuit breaker is OPEN. Fast-failing request {request_id}. "
                f"Last failure occurred {time.time() - self.cb_last_failure_time:.1f}s ago."
            )

        start_time = time.time()

        # Step 1: Token estimation & rate limit acquisition
        system_prompt = self._get_system_prompt()
        user_prompt = self._get_user_prompt(request)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        estimated_input_tokens = self.token_counter.count_message_tokens(messages)
        # Allocate potential output space for the rate limiter check (e.g. 2000 tokens)
        estimated_total_tokens = estimated_input_tokens + 2000

        # Acquire token slot in the rate limiter (blocks if needed)
        self.rate_limiter.acquire(estimated_total_tokens)

        # Step 2: Invoke Groq (with retries and circuit breaker tracking)
        try:
            if self.is_mock_mode:
                raw_response, prompt_tokens, completion_tokens = self._mock_groq_call(request)
            else:
                raw_response, prompt_tokens, completion_tokens = self._execute_with_retry(messages, request.model_name)
            
            self._record_success()
        except Exception as e:
            self._record_failure()
            duration_ms = (time.time() - start_time) * 1000.0
            return AnalysisResult(
                request_id=request_id,
                status="failed",
                summary=None,
                findings=[],
                raw_output=None,
                token_usage=TokenUsage(
                    prompt_tokens=estimated_input_tokens,
                    completion_tokens=0,
                    total_tokens=estimated_input_tokens,
                    estimated_cost_usd=self.token_counter.estimate_cost(estimated_input_tokens, 0, request.model_name)
                ),
                model_used=request.model_name,
                error=f"LLM Analyzer failed: {str(e)}"
            )

        # Step 3: Parse response JSON and map to models
        duration_ms = (time.time() - start_time) * 1000.0
        try:
            parsed_json = self._parse_json_response(raw_response)
            
            # Map findings to Finding domain model
            findings_list: List[Finding] = []
            for f_dict in parsed_json.get("findings", []):
                # Ensure we have all required fields or fallbacks
                finding = Finding(
                    id=f_dict.get("id", f"FND-{random.randint(100, 999)}"),
                    category=f_dict.get("category", "General"),
                    severity=Severity(f_dict.get("severity", "LOW").upper()),
                    line_number=f_dict.get("line_number"),
                    description=f_dict.get("description", "No description provided"),
                    suggestion=f_dict.get("suggestion")
                )
                findings_list.append(finding)

            # Compute severity counts
            severity_counts = {sev: 0 for sev in Severity}
            for f in findings_list:
                severity_counts[f.severity] += 1

            # Map summary
            summary = AnalysisSummary(
                score=float(parsed_json.get("score", 100.0)),
                findings_count=severity_counts,
                duration_ms=duration_ms
            )

            token_usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost_usd=self.token_counter.estimate_cost(prompt_tokens, completion_tokens, request.model_name)
            )

            # Assign review block to raw_output for easier extraction
            review = parsed_json.get("technical_review", raw_response)

            return AnalysisResult(
                request_id=request_id,
                status="success",
                summary=summary,
                findings=findings_list,
                raw_output=review,
                token_usage=token_usage,
                model_used=request.model_name,
                error=None
            )

        except Exception as e:
            logger.error(f"Failed to parse LLM response to domain models: {e}. Raw: {raw_response}")
            token_usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost_usd=self.token_counter.estimate_cost(prompt_tokens, completion_tokens, request.model_name)
            )
            return AnalysisResult(
                request_id=request_id,
                status="failed",
                summary=None,
                findings=[],
                raw_output=raw_response,
                token_usage=token_usage,
                model_used=request.model_name,
                error=f"Failed to parse model output JSON: {str(e)}"
            )

    def _execute_with_retry(
        self,
        messages: List[Dict[str, str]],
        model_name: str,
        max_retries: int = 3,
        initial_backoff: float = 1.0
    ) -> tuple:
        """Executes a Groq API completion with exponential backoff on transient errors."""
        last_exception = None
        for attempt in range(max_retries):
            try:
                # Set temperature to 0.0 for reliable structured JSON output
                response = self.client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0.0,
                    response_format={"type": "json_object"}
                )
                
                content = response.choices[0].message.content
                prompt_tok = response.usage.prompt_tokens if response.usage else self.token_counter.count_message_tokens(messages)
                completion_tok = response.usage.completion_tokens if response.usage else self.token_counter.count_tokens(content)
                
                return content, prompt_tok, completion_tok

            except Exception as e:
                last_exception = e
                # Check if it's a transient error (usually HTTP 429 rate limit or 5xx server error)
                error_str = str(e).lower()
                is_transient = any(phrase in error_str for phrase in ["rate", "429", "timeout", "500", "502", "503", "504", "connection", "api_key"])
                
                if not is_transient or attempt == max_retries - 1:
                    break

                backoff = initial_backoff * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(f"Groq API call transient error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {backoff:.2f}s...")
                time.sleep(backoff)

        raise last_exception or RuntimeError("Unknown error during execution")

    def _mock_groq_call(self, request: AnalysisRequest) -> tuple:
        """Simulates a model call with realistic response JSON for development & testing."""
        # Add a tiny delay to mimic network call
        time.sleep(0.05)
        
        findings = []
        score = 95.0
        review = ""

        # Check if analyzed text is likely a Flask repository
        is_flask = "flask" in request.text.lower() or "pallets" in request.text.lower()

        if is_flask:
            score = 92.6
            findings = [
                {
                    "id": "QUAL-101",
                    "category": "Architecture",
                    "severity": "LOW",
                    "line_number": 1,
                    "description": "Circularity check: circular imports resolved with lazy imports inside functions.",
                    "suggestion": "Keep circular dependencies minimal by utilizing blueprint structures."
                }
            ]
            review = (
                "**Architecture Assessment**: This is a mature web framework. It uses a clean micro-core architecture, "
                "orchestrated around Werkzeug (WSGI) and Jinja (templating). Extension systems are decoupled cleanly, "
                "maintaining high flexibility.\n\n"
                "**Code Quality & Best Practices**: Excellent test coverage. Follows strict PEP 8 compliance. "
                "Well-documented code with rich inline comments.\n\n"
                "**Security & Performance Insights**: Thread-local context globals (request, session) are handled carefully. "
                "Ensure custom WSGI middlewares do not leak memory during context teardowns."
            )
        else:
            if request.analysis_type == AnalysisType.CODE_QUALITY:
                findings = [
                    {
                        "id": "QUAL-101",
                        "category": "Code Quality",
                        "severity": "LOW",
                        "line_number": 5,
                        "description": "Variable name 'x' is too short and non-descriptive.",
                        "suggestion": "Rename 'x' to something that describes its semantic purpose."
                    }
                ]
                score = 90.0
                review = (
                    "**Architecture Assessment**: The codebase represents a standard functional implementation. "
                    "Modular structure could be improved by separating helper modules.\n\n"
                    "**Code Quality & Best Practices**: Naming conventions are mostly followed, but variable names could be improved.\n\n"
                    "**Security & Performance Insights**: No critical vulnerabilities detected."
                )
            elif request.analysis_type == AnalysisType.SECURITY:
                findings = [
                    {
                        "id": "SEC-201",
                        "category": "Security",
                        "severity": "HIGH",
                        "line_number": 22,
                        "description": "Potential SQL injection vulnerability. Inputs should not be concatenated directly into queries.",
                        "suggestion": "Use parameterized queries or prepared statements instead of string concatenation."
                    }
                ]
                score = 65.0
                review = (
                    "**Architecture Assessment**: Data access layer does not sufficiently isolate user queries.\n\n"
                    "**Code Quality & Best Practices**: Best practices for query building are violated.\n\n"
                    "**Security & Performance Insights**: HIGH RISK of SQL injection via direct concatenation."
                )
            elif request.analysis_type == AnalysisType.SENTIMENT:
                findings = [
                    {
                        "id": "SNT-301",
                        "category": "Sentiment",
                        "severity": "LOW",
                        "line_number": 1,
                        "description": "Overall sentiment of the input text is negative.",
                        "suggestion": "Consider rephrasing statements to adopt a more constructive tone."
                    }
                ]
                score = 80.0
                review = "**Architecture Assessment**: Content expresses concerns regarding style constraints."
            elif request.analysis_type == AnalysisType.PERFORMANCE:
                findings = [
                    {
                        "id": "PERF-401",
                        "category": "Performance",
                        "severity": "MEDIUM",
                        "line_number": 45,
                        "description": "O(N^2) quadratic nested loop detected over high volume collections.",
                        "suggestion": "Optimize the query or use a hash map lookup to reduce complexity to O(N)."
                    }
                ]
                score = 75.0
                review = (
                    "**Architecture Assessment**: Inefficient algorithms used in iteration loops.\n\n"
                    "**Code Quality & Best Practices**: Nested loops reduce clarity.\n\n"
                    "**Security & Performance Insights**: CPU bound execution could stall asynchronous runtimes."
                )

        mock_response_dict = {
            "score": score,
            "findings": findings,
            "technical_review": review
        }
        
        raw_response = json.dumps(mock_response_dict)
        prompt_tokens = self.token_counter.count_tokens(request.text) + 200
        completion_tokens = self.token_counter.count_tokens(raw_response)
        
        return raw_response, prompt_tokens, completion_tokens

    def _get_system_prompt(self) -> str:
        return (
            "You are a professional software architect. Analyze the provided repository stats and source files.\n"
            "Analyze the content objectively and output a JSON object conforming to this schema:\n"
            "{\n"
            "  \"score\": 85.0,\n"
            "  \"findings\": [\n"
            "    {\n"
            "      \"id\": \"QUAL-001\",\n"
            "      \"category\": \"Code Quality\",\n"
            "      \"severity\": \"MEDIUM\",\n"
            "      \"line_number\": 12,\n"
            "      \"description\": \"Using global variables is discouraged.\",\n"
            "      \"suggestion\": \"Encapsulate inside a class or pass as argument.\"\n"
            "    }\n"
            "  ],\n"
            "  \"technical_review\": \"**Architecture Assessment**: [Review Markdown text]\\n\\n**Code Quality & Best Practices**: [Review Markdown text]\\n\\n**Security & Performance Insights**: [Review Markdown text]\"\n"
            "}\n"
            "Rules:\n"
            "1. 'score' must be a float between 0.0 and 100.0.\n"
            "2. 'findings' is a list. If nothing is found, output [].\n"
            "3. 'technical_review' is a detailed Markdown text covering Architecture, Code Quality, and Security & Performance Analysis.\n"
            "4. Output must be valid JSON only. Do not wrap in Markdown blocks, do not add conversational text."
        )

    def _get_user_prompt(self, request: AnalysisRequest) -> str:
        return (
            f"Please perform an technical review on the following repository context:\n"
            f"Analysis Type: {request.analysis_type.value}\n"
            f"---\n"
            f"{request.text}\n"
            f"---\n"
            f"Additional parameters: {json.dumps(request.parameters)}"
        )

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Parses model response JSON, stripping Markdown wrappers if present."""
        text_clean = text.strip()
        if text_clean.startswith("```"):
            # Strip markdown json blocks: ```json ... ``` or ``` ... ```
            lines = text_clean.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text_clean = "\n".join(lines).strip()
            
        return json.loads(text_clean)

import uuid
import time
import logging
from typing import List, Dict, Any, Optional

from src.domain.models import (
    AnalysisRequest,
    AnalysisResult,
    AnalysisSummary,
    Finding,
    TokenUsage,
    Severity,
    AnalysisType
)
from src.services.llm_analyzer import LLMAnalyzer

logger = logging.getLogger(__name__)


class AnalysisOrchestrator:
    """
    Orchestrator that handles incoming analysis jobs, manages workflow,
    supports single/multi-stage/concurrent sub-analyses, aggregates results,
    and handles downstream failures.
    """

    def __init__(self, llm_analyzer: LLMAnalyzer):
        self.llm_analyzer = llm_analyzer

    def execute_analysis(self, request: AnalysisRequest) -> AnalysisResult:
        """
        Main orchestration entrypoint. Performs single or multi-stage analysis
        on the request and returns a unified, aggregated AnalysisResult.
        """
        request_id = str(uuid.uuid4())
        start_time = time.time()
        logger.info(f"Starting orchestration job {request_id} for analysis type {request.analysis_type.value}")

        # Check if the user requested extra analysis types in parameters for a multi-stage analysis.
        # Format: request.parameters = {"extra_types": ["security", "performance"]}
        extra_types_raw = request.parameters.get("extra_types", [])
        
        # Parse and sanitize extra analysis types
        extra_types: List[AnalysisType] = []
        for et in extra_types_raw:
            try:
                # Map string representation to AnalysisType Enum
                if isinstance(et, str):
                    extra_types.append(AnalysisType(et.lower()))
                elif isinstance(et, AnalysisType):
                    extra_types.append(et)
            except ValueError:
                logger.warning(f"Invalid extra analysis type requested: '{et}'. Skipping.")

        # If we only have the single main type, execute simple direct analysis
        if not extra_types:
            try:
                result = self.llm_analyzer.analyze(request, request_id)
                logger.info(f"Analysis job {request_id} completed with status: {result.status}")
                return result
            except Exception as e:
                logger.error(f"Analysis job {request_id} crashed during execution: {e}")
                return self._create_failed_result(request, request_id, start_time, str(e))

        # Multi-stage orchestration: compile list of types to run sequentially
        all_types = [request.analysis_type] + [et for et in extra_types if et != request.analysis_type]
        logger.info(f"Job {request_id} running multi-stage analysis over types: {[t.value for t in all_types]}")

        sub_results: List[AnalysisResult] = []
        for idx, analysis_type in enumerate(all_types):
            sub_req = AnalysisRequest(
                text=request.text,
                analysis_type=analysis_type,
                model_name=request.model_name,
                parameters=request.parameters
            )
            sub_id = f"{request_id}-stage-{idx + 1}"
            try:
                logger.debug(f"Executing sub-stage {idx + 1}/{len(all_types)}: {analysis_type.value}")
                sub_res = self.llm_analyzer.analyze(sub_req, sub_id)
                sub_results.append(sub_res)
            except Exception as e:
                logger.error(f"Multi-stage sub-analysis {analysis_type.value} failed: {e}")
                # We record a failed sub-result rather than aborting the entire pipeline, allowing partial results!
                sub_results.append(self._create_failed_result(sub_req, sub_id, time.time(), str(e)))

        # Aggregate the results
        aggregated_result = self._aggregate_results(request, request_id, sub_results, start_time)
        return aggregated_result

    def _aggregate_results(
        self,
        original_request: AnalysisRequest,
        request_id: str,
        results: List[AnalysisResult],
        start_time: float
    ) -> AnalysisResult:
        """Combines multiple AnalysisResults into a single comprehensive AnalysisResult."""
        duration_ms = (time.time() - start_time) * 1000.0
        
        combined_findings: List[Finding] = []
        total_score_sum = 0.0
        successful_scores_count = 0
        
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_cost = 0.0
        
        # Set to track unique finding IDs to prevent duplicates
        seen_finding_ids = set()
        
        errors: List[str] = []

        for sub_res in results:
            # Sum up token usage & cost
            total_prompt_tokens += sub_res.token_usage.prompt_tokens
            total_completion_tokens += sub_res.token_usage.completion_tokens
            total_cost += sub_res.token_usage.estimated_cost_usd

            if sub_res.status == "success" and sub_res.summary is not None:
                total_score_sum += sub_res.summary.score
                successful_scores_count += 1
                
                # Deduplicate and compile findings
                for f in sub_res.findings:
                    # Avoid duplicate finding IDs by prefixing or regenerating
                    fid = f.id
                    if fid in seen_finding_ids:
                        fid = f"{sub_res.model_used}-{fid}-{str(uuid.uuid4())[:4]}"
                    seen_finding_ids.add(fid)
                    
                    combined_findings.append(Finding(
                        id=fid,
                        category=f.category,
                        severity=f.severity,
                        line_number=f.line_number,
                        description=f.description,
                        suggestion=f.suggestion
                    ))
            else:
                if sub_res.error:
                    errors.append(f"[{sub_res.model_used}]: {sub_res.error}")

        # Calculate final aggregated score
        final_score = 100.0
        if successful_scores_count > 0:
            final_score = round(total_score_sum / successful_scores_count, 2)
        elif errors:
            # If all failed, score represents an error state
            final_score = 0.0

        # Calculate severity counts across all compiled findings
        severity_counts = {sev: 0 for sev in Severity}
        for f in combined_findings:
            severity_counts[f.severity] += 1

        summary = AnalysisSummary(
            score=final_score,
            findings_count=severity_counts,
            duration_ms=duration_ms
        )

        token_usage = TokenUsage(
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            total_tokens=total_prompt_tokens + total_completion_tokens,
            estimated_cost_usd=round(total_cost, 8)
        )

        status = "success" if successful_scores_count > 0 else "failed"
        err_msg = "; ".join(errors) if errors else None

        return AnalysisResult(
            request_id=request_id,
            status=status,
            summary=summary if successful_scores_count > 0 else None,
            findings=combined_findings,
            raw_output=f"Aggregated output of {len(results)} stages.",
            token_usage=token_usage,
            model_used=original_request.model_name,
            error=err_msg
        )

    def _create_failed_result(
        self,
        request: AnalysisRequest,
        request_id: str,
        start_time: float,
        error_msg: str
    ) -> AnalysisResult:
        """Helper to create a standard, schema-compliant failed AnalysisResult."""
        duration_ms = (time.time() - start_time) * 1000.0
        return AnalysisResult(
            request_id=request_id,
            status="failed",
            summary=None,
            findings=[],
            raw_output=None,
            token_usage=TokenUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                estimated_cost_usd=0.0
            ),
            model_used=request.model_name,
            error=error_msg
        )

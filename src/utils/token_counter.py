import logging
import tiktoken
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Standard Groq pricing per 1,000,000 tokens
# (Input, Output) pricing in USD
GROQ_PRICING: Dict[str, tuple] = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "mixtral-8x7b-32768": (0.24, 0.24),
    "gemma2-9b-it": (0.20, 0.20),
    "default": (0.15, 0.15)  # Generic fallback
}


class TokenCounter:
    """
    Utility for counting tokens and estimating api costs for Groq models.
    Uses tiktoken cl100k_base tokenizer as an accurate proxy for modern LLMs.
    """

    def __init__(self, fallback_chars_per_token: float = 4.0):
        self.fallback_chars_per_token = fallback_chars_per_token
        try:
            # Use cl100k_base (used by GPT-4 and others) as a strong proxy tokenizer
            self.encoding = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.warning(f"Failed to load tiktoken encoding cl100k_base: {e}. Falling back to character-based heuristic.")
            self.encoding = None

    def count_tokens(self, text: str) -> int:
        """
        Counts the number of tokens in a string.
        Falls back to a heuristic (len(text) / chars_per_token) if the tokenizer is unavailable.
        """
        if not text:
            return 0

        if self.encoding:
            try:
                return len(self.encoding.encode(text))
            except Exception as e:
                logger.debug(f"Error encoding text with tiktoken: {e}. Using fallback heuristic.")

        # Heuristic: ~4 characters per token
        return max(1, int(len(text) / self.fallback_chars_per_token))

    def count_message_tokens(self, messages: List[Dict[str, str]]) -> int:
        """
        Counts the tokens in a list of chat messages, accounting for prompt formatting overhead.
        """
        num_tokens = 0
        for message in messages:
            # Overhead for message syntax (role, content, etc.)
            num_tokens += 4
            for key, value in message.items():
                num_tokens += self.count_tokens(value)
                if key == "name":
                    num_tokens += 1  # Role overhead adaptation

        num_tokens += 2  # Priming for assistant response
        return num_tokens

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int, model_name: str) -> float:
        """
        Estimates USD cost of a model call based on input and output token counts.
        """
        rates = GROQ_PRICING.get(model_name, GROQ_PRICING["default"])
        input_rate_per_million, output_rate_per_million = rates
        
        input_cost = (prompt_tokens / 1_000_000.0) * input_rate_per_million
        output_cost = (completion_tokens / 1_000_000.0) * output_rate_per_million
        
        return round(input_cost + output_cost, 8)

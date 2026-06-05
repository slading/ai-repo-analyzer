from src.utils.token_counter import TokenCounter


def test_token_counter_empty():
    counter = TokenCounter()
    assert counter.count_tokens("") == 0
    assert counter.count_tokens(None) == 0


def test_token_counter_simple():
    counter = TokenCounter()
    text = "Hello world! This is a simple test string."
    tokens = counter.count_tokens(text)
    assert tokens > 0
    # Heuristic fallback vs tiktoken
    if counter.encoding:
        assert tokens == 10  # cl100k_base encodes this to exactly 10 tokens
    else:
        assert tokens == len(text) // 4


def test_count_message_tokens():
    counter = TokenCounter()
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Analyze this content."}
    ]
    tokens = counter.count_message_tokens(messages)
    assert tokens > 0


def test_estimate_cost():
    counter = TokenCounter()
    # Test Llama-3.3-70b: Input $0.59 / M, Output $0.79 / M
    # 1,000,000 prompt, 1,000,000 completion -> $1.38 total
    cost = counter.estimate_cost(1_000_000, 1_000_000, "llama-3.3-70b-versatile")
    assert cost == 1.38

    # Test Llama-3.1-8b-instant: Input $0.05 / M, Output $0.08 / M
    # 1,000,000 prompt, 1,000,000 completion -> $0.13
    cost_small = counter.estimate_cost(1_000_000, 1_000_000, "llama-3.1-8b-instant")
    assert cost_small == 0.13

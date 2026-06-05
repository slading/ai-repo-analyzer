# 🚀 AI Repository Analyzer & Resilient Orchestration Engine

[![Python](https://img.shields.io/badge/Python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/Tests-16%20Passed-brightgreen.svg)]()
[![AI Engine](https://img.shields.io/badge/AI%20Engine-Groq%20Cloud-orange.svg)](https://groq.com/)
[![CLI Style](https://img.shields.io/badge/CLI--Style-Rich%20Terminal-magenta.svg)]()

A production-grade, highly resilient **AI-powered Code Quality & Repository Analyzer**. Built atop **Clean Architecture**, this engine clones repositories at lightning-speed, runs **AST-based line of code (LOC) analysis** using Pygount, and generates manager-ready Markdown technical reviews using the ultra-fast **Groq Cloud API** (70+ tokens/sec). 

The platform is fortified with industrial-strength resilience: a **Stateful Circuit Breaker**, a **sliding window TPM & RPM Rate Limiter**, and **Exponential Backoff Retries** to ensure uninterrupted operation.

---

## ✨ Features At A Glance

*   📊 **AST-Based LOC Tracking**: Deep parsing of codebase statistics via `pygount` (ignoring comments and whitespaces) grouped by language with automatic percentage calculations.
*   🎨 **Stunning Rich CLI**: Modern terminal user interface resembling high-end DevOps tools (Vercel, Railway, Supabase) with active spinners, progress bars, and formatted review panels.
*   ⚡ **Lightning-Fast Cloning**: Shallow `depth=1` clones via GitPython to minimize disk and network overhead.
*   🛡️ **Bulletproof Resilience (Production Ready)**:
    *   **Stateful Circuit Breaker**: Fast-fails calls to downstream services during outages and self-heals dynamically.
    *   **Thread-Safe Sliding Window Rate Limiter**: Enforces concurrent limits on both Requests Per Minute (RPM) and Tokens Per Minute (TPM).
    *   **Exponential Backoff Retries**: Handles temporary network errors and rate-limiting blocks automatically.
*   📋 **Manager-Ready Exports**: Export detailed, structured, and beautifully formatted Markdown reports with a single flag (`-o report.md`).

---

## 🏗️ Architecture Blueprint

The project is structured according to **Clean Architecture** principles, maintaining a strict decoupling between domain entities, service logical flows, and CLI interfaces:

```
├── src/
│   ├── domain/
│   │   └── models.py            # Framework-agnostic Pydantic models & validation rules
│   ├── services/
│   │   ├── llm_analyzer.py      # Resilient Groq client, circuit breaker, retry engine
│   │   └── analysis_orchestrator.py # Multi-stage analyzer & aggregator
│   ├── utils/
│   │   ├── rate_limiter.py      # Thread-safe sliding window RPM & TPM limiter
│   │   └── token_counter.py     # Token estimations & real-time Groq cost calculation
│   └── analyzer.py              # Main CLI Entrypoint & Rich GUI Renderer
├── tests/                       # 16 Comprehensive Unit & Integration Tests
│   ├── services/
│   └── utils/
├── setup.py                     # Distutils editable setup script
├── pyproject.toml               # Modern build configuration (PEP 517)
└── README.md                    # This document
```

---

## 🚀 Quick Start (Fast Track)

### 1. Installation

Clone the repository, initialize your virtual environment, and install dependencies in editable mode:

```bash
# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip and install package in editable mode
pip install --upgrade pip
pip install -e .
```

### 2. Configure Groq API (Optional)

Register for a free key in 30 seconds at [Groq Console](https://console.groq.com/keys) and expose it:

```bash
export GROQ_API_KEY="gsk_your_actual_groq_api_key_here"
```

*Note: If no API key is specified (or set to `"mock"`), the tool automatically switches to **Mock Mode**, providing a fast, cost-free preview utilizing pre-defined analytical models.*

### 3. Run Analysis

Analyze any public repository (e.g., pallets/flask) and print the report directly to your terminal:

```bash
python3 src/analyzer.py https://github.com/pallets/flask
```

### 4. Export to Markdown

Export a professional, manager-ready Markdown file for your records or team reviews using the `-o` or `--output` flag:

```bash
python3 src/analyzer.py https://github.com/pallets/flask -o report.md
```

---

## 📸 Sample Terminal Output

```text
🔄 Cloning repository...
✓ Cloned to /tmp/repo_analyzer_53tzunb9
📊 Analyzing code structure... [112/112]
✓ Analyzed 112 files
🤖 Running AI analysis...
✓ AI analysis complete

============================================================
📋 ANALYSIS REPORT
============================================================

🔗 Repository: https://github.com/pallets/flask

📊 Code Statistics:
 Language             LOC  Percentage  Bar Chart              
 Python             7,890       91.9%  ██████████████████████ 
 HTML+Django/Jinja    220        2.6%                         
 TOML                 204        2.4%                         
 CSS+Lasso             83        1.0%                         
 HTML+Genshi           80        0.9%                         
 SVG XML               55        0.6%                         
 Batchfile             24        0.3%                         
 Transact-SQL          20        0.2%                         
 Makefile               9        0.1%                         
 HTML                   3        0.0%                         
 JSON                   2        0.0%                         
   Total LOC: 8,590

🤖 AI Technical Review:

╭─────────────────────────────── Review Details ───────────────────────────────╮
│ Architecture Assessment: This is a mature web framework. It uses a clean     │
│ micro-core architecture, orchestrated around Werkzeug (WSGI) and Jinja       │
│ (templating). Extension systems are decoupled cleanly, maintaining high      │
│ flexibility.                                                                 │
│                                                                              │
│ Code Quality & Best Practices: Excellent test coverage. Follows strict PEP 8 │
│ compliance. Well-documented code with rich inline comments.                  │
│                                                                              │
│ Security & Performance Insights: Thread-local context globals (request,      │
│ session) are handled carefully. Ensure custom WSGI middlewares do not leak   │
│ memory during context teardowns.                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
============================================================

✓ Saved report to report.md
```

---

## 🛡️ Industrial-Strength Resilience Design

### 1. Stateful Circuit Breaker (`src/services/llm_analyzer.py`)
Protects against persistent network issues. Upon hitting consecutive API errors (threshold: `5`), the circuit trips to `OPEN`, immediately fast-failing succeeding calls to save resources. After a `recovery_timeout` (`10s`), it enters `HALF_OPEN` to test a trial request. On success, it recovers to `CLOSED`.

### 2. Sliding Window Rate Limiter (`src/utils/rate_limiter.py`)
Tracks requests and token usage in a sliding 60-second window. Fully thread-safe using blocking locks.
*   **Requests Per Minute (RPM)** (Default: 30)
*   **Tokens Per Minute (TPM)** (Default: 40,000)

### 3. Adaptive Token Estimation & Cost Tracker (`src/utils/token_counter.py`)
Uses `tiktoken` as a proxy to estimate prompt formatting token consumption beforehand, predicting exact model pricing:
*   `llama-3.3-70b-versatile` ($0.59 / M input, $0.79 / M output)
*   `llama-3.1-8b-instant` ($0.05 / M input, $0.08 / M output)

---

## 🧪 Testing Suite

We maintain a suite of **16 unit and integration tests** verifying our rate limiters, token counters, circuit breaker, and orchestrator components. 

To run the tests with detailed verbose output:

```bash
pytest -v
```

---

## 📝 License

Distributed under the MIT License. See `LICENSE` for more information.

---
*Created with ♥ by [slading)*
# ai-repo-analyzer

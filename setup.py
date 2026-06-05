from setuptools import setup, find_packages

setup(
    name="llm-orchestrator",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pydantic>=2.0.0",
        "pytest>=8.0.0",
        "httpx>=0.23.0",
        "tiktoken>=0.5.0",
        "groq>=0.9.0",
        "GitPython>=3.1.50",
        "pygount>=3.2.0"
    ],
)

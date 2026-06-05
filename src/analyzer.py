import os
import sys
import argparse
from datetime import datetime

# Add project root directory to sys.path to support robust absolute imports of src.*
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import tempfile
import shutil
import logging
from typing import Dict, Any, List

# GitPython for cloning
import git

# Pygount for LOC counting
from pygount import SourceAnalysis

# Rich Terminal UI components
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

# Clean Architecture layers
from src.domain.models import AnalysisRequest, AnalysisType
from src.services.llm_analyzer import LLMAnalyzer
from src.services.analysis_orchestrator import AnalysisOrchestrator

# Setup basic logging to file, keep stdout clean for the user report
logging.basicConfig(
    filename="analyzer.log",
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize Rich Console
console = Console()


def count_code_statistics_with_progress(repo_dir: str) -> Dict[str, Any]:
    """
    Scans the repository directory, finds all source files, and processes
    them using pygount with an elegant Rich progress bar to count LOC.
    """
    # First, collect all file paths to compute total file count
    files_to_analyze: List[str] = []
    for root, dirs, files in os.walk(repo_dir):
        # Exclude hidden directories like .git
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            if not file.startswith('.'):
                files_to_analyze.append(os.path.join(root, file))

    total_files = len(files_to_analyze)
    total_loc = 0
    languages: Dict[str, int] = {}
    analyzed_count = 0

    # Process files with a beautiful progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description} [bold white]{task.completed}/{task.total}[/bold white]"),
        transient=True
    ) as progress:
        task = progress.add_task("[cyan]📊 Analyzing code structure...", total=total_files)
        
        for file_path in files_to_analyze:
            try:
                analysis = SourceAnalysis.from_file(file_path, "pygount")
                if analysis.is_countable and analysis.code_count > 0:
                    lang = analysis.language or "Unknown"
                    languages[lang] = languages.get(lang, 0) + analysis.code_count
                    total_loc += analysis.code_count
                    analyzed_count += 1
            except Exception as e:
                logger.debug(f"Skipping file {file_path} due to: {e}")
            finally:
                progress.update(task, advance=1)
                
    return {
        "total_files": analyzed_count,
        "total_loc": total_loc,
        "languages": languages
    }


def gather_repository_context(repo_dir: str, stats: Dict[str, Any]) -> str:
    """
    Compiles a concise, structural summary of the repository including
    top files and statistics to provide as context for the Groq AI model.
    """
    context_lines = []
    context_lines.append(f"Repository Statistics:")
    context_lines.append(f"Total Files Analyzed: {stats['total_files']}")
    context_lines.append(f"Total Lines of Code (LOC): {stats['total_loc']}")
    
    lang_breakdowns = [f" - {lang}: {loc} LOC" for lang, loc in stats['languages'].items()]
    context_lines.extend(lang_breakdowns)
    context_lines.append("\nSample file names and structure:")
    
    file_sample = []
    count = 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for file in files:
            if not file.startswith('.'):
                rel_path = os.path.relpath(os.path.join(root, file), repo_dir)
                file_sample.append(rel_path)
                count += 1
                if count >= 30:
                    break
        if count >= 30:
            break
            
    context_lines.append(", ".join(file_sample))
    
    # Read a tiny piece of README.md if it exists to help the model understand the project purpose
    readme_paths = [os.path.join(repo_dir, "README.md"), os.path.join(repo_dir, "readme.md")]
    for path in readme_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    readme_content = f.read(1000)  # Read first 1000 characters
                    context_lines.append(f"\n--- README.md Summary ---\n{readme_content}\n--- End README.md ---")
                break
            except Exception:
                pass
                
    return "\n".join(context_lines)


def generate_markdown_report(repo_url: str, stats: Dict[str, Any], ai_review: str) -> str:
    """
    Generates a professionally formatted Markdown report summarizing LOC stats and AI reviews.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Compile the table rows of statistics
    table_rows = []
    sorted_langs = sorted(stats["languages"].items(), key=lambda x: x[1], reverse=True)
    for lang, loc in sorted_langs:
        percentage = (loc / stats["total_loc"]) * 100 if stats["total_loc"] > 0 else 0.0
        table_rows.append(f"| {lang} | {loc:,} | {percentage:.1f}% |")
        
    table_body = "\n".join(table_rows)

    markdown_report = f"""# Repository Analysis Report

**Repository:** {repo_url}  
**Analyzed:** {timestamp}  

## Code Statistics

| Language | LOC | Percentage |
| :--- | :---: | :---: |
{table_body}
| **Total** | **{stats['total_loc']:,}** | **100.0%** |

## AI Technical Review

{ai_review}

---
*Generated by [AI Repository Analyzer]({repo_url})*
"""
    return markdown_report


def main():
    parser = argparse.ArgumentParser(
        description="Resilient AI-powered GitHub/Git repository LOC statistics and review tool."
    )
    parser.add_argument("repo_url", help="URL of the Git repository to analyze")
    parser.add_argument("-o", "--output", help="Save report to markdown file (e.g., report.md)")
    
    args = parser.parse_args()
    repo_url = args.repo_url.strip()
    output_file = args.output

    temp_dir = None
    try:
        # Step 1: Cloning repository with a beautiful spinner
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            transient=True
        ) as progress:
            progress.add_task("🔄 Cloning repository...", total=None)
            temp_dir = tempfile.mkdtemp(prefix="repo_analyzer_")
            git.Repo.clone_from(repo_url, temp_dir, depth=1)

        dir_name = os.path.basename(temp_dir)
        console.print(f"✓ Cloned to /tmp/{dir_name}", style="green")

        # Step 2: Analyzing code structure
        stats = count_code_statistics_with_progress(temp_dir)
        console.print(f"✓ Analyzed {stats['total_files']} files", style="green")

        # Step 3: Running AI Analysis with progress spinner
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold magenta]{task.description}"),
            transient=True
        ) as progress:
            progress.add_task("🤖 Running AI analysis...", total=None)
            
            # Compile text context of the repo
            repo_context = gather_repository_context(temp_dir, stats)
            
            # Instantiate services (picks up GROQ_API_KEY from environment)
            analyzer = LLMAnalyzer()
            orchestrator = AnalysisOrchestrator(analyzer)
            
            # Formulate request
            request = AnalysisRequest(
                text=repo_context,
                analysis_type=AnalysisType.CODE_QUALITY
            )
            
            # Execute analysis (resiliently via our orchestrator)
            result = orchestrator.execute_analysis(request)

        console.print("✓ AI analysis complete", style="green")

        # Step 4: Printing gorgeous report using Rich Panels and Tables
        console.print("\n============================================================", style="bold blue")
        console.print("📋 [bold white]ANALYSIS REPORT[/bold white]", style="bold blue")
        console.print("============================================================", style="bold blue")
        console.print(f"\n🔗 [bold]Repository:[/bold] [underline cyan]{repo_url}[/underline cyan]")
        
        console.print("\n📊 [bold]Code Statistics:[/bold]")
        
        # Define statistics Table
        table = Table(show_header=True, header_style="bold magenta", box=None)
        table.add_column("Language", style="bold white")
        table.add_column("LOC", justify="right", style="green")
        table.add_column("Percentage", justify="right", style="yellow")
        table.add_column("Bar Chart", style="cyan")

        # Sort languages by LOC descending
        sorted_langs = sorted(stats["languages"].items(), key=lambda x: x[1], reverse=True)
        for lang, loc in sorted_langs:
            percentage = (loc / stats["total_loc"]) * 100 if stats["total_loc"] > 0 else 0.0
            # 1 block per 4%
            bar_len = int(percentage / 4)
            bar = "█" * bar_len
            table.add_row(lang, f"{loc:,}", f"{percentage:.1f}%", bar)

        console.print(table)
        console.print(f"   [bold]Total LOC:[/bold] [bold green]{stats['total_loc']:,}[/bold green]\n")

        console.print("🤖 [bold]AI Technical Review:[/bold]\n")
        
        ai_review_content = ""
        if result.status == "success" and result.raw_output:
            ai_review_content = result.raw_output
            # Render Markdown nicely formatted inside a cyan Panel
            markdown_review = Markdown(ai_review_content)
            panel = Panel(
                markdown_review,
                title="[bold cyan]Review Details[/bold cyan]",
                border_style="cyan"
            )
            console.print(panel)
        else:
            ai_review_content = f"Failed to generate review. Error: {result.error}"
            # Print error inside a red Panel
            error_panel = Panel(
                f"[bold red]Failed to generate review.[/bold red]\nError: {result.error}",
                title="[bold red]Error Details[/bold red]",
                border_style="red"
            )
            console.print(error_panel)
            
        console.print("============================================================", style="bold blue")

        # Step 5: Save Markdown file if option provided
        if output_file:
            try:
                markdown_text = generate_markdown_report(repo_url, stats, ai_review_content)
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(markdown_text)
                console.print(f"\n✓ Saved report to {output_file}", style="green")
            except Exception as e:
                console.print(f"\n❌ Failed to save markdown report to {output_file}: {e}", style="bold red")

    except Exception as e:
        console.print(f"\n❌ Error analyzing repository: {e}", style="bold red")
        logger.exception("Failed during analysis run")
        sys.exit(1)
        
    finally:
        # Clean up temporary cloned repository
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

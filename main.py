#!/usr/bin/env python3
"""
Run from the project root: for each repo in repos.json, fetch open PRs, analyze, and refresh viz/.
"""

from gh_pr_analysis.cli import run

if __name__ == "__main__":
    run()

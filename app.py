#!/usr/bin/env python3
"""Minimal Streamlit entrypoint for Zero-Trace RAG."""

from __future__ import annotations

from app_runtime import main as runtime_main


def main() -> None:
    """Run the application runtime."""
    runtime_main()


if __name__ == "__main__":
    main()

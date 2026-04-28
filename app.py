#!/usr/bin/env python3
"""Minimal Streamlit entrypoint for Zero-Trace RAG."""

from __future__ import annotations

import app_runtime


def main() -> None:
    """Run the application runtime."""
    app_runtime.main()


if __name__ == "__main__":
    main()

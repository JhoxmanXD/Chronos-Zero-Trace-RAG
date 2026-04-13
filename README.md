[🇪🇸 Leer en Español](README.es.md)

# Chronos: Zero-Trace Local RAG

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-App-red)
![Source Available](https://img.shields.io/badge/Source_Available-Non_Commercial-blue)

Chronos is a privacy-focused local RAG assistant designed for technical research and OSINT workflows. It combines local-first model support with hardened network controls, encrypted secret storage, and no-trace chat modes.

## Features

- Local LLM support with OpenAI-compatible endpoints (LM Studio/Ollama style) and provider switching.
- Tor-routed OSINT web retrieval with `socks5h` policy checks and fail-closed privacy behavior.
- SearXNG instance rotation to reduce single-endpoint dependence and improve resilience.
- Brave Search API mode for fast, key-authenticated web search.
- Encrypted local Vault for API keys and provider secrets (`.secrets` with Fernet encryption).
- No-logging Incognito mode that keeps conversations out of persistent chat storage.

## Getting Started

For a beginner-friendly setup, follow [INSTALL_GUIDE.txt](INSTALL_GUIDE.txt).

Quick run:

1. Install dependencies:
   `pip install -r requirements.txt`
2. Start Tor (port `9050` or `9150`).
3. Launch the app:
   `streamlit run app.py`

On first run, Chronos creates `.secrets` automatically for encrypted credential storage.

## License

This project uses a custom source-available license in [LICENSE.txt](LICENSE.txt).
Commercial use requires a royalty agreement with the maintainer.
Commercial contact: jhoxmanvalenzuela06@gmail.com

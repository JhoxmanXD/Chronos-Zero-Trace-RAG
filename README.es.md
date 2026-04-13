[🇬🇧 Read in English](README.md)

# Chronos: Zero-Trace Local RAG

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-App-red)
![Source Available](https://img.shields.io/badge/Source_Available-Non_Commercial-blue)

Chronos es un asistente RAG local centrado en privacidad, diseñado para investigación técnica y flujos OSINT. Combina soporte local-first para modelos con controles de red reforzados, almacenamiento cifrado de secretos y modos de chat sin rastro.

## Caracteristicas

- Soporte de LLM local con endpoints compatibles con OpenAI (estilo LM Studio/Ollama) y cambio de proveedor.
- Recuperación web OSINT enrutada por Tor con políticas `socks5h` y comportamiento de privacidad fail-closed.
- Rotación de instancias SearXNG para reducir dependencia de un solo endpoint y mejorar resiliencia.
- Modo Brave Search API para búsquedas web rápidas con autenticación por API key.
- Vault local cifrado para API keys y secretos de proveedores (`.secrets` con cifrado Fernet).
- Modo Incógnito sin logs que mantiene conversaciones fuera del almacenamiento persistente de chats.

## Inicio Rapido

Para una configuracion amigable para principiantes, sigue [INSTALL_GUIDE.txt](INSTALL_GUIDE.txt).

Ejecucion rapida:

1. Instala las dependencias:
   `pip install -r requirements.txt`
2. Inicia Tor (puerto `9050` o `9150`).
3. Ejecuta la app:
   `streamlit run app.py`

En la primera ejecucion, Chronos crea `.secrets` automaticamente para el almacenamiento cifrado de credenciales.

## Licencia

Este proyecto usa una licencia personalizada tipo source-available en [LICENSE.txt](LICENSE.txt).
El uso comercial requiere un acuerdo de regalias con el mantenedor.
Contacto comercial: jhoxmanvalenzuela06@gmail.com

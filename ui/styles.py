"""Streamlit style injection for Zero-Trace RAG."""

from __future__ import annotations

import streamlit as st

def inject_styles() -> None:
    st.markdown(
        """
        <style>
            :root {
                --zt-bg-1: #0b1220;
                --zt-bg-2: #101827;
                --zt-bg-3: #111827;
                --zt-surface: rgba(17, 24, 39, 0.68);
                --zt-border: rgba(148, 163, 184, 0.30);
                --zt-text: #e5e7eb;
                --zt-muted: #9ca3af;
                --zt-ok: #10b981;
                --zt-warn: #f59e0b;
                --zt-bad: #ef4444;
                --zt-left-sidebar-width: 22rem;
                --zt-right-console-width: 22rem;
                --zt-right-gap: 0.85rem;
                --zt-composer-height: 7.6rem;
                --zt-chat-bottom-safe: 6rem;
                --zt-chat-available-width: calc(100vw - var(--zt-left-sidebar-width) - var(--zt-right-console-width) - var(--zt-right-gap) - 2.2rem);
                --zt-main-left-offset: calc(var(--zt-left-sidebar-width) + 1rem);
                --zt-main-right-offset: calc(var(--zt-right-console-width) + var(--zt-right-gap) + 1rem);
            }

            [data-testid="stHeader"],
            [data-testid="stToolbar"],
            [data-testid="stAppToolbar"],
            [data-testid="stDecoration"],
            [data-testid="stStatusWidget"],
            header,
            #MainMenu,
            footer {
                display: none !important;
                visibility: hidden !important;
                height: 0 !important;
            }

            html, body, [data-testid="stAppViewContainer"] {
                color: var(--zt-text);
                background:
                    radial-gradient(1200px 600px at 0% 0%, #1f293780 0%, transparent 60%),
                    radial-gradient(900px 600px at 100% 100%, #0f766e30 0%, transparent 65%),
                    linear-gradient(145deg, var(--zt-bg-1) 0%, var(--zt-bg-2) 40%, var(--zt-bg-3) 100%);
            }

            .st-emotion-cache-19iia29 {
                margin-bottom: 100px !important;
            }

            [data-testid="stSidebar"] {
                border-right: 1px solid var(--zt-border);
                background: linear-gradient(180deg, #0b1220 0%, #0f172a 100%);
                width: var(--zt-left-sidebar-width) !important;
                min-width: var(--zt-left-sidebar-width) !important;
                max-width: var(--zt-left-sidebar-width) !important;
            }

            [data-testid="stSidebar"][aria-expanded="false"] {
                transform: translateX(0) !important;
                margin-left: 0 !important;
                width: var(--zt-left-sidebar-width) !important;
                min-width: var(--zt-left-sidebar-width) !important;
                max-width: var(--zt-left-sidebar-width) !important;
            }

            [data-testid="stSidebarCollapseButton"] {
                display: none !important;
            }

            /* Hacer que toda la fila actue como un solo elemento con hover */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-open_chat_"]) {
                align-items: center;
                border-radius: 8px;
                margin-bottom: 4px;
                padding: 0 4px;
                transition: background-color 0.2s ease;
                gap: 0 !important;
            }

            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-open_chat_"]):not(:has([class*="st-key-open_chat_active_"])) {
                background-color: rgba(148, 163, 184, 0.16);
            }

            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-open_chat_"]):not(:has([class*="st-key-open_chat_active_"])):hover {
                background-color: rgba(148, 163, 184, 0.19);
            }

            /* Resaltar el chat activo */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-open_chat_active_"]) {
                background-color: rgba(148, 163, 240, 0.50);
            }

            /* Quitar fondos nativos de los botones del chat */
            [data-testid="stSidebar"] [class*="st-key-open_chat_"] button {
                background: transparent !important;
                border: none !important;
                box-shadow: none !important;
                justify-content: flex-start;
                padding: 0.5rem 0.5rem;
                color: var(--zt-text);
            }

            /* Ocultar la columna de los 3 puntos por defecto */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-open_chat_"]) [data-testid="column"]:nth-child(2) {
                opacity: 0;
                transition: opacity 0.2s ease;
            }

            /* Mostrar la columna de los 3 puntos solo al hacer hover en la fila O si el menu esta abierto */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([class*="st-key-open_chat_"]):hover [data-testid="column"]:nth-child(2),
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"]:has([data-testid="stPopover"] button[aria-expanded="true"]) [data-testid="column"]:nth-child(2) {
                opacity: 1;
            }

            /* Limpiar el boton del Popover (quitar textos, svg y flechas nativas) */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button {
                background: transparent !important;
                border: none !important;
                box-shadow: none !important;
                color: transparent !important;
                position: relative;
                min-height: 2.2rem;
                padding: 0 !important;
            }

            /* Hacer transparente todo el contenedor visual del menu de 3 puntos */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > div {
                background: transparent !important;
                border: 0 !important;
                box-shadow: none !important;
            }

            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"]:hover,
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"]:active,
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"]:focus,
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"]:focus-visible,
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"][aria-expanded="true"] {
                background: transparent !important;
                border: 0 !important;
                box-shadow: none !important;
                outline: none !important;
            }

            /* Aniquilar el contenido interno nativo, cazando la flecha y los spans especificamente */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button span,
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button div,
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button svg {
                display: none !important;
                opacity: 0 !important;
                visibility: hidden !important;
                width: 0 !important;
                height: 0 !important;
            }

            /* Remove the Material Design icon (arrow) in any state, including click */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button [data-testid="stIconMaterial"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button[aria-expanded="true"] [data-testid="stIconMaterial"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button:active [data-testid="stIconMaterial"] {
                display: none !important;
                opacity: 0 !important;
                font-size: 0 !important;
                visibility: hidden !important;
                width: 0 !important;
                height: 0 !important;
            }

            /* Force button text to stay transparent in case Streamlit re-injects it */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button,
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button[aria-expanded="true"] {
                color: transparent !important;
                font-size: 0 !important;
                line-height: 0 !important;
                text-indent: -9999px !important;
                overflow: hidden !important;
                white-space: nowrap !important;
            }

            /* Extra guard against dynamic Material/Emotion classes that reappear on rerender */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button [class*="material"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button [class*="Material"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button [class*="icon"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button [class*="Icon"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button [class*="emotion"] {
                display: none !important;
                opacity: 0 !important;
                visibility: hidden !important;
                width: 0 !important;
                height: 0 !important;
            }

            /* Final guard: collapse the right internal block containing expand_more */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"] > div > div:last-child,
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"][aria-expanded="true"] > div > div:last-child,
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"]:active > div > div:last-child {
                display: none !important;
                opacity: 0 !important;
                visibility: hidden !important;
                width: 0 !important;
                height: 0 !important;
                margin: 0 !important;
                padding: 0 !important;
                border: 0 !important;
                flex: 0 0 0 !important;
                max-width: 0 !important;
                min-width: 0 !important;
                overflow: hidden !important;
            }

            /* Final guard: hide the exact data-testid node that Streamlit re-injects */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"] [data-testid="stIconMaterial"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"][aria-expanded="true"] [data-testid="stIconMaterial"],
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] button[data-testid="stPopoverButton"]:active [data-testid="stIconMaterial"] {
                display: none !important;
                opacity: 0 !important;
                visibility: hidden !important;
                width: 0 !important;
                height: 0 !important;
                margin: 0 !important;
                padding: 0 !important;
                font-size: 0 !important;
                line-height: 0 !important;
                overflow: hidden !important;
            }

            /* Draw a clean custom 3-dots icon */
            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button::after {
                content: "⋮";
                position: absolute;
                left: 50%;
                top: 50%;
                transform: translate(-50%, -50%);
                color: var(--zt-muted);
                font-size: 1.4rem;
                font-weight: bold;
                line-height: 1;
                text-indent: 0 !important;
                visibility: visible;
            }

            [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] [data-testid="stPopover"] > button:hover::after {
                color: var(--zt-text);
            }

            /* Reduce font size in secondary/delete buttons */
            [data-testid="stPopoverBody"] button {
                font-size: 0.82rem !important;
                padding: 0.2rem 0.5rem !important;
                min-height: 2rem !important;
            }

            .main {
                box-sizing: border-box;
                min-width: 0;
                padding-right: 0;
            }

            .main .block-container {
                box-sizing: border-box;
                min-width: 0;
                max-width: none;
                width: min(1240px, calc(100vw - var(--zt-left-sidebar-width) - var(--zt-right-console-width) - var(--zt-right-gap) - 2.2rem));
                padding-top: 0.7rem;
                padding-bottom: calc(var(--zt-composer-height) + var(--zt-chat-bottom-safe));
                padding-left: 1rem;
                padding-right: 1.45rem;
                margin-left: 0.9rem;
                margin-right: auto;
            }

            [data-testid="stAppViewContainer"] .main .block-container {
                width: min(1240px, var(--zt-chat-available-width)) !important;
                max-width: min(1240px, var(--zt-chat-available-width)) !important;
                margin-right: auto !important;
            }

            [data-testid="stBottomBlockContainer"] {
                position: fixed;
                left: var(--zt-main-left-offset);
                right: var(--zt-main-right-offset);
                bottom: 0.85rem;
                z-index: 92;
                margin: 0;
                padding: 0 !important;
                width: auto !important;
                background: transparent !important;
            }

            [data-testid="stBottomBlockContainer"] > div {
                max-width: none !important;
                padding: 0 !important;
            }

            [data-testid="stBottomBlockContainer"] [data-testid="stChatInput"] {
                margin: 0;
                padding: 0.5rem 0.55rem;
                border: 1px solid var(--zt-border);
                border-radius: 14px;
                background: linear-gradient(180deg, rgba(15, 23, 42, 0.96), rgba(15, 23, 42, 0.90));
                backdrop-filter: blur(8px);
                -webkit-backdrop-filter: blur(8px);
                box-shadow: 0 10px 28px rgba(2, 6, 23, 0.3);
            }

            [data-testid="stBottomBlockContainer"] [data-testid="stChatInput"] > div {
                margin-bottom: 0 !important;
                max-width: 100%;
            }

            [data-testid="stChatMessage"] {
                background: var(--zt-surface);
                border: 1px solid var(--zt-border);
                border-radius: 16px;
                backdrop-filter: blur(6px);
                -webkit-backdrop-filter: blur(6px);
                box-shadow: 0 8px 30px rgba(2, 6, 23, 0.20);
                width: 100%;
                max-width: 100%;
                min-width: 0;
                overflow: hidden;
            }

            [data-testid="stHorizontalBlock"] {
                max-width: 100%;
                min-width: 0;
            }

            [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
                overflow-wrap: anywhere;
                word-break: break-word;
            }

            [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stMarkdownContainer"] {
                padding-right: 0.85rem;
            }

            [data-testid="stChatMessage"] pre {
                max-width: 100%;
                overflow-x: auto;
            }

            .zt-header {
                font-size: 1.3rem;
                font-weight: 700;
                letter-spacing: 0.02em;
                margin-bottom: 0.2rem;
            }

            .zt-subtitle {
                color: var(--zt-muted);
                margin-bottom: 0.8rem;
            }

            .zt-badge {
                display: inline-flex;
                align-items: center;
                gap: 0.45rem;
                font-size: 0.86rem;
                font-weight: 600;
                padding: 0.28rem 0.6rem;
                border-radius: 999px;
                border: 1px solid;
                width: fit-content;
            }

            .zt-dot {
                width: 0.5rem;
                height: 0.5rem;
                border-radius: 50%;
                display: inline-block;
            }

            .zt-ok {
                color: #a7f3d0;
                border-color: #10b98166;
                background: #022c2230;
            }

            .zt-warn {
                color: #fde68a;
                border-color: #f59e0b66;
                background: #3b2f0330;
            }

            .zt-bad {
                color: #fecaca;
                border-color: #ef444466;
                background: #3b111130;
            }

            .zt-small {
                color: var(--zt-muted);
                font-size: 0.83rem;
                margin-top: 0.35rem;
            }

            .zt-cache-indicator {
                display: inline-block;
                margin-bottom: 0.45rem;
                padding: 0.18rem 0.55rem;
                border-radius: 999px;
                border: 1px solid #14b8a666;
                background: #052e2b80;
                color: #99f6e4;
                font-size: 0.74rem;
                font-weight: 600;
                letter-spacing: 0.01em;
            }

            .zt-think-box {
                margin: 0.2rem 0 0.55rem 0;
                border: 1px solid rgba(148, 163, 184, 0.28);
                border-radius: 10px;
                background: rgba(15, 23, 42, 0.45);
                overflow: hidden;
            }

            .zt-think-box summary {
                cursor: pointer;
                padding: 0.32rem 0.55rem;
                color: #c7d2fe;
                background: rgba(30, 41, 59, 0.55);
                font-size: 0.76rem;
                font-weight: 600;
                white-space: nowrap;
                text-overflow: ellipsis;
                overflow: hidden;
            }

            .zt-think-body {
                padding: 0.45rem 0.55rem;
                color: #d1d5db;
                font-size: 0.82rem;
                white-space: pre-wrap;
                line-height: 1.38;
            }

            .zt-thinking-live {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                color: #93c5fd;
            }

            .zt-thinking-dot {
                width: 0.46rem;
                height: 0.46rem;
                border-radius: 50%;
                background: #22d3ee;
                animation: zt-thinking-pulse 1.15s ease-in-out infinite;
            }

            .zt-thinking-dots::after {
                content: "...";
                display: inline-block;
                width: 1.2rem;
                overflow: hidden;
                vertical-align: bottom;
                animation: zt-thinking-dots 1s steps(4, end) infinite;
            }

            @keyframes zt-thinking-pulse {
                0% {
                    opacity: 0.35;
                    transform: scale(0.85);
                }
                50% {
                    opacity: 1;
                    transform: scale(1);
                }
                100% {
                    opacity: 0.35;
                    transform: scale(0.85);
                }
            }

            @keyframes zt-thinking-dots {
                0% {
                    width: 0;
                }
                100% {
                    width: 1.2rem;
                }
            }

            .zt-card {
                border: 1px solid var(--zt-border);
                background: var(--zt-surface);
                border-radius: 14px;
                padding: 0.65rem 0.75rem;
                margin-bottom: 0.65rem;
            }

            .zt-sticky-context {
                position: fixed;
                top: 0.55rem;
                left: calc(var(--zt-left-sidebar-width) + 1.1rem);
                right: calc(var(--zt-right-console-width) + var(--zt-right-gap) + 1rem);
                z-index: 90;
                border: 1px solid var(--zt-border);
                background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.80));
                border-radius: 12px;
                padding: 0.58rem 0.68rem;
                margin-bottom: 0.75rem;
                backdrop-filter: blur(8px);
                -webkit-backdrop-filter: blur(8px);
            }

            .zt-context-spacer {
                height: 5.2rem;
            }

            .zt-sticky-topline {
                display: flex;
                justify-content: space-between;
                gap: 0.5rem;
                font-size: 0.84rem;
                color: var(--zt-text);
                margin-bottom: 0.32rem;
            }

            .zt-sticky-subline {
                font-size: 0.76rem;
                color: var(--zt-muted);
                margin-top: 0.3rem;
            }

            .zt-token-track {
                width: 100%;
                height: 8px;
                border-radius: 999px;
                background: rgba(148, 163, 184, 0.22);
                overflow: hidden;
            }

            .zt-token-fill {
                height: 100%;
                border-radius: 999px;
                transition: width 0.18s ease;
            }

            .zt-right-console {
                position: fixed;
                top: 0;
                right: var(--zt-right-gap);
                width: var(--zt-right-console-width);
                height: 100vh;
                border-left: 1px solid var(--zt-border);
                background: linear-gradient(180deg, #0b1220 0%, #0f172a 100%);
                box-shadow: 0 16px 40px rgba(2, 6, 23, 0.35);
                z-index: 95;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }

            .zt-console-head {
                padding: 1rem 1rem 0.7rem 1rem;
                border-bottom: 1px solid var(--zt-border);
            }

            .zt-console-title {
                margin: 0;
                font-size: 1.05rem;
                font-weight: 700;
                color: var(--zt-text);
            }

            .zt-console-status {
                margin-top: 0.2rem;
                color: var(--zt-muted);
                font-size: 0.8rem;
            }

            .zt-console-body {
                margin: 0;
                padding: 0.9rem 0.9rem 1.1rem 0.9rem;
                overflow-y: auto;
                font-family: Consolas, "Courier New", monospace;
                font-size: 0.75rem;
                line-height: 1.35;
                color: #dbeafe;
                flex: 1;
                background: linear-gradient(180deg, rgba(2, 6, 23, 0.28), rgba(2, 6, 23, 0.08));
            }

            .zt-console-empty {
                border: 1px dashed var(--zt-border);
                border-radius: 10px;
                padding: 0.75rem;
                color: var(--zt-muted);
                font-size: 0.76rem;
            }

            .zt-console-line {
                display: grid;
                grid-template-columns: 14px 1fr;
                gap: 0.45rem;
                padding: 0.22rem 0.36rem;
                border-radius: 6px;
                margin-bottom: 0.2rem;
                background: rgba(15, 23, 42, 0.28);
            }

            .zt-console-prompt {
                color: #22d3ee;
                opacity: 0.9;
            }

            .zt-console-text {
                color: #dbeafe;
                white-space: pre-wrap;
                word-break: break-word;
            }

            .zt-log-group {
                margin: 0 0 0.45rem 0;
                border: 1px solid rgba(148, 163, 184, 0.26);
                border-radius: 8px;
                background: rgba(15, 23, 42, 0.38);
                overflow: hidden;
            }

            .zt-log-summary {
                cursor: pointer;
                padding: 0.34rem 0.5rem;
                background: rgba(56, 189, 248, 0.12);
                color: #bae6fd;
                font-weight: 600;
                font-size: 0.73rem;
                border-bottom: 1px solid transparent;
            }

            .zt-log-group[open] .zt-log-summary {
                border-bottom-color: rgba(148, 163, 184, 0.2);
            }

            .zt-log-group-body {
                padding: 0.25rem;
            }

            @media (max-width: 1200px) {
                .main {
                    padding-right: 0;
                }

                :root {
                    --zt-main-right-offset: 0.9rem;
                }

                .main .block-container {
                    padding-right: 0.8rem;
                    width: auto;
                }

                [data-testid="stBottomBlockContainer"] {
                    bottom: 0.75rem;
                }

                .zt-right-console {
                    position: static;
                    width: 100%;
                    height: 22rem;
                    margin-top: 0.8rem;
                    border: 1px solid var(--zt-border);
                    border-radius: 14px;
                }

                .zt-sticky-context {
                    position: sticky;
                    top: 0.4rem;
                    left: auto;
                    right: auto;
                }

                .zt-context-spacer {
                    height: 0.35rem;
                }
            }

            @media (max-width: 900px) {
                :root {
                    --zt-main-left-offset: 0.8rem;
                    --zt-main-right-offset: 0.8rem;
                    --zt-composer-height: 6.2rem;
                    --zt-chat-bottom-safe: 1.8rem;
                }

                .main .block-container {
                    padding-top: 0.75rem;
                    padding-left: 0.8rem;
                    padding-right: 0.8rem;
                    padding-bottom: calc(var(--zt-composer-height) + var(--zt-chat-bottom-safe));
                }

                [data-testid="stBottomBlockContainer"] {
                    bottom: 0.55rem;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )



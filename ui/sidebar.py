"""Sidebar controls and settings panel for Streamlit UI."""

from __future__ import annotations

from typing import Any, List

import streamlit as st

def sidebar_controls(runtime: dict[str, Any]) -> tuple[str, str, str, bool, str, List[str]]:
    """Render the full sidebar controls and return runtime chat settings."""
    globals().update(runtime)
    with st.sidebar:
        is_generating = bool(st.session_state.generation_active)
        st.subheader("Conversations")

        col1, col2 = st.columns(2, gap="small")
        with col1:
            if st.button("New Chat", use_container_width=True, disabled=is_generating):
                save_ui_settings_to_disk()
                create_new_conversation(is_incognito=False)
                st.rerun()
        with col2:
            if st.button("Incognito", use_container_width=True, disabled=is_generating):
                save_ui_settings_to_disk()
                create_new_conversation(is_incognito=True)
                st.rerun()

        current_id = st.session_state.current_conversation_id
        chat_items = list(st.session_state.conversations.values())
        chat_items.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)

        for chat in chat_items:
            chat_id = chat["id"]
            is_active = chat_id == current_id
            chat_title = str(chat.get("title", "")).strip() or "Untitled chat"
            display_title = chat_title
            if len(display_title) > 42:
                display_title = f"{display_title[:39]}..."

            with st.container():
                open_col, menu_col = st.columns([8, 1], gap="small")

                with open_col:
                    open_key = f"open_chat_active_{chat_id}" if is_active else f"open_chat_{chat_id}"
                    if st.button(
                        display_title,
                        key=open_key,
                        use_container_width=True,
                        type="secondary",
                        disabled=is_generating,
                    ):
                        save_ui_settings_to_disk()
                        st.session_state.current_conversation_id = chat_id
                        st.rerun()

                with menu_col:
                    if hasattr(st, "popover"):
                        with st.popover("⋮", use_container_width=True):
                            rename_value = st.text_input(
                                "Rename",
                                value=chat_title,
                                key=f"rename_chat_{chat_id}",
                                label_visibility="collapsed",
                                disabled=is_generating,
                            ).strip()

                            if st.button(
                                "Save Name",
                                key=f"rename_chat_save_{chat_id}",
                                use_container_width=True,
                                disabled=is_generating,
                            ):
                                chat["title"] = rename_value or chat_title
                                save_conversation_to_disk(chat)
                                save_ui_settings_to_disk()
                                st.rerun()

                            if st.button(
                                "Delete",
                                key=f"delete_chat_{chat_id}",
                                use_container_width=True,
                                disabled=is_generating,
                            ):
                                save_ui_settings_to_disk()
                                st.session_state.current_conversation_id = chat_id
                                delete_current_conversation()
                                st.rerun()
                    else:
                        if st.button(
                            "Del",
                            key=f"delete_chat_inline_{chat_id}",
                            use_container_width=True,
                            disabled=is_generating,
                        ):
                            save_ui_settings_to_disk()
                            st.session_state.current_conversation_id = chat_id
                            delete_current_conversation()
                            st.rerun()

        st.divider()
        st.subheader("Configuration")

        with st.expander("LLM Configuration", expanded=True):
            ensure_provider_state_consistency()
            selected_provider = st.selectbox(
                "Provider",
                options=PROVIDER_OPTIONS,
                index=safe_option_index(PROVIDER_OPTIONS, st.session_state.active_provider),
                disabled=is_generating,
            )

            if selected_provider != st.session_state.active_provider:
                st.session_state.active_provider = selected_provider
                sync_active_provider_runtime_state()
                save_ui_settings_to_disk()
                st.rerun()

            active_provider = st.session_state.active_provider
            active_cfg = st.session_state.provider_settings[active_provider]
            provider_key_suffix = re.sub(r"[^a-zA-Z0-9]+", "_", active_provider).strip("_").lower()

            if active_provider == PROVIDER_LOCAL:
                active_cfg["base_url"] = (
                    st.text_input(
                        "API URL",
                        value=str(active_cfg.get("base_url", DEFAULT_LM_URL) or DEFAULT_LM_URL),
                        help="Example: http://localhost:1234/v1",
                        disabled=is_generating,
                    ).strip()
                    or DEFAULT_LM_URL
                )
                st.caption("Local mode does not require an API key (LM Studio/Ollama).")
            elif active_provider == PROVIDER_OPENAI_COMPAT:
                active_cfg["base_url"] = (
                    st.text_input(
                        "Base URL",
                        value=str(active_cfg.get("base_url", DEFAULT_OPENAI_COMPAT_URL) or DEFAULT_OPENAI_COMPAT_URL),
                        help="Example: https://api.openai.com/v1",
                        disabled=is_generating,
                    ).strip()
                    or DEFAULT_OPENAI_COMPAT_URL
                )
                active_cfg["api_key"] = st.text_input(
                    "API Key",
                    value=str(active_cfg.get("api_key", "") or ""),
                    type="password",
                    key=f"provider_api_key_{provider_key_suffix}",
                    disabled=is_generating,
                ).strip()
            else:
                active_cfg["base_url"] = OPENROUTER_BASE_URL
                st.caption(f"Fixed Base URL: {OPENROUTER_BASE_URL}")
                active_cfg["api_key"] = st.text_input(
                    "API Key",
                    value=str(active_cfg.get("api_key", "") or ""),
                    type="password",
                    key=f"provider_api_key_{provider_key_suffix}",
                    disabled=is_generating,
                ).strip()

            model_dict = dict(
                sorted(_normalize_provider_custom_models(active_cfg.get("custom_models_dict", {})).items(), key=lambda item: item[0].casefold())
            )
            active_cfg["custom_models_dict"] = model_dict

            default_provider_model = DEFAULT_PROVIDER_MODELS[active_provider]
            model_options = [default_provider_model, *list(model_dict.keys())]
            selected_label = default_provider_model
            current_model_id = str(active_cfg.get("model_name", "")).strip() or default_provider_model
            if current_model_id != default_provider_model:
                for label, model_id in model_dict.items():
                    if str(model_id).strip() == current_model_id:
                        selected_label = label
                        break

            selected_model_label = st.selectbox(
                "Model Selector",
                options=model_options,
                index=safe_option_index(model_options, selected_label),
                disabled=is_generating,
            )
            active_cfg["model_name"] = (
                default_provider_model
                if selected_model_label == default_provider_model
                else str(model_dict.get(selected_model_label, default_provider_model)).strip() or default_provider_model
            )

            if hasattr(st, "popover"):
                models_container = st.popover("Manage Models", use_container_width=True)
            else:
                models_container = st.expander("Manage Models", expanded=False)

            with models_container:
                new_display_name = st.text_input(
                    "Display Name",
                    key=f"custom_model_display_name_{provider_key_suffix}",
                    disabled=is_generating,
                ).strip()
                new_model_id = st.text_input(
                    "Model ID",
                    key=f"custom_model_id_{provider_key_suffix}",
                    disabled=is_generating,
                ).strip()

                if st.button(
                    "Add Model",
                    key=f"add_custom_model_{provider_key_suffix}",
                    use_container_width=True,
                    disabled=is_generating,
                ):
                    if new_display_name and new_model_id:
                        active_cfg["custom_models_dict"][new_display_name] = new_model_id
                        active_cfg["custom_models_dict"] = dict(
                            sorted(active_cfg["custom_models_dict"].items(), key=lambda item: item[0].casefold())
                        )
                        active_cfg["model_name"] = new_model_id
                        st.session_state.provider_settings[active_provider] = active_cfg
                        save_ui_settings_to_disk()
                        st.rerun()

                custom_model_keys = list(active_cfg["custom_models_dict"].keys())
                if custom_model_keys:
                    delete_target = st.selectbox(
                        "Custom Model",
                        options=custom_model_keys,
                        disabled=is_generating,
                    )
                    if st.button(
                        "Delete",
                        key=f"delete_custom_model_{provider_key_suffix}",
                        use_container_width=True,
                        disabled=is_generating,
                    ):
                        removed_id = active_cfg["custom_models_dict"].pop(delete_target, None)
                        if removed_id and active_cfg["model_name"] == str(removed_id).strip():
                            active_cfg["model_name"] = default_provider_model
                        st.session_state.provider_settings[active_provider] = active_cfg
                        save_ui_settings_to_disk()
                        st.rerun()
                else:
                    st.caption("No custom models configured.")

            st.session_state.provider_settings[active_provider] = active_cfg

            if active_provider in {PROVIDER_OPENAI_COMPAT, PROVIDER_OPENROUTER}:
                if st.button("Save Credentials", use_container_width=True, disabled=is_generating):
                    save_provider_credentials_to_vault(st.session_state.provider_settings)
                    st.success("Credentials saved in the encrypted vault.")

            st.session_state.context_limit_tokens = st.number_input(
                "Context Limit (Tokens)",
                min_value=1024,
                max_value=MAX_CONTEXT_LIMIT_TOKENS,
                value=int(st.session_state.context_limit_tokens),
                step=256,
                help="Context budget for the active conversation.",
                disabled=is_generating,
            )

            preset_limits = [4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1_000_000]
            st.caption("Context presets:")
            for row_start in range(0, len(preset_limits), 3):
                row_values = preset_limits[row_start : row_start + 3]
                row_cols = st.columns(len(row_values), gap="small")
                for idx, preset_value in enumerate(row_values):
                    preset_label = "1M" if preset_value == 1_000_000 else f"{preset_value:,}"
                    if row_cols[idx].button(
                        preset_label,
                        key=f"preset_context_{preset_value}",
                        use_container_width=True,
                        disabled=is_generating,
                    ):
                        st.session_state.context_limit_tokens = int(preset_value)
                        save_ui_settings_to_disk()
                        st.rerun()

            st.session_state.llm_thinking_enabled = st.toggle(
                "Enable Reasoning",
                value=bool(st.session_state.llm_thinking_enabled),
                help="Force the model to reason first inside <think>...</think> before answering.",
                disabled=is_generating,
            )
            if st.session_state.llm_thinking_enabled:
                st.caption("Reasoning mode is enabled for all response requests.")

            sync_active_provider_runtime_state()
            render_lm_badge()

        with st.expander("Privacy Settings", expanded=True):
            privacy_options = list(PRIVACY_PROFILES.keys())
            if st.session_state.privacy_profile not in privacy_options:
                st.session_state.privacy_profile = "max_tor"
            if st.session_state.get("privacy_profile_ui") not in privacy_options:
                st.session_state.privacy_profile_ui = st.session_state.privacy_profile
            if st.session_state.tor_port not in {"9050", "9150"}:
                st.session_state.tor_port = DEFAULT_TOR_PORT

            selected_profile = st.radio(
                "Privacy Profile",
                options=privacy_options,
                key="privacy_profile_ui",
                format_func=lambda key: PRIVACY_PROFILES[key]["label"],
            )

            st.session_state.privacy_profile = selected_profile

            previous_profile = st.session_state.get("last_privacy_profile", selected_profile)
            if selected_profile == "max_tor" and previous_profile != "max_tor":
                create_new_conversation(is_incognito=True)
            st.session_state.last_privacy_profile = selected_profile

            profile = PRIVACY_PROFILES[st.session_state.privacy_profile]
            st.markdown("<div class='zt-card'>", unsafe_allow_html=True)
            st.caption(profile["description"])
            st.markdown("</div>", unsafe_allow_html=True)

            st.selectbox(
                "Tor Port",
                options=["9050", "9150"],
                key="tor_port",
            )

            if st.session_state.tor_port != st.session_state.last_tor_port_seen:
                st.session_state.last_tor_port_seen = st.session_state.tor_port
                st.session_state.tor_verified_status = "unknown"
                st.session_state.tor_verified_detail = (
                    f"Port changed to {st.session_state.tor_port}. Re-validating Tor egress automatically..."
                )
                st.session_state.pending_tor_revalidate = True

            web_mode = profile["web_mode"]
            if web_mode == "off":
                st.session_state.web_search_enabled = False
                st.session_state.auto_web_for_informational_queries = False
                st.caption("Web search is disabled by the current privacy profile.")
            else:
                st.toggle(
                    "Enable Web Search",
                    key="web_search_enabled",
                )
                st.toggle(
                    "Smart Search (Only When Needed)",
                    key="auto_web_for_informational_queries",
                    help=(
                        "Avoid web search for trivial messages (e.g., hello) and trigger it for "
                        "informational or current-events questions."
                    ),
                )

                if web_mode == "tor":
                    engine_keys = list(TOR_WEB_ENGINE_OPTIONS.keys())
                    current_engine = st.session_state.tor_web_engine_preference
                    if current_engine == "wikipedia":
                        st.session_state.tor_web_engine_preference = "wikipedia_only"
                    elif current_engine not in TOR_WEB_ENGINE_OPTIONS:
                        st.session_state.tor_web_engine_preference = "auto"

                    st.selectbox(
                        "Preferred Engine (Tor Mode)",
                        options=engine_keys,
                        key="tor_web_engine_preference",
                        format_func=lambda key: TOR_WEB_ENGINE_OPTIONS[key],
                        help=(
                            "Auto/SearXNG/DuckDuckGo never use Wikipedia as fallback. "
                            "Wikipedia is only used when you explicitly select 'Wikipedia Only'."
                        ),
                    )

                if web_mode == "brave":
                    st.text_input(
                        "Brave API Key",
                        key="brave_api_key",
                        type="password",
                        help="Subscription token for https://api.search.brave.com.",
                        disabled=is_generating,
                    )
                    if st.button("Save Brave API Key", use_container_width=True, disabled=is_generating):
                        save_brave_api_key_to_vault(str(st.session_state.get("brave_api_key", "") or "").strip())
                        st.success("Brave API key saved in the encrypted vault.")

            render_tor_daemon_badge()
            render_tor_badge()

            if st.button(
                "Verify Tor Now",
                use_container_width=True,
                disabled=not bool(st.session_state.model_name.strip()),
            ):
                tor_proxy = tor_proxy_from_port(st.session_state.tor_port)
                ok, detail = verify_tor_now(
                    lm_url=st.session_state.lm_url,
                    model_name=st.session_state.model_name,
                    tor_proxy=tor_proxy,
                )
                st.session_state.tor_verified_status = "ok" if ok else "error"
                st.session_state.tor_verified_detail = detail
                st.session_state.pending_tor_revalidate = not ok
                st.rerun()

            render_live_monitor(
                st.session_state.lm_url,
                st.session_state.model_name,
                st.session_state.tor_port,
                st.session_state.privacy_profile,
                st.session_state.web_search_enabled,
            )

        with st.expander("Search Settings", expanded=True):
            st.session_state.searx_instances_raw = st.text_area(
                "SearXNG Instances (One Per Line)",
                value=st.session_state.searx_instances_raw,
                height=140,
            )

            cache_entries = len(st.session_state.search_cache) if isinstance(st.session_state.search_cache, dict) else 0
            st.caption(
                "Ephemeral cache (current session only): "
                f"{cache_entries} entries | "
                f"hits={int(st.session_state.search_cache_hits)} | "
                f"misses={int(st.session_state.search_cache_misses)}"
            )
            if st.button("Clear Web Cache", use_container_width=True, disabled=is_generating):
                clear_search_cache()
                st.rerun()

        if st.button("Clear Chat Messages", use_container_width=True, disabled=is_generating):
            get_current_conversation()["messages"] = []
            save_current_conversation()
            st.rerun()

        searx_list = parse_searx_instances(st.session_state.searx_instances_raw)
        tor_proxy = tor_proxy_from_port(st.session_state.tor_port)
        save_ui_settings_to_disk()

        return (
            str(st.session_state.lm_url or "").strip(),
            str(st.session_state.model_name or "").strip(),
            tor_proxy,
            bool(st.session_state.web_search_enabled),
            st.session_state.tor_web_engine_preference,
            searx_list,
        )



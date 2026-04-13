"""Chat and console rendering components for Streamlit UI."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

import streamlit as st


def render_assistant_content(
    content: str,
    thinking_elapsed_seconds: float | None = None,
    *,
    split_thinking_blocks_fn: Callable[[str], list[tuple[str, str, bool]]],
) -> None:
    """Render assistant output with collapsible reasoning blocks.

    Args:
        content: Assistant output text.
        thinking_elapsed_seconds: Optional elapsed reasoning timer.
        split_thinking_blocks_fn: Function that splits text and <think> blocks.
    """
    blocks = split_thinking_blocks_fn(content)
    for block_type, block_text, closed in blocks:
        if block_type == "text":
            clean_text = str(block_text or "").replace("<think>", "").replace("</think>", "")
            if clean_text.strip():
                st.markdown(clean_text)
            continue

        think_text = block_text.strip()
        preview = think_text[-100:] if len(think_text) > 100 else think_text
        summary_text = escape(preview) if preview else "..."
        body_text = escape(think_text) if think_text else "..."

        if closed:
            if thinking_elapsed_seconds is not None and thinking_elapsed_seconds > 0:
                summary_html = f"Reasoning ({thinking_elapsed_seconds:.1f}s): {summary_text}"
            else:
                summary_html = f"Reasoning: {summary_text}"
        else:
            timer_text = f" {thinking_elapsed_seconds:.1f}s" if thinking_elapsed_seconds is not None else ""
            summary_html = (
                "<span class='zt-thinking-live'>"
                "<span class='zt-thinking-dot'></span>"
                f"Thinking{timer_text}"
                "<span class='zt-thinking-dots'></span>"
                "</span>"
                f": {summary_text}"
            )

        st.markdown(
            (
                "<details class='zt-think-box'>"
                f"<summary>{summary_html}</summary>"
                f"<div class='zt-think-body'>{body_text}</div>"
                "</details>"
            ),
            unsafe_allow_html=True,
        )


def render_message_bubble(
    role: str,
    content: str,
    sources: list[dict] | None = None,
    *,
    from_cache: bool = False,
    copy_key: str | None = None,
    thinking_elapsed_seconds: float | None = None,
    split_thinking_blocks_fn: Callable[[str], list[tuple[str, str, bool]]],
    render_cache_indicator_fn: Callable[[bool], None],
    render_sources_fn: Callable[[list[dict] | None], None],
    render_copy_button_fn: Callable[[str, str], None],
) -> None:
    """Render one chat bubble, including assistant metadata and tools.

    Args:
        role: Message role (user or assistant).
        content: Message text.
        sources: Optional source list.
        from_cache: Whether web context came from cache.
        copy_key: Optional key suffix for copy button.
        thinking_elapsed_seconds: Optional elapsed reasoning timer.
        split_thinking_blocks_fn: Function that splits text and <think> blocks.
        render_cache_indicator_fn: Function that renders cache badge.
        render_sources_fn: Function that renders sources list.
        render_copy_button_fn: Function that renders copy-to-clipboard button.
    """
    if role == "user":
        left_spacer, bubble_col, _ = st.columns([1.5, 1.25, 1.0], gap="small")
        _ = left_spacer
        with bubble_col:
            with st.chat_message("user"):
                st.markdown(content)
        return

    bubble_col, _, right_spacer = st.columns([1.75, 0.35, 0.9], gap="small")
    _ = right_spacer
    with bubble_col:
        with st.chat_message("assistant"):
            render_cache_indicator_fn(from_cache)
            render_assistant_content(
                content,
                thinking_elapsed_seconds=thinking_elapsed_seconds,
                split_thinking_blocks_fn=split_thinking_blocks_fn,
            )
            render_sources_fn(sources)
            if copy_key:
                render_copy_button_fn(content, copy_key)


def render_chat_history(
    messages: list[dict],
    *,
    render_message_bubble_fn: Callable[..., None],
) -> None:
    """Render the full conversation history.

    Args:
        messages: Ordered message list.
        render_message_bubble_fn: Function to render each bubble.
    """
    for idx, msg in enumerate(messages):
        render_message_bubble_fn(
            role=msg["role"],
            content=msg.get("content", ""),
            sources=msg.get("sources"),
            from_cache=bool(msg.get("from_cache", False)),
            copy_key=f"hist_{idx}",
            thinking_elapsed_seconds=msg.get("thinking_elapsed_seconds"),
        )


def render_logs_console(
    conversation: dict,
    *,
    generation_active: bool,
    placeholder=None,
) -> None:
    """Render the right-side runtime console for the active conversation.

    Args:
        conversation: Active conversation payload.
        generation_active: Whether generation is currently running.
        placeholder: Optional Streamlit placeholder container.
    """
    status = "Generating" if generation_active else "Idle"
    logs = conversation.get("logs", [])

    if logs:
        rendered_blocks: list[str] = []
        group_open = False

        for line in logs[-420:]:
            line_text = str(line)
            marker = "MSG_START:"
            marker_idx = line_text.find(marker)

            if marker_idx >= 0:
                if group_open:
                    rendered_blocks.append("</div></details>")

                summary_text = line_text[marker_idx + len(marker):].strip() or "New request"
                rendered_blocks.append(
                    "<details open class='zt-log-group'>"
                    f"<summary class='zt-log-summary'>{escape(summary_text)}</summary>"
                    "<div class='zt-log-group-body'>"
                )
                group_open = True
                continue

            rendered_blocks.append(
                "<div class='zt-console-line'>"
                "<span class='zt-console-prompt'>&gt;</span>"
                f"<span class='zt-console-text'>{escape(line_text)}</span>"
                "</div>"
            )

        if group_open:
            rendered_blocks.append("</div></details>")

        lines_html = "".join(rendered_blocks)
    else:
        lines_html = (
            "<div class='zt-console-empty'>"
            "No logs yet.<br/>"
            "Translation, web search, and generation events will appear here in real time."
            "</div>"
        )

    markup = (
        "<aside class='zt-right-console'>"
        "<div class='zt-console-head'>"
        "<h3 class='zt-console-title'>Console</h3>"
        f"<div class='zt-console-status'>Status: {escape(status)}</div>"
        "</div>"
        f"<div class='zt-console-body'>{lines_html}</div>"
        "</aside>"
    )

    target = placeholder if placeholder is not None else st
    target.markdown(markup, unsafe_allow_html=True)

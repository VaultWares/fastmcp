"""VaultWares FastMCP server.

Exposes Credit Optimizer and Fast Navigation skills via the Model Context
Protocol (MCP).  Supports three transports:

  stdio            — for Claude Desktop, Cursor, Windsurf, VS Code
  sse              — legacy HTTP SSE (backward-compat with older MCP clients)
  streamable-http  — modern HTTP transport recommended for Manus AI

Usage
-----
Run with stdio (default):
    python server.py

Run with HTTP (Manus AI / any browser-based client):
    python server.py --transport streamable-http --port 8000

Environment variables:
    MCP_TRANSPORT   One of: stdio, sse, streamable-http  (default: stdio)
    MCP_HOST        Host to bind for HTTP transports      (default: 0.0.0.0)
    MCP_PORT        Port for HTTP transports              (default: 8000)
    MCP_PATH        URL path for HTTP transports          (default: /mcp)
"""

from __future__ import annotations

import argparse
import os

from fastmcp import FastMCP

from tools.credit_optimizer import (
    analyze_batch,
    classify_intent,
    estimate_credits,
    optimize_prompt,
    recommend_model,
)
from tools.fast_navigation import fetch_url, fetch_urls

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="VaultWares MCP",
    instructions=(
        "This server provides Credit Optimizer and Fast Navigation tools "
        "for Manus AI and other MCP-compatible clients. "
        "Use the credit_* tools to route prompts to the cheapest Manus AI "
        "model without sacrificing quality. "
        "Use the nav_* tools for fast, parallel web fetching without "
        "browser overhead."
    ),
)

# ---------------------------------------------------------------------------
# Credit Optimizer tools
# ---------------------------------------------------------------------------


@mcp.tool
def credit_classify(prompt: str) -> dict:
    """Classify the intent of a prompt into one of 12 categories.

    Categories: code, research, creative, data, translation, bug_fix,
    documentation, analysis, qa, brainstorm, refactor, mixed.

    Args:
        prompt: The user prompt to classify.

    Returns:
        A dict with key 'intent' containing the classified category string.
    """
    return {"intent": classify_intent(prompt)}


@mcp.tool
def credit_recommend(prompt: str) -> dict:
    """Recommend the cheapest Manus AI model that delivers identical quality.

    Applies the Quality Veto Rule: if using a cheaper model would reduce
    output quality, this tool upgrades the recommendation automatically —
    so there is zero risk of degraded results.

    Returns one of:
      chat      — $0 cost; pure Q&A / translation / brainstorm tasks
      standard  — ~60% cheaper than Max; covers most everyday tasks
      max       — full power; used only when complexity genuinely requires it

    Args:
        prompt: The user prompt to analyse.

    Returns:
        A dict with keys: intent, model, reason, estimated_savings_pct.
    """
    return recommend_model(prompt)


@mcp.tool
def credit_optimize(prompt: str, max_tokens: int = 1500) -> dict:
    """Compress a prompt to reduce token costs while preserving its meaning.

    Removes filler phrases, normalises whitespace, and truncates very long
    prompts at a natural sentence boundary.

    Args:
        prompt: The original prompt text.
        max_tokens: Approximate character limit (4 chars ≈ 1 token).

    Returns:
        A dict with keys: original_length, optimized_prompt, optimized_length,
        reduction_pct.
    """
    return optimize_prompt(prompt, max_tokens=max_tokens)


@mcp.tool
def credit_estimate(prompt: str, model: str = "") -> dict:
    """Estimate the Manus credit cost for a given prompt.

    Uses approximate token counts and Manus public pricing rates.

    Args:
        prompt: The prompt text to estimate credits for.
        model:  Override the model recommendation. One of: chat, standard,
                max.  Leave blank to use the automatic recommendation.

    Returns:
        A dict with keys: tokens_approx, model, credits_approx,
        recommended_model, potential_savings_pct.
    """
    return estimate_credits(prompt, model=model or None)


@mcp.tool
def credit_analyze_batch(prompts: list[str]) -> dict:
    """Analyse multiple prompts and return a consolidated optimisation plan.

    Groups prompts by intent, surfaces batching opportunities, and returns
    per-prompt model recommendations alongside an aggregate savings estimate.

    Args:
        prompts: List of prompt strings (up to 50).

    Returns:
        A dict with keys: total_prompts, items, total_estimated_savings_pct,
        batching_suggestion.
    """
    return analyze_batch(prompts[:50])


# ---------------------------------------------------------------------------
# Fast Navigation tools
# ---------------------------------------------------------------------------


@mcp.tool
def nav_fetch(url: str, as_text: bool = True, ttl: int = 300) -> dict:
    """Fetch a single URL using direct httpx — far faster than browser calls.

    30–2 000× faster than Manus browser tool calls for read-only pages.
    HTML responses are automatically converted to clean plain text for LLM
    consumption.

    Args:
        url:     The URL to fetch (must start with http:// or https://).
        as_text: Convert HTML to clean plain text (default: True).
        ttl:     Cache TTL in seconds; 0 disables caching (default: 300).

    Returns:
        A dict with keys: url, status, content, error.
    """
    return fetch_url(url, as_text=as_text, ttl=ttl)


@mcp.tool
def nav_fetch_many(
    urls: list[str],
    as_text: bool = True,
    ttl: int = 300,
    max_concurrency: int = 10,
) -> dict:
    """Fetch up to 20 URLs in parallel — 10 URLs in ~1.3 seconds.

    Uses async httpx with configurable concurrency.  Achieves sub-2-second
    total fetch time vs. 150+ seconds with sequential browser tool calls.

    Args:
        urls:            List of URLs to fetch (max 20).
        as_text:         Convert HTML to plain text (default: True).
        ttl:             Cache TTL in seconds (default: 300; 0 = disabled).
        max_concurrency: Max simultaneous connections (default: 10).

    Returns:
        A dict with keys: total, succeeded, failed, results.
    """
    return fetch_urls(urls, as_text=as_text, ttl=ttl, max_concurrency=max_concurrency)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="VaultWares FastMCP server")
    parser.add_argument(
        "--transport",
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
        choices=["stdio", "sse", "streamable-http"],
        help="Transport to use (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST", "0.0.0.0"),
        help="Host for HTTP transports (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", "8000")),
        help="Port for HTTP transports (default: 8000)",
    )
    parser.add_argument(
        "--path",
        default=os.environ.get("MCP_PATH", "/mcp"),
        help="URL path for HTTP transports (default: /mcp)",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport=args.transport,
            host=args.host,
            port=args.port,
            path=args.path,
        )


if __name__ == "__main__":
    main()

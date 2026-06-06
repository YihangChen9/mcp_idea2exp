"""MCP server: idea2exp tools over stdio.

Production registration (any MCP client):

    {
      "mcpServers": {
        "idea2exp": {
          "command": "mcp-idea2exp",
          "env": {
            "IDEA2EXP_BASE_URL": "https://<your-litellm-gateway>/v1",
            "IDEA2EXP_API_KEY": "<key>"
          }
        }
      }
    }
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import pipeline
from .llm import make_complete

mcp = FastMCP(
    "idea2exp",
    instructions=(
        "Turns a Stage-3 research idea (selected hypotheses) into a Stage-5 "
        "experiment design. idea_to_experiment is the one-shot tool; the "
        "stage-wise tools exist for callers that want to review/edit the "
        "methodology in between. verify_codebase_pin checks a pinned repo "
        "for real (ls-remote + ls-tree) — run it before implementing any pin."
    ),
)


@mcp.tool()
def idea_to_experiment(stage3_output: str, topic: str = "", constraints: str = "") -> dict:
    """Full chain: Stage-3 idea -> Stage-4 methodology -> Stage-5 experiment
    plan, with the codebase pin verified against the real repository.

    Args:
        stage3_output: the Stage-3 document (selected hypotheses / idea).
        topic: optional one-line topic context.
        constraints: optional hard constraints (budget, hardware, data access).

    Returns:
        dict with stage4_methodology_md, stage5_experiment_design_md and
        pin_verification (evidence block, or empty when the plan is
        from-scratch).
    """
    return pipeline.idea_to_experiment(make_complete(), stage3_output, topic, constraints)


@mcp.tool()
def idea_to_methodology(stage3_output: str, topic: str = "", constraints: str = "") -> str:
    """Stage-3 idea -> Stage-4 methodology only (review/edit it, then call
    methodology_to_experiment)."""
    return pipeline.idea_to_methodology(make_complete(), stage3_output, topic, constraints)


@mcp.tool()
def methodology_to_experiment(stage4_methodology: str, stage3_output: str = "",
                              constraints: str = "") -> str:
    """Stage-4 methodology -> Stage-5 experiment plan (design matrix, seeds,
    power, locked stats, smoke contract, environment-first execution notes,
    assignments table, codebase pin)."""
    return pipeline.methodology_to_experiment(
        make_complete(), stage4_methodology, stage3_output, constraints
    )


@mcp.tool()
def verify_codebase_pin(repo_url: str, files: list[str] | None = None) -> str:
    """Verify a codebase pin for real: git ls-remote for the live HEAD sha
    and (when files are given) a shallow ls-tree check that every
    adaptation-surface file exists. Paste the returned evidence under the
    plan's §9. A FAIL verdict means the pin is hallucinated — do not
    implement against it."""
    return pipeline.verify_pin(repo_url, files or [])


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="idea2exp MCP server (stdio by default; --http for the "
                    "production Streamable-HTTP deployment, same pattern as "
                    "the aigraph MCP on :8765)",
    )
    parser.add_argument("--http", action="store_true",
                        help="serve Streamable HTTP at http://HOST:PORT/mcp/ instead of stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()

    if args.http:
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        # Pin the endpoint path explicitly — mcp-SDK versions differ in
        # their default (/mcp vs /mcp/ with/without redirect). Production
        # contract: POST http://HOST:PORT/mcp
        mcp.settings.streamable_http_path = "/mcp"
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()

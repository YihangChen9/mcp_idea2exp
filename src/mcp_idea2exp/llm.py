"""Gateway LLM client.

Configuration (env, in priority order):
  IDEA2EXP_BASE_URL / IDEA2EXP_API_KEY   — explicit for this server
  OPENROUTER_BASE_URL / OPENROUTER_API_KEY — shared team gateway fallback
  IDEA2EXP_MODEL — optional; otherwise the first model from the gateway's
                   live ``/models`` listing is used (the production gateway's
                   model set changes over time — never hardcode model names).
  IDEA2EXP_MAX_TOKENS — per-call completion budget (default 8192; the
                   gateway's models are reasoners — too-small budgets get
                   eaten by reasoning and return empty content).
"""
from __future__ import annotations

import os


def _cfg() -> tuple[str, str]:
    base = os.environ.get("IDEA2EXP_BASE_URL") or os.environ.get("OPENROUTER_BASE_URL", "")
    key = os.environ.get("IDEA2EXP_API_KEY") or os.environ.get("OPENROUTER_API_KEY", "")
    if not base or not key:
        raise RuntimeError(
            "LLM gateway not configured: set IDEA2EXP_BASE_URL + IDEA2EXP_API_KEY "
            "(or OPENROUTER_BASE_URL + OPENROUTER_API_KEY)"
        )
    return base, key


def pick_model(client) -> str:
    override = os.environ.get("IDEA2EXP_MODEL")
    if override:
        return override
    models = [m.id for m in client.models.list()]
    if not models:
        raise RuntimeError("gateway returned an empty model list")
    return models[0]


def make_complete():
    """Return ``complete(system, user) -> str`` bound to the gateway."""
    from openai import OpenAI

    base, key = _cfg()
    client = OpenAI(base_url=base, api_key=key)
    model = pick_model(client)
    max_tokens = int(os.environ.get("IDEA2EXP_MAX_TOKENS", "8192"))

    def _once(system: str, user: str) -> str:
        # STREAMING is load-bearing, not an optimisation: the production
        # gateway sits behind a proxy (observed: alibaba-ga) that 504s
        # long idle responses. A multi-kilotoken document on a reasoning
        # model takes minutes; streaming keeps bytes flowing so the LB
        # never times out.
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
            stream=True,
        )
        parts: list[str] = []
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                parts.append(chunk.choices[0].delta.content)
        content = "".join(parts).strip()
        if not content:
            raise RuntimeError(
                f"gateway returned empty content (model={model}) — the model "
                "may have spent the whole budget on reasoning; raise IDEA2EXP_MAX_TOKENS"
            )
        return content

    def complete(system: str, user: str) -> str:
        try:
            return _once(system, user)
        except Exception as first:  # noqa: BLE001 — one retry for transient gateway errors
            import time
            time.sleep(3)
            try:
                return _once(system, user)
            except Exception:
                raise first

    return complete

# mcp_idea2exp

MCP server that turns a **Stage-3 research idea** (selected hypotheses) into a
**Stage-5 experiment design**: pre-registered methodology → executable
experiment plan (design matrix, seeds, power, locked statistics, smoke
contract, environment-first execution notes, assignments table) → **verified**
codebase pin.

Distilled from the AutoResearch pipeline's production runbooks — every rule in
the prompts was paid for by a real pipeline failure (hallucinated pins,
truncation confounds, single-seed claims, per-example inference loops,
unverified environments).

## Tools

| tool | in | out |
|---|---|---|
| `idea_to_experiment` | `stage3_output`, `topic?`, `constraints?` | `{stage4_methodology_md, stage5_experiment_design_md, pin_verification}` |
| `idea_to_methodology` | `stage3_output`, … | `stage4_methodology.md` content |
| `methodology_to_experiment` | `stage4_methodology`, … | `stage5_experiment_design.md` content |
| `verify_codebase_pin` | `repo_url`, `files?` | ls-remote + ls-tree evidence block with PASS/FAIL verdict |

Built-in quality gates (deterministic, not LLM-judged):

- required-section gate on both documents (one bounded retry naming the
  missing sections, then a loud failure — never a silent partial doc);
- codebase pins are verified against the **real repository** (`git ls-remote`
  for the live HEAD, shallow `ls-tree` for every adaptation-surface file);
  a FAIL verdict means the pin is hallucinated;
- prompts enforce: equal generation budgets + truncation diagnostic arm,
  ≥3 seeds for stochastic decoding (greedy single-run needs an explicit
  justification), smoke contract (same code path / same schema / ≤5 min),
  environment verified-or-built **before** any experiment run, batch-first
  execution (no per-item model-call loops).

## Configuration (env)

| var | meaning |
|---|---|
| `IDEA2EXP_BASE_URL` | OpenAI-compatible gateway base URL (falls back to `OPENROUTER_BASE_URL`) |
| `IDEA2EXP_API_KEY` | gateway key (falls back to `OPENROUTER_API_KEY`) |
| `IDEA2EXP_MODEL` | optional; default = first model from the gateway's live `/models` listing (model set changes over time — nothing is hardcoded) |
| `IDEA2EXP_MAX_TOKENS` | completion budget per call (default 8192 — the gateway models are reasoners; small budgets return empty content) |

## Install & run

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e .
IDEA2EXP_BASE_URL=... IDEA2EXP_API_KEY=... .venv/bin/mcp-idea2exp   # stdio MCP server
```

### Register in an MCP client

```json
{
  "mcpServers": {
    "idea2exp": {
      "command": "/path/to/.venv/bin/mcp-idea2exp",
      "env": {
        "IDEA2EXP_BASE_URL": "https://<your-litellm-gateway>/v1",
        "IDEA2EXP_API_KEY": "<key>"
      }
    }
  }
}
```

## Production deployment (same pattern as the aigraph MCP)

This server is the **downstream stage of the aigraph MCP** (`:8765`,
Stage-3 idea reports). Deploy it next to aigraph on the production box,
port **8766**, Streamable HTTP:

```bash
cd ~/mcp_idea2exp
# venv (Tsinghua mirror box):
python3 -m venv .venv && .venv/bin/pip install -e . \
  -i https://pypi.tuna.tsinghua.edu.cn/simple/

# make sure 8766 is free, then run in tmux:
ss -ltnp | grep 8766 && tmux kill-session -t idea2exp 2>/dev/null
tmux new-session -d -s idea2exp \
  "cd ~/mcp_idea2exp && IDEA2EXP_BASE_URL=https://<gateway>/v1 \
   IDEA2EXP_API_KEY=<key> .venv/bin/mcp-idea2exp --http --host 0.0.0.0 --port 8766 \
   2>&1 | tee /tmp/idea2exp_mcp.log"

sleep 3 && ss -ltnp | grep 8766
```

MCP endpoint: `http://<host>:8766/mcp` (Streamable HTTP, same protocol
shape as aigraph). Sanity:

```bash
curl -sL -XPOST http://127.0.0.1:8766/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
# expect 4 tools: idea_to_experiment, idea_to_methodology,
#                 methodology_to_experiment, verify_codebase_pin
```

> Like aigraph's MCP, there is **no auth** — keep it on the trusted box /
> internal network. Unlike aigraph's read tools, every generation tool
> here spends LLM tokens.

### Chaining from aigraph (Stage 3 → Stage 5, end to end)

```python
import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient

async def main():
    c = MultiServerMCPClient({
        "aigraph":  {"url": "http://127.0.0.1:8765/mcp/", "transport": "streamable_http"},
        "idea2exp": {"url": "http://127.0.0.1:8766/mcp", "transport": "streamable_http"},
    })
    tools = {t.name: t for t in await c.get_tools()}
    stage3 = await tools["get_idea_report"].ainvoke({
        "topic": "chain of thought reasoning",
        "run": "arxiv-reasoning-v0.7-540p-thaw1", "k": 8})
    design = await tools["idea_to_experiment"].ainvoke({"stage3_output": stage3})
    print(design["stage5_experiment_design_md"][:400])

asyncio.run(main())
```

Generation wall-clock: ~1–3 min per document on the team gateway
(streamed — streaming is what survives the gateway's proxy timeout;
a non-streamed call of this size 504s).

## Tests

```bash
uv pip install --python .venv/bin/python pytest
.venv/bin/python -m pytest -q     # unit tests are zero-network
```

(`test_verify_pin_fails_unreachable_repo` touches github.com; skip with
`-k "not unreachable"` on an air-gapped CI.)

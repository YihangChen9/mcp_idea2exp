# idea2exp — 测试指引(交付 QA)

生产端点:**`http://8.208.118.99:8768/mcp`**(Streamable HTTP,无尾斜杠,无鉴权 — 内网信任边界)
下面所有序列都已对生产实测通过(2026-06-06)。

## 0. 一分钟看懂协议

MCP over Streamable HTTP 是**有会话**的:
1. `initialize` → 响应头里拿 `mcp-session-id`
2. 发 `notifications/initialized`(带 session 头,期望 202)
3. 之后的 `tools/list` / `tools/call` 都带 `mcp-session-id` 头
4. 响应是 SSE 格式(`data: {...}` 行),取 `data:` 后面的 JSON

## 1. 整段可粘贴的 curl 冒烟(零 LLM 成本,~5 秒)

```bash
B=http://8.208.118.99:8768/mcp
H1='Content-Type: application/json'; H2='Accept: application/json, text/event-stream'

# ① 握手,抓 session
SID=$(curl -s -D - -o /dev/null -XPOST $B -H "$H1" -H "$H2" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"tester","version":"1.0"}}}' \
  | grep -i mcp-session-id | tr -d '\r' | awk '{print $2}')
echo "session: $SID"        # 非空即通过

# ② initialized(期望 202)
curl -s -o /dev/null -w "initialized -> %{http_code}\n" -XPOST $B \
  -H "$H1" -H "$H2" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# ③ 工具列表(期望 4 个)
curl -s -XPOST $B -H "$H1" -H "$H2" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | grep -o '"name":"[a-z_]*"'

# ④ 真调零成本工具:验证一个真实 GitHub pin(期望 VERDICT: PASS)
curl -s -XPOST $B -H "$H1" -H "$H2" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"verify_codebase_pin","arguments":{"repo_url":"https://github.com/pypa/sampleproject","files":["pyproject.toml"]}}}'
```

实测期望输出(④,SSE data 里的 text):

```
## Pin verification — https://github.com/pypa/sampleproject
git ls-remote HEAD: <40位真实sha>
file OK      pyproject.toml
VERDICT: PASS
```

负例(应得 `PIN VERIFICATION FAILED ... unreachable`):
`"repo_url":"https://github.com/this-org-does-not-exist-xx/nope"`

## 2. LLM 生成工具(烧 token,慢)

| 工具 | 入参 | 时长/成本 |
|---|---|---|
| `idea_to_methodology` | `{"stage3_output": "<Stage-3 文档>", "constraints": "..."}` | ~1-2 分钟,数千 token |
| `methodology_to_experiment` | `{"stage4_methodology": "<上一步输出>"}` | ~1-3 分钟 |
| `idea_to_experiment` | `{"stage3_output": "..."}`(一发到底)| ~2-5 分钟,1-2 万 token |

最小可用的 `stage3_output` 测试样例:

```
# Selected Hypotheses
H1: For grade-school math word problems, instructing Qwen2.5-7B-Instruct to
reason step-by-step (chain-of-thought) raises exact-match accuracy by at
least 10 percentage points over direct answering, under equal token budgets.
```

curl 调用(沿用上面的 $SID;注意 JSON 里换行要转义,建议直接用 §3 的 python):

```bash
curl -s --max-time 400 -XPOST $B -H "$H1" -H "$H2" -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"idea_to_methodology","arguments":{"stage3_output":"# Selected Hypotheses\nH1: CoT prompting raises Qwen2.5-7B GSM8K accuracy by >=10pp over direct answering under equal token budgets.","constraints":"one H100 or CPU; <=30 min compute"}}}'
```

**通过标准**:返回的 markdown 含全部 6 个章节(`## 1. Problem` … `## 6. Threats to validity`)——服务端有确定性分节门,缺节会自动重试一次后报错,所以拿到正常返回即合格。

## 3. Python 测试脚本(推荐,免 curl 转义之苦)

```python
# pip install mcp
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://8.208.118.99:8768/mcp"

async def main():
    async with streamablehttp_client(URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])

            # 零成本冒烟
            pin = await s.call_tool("verify_codebase_pin", {
                "repo_url": "https://github.com/pypa/sampleproject",
                "files": ["pyproject.toml"]})
            print(pin.content[0].text)

            # LLM 全链(可注释掉;~2-5 分钟)
            # out = await s.call_tool("idea_to_experiment", {"stage3_output": "H1: ..."})
            # print(out.content[0].text[:500])

asyncio.run(main())
```

## 4. 上游串联(完整 Stage 3 → 5)

aigraph MCP 在同机 `:8765`,其 `get_idea_report` 的输出就是这里的 `stage3_output`:

```python
stage3 = await aigraph_session.call_tool("get_idea_report", {
    "topic": "chain of thought reasoning",
    "run": "arxiv-reasoning-v0.7-540p-thaw1", "k": 8})
design = await idea2exp_session.call_tool("idea_to_experiment",
    {"stage3_output": stage3.content[0].text})
```

## 5. 故障速查

| 症状 | 原因 |
|---|---|
| 404 Not Found | 路径用了 `/mcp/`(带尾斜杠)或打错端口(8766 是 memento_mcp,8767 是 paper-writer)|
| 400 Bad Request: Missing session ID | `tools/*` 没带 `mcp-session-id` 头(先 initialize)|
| 421 | 旧版本服务(< fd05e3a);让运维 `git pull` 重启 |
| LLM 工具报 empty content | 提高服务端 `IDEA2EXP_MAX_TOKENS`(reasoner 预算被思考吃光)|
| 服务挂了 | 运维:`tmux attach -t idea2exp`,日志 `/tmp/idea2exp_mcp.log`,重启见 README §Production deployment |

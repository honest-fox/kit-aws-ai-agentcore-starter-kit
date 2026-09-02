# Extension guide: connecting MCP servers

Kit ships with **no** MCP servers connected. That's deliberate: an MCP
connection sends parts of your conversations to whatever server you
connect, so it's opt-in, not default.

A ready-made client lives in `app/kit/mcp_client/client.py`.

## Connect a server

1. Edit `app/kit/mcp_client/client.py` and set the endpoint:

```python
MCP_ENDPOINT = "https://your-mcp-server.example/mcp"

def get_streamable_http_mcp_client() -> MCPClient:
    return MCPClient(lambda: streamablehttp_client(MCP_ENDPOINT))
```

For servers requiring auth, pass headers:

```python
streamablehttp_client(MCP_ENDPOINT,
                      headers={"Authorization": f"Bearer {token}"})
```

Keep secrets out of code — read the token from an environment variable
and inject it via the runtime's `envVars` in `agentcore/agentcore.json`
(or better, AWS Secrets Manager).

2. Register the client in `app/kit/main.py`:

```python
from mcp_client.client import get_streamable_http_mcp_client
mcp_clients = [get_streamable_http_mcp_client()]
```

3. Redeploy: `agentcore deploy`

The server's tools appear in the agent's tool list automatically.

## Before you connect anything

- Read the server's data handling policy — your prompts flow through it.
- Prefer servers you host yourself or that your organisation controls.
- The agent's IAM role does not gate MCP traffic; network egress is the
  boundary. For strict environments, deploy Kit with `networkMode: VPC`
  and control egress with security groups.

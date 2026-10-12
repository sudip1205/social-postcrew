# Security

Postcrew handles a LinkedIn access token that can post on your behalf. Its design:

- Secrets live only in `workspace/secrets.json`, created with mode 600 and git-ignored. The Studio can set
  secrets but never sends them back to the browser.
- The Studio binds to 127.0.0.1, rejects requests whose Host is not localhost (DNS rebinding), and requires a
  custom header plus a localhost Origin for every state-changing request (CSRF).
- OAuth uses a random, single-use `state` that expires after 15 minutes.
- Agents run through `claude -p --restricted --strict-mcp-config`: no shell or code tools, no MCP servers,
  your Claude settings and hooks are ignored, and each agent gets only the tools it needs (the Researcher:
  WebSearch). Web content is treated as data in every prompt.
- File downloads from the Studio are confined to the workspace's `media/` and `runs/` folders.

Please report vulnerabilities privately through GitHub's "Report a vulnerability" (Security tab) rather than
a public issue.

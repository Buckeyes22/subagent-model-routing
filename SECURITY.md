# Security Policy

## Supported Versions

Only the latest commit on the `main` branch is supported.

## Reporting a Vulnerability

Report vulnerabilities via **GitHub private vulnerability reporting**:

1. Open the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Include a description, reproduction steps, and impact.

Do not open public issues for undisclosed vulnerabilities. Best-effort acknowledgment within 7 days (solo maintainer).

## Scope

The shims intentionally execute AI-directed commands. The default `SUBAGENT_MODEL_ROUTING_UNRESTRICTED=1` setting bypasses child-CLI sandbox prompts; this is documented, designed behavior — not a vulnerability.

In-scope: command/argument injection through shim parameters, ledger-write path traversal, hook parsing flaws that could execute content, installer download/verification weaknesses.

Out of scope: risks from the documented opt-in unrestricted execution model; social engineering.

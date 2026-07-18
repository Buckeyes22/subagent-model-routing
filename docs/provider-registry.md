# Provider registry

`config/provider-registry.json` is the machine-readable source of truth for provider binaries, native-host ownership, prompt delivery, default/model selectors, effort controls, diagnostic capabilities, known models, OpenCode route families, and reference wiring. Kimi is a dedicated provider backed by Kimi Code; it declares a read-only configuration probe and explicitly declares no per-invocation effort control. OpenCode remains the generic pass-through provider.

It does not generate or replace evidence-derived prompting prose. Canonical prompting guidance remains under `prompting/`, and each plugin retains a self-contained `references/model-prompting.md` bundle.

## Validation and generation

Run:

```bash
python3 tools/validate_registry.py
python3 tools/sync_routes.py --check
```

Semantic validation supplements `schemas/provider-registry.schema.json`. It checks required fields, identifier shapes, repository-contained paths, reference anchors, alias uniqueness, adapter/registry parity, reciprocal native ownership, valid defaults, and the explicit absence of any Mythos-specific route or card.

`tools/sync_routes.py` writes two deterministic files into each plugin package:

- `references/routes.generated.md`
- `references/provider-registry.generated.json`

Claude's generated catalog omits the native Claude provider, Codex's omits native Codex, and Copilot's includes all five transports. Unknown provider-supported model IDs remain pass-through; the catalog is guidance, not a live availability claim.

## Adding a fixed model

Add the registry entry and its substantive prompting reference/capability card together. Every model entry requires:

- display name and aliases;
- allowed effort values;
- canonical prompting reference;
- package-local runtime reference anchor;
- capability-card path;
- provenance classification.

Then regenerate with `python3 tools/sync_routes.py` and run the full test suite. Discovery backends live in `runtime/model_routing/discovery.py`; keep executable discovery behavior out of the declarative registry and preserve unknown-model pass-through where configured.

## Binary candidates

Adapters implement the actual executable lookup behavior. `binaryCandidates` documents the ordered candidates, while `binaryOverrideEnv` names the additive override. Candidate strings such as `$HOME/.opencode/bin/opencode` are expanded by the relevant adapter rather than interpreted by a shell; provider commands are never assembled with `shell=True`.

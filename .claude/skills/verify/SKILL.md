---
name: verify
description: Run radagent's CI checks locally before committing or opening a PR — Python compile/import, client tsc + vite build, Rust cargo check, Terraform fmt/validate. Use after any code change, and only run the parts for folders you touched.
---

# Verifying a change

CI (`.github/workflows/main.yml`) only compiles; there are no unit tests. Run the jobs for what changed
(`git diff --name-only staging...`), from the repo root:

**agent/**
```sh
cd agent && uv sync --locked \
  && uv run --locked python -m compileall -q src \
  && uv run --locked python -c "import radagent.main, radagent.server.app, radagent.repl, radagent.tools"
```

**client/src** (TypeScript)
```sh
cd client && bun install --frozen-lockfile && bun run build
```

**client/src-tauri** (Rust; skip if only `src/` changed). Needs WebKitGTK on Linux:
```sh
sudo apt-get install -y --no-install-recommends libwebkit2gtk-4.1-dev librsvg2-dev   # once
cd client/src-tauri && cargo check --locked --all-targets
```

**infra/**
```sh
terraform fmt -check -recursive infra
for dir in infra infra/bootstrap; do terraform -chdir="$dir" init -backend=false -input=false && terraform -chdir="$dir" validate; done
```

**scripts/*.sh**: `bash -n scripts/<file>.sh`.

A dependency change must update the lockfile with the tool (`uv add` / `uv lock`, `bun add`, `cargo`), never by
hand.

## Behavior

Compiling doesn't show the feature works. Write a throwaway script in the scratchpad (not the repo) that:

- calls the tool function or `RadAgent`-free helpers directly, with `unittest.mock.patch` on the network call
  (`urlopen`, the API client) and a realistic response;
- or drives `radagent.server.core.dispatch` with a fake `Client` collecting `send()` events, model stubbed;
- uses moto for S3/Secrets Manager.

Bedrock and third-party accounts aren't reachable from a dev container. Say in the PR exactly what was and wasn't
tested.

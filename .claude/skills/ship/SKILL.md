---
name: ship
description: Commit, push and open a pull request for radagent following the repo's conventions (branch off staging, PR into staging, conventional commit subject, What/How/Testing PR body). Use when asked to commit, open a PR, or wrap up a feature.
---

# Shipping a change

1. **Branch** off the latest `staging`: `git fetch origin staging && git checkout -b feat/<thing> origin/staging`
   (`fix/`, `ci/`, `docs/` as fits). Never commit to `main` or `staging` directly.
2. **Verify** with skill `verify` for the folders touched.
3. **Commit**: subject `feat: <what the user gets>` / `fix: <what was wrong, now right>` / `fix(infra): …` /
   `ci: …` / `docs: …`, lower case, no trailing period, under ~72 chars. Body only when the why isn't obvious
   (cause, constraint, trade-off), wrapped at ~72. One commit per feature is the norm; agent, client and README
   changes go together.
4. **Push**: `git push -u origin <branch>`.
5. **PR into `staging`** (never `main`; `staging` → `main` is merged separately and deploys). Title = the commit
   subject. Body, in this shape:

   ```markdown
   ## What
   What the user can do now / what was broken, in a few sentences.

   ## How it works
   - **`path/to/file.py`**: what changed there and why. One bullet per meaningful piece; tables for tool suites.
   - Safety: trust gate / secrets handling, if any.
   - Infra / scripts: new variables, secrets, IAM, or "No infra change is needed".

   ## Testing
   - CI's own checks pass (the ones you ran).
   - Scripted checks with mocks: what was covered.
   - **Not tested:** what couldn't be (real Bedrock calls, real devices, real OAuth), and why.
   ```

   For a fix, lead with `## Cause` and `## Fix` instead of What/How. Keep it factual; no marketing.

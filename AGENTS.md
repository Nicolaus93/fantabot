# Repository instructions for coding agents

## Branches

- Every change must be made on a dedicated, task-specific branch based on `main`.
- Never commit or push changes directly to `main`.
- Related follow-up work for an open pull request belongs on that pull request's branch; unrelated work needs a new branch.
- Preserve unrelated local changes and never include them in commits without explicit approval.

## Versioning

- Every change must include a Semantic Versioning increase, including documentation, tests, CI, tooling, and configuration changes.
- Use `pyproject.toml` as the version source of truth and keep `uv.lock` synchronized.
- Choose the bump intentionally:
  - **major**: breaking changes to supported behavior or interfaces.
  - **minor**: backward-compatible features.
  - **patch**: backward-compatible fixes, maintenance, documentation, tests, CI, and tooling.
- Run `uv version --bump major|minor|patch --no-sync` with the chosen bump (for example, `uv version --bump patch --no-sync`).
- Commit both `pyproject.toml` and `uv.lock` with the change. A follow-up commit that changes repository content must also bump the version; do not bump solely for a merge commit.
- Explain the chosen bump in the pull request. Do not create release tags or deploy unless requested.

## Validation

- Run the relevant tests and `uv run --locked prek run --all-files` before committing.
- Verify `uv lock --check` and `git diff --check` pass.
- Report any checks that could not be run; do not claim unverified success.

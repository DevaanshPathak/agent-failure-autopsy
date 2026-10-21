# Working rules

## Commit and push to main after every piece of finished work

Whenever a feature ships, a task is finished, or something works that didn't before (a passing test, a working endpoint, a recorded trace, a fixed bug), commit it and push it to `main` right away. Don't wait to be asked, and don't batch several finished things into one commit.

- Push straight to `main`. No feature branches or PRs on this project.
- Before pushing, run `git pull --rebase origin main`, since both of us push to `main`. If the rebase conflicts, resolve it and keep both sides' work. Never force-push.
- One commit per finished unit. Message format: a Conventional Commit, plus the task id when there is one, e.g. `feat(api): P2-A1 TinyFish client` or `fix(web): P4-B1 red step scroll`.
- Once `make lint test` exists (Phase 1), run it before committing. If it fails, fix it first, or say why it's being committed anyway.
- Never commit `prd/` (gitignored, kept local) or any `.env` file. Check `git status` before every commit.

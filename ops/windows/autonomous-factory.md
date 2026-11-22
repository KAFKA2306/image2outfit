# Bounded autonomous factory

`task factory:schedule` installs the Windows task `Image2Outfit Factory Daily`. It runs the tracked batch once per day at 03:00 local time and calls the existing `task batch:run` path. The three requests run serially and resume from their canonical checkpoints.

The task runs only for the current logged-in user, after 15 minutes of idle time, and on AC power. It waits up to two hours for idle time and has a four-hour execution limit. Missed runs start when Windows becomes available to that user. Each source commit gets at most three failed attempts. A successful execution or a visual-review stop is cached for that commit; a new committed revision allows the queue to resume.

Before manufacturing, the runner requires a named branch and a clean worktree. If a run changes tracked product evidence, the next scheduled run waits until that evidence is reviewed and committed. Runtime checkpoints and the automation state/log stay under the existing Git-ignored `.image2outfit/` directory.

This automation manufactures and resumes candidates only. It does not record visual acceptance, mark a product `COMPLETE`, evaluate release eligibility, publish, or replace a last-good product. Direct visual review remains a required stop. Inspect the local run state at `.image2outfit/autonomous-factory/state.json` and the latest output at `.image2outfit/autonomous-factory/latest-run.log`; use `task batch:status UV_ENV=Assets/_Local/uv-env-task-v311` for the canonical per-product scheduler summary on this machine.

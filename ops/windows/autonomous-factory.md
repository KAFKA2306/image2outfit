# Bounded autonomous factory

`task factory:schedule` installs the Windows task `Image2Outfit Factory Daily`. It runs the tracked batch once per day at 03:00 local time and calls the existing `task batch:run` path. The three requests run serially and resume from their canonical checkpoints.

The task runs for the current logged-in user (`InteractiveToken`, limited privilege) with a four-hour execution limit, `StartWhenAvailable=true`, `WakeToRun=true`, `RunOnlyIfIdle=false`, `DisallowStartIfOnBatteries=false`, and `StopIfGoingOnBatteries=false`. Do not require Windows OS idle for this daily trigger: background agent or workstation activity around 03:00–05:00 otherwise causes Windows Task Scheduler to silently drop the trigger after `IdleWaitTimeout`. Instead, concurrency and foreground/worktree safety are enforced inside `tools/run_autonomous_factory.ps1` via an exclusive file lock (`run.lock`) and clean-worktree check.

Each source commit gets at most three failed attempts. A successful execution or a visual-review stop is cached for that commit; a new committed revision allows the queue to resume. Before manufacturing, the runner requires a named branch and a clean worktree. If a run changes tracked product evidence or another workline has uncommitted changes, the scheduled run records `SKIPPED_DIRTY_WORKTREE` and exits `0` without manufacturing. Runtime checkpoints and the automation state/log stay under the existing Git-ignored `.image2outfit/` directory.

Verify the entrypoint without starting manufacturing via:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File tools/run_autonomous_factory.ps1 -DryRun
```

This automation manufactures and resumes candidates only. It does not record visual acceptance, mark a product `COMPLETE`, evaluate release eligibility, publish, or replace a last-good product. Direct visual review remains a required stop. Inspect the local run state at `.image2outfit/autonomous-factory/state.json` and the latest output at `.image2outfit/autonomous-factory/latest-run.log`; use `task batch:status UV_ENV=Assets/_Local/uv-env-task-v311` for the canonical per-product scheduler summary on this machine.

<!-- workstream: replace-with-product-slug-or-repository-scope -->
<!-- Optional explicit replacement: supersedes: #123 -->
<!-- Branch names must start with agent/, fix/, feat/, work/, release/, ops/, chore/, ci/, or dependabot/. -->
<!-- Product paths are authoritative: all PRs touching one Assets/GenWorks/<slug> or config/products/<slug> share one product workstream. -->
<!-- An older PR closes only after a successor passes Release policy tests or explicitly declares supersedes: #N. -->

## Scope

- 

## Validation

- [ ] The branch continues the latest canonical checkpoint instead of restarting the same work in parallel.
- [ ] Required repository, asset, render, Unity, or runtime checks have been executed for this change.
- [ ] The PR contains the intended canonical state, not only generated transport artifacts.
- [ ] `Release policy tests` passes for the exact head commit before this PR replaces another workstream PR.

## Completion

- [ ] Merge into `main` only after required gates pass.
- [ ] Confirm the work branch is deleted after merge or closure.

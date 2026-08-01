# Former Published snapshots

Files previously stored under the repository-root `Published/` directory predate the image2outfit v2 release gate. They are retained under `Assets/GenWorks/Legacy/Snapshots/` only as historical candidates and must not be represented as customer-ready releases.

A valid release is created only by `.github/workflows/release-self-hosted.yml` after `Artifacts/<job-id>/audit.json` records `decision: GO` and the release ZIP is bound to the reviewed candidate manifest hash.

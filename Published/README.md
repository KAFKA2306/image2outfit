# Legacy snapshots only

Files under `Published/` predate the image2outfit v2 release gate. They are retained only as historical candidates and must not be represented as customer-ready releases.

A valid release is created only by `.github/workflows/release-self-hosted.yml` after `Artifacts/<job-id>/audit.json` records `decision: GO` and the release ZIP is bound to the reviewed candidate manifest hash.

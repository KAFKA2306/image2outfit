# Legacy snapshots

This directory contains historical image2outfit snapshots moved from the repository-root `Published/` directory so Unity can import and inspect them under `Assets/` without keeping a Unity-visible folder named `Published`.

- Existing file blobs and committed Unity `.meta` files are preserved.
- These files are retained for reproducibility, visual inspection, and hash verification.
- They are not current customer releases and must not be promoted automatically.
- New products belong in `Assets/GenWorks/Products/<product-slug>/` and require the full release evidence gates.

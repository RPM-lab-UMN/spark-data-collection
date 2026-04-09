# Viewer Integration

## Purpose

This page explains the current local viewer design, what it owns, and where the
remaining design debt still lives.


## Core Decision

The viewer is supported as a local review tool, not as a networked service
surface.

Current supported contract:

- the viewer server runs on the same machine as the operator console
- the browser opens on that same machine
- the base URL defaults to an account-local localhost port
- `PIPELINE_VIEWER_BASE_URL` can override the host and port when needed

This local-only assumption removed a lot of confusion around hostname choice and
stale environment-specific settings.

Current runtime assumptions are also account-local:

- the viewer repo lives at the sibling path `../lerobot-dataset-visualizer`
- `bun` lives under `~/.bun/bin/bun`
- the viewer must already have a production build from
  `data_pipeline/setup_viewer_env.sh`


## Why `Open Viewer` Owns Startup

The operator should not need to manually manage a separate viewer lifecycle for
normal review.

That is why `Open Viewer` owns:

- resolving the current published dataset target
- ensuring the local dataset server is running
- starting or restarting the viewer server if needed
- opening the resolved episode URL

The setup script prepares the toolchain and production build. Runtime startup is
still owned by the operator console.

In the current backend, `Open Viewer` also checks that the selected dataset's
`meta/info.json` is actually reachable before treating the viewer as ready.


## Why The Viewer Is Separate From Conversion

The viewer inspects published datasets.
It does not define them.

That boundary matters because:

- conversion should succeed without the viewer running
- the viewer should not become a hidden dependency of raw recording
- published datasets remain filesystem artifacts, not viewer-owned objects


## Current Local Dataset Serving Model

The current local viewer integration uses two explicit local servers:

- a generic viewer server from `lerobot-dataset-visualizer`
- a read-only dataset server owned by `spark-data-collection`

The dataset server exposes published datasets directly from:

- `spark-data-collection/published/<dataset_id>`

through the URL shape the viewer expects:

- `/datasets/local/<dataset_id>/resolve/main/...`

And the backend starts the viewer with:

- `DATASET_URL=<dataset_base_url>/datasets`

This keeps the dataset truth in one place and removes the hidden mirror state
that previously lived inside the viewer repo.

By default, each Unix account gets its own local viewer port and its own local
dataset-server port. That prevents the cross-account failure mode where two
users on the same machine silently reuse the same `localhost` service.


## Remaining Design Debt

The viewer path is cleaner now, but some real design debt remains:

- the contract still spans two sibling repos
- the frontend toolchain still introduces a separate per-account setup surface
- the viewer is still adapted from a Hugging Face-oriented app rather than
  designed natively for this local pipeline


## Design Rule

Any future viewer work should preserve these operator-facing truths:

- `Open Viewer` is the one-click review entrypoint
- the operator should not think about dataset-serving plumbing
- published datasets remain the source artifact being reviewed

If the implementation changes later, those user-facing properties should stay.

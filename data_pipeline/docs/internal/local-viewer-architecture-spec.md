# Local Viewer Architecture Spec

## Problem

The old local viewer path relied on hidden compatibility state inside the
viewer repo:

- local datasets lived in `published/<dataset_id>/`
- the viewer expected Hugging Face style paths under:
  - `/datasets/local/<dataset_id>/resolve/main/...`
- a symlink tree under `lerobot-dataset-visualizer/public/datasets/local/...`
  made the viewer believe those paths existed locally

This caused repeated failures:

- browser-side fallback to Hugging Face when dataset base handling was wrong
- 404s for newly created datasets until a matching symlink existed
- stale viewer processes that encoded an old dataset/episode target
- machine-global `localhost:3000` collisions across Unix accounts
- the worst failure mode: opening the wrong dataset successfully when two
  accounts used the same published folder name

## Design Goals

- `published/` is the only source of truth for local datasets
- no symlink or mirror state inside `lerobot-dataset-visualizer`
- no dataset-specific viewer process state
- no cross-account reuse of the same localhost port by default
- `Open Viewer` remains the one-click entrypoint
- the viewer app stays generic and reusable

## New Process Model

There are two local servers:

1. `dataset_server`
   - owned by `spark-data-collection`
   - serves read-only files directly from `published/`

2. `viewer_server`
   - owned by `lerobot-dataset-visualizer`
   - serves the UI only
   - does not encode a dataset choice in its startup command

## URL Contract

The dataset server exposes:

- `/healthz`
- `/datasets/local/<dataset_id>/resolve/main/<path>`

Examples:

- `/datasets/local/my_dataset/resolve/main/meta/info.json`
- `/datasets/local/my_dataset/resolve/main/meta/episodes/chunk-000/file-000.parquet`
- `/datasets/local/my_dataset/resolve/main/videos/observation.images.world.scene_1/chunk-000/file-000.mp4`

The viewer uses:

- `DATASET_URL=<dataset_base_url>/datasets`

The browser route remains:

- `<viewer_base_url>/local/<dataset_id>/episode_<n>`

## Port Model

Both servers default to account-local localhost ports derived from the Unix UID.

This is a core part of the design, not a patch:

- two accounts on the same machine must not fight over the same viewer port
- `Open Viewer` must never silently reuse another account's local server

Overrides remain possible through environment variables:

- `PIPELINE_VIEWER_BASE_URL`
- `PIPELINE_DATASET_BASE_URL`

## Backend Responsibilities

`Open Viewer` must:

1. resolve the target dataset from `published/<dataset_id>/meta/info.json`
2. compute the latest episode index from that metadata
3. ensure the dataset server is running
4. ensure the viewer server is running
5. verify that the dataset info URL is reachable through the dataset server
6. open `<viewer_base_url>/local/<dataset_id>/episode_<n>`

`Open Viewer` must not:

- create symlinks in the viewer repo
- treat “port reachable” as equivalent to “correct dataset loaded”
- restart the viewer when only the dataset target changes

## Dataset Server Requirements

The dataset server must:

- serve files read-only from `published/`
- prevent path traversal outside the selected dataset root
- return clean 404s for missing datasets or files
- support `GET`, `HEAD`, and `OPTIONS`
- send permissive CORS headers for the local browser-to-dataset-server fetch path
- support byte-range requests for video playback
- avoid directory listings

## What Gets Deleted

The old integration pieces should disappear:

- `lerobot-dataset-visualizer/public/datasets/local/...` as a required runtime contract
- viewer dataset mount creation logic in `operator_console_backend.py`
- dataset-specific viewer startup using:
  - `REPO_ID`
  - `EPISODES`

## Expected Result

After this rewrite:

- local dataset truth lives only in `published/`
- viewer startup is generic
- switching datasets no longer requires restarting the viewer
- cross-account collisions are prevented by design
- wrong-dataset success becomes much harder than a clean error

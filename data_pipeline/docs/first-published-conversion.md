# First Published Conversion

This page starts after [First Raw Demo](./first-raw-demo.md) is already complete.

It applies to both:

- `shared_account` after [Lab Machine Quick Start](./lab-machine-quick-start.md)
- a lab member using their own account after [Personal Account Setup](./personal-account-setup.md)

The goal is simple:

- convert one recorded episode into a published dataset successfully
- verify the expected published files exist
- stop before local viewer debugging


## Before You Start

Make sure these are already true:

- at least one episode was recorded successfully
- the `Recorder` card ended at:
  - `Last recording complete`
- the latest raw episode exists under:
  - `raw_episodes/<episode_id>/`
- the repo-local `.venv` is ready
- the conversion profile and published folder you want to use are known

If those are not true yet, go back to:

- [First Raw Demo](./first-raw-demo.md)

Normal workflow note:

- on `shared_account`, the repo-local `.venv` should already be provisioned
- on a personal account, that setup should already be covered by [Personal Account Setup](./personal-account-setup.md)


## 1. Confirm Native Depth Bounds

Native depth publication requires one approved dataset-wide range in meters.
The checked-in profile intentionally does not choose that range yet.

Analyze a representative recording before setting it:

```bash
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
python data_pipeline/convert_episode_bag_to_lerobot.py \
  raw_episodes/<episode_id> \
  --analyze-depth-only \
  --analysis-output /tmp/depth-analysis.json
```

Once approved, add both values to the conversion profile:

```yaml
depth_encoding:
  depth_min_m: <approved_minimum>
  depth_max_m: <approved_maximum>
```

The same published folder must always use the same depth bounds. Conversion
refuses to publish depth while either value is missing.


## 2. Choose The Conversion Profile

In the operator console, set `Conversion Profile`.

For the normal workflow, the default is:

- `data_pipeline/configs/multisensor_20hz.yaml`

Use `Browse` if you want a different conversion YAML.

Important rule:

- if you change the conversion profile, use a new `Published Folder`

That keeps one published folder aligned with one conversion contract.


## 3. Choose The Published Dataset Target

In the operator console, set `Published Folder`.

Choose one dataset folder. It can live in the repository or on another drive.
The `Browse` dialog includes shortcuts to `/mnt` and `/mnt/SSDdata`, and you can
type an absolute path into the `Published Folder` field. Use a dataset-specific
folder such as `/mnt/SSDdata/srinivas/pick_place_v1`, rather than the whole SSD.

Valid examples:

- `spark_multisensor_lightning_v1`
- `published/spark_multisensor_lightning_v1`
- `/mnt/SSDdata/srinivas/spark_multisensor_lightning_v1`
- `published/experiments/spark_multisensor_lightning_v1`

Invalid examples:

- `published/`
- `/`
- a regular file

Why this exists:

- one published folder should represent one coherent dataset contract
- the converter appends episodes into that dataset root
- the target must therefore be one specific dataset folder

A short name still defaults to `published/<name>`. Absolute paths are saved as
absolute paths. `Open Viewer` uses the selected location for dataset files and
native-depth video; changing drives does not require rebuilding the viewer.


## 4. Check The Converter Card

After a successful raw recording, the `Converter` card should show:

- `Latest recording ready to convert`

If it does not:

- make sure the latest raw recording actually completed
- make sure the raw episode folder still exists
- make sure the `Conversion Profile` field is set
- make sure the `Published Folder` field is set


## 5. Start Conversion

Click:

- `Convert`

on the `Converter` card.

What should happen:

- the card should switch to:
  - `Converter running`
- the latest episode id remains the source episode for this conversion
- the verified archive is used automatically when available; otherwise the
  capture bag is used
- the published dataset target becomes the destination dataset

You do **not** need to launch `convert_episode_bag_to_lerobot.py` manually in the normal workflow.


## 6. Wait For Completion

When conversion succeeds, the `Converter` card should settle to:

- `Latest dataset ready for review`

The artifacts section should now show:

- `Episode`
  - the source raw episode id
- `Dataset`
  - the published folder name you just converted into

If conversion fails, the card will show:

- `Converter failed with exit code ...`

In that case, inspect the console output before retrying.


## 7. Verify The Published Dataset On Disk

From the repository root:

```bash
cd ~/spark-workspace/spark-data-collection
ls -la published/<dataset_id>
```

At minimum, a successful conversion should produce:

- `data/`
- `meta/`
- `videos/` when image fields are present

If depth was published, its native LeRobot video lives under `videos/` and its
feature metadata lives in `meta/info.json`.


## 8. Check The Episode-Specific Metadata

The converter also writes episode-level metadata under:

- `published/<dataset_id>/meta/spark_conversion/<episode_id>/`

That directory should contain:

- `conversion_summary.json`
- `diagnostics.json`
- `effective_profile.yaml`

The published dataset also keeps a copy of the episode source snapshot under:

- `published/<dataset_id>/meta/spark_source/<episode_id>/episode_manifest.json`
- `published/<dataset_id>/meta/spark_source/<episode_id>/notes.md`
- `published/<dataset_id>/meta/spark_source/<episode_id>/archive_manifest.json`
  when conversion used the archive

That copied source snapshot is the provenance record for the published episode.


`diagnostics.json` includes `native_depth_validation`, with the recorded scale,
invalid-zero fraction, encoder clipping fractions, and reconstruction-error
percentiles.


## 9. Optional Quick Sanity Check

You can inspect the published dataset metadata quickly with:

```bash
python - <<'PY'
import json
from pathlib import Path
dataset_root = Path("published") / "<dataset_id>"
info = json.loads((dataset_root / "meta" / "info.json").read_text())
print("fps =", info["fps"])
print("total_episodes =", info["total_episodes"])
print("total_frames =", info["total_frames"])
PY
```

And the conversion summary for the newest episode:

```bash
python - <<'PY'
import json
from pathlib import Path
dataset_root = Path("published") / "<dataset_id>"
artifact_root = dataset_root / "meta" / "spark_conversion"
latest = sorted(artifact_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[0]
print((latest / "conversion_summary.json").read_text())
PY
```


## What Success Looks Like

Your first published conversion is successful when:

- the `Converter` card ends at `Latest dataset ready for review`
- the expected dataset root exists under `published/<dataset_id>/`
- the episode-level conversion artifacts exist under:
  - `meta/spark_conversion/<episode_id>/`
- the copied source manifest and notes exist under:
  - `meta/spark_source/<episode_id>/`

At that point, the recorded-to-published conversion path is working.


## Next Step

Once one episode converts successfully, move on to:

- [First Viewer Review](./first-viewer-review.md)

That should stay separate from the conversion page.

"""Tests for model-service/entrypoint.sh with fake aws, hf and vllm commands.

The fake aws keeps its "bucket" in a local folder, so the tests can check
what the script uploads and how it reacts to a cache that is only half there.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "model-service" / "entrypoint.sh"

FAKE_AWS = """#!/usr/bin/env bash
set -eu
echo "aws $*" >> "$FAKE_DIR/calls.log"
[ "$1" = "s3" ] || exit 1
mode="$2"; src="$3"; dst="$4"
exclude=0
case "$*" in *'--exclude .complete'*) exclude=1 ;; esac
if [ "$mode" = "cp" ]; then
  case "$dst" in
    s3://*) mkdir -p "$FAKE_S3"; cp "$src" "$FAKE_S3/$(basename "$dst")" ;;
    *) [ -f "$FAKE_S3/$(basename "$src")" ] || exit 1; cp "$FAKE_S3/$(basename "$src")" "$dst" ;;
  esac
  exit 0
fi
case "$src" in
  s3://*)
    [ -d "$FAKE_S3" ] || exit 0
    if [ -n "${FAKE_SYNC_FAIL:-}" ]; then
      # Copies the marker first like a real sync would (dot files sort first), then dies.
      [ "$exclude" = 1 ] || cp "$FAKE_S3/.complete" "$dst/.complete" 2> /dev/null || true
      cp "$FAKE_S3/config.json" "$dst/config.json"
      exit 1
    fi
    for f in "$FAKE_S3"/* "$FAKE_S3"/.[!.]*; do
      [ -e "$f" ] || continue
      [ "$exclude" = 1 ] && [ "$(basename "$f")" = ".complete" ] && continue
      cp -r "$f" "$dst/"
    done
    ;;
  *) mkdir -p "$FAKE_S3"; cp -r "$src/." "$FAKE_S3/" ;;
esac
"""

FAKE_HF = """#!/usr/bin/env bash
set -eu
echo "hf $*" >> "$FAKE_DIR/calls.log"
dir=""
while [ $# -gt 0 ]; do
  [ "$1" = "--local-dir" ] && dir="$2"
  shift
done
mkdir -p "$dir"
echo '{}' > "$dir/config.json"
echo weights > "$dir/model.safetensors"
"""

FAKE_VLLM = """#!/usr/bin/env bash
echo "vllm $*" >> "$FAKE_DIR/calls.log"
"""


@pytest.fixture
def box(tmp_path):
    fake = tmp_path / "fake"
    fake.mkdir()
    for name, body in (("aws", FAKE_AWS), ("hf", FAKE_HF), ("vllm", FAKE_VLLM)):
        (fake / name).write_text(body)
        (fake / name).chmod(0o755)
    env = dict(os.environ)
    env.update(
        PATH=f"{fake}:{env['PATH']}",
        FAKE_DIR=str(fake),
        FAKE_S3=str(tmp_path / "s3"),
        MODEL_DIR=str(tmp_path / "models"),
        WEIGHTS_BUCKET="bucket",
        API_KEY="key",
        HF_TOKEN="token",
    )
    return env, tmp_path


def start(env):
    result = subprocess.run(
        ["bash", str(SCRIPT)], env=env, text=True, capture_output=True
    )
    calls = Path(env["FAKE_DIR"], "calls.log").read_text().splitlines()
    return result, calls


def test_first_run_downloads_uploads_and_marks_the_cache(box):
    env, tmp = box
    result, calls = start(env)
    assert result.returncode == 0, result.stderr
    assert any(c.startswith("hf download") for c in calls)
    assert (tmp / "s3" / ".complete").exists()
    assert (tmp / "s3" / "config.json").exists()
    assert (tmp / "models" / ".complete").exists()
    assert calls[-1].startswith("vllm serve")


def test_complete_cache_skips_the_download(box):
    env, tmp = box
    s3 = tmp / "s3"
    s3.mkdir()
    for name in ("config.json", "model.safetensors", ".complete"):
        (s3 / name).write_text("x")
    result, calls = start(env)
    assert result.returncode == 0, result.stderr
    assert not any(c.startswith("hf ") for c in calls)
    assert (tmp / "models" / "model.safetensors").exists()
    assert calls[-1].startswith("vllm serve")


def test_half_finished_cache_is_not_trusted(box):
    env, tmp = box
    s3 = tmp / "s3"
    s3.mkdir()
    (s3 / "config.json").write_text("{}")
    result, calls = start(env)
    assert result.returncode == 0, result.stderr
    assert any(c.startswith("hf download") for c in calls)
    assert (s3 / "model.safetensors").exists()
    assert (s3 / ".complete").exists()


def test_local_weights_with_marker_need_no_network(box):
    env, tmp = box
    models = tmp / "models"
    models.mkdir()
    (models / ".complete").write_text("")
    result, calls = start(env)
    assert result.returncode == 0, result.stderr
    assert calls == [c for c in calls if c.startswith("vllm")]


def test_a_failed_download_stops_before_vllm(box):
    env, tmp = box
    Path(env["FAKE_DIR"], "hf").write_text("#!/usr/bin/env bash\nexit 1\n")
    result, calls = start(env)
    assert result.returncode != 0
    assert not any(c.startswith("vllm") for c in calls)
    assert not (tmp / "s3" / ".complete").exists()


def test_sync_that_dies_halfway_leaves_no_marker(box):
    env, tmp = box
    s3 = tmp / "s3"
    s3.mkdir()
    for name in ("config.json", "model.safetensors", ".complete"):
        (s3 / name).write_text("x")
    env["FAKE_SYNC_FAIL"] = "1"
    result, calls = start(env)
    assert result.returncode == 0, result.stderr
    assert "did not finish" in result.stdout
    assert any(c.startswith("hf download") for c in calls)


def test_empty_api_key_stops_everything(box):
    env, _ = box
    env["API_KEY"] = ""
    result = subprocess.run(["bash", str(SCRIPT)], env=env, text=True, capture_output=True)
    assert result.returncode != 0
    assert "API_KEY" in result.stderr
    assert not Path(env["FAKE_DIR"], "calls.log").exists()

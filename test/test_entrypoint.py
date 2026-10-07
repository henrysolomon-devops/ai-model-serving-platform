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
[ "$1 $2" = "s3 sync" ] || [ "$1 $2" = "s3 cp" ] || exit 1
src="$3"; dst="$4"
if [ "$2" = "cp" ]; then
  case "$dst" in
    s3://*) mkdir -p "$FAKE_S3"; cp "$src" "$FAKE_S3/$(basename "$dst")" ;;
  esac
  exit 0
fi
case "$src" in
  s3://*) [ -d "$FAKE_S3" ] && cp -r "$FAKE_S3/." "$dst/" || true ;;
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

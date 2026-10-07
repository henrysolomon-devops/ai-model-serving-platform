"""Tests for the scripts in scripts/: canary-plan, canary-state, promote-plan
and finish-plan.

gh is replaced by a small fake script. git is real, with a bare repository
standing in for GitHub.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "scripts" / "canary-plan.sh"
STATE = ROOT / "scripts" / "canary-state.sh"
PROMOTE = ROOT / "scripts" / "promote-plan.sh"
FINISH = ROOT / "scripts" / "finish-plan.sh"

STAGING_TAG = "a" * 40
PROD_TAG = "b" * 40

FAKE_GH = r"""#!/usr/bin/env bash
set -eu
echo "gh $*" >> "$FAKE_DIR/gh.log"
case "$1 $2" in
  "api repos/"*)
    context=$(printf '%s' "$*" | sed -n 's/.*context == "\([^"]*\)".*/\1/p')
    state=$(sed -n "s/^${context}=//p" "$FAKE_DIR/statuses" | head -1)
    echo "${state:-none}"
    ;;
  "pr create")
    echo "https://github.com/example/repo/pull/7"
    ;;
  "pr merge")
    git --git-dir="$FAKE_REMOTE" update-ref refs/heads/main "refs/heads/$3"
    ;;
  "pr view")
    echo "${FAKE_PR_STATE:-MERGED}"
    ;;
  "pr list")
    cat "$FAKE_DIR/open_prs" 2> /dev/null || true
    ;;
  "pr close")
    echo "closed $3" >> "$FAKE_DIR/closed.log"
    ;;
  *)
    echo "unexpected gh call: $*" >&2
    exit 1
    ;;
esac
"""


def run(cmd, cwd, env, check=False):
    return subprocess.run(
        cmd, cwd=cwd, env=env, text=True, capture_output=True, check=check
    )


def values(tag):
    return f'model:\n  image:\n    tag: "{tag}"\nchat:\n  image:\n    tag: "{tag}"\n'


@pytest.fixture
def plan_env(tmp_path):
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    gh = fake_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    (fake_dir / "statuses").write_text("staging-smoke-test=success\n")

    files = {}
    for name, tag in (("staging", STAGING_TAG), ("production", PROD_TAG)):
        files[name] = tmp_path / f"{name}.yaml"
        files[name].write_text(values(tag))
    files["canary"] = tmp_path / "canary.yaml"
    set_canary(files["canary"], "off", 0, "")

    env = dict(os.environ)
    env.update(
        PATH=f"{fake_dir}:{env['PATH']}",
        FAKE_DIR=str(fake_dir),
        GITHUB_REPOSITORY="example/repo",
        STAGING_VALUES=str(files["staging"]),
        PRODUCTION_VALUES=str(files["production"]),
        CANARY_VALUES=str(files["canary"]),
    )
    return env, files, fake_dir


def set_canary(path, mode, weight, tag):
    run(["bash", str(STATE), "write", mode, str(weight), tag], ROOT,
        dict(os.environ, CANARY_VALUES=str(path)), check=True)


def set_statuses(fake_dir, **states):
    lines = ["staging-smoke-test=success"]
    lines += [f"{k.replace('_', '-')}={v}" for k, v in states.items()]
    (fake_dir / "statuses").write_text("\n".join(lines) + "\n")


def plan(env, weight):
    return run(["bash", str(PLAN), str(weight)], ROOT, env)


def test_first_step_wakes_the_canary(plan_env):
    env, _, _ = plan_env
    result = plan(env, 10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"tag={STAGING_TAG}", "wake=true"]


def test_weight_must_be_a_known_step(plan_env):
    env, _, _ = plan_env
    result = plan(env, 30)
    assert result.returncode == 1
    assert "10, 50 or 100" in result.stderr


def test_nothing_to_release(plan_env):
    env, files, _ = plan_env
    files["production"].write_text(values(STAGING_TAG))
    result = plan(env, 10)
    assert result.returncode == 1
    assert "nothing to release" in result.stderr


def test_staging_with_two_tags_is_refused(plan_env):
    env, files, _ = plan_env
    files["staging"].write_text(
        f'model:\n  image:\n    tag: "{STAGING_TAG}"\nchat:\n  image:\n    tag: "{PROD_TAG}"\n'
    )
    result = plan(env, 10)
    assert result.returncode == 1
    assert "exactly one" in result.stderr


def test_smoke_test_must_have_passed(plan_env):
    env, _, fake_dir = plan_env
    (fake_dir / "statuses").write_text("staging-smoke-test=failure\n")
    result = plan(env, 10)
    assert result.returncode == 1
    assert "smoke test" in result.stderr


def test_missing_smoke_test_status(plan_env):
    env, _, fake_dir = plan_env
    (fake_dir / "statuses").write_text("")
    assert plan(env, 10).returncode == 1


def test_other_release_still_running(plan_env):
    env, files, _ = plan_env
    set_canary(files["canary"], "on", 10, PROD_TAG)
    result = plan(env, 10)
    assert result.returncode == 1
    assert "still running" in result.stderr


def test_later_step_needs_a_running_canary(plan_env):
    env, _, fake_dir = plan_env
    set_statuses(fake_dir, canary_weight_10="success")
    result = plan(env, 50)
    assert result.returncode == 1
    assert "not running" in result.stderr


def test_step_50_needs_step_10_approved(plan_env):
    env, files, _ = plan_env
    set_canary(files["canary"], "on", 10, STAGING_TAG)
    result = plan(env, 50)
    assert result.returncode == 1
    assert "canary-weight-10" in result.stderr


def test_step_50_with_running_canary(plan_env):
    env, files, fake_dir = plan_env
    set_canary(files["canary"], "on", 10, STAGING_TAG)
    set_statuses(fake_dir, canary_weight_10="success")
    result = plan(env, 50)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"tag={STAGING_TAG}", "wake=false"]


def test_step_100_needs_step_50_approved(plan_env):
    env, files, fake_dir = plan_env
    set_canary(files["canary"], "on", 50, STAGING_TAG)
    set_statuses(fake_dir, canary_weight_10="success")
    result = plan(env, 100)
    assert result.returncode == 1
    assert "canary-weight-50" in result.stderr


def test_going_back_is_refused(plan_env):
    env, files, fake_dir = plan_env
    set_canary(files["canary"], "on", 50, STAGING_TAG)
    set_statuses(fake_dir, canary_weight_10="success", canary_weight_50="success")
    result = plan(env, 10)
    assert result.returncode == 1
    assert "already approved" in result.stderr


def test_repeating_a_failed_step_is_allowed(plan_env):
    env, files, fake_dir = plan_env
    set_canary(files["canary"], "off", 0, "")
    set_statuses(fake_dir, canary_weight_10="failure")
    assert plan(env, 10).returncode == 0


# canary-state.sh


def test_write_on(tmp_path):
    target = tmp_path / "canary.yaml"
    env = dict(os.environ, CANARY_VALUES=str(target))
    run(["bash", str(STATE), "write", "on", "50", "abc123"], ROOT, env, check=True)
    assert target.read_text() == (
        "# The state of the current release. Only the canary workflows edit this file.\n"
        "canary:\n  enabled: true\n  weight: 50\n  image:\n    tag: \"abc123\"\n"
    )


def test_write_off(tmp_path):
    target = tmp_path / "canary.yaml"
    env = dict(os.environ, CANARY_VALUES=str(target))
    run(["bash", str(STATE), "write", "off", "0", ""], ROOT, env, check=True)
    text = target.read_text()
    assert "enabled: false" in text
    assert "weight: 0" in text
    assert 'tag: ""' in text


@pytest.mark.parametrize(
    "args",
    [
        ["on", "101", "abc"],
        ["on", "ten", "abc"],
        ["on", "10", ""],
        ["maybe", "10", "abc"],
    ],
)
def test_write_rejects_bad_input(tmp_path, args):
    env = dict(os.environ, CANARY_VALUES=str(tmp_path / "canary.yaml"))
    result = run(["bash", str(STATE), "write", *args], ROOT, env)
    assert result.returncode == 1
    assert not (tmp_path / "canary.yaml").exists()


def test_usage_errors(tmp_path):
    env = dict(os.environ)
    assert run(["bash", str(STATE)], ROOT, env).returncode == 2
    assert run(["bash", str(STATE), "write", "on"], ROOT, env).returncode == 2
    assert run(["bash", str(STATE), "pr", "only-one"], ROOT, env).returncode == 2


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    gh = fake_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)

    run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], tmp_path, os.environ, check=True)
    run(["git", "clone", "-q", str(remote), str(work)], tmp_path, os.environ, check=True)
    env = dict(os.environ)
    env.update(
        PATH=f"{fake_dir}:{env['PATH']}",
        FAKE_DIR=str(fake_dir),
        FAKE_REMOTE=str(remote),
        CANARY_VALUES="canary.yaml",
        PR_WAIT_SECONDS="3",
        PR_POLL_SECONDS="1",
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.com",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.com",
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    run(["bash", str(STATE), "write", "off", "0", ""], work, env, check=True)
    run(["git", "add", "-A"], work, env, check=True)
    run(["git", "commit", "-q", "-m", "start"], work, env, check=True)
    run(["git", "push", "-q", "origin", "main"], work, env, check=True)
    return work, remote, fake_dir, env


def test_pr_flow(repo):
    work, remote, fake_dir, env = repo
    run(["bash", str(STATE), "write", "on", "0", "abc"], work, env, check=True)
    result = run(["bash", str(STATE), "pr", "bot/canary-start", "Start the canary"], work, env)
    assert result.returncode == 0, result.stderr + result.stdout

    log = (fake_dir / "gh.log").read_text()
    assert "pr create --base main --head bot/canary-start" in log
    assert "pr merge bot/canary-start --auto --squash" in log
    assert "pr=7" in Path(env["GITHUB_OUTPUT"]).read_text()

    branch = run(["git", "branch", "--show-current"], work, env).stdout.strip()
    assert branch == "main"
    assert "enabled: true" in (work / "canary.yaml").read_text()
    remote_file = run(["git", "--git-dir", str(remote), "show", "main:canary.yaml"], work, env)
    assert "enabled: true" in remote_file.stdout


def test_pr_skipped_when_nothing_changed(repo):
    work, _, fake_dir, env = repo
    result = run(["bash", str(STATE), "pr", "bot/nothing", "No change"], work, env)
    assert result.returncode == 0
    assert "no pull request needed" in result.stdout
    assert not (fake_dir / "gh.log").exists()


def test_pr_that_is_never_merged_times_out(repo):
    work, _, _, env = repo
    env["FAKE_PR_STATE"] = "OPEN"
    run(["bash", str(STATE), "write", "on", "0", "abc"], work, env, check=True)
    result = run(["bash", str(STATE), "pr", "bot/slow", "Slow"], work, env)
    assert result.returncode == 1
    assert "not merged in time" in result.stdout


def test_pr_closed_without_merge(repo):
    work, _, _, env = repo
    env["FAKE_PR_STATE"] = "CLOSED"
    run(["bash", str(STATE), "write", "on", "0", "abc"], work, env, check=True)
    result = run(["bash", str(STATE), "pr", "bot/closed", "Closed"], work, env)
    assert result.returncode == 1
    assert "closed without being merged" in result.stdout


# promote-plan.sh


def promote(env):
    return run(["bash", str(PROMOTE)], ROOT, env)


def ready_to_promote(plan_env):
    env, files, fake_dir = plan_env
    set_canary(files["canary"], "on", 100, STAGING_TAG)
    set_statuses(fake_dir, canary_weight_100="success")
    return env, files, fake_dir


def test_promote_when_the_canary_is_done(plan_env):
    env, _, _ = ready_to_promote(plan_env)
    result = promote(env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f"tag={STAGING_TAG}", f"old={PROD_TAG}"]


def test_promote_needs_the_100_percent_approval(plan_env):
    env, _, fake_dir = ready_to_promote(plan_env)
    set_statuses(fake_dir, canary_weight_50="success")
    result = promote(env)
    assert result.returncode == 1
    assert "100 percent" in result.stderr


def test_promote_refuses_a_failed_approval(plan_env):
    env, _, fake_dir = ready_to_promote(plan_env)
    set_statuses(fake_dir, canary_weight_100="failure")
    assert promote(env).returncode == 1


@pytest.mark.parametrize(
    "mode,weight,tag",
    [("on", 50, STAGING_TAG), ("on", 100, PROD_TAG), ("off", 0, "")],
)
def test_promote_needs_the_canary_live_at_100(plan_env, mode, weight, tag):
    env, files, _ = ready_to_promote(plan_env)
    set_canary(files["canary"], mode, weight, tag)
    result = promote(env)
    assert result.returncode == 1
    assert "not at 100 percent" in result.stderr


def test_promote_nothing_to_do(plan_env):
    env, files, _ = ready_to_promote(plan_env)
    files["production"].write_text(values(STAGING_TAG))
    result = promote(env)
    assert result.returncode == 1
    assert "nothing to promote" in result.stderr


def test_promote_staging_with_two_tags(plan_env):
    env, files, _ = ready_to_promote(plan_env)
    files["staging"].write_text(
        f'model:\n  image:\n    tag: "{STAGING_TAG}"\nchat:\n  image:\n    tag: "{PROD_TAG}"\n'
    )
    assert promote(env).returncode == 1


# finish-plan.sh


def finish(env):
    return run(["bash", str(FINISH)], ROOT, env)


def test_finish_after_production_moved(plan_env):
    env, files, _ = plan_env
    files["production"].write_text(values(STAGING_TAG))
    set_canary(files["canary"], "on", 100, STAGING_TAG)
    result = finish(env)
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["act=true", f"tag={STAGING_TAG}"]


def test_finish_with_no_canary(plan_env):
    env, _, _ = plan_env
    result = finish(env)
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == "act=false"
    assert "No canary" in result.stderr


def test_finish_when_production_is_a_different_tag(plan_env):
    env, files, _ = plan_env
    set_canary(files["canary"], "on", 10, STAGING_TAG)
    result = finish(env)
    assert result.returncode == 0
    assert result.stdout.splitlines()[0] == "act=false"
    assert "not the end of a release" in result.stderr


# close-open and running


def test_close_open_closes_every_listed_pr(plan_env):
    env, _, fake_dir = plan_env
    (fake_dir / "open_prs").write_text("11\n12\n")
    result = run(["bash", str(STATE), "close-open"], ROOT, env)
    assert result.returncode == 0, result.stderr
    assert (fake_dir / "closed.log").read_text().splitlines() == ["closed 11", "closed 12"]


def test_close_open_with_nothing_open(plan_env):
    env, _, fake_dir = plan_env
    result = run(["bash", str(STATE), "close-open"], ROOT, env)
    assert result.returncode == 0
    assert not (fake_dir / "closed.log").exists()


def test_running_is_true_only_for_the_live_tag(plan_env):
    env, files, _ = plan_env
    set_canary(files["canary"], "on", 10, STAGING_TAG)
    assert run(["bash", str(STATE), "running", STAGING_TAG], ROOT, env).returncode == 0
    assert run(["bash", str(STATE), "running", PROD_TAG], ROOT, env).returncode == 1
    set_canary(files["canary"], "off", 0, "")
    assert run(["bash", str(STATE), "running", STAGING_TAG], ROOT, env).returncode == 1
    assert run(["bash", str(STATE), "running", ""], ROOT, env).returncode == 1

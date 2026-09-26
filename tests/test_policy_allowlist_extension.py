"""The allowlist extension: additive, explicit, and never a way to rebind."""
import importlib
import json

import pytest


def _reload_policy(monkeypatch, path=None):
    from smadp.sandbox import policy as mod
    if path is None:
        monkeypatch.delenv(mod.EXTRA_APPROVED_IMAGES_ENV, raising=False)
    else:
        monkeypatch.setenv(mod.EXTRA_APPROVED_IMAGES_ENV, str(path))
    return importlib.reload(mod)


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def test_without_the_env_var_the_baseline_is_the_whole_allowlist(monkeypatch):
    mod = _reload_policy(monkeypatch)
    assert mod.APPROVED_IMAGES == mod._BASELINE_APPROVED_IMAGES


def test_an_extension_adds_entries_without_touching_the_baseline(monkeypatch, tmp_path):
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({"crucible-test-agent": DIGEST_A}))

    with pytest.warns(UserWarning, match="allowlist extended"):
        mod = _reload_policy(monkeypatch, extra)

    assert mod.validate_image_digest(DIGEST_A) is True
    # The committed baseline is untouched: this widened one process, not the
    # set every host validates against.
    assert "crucible-test-agent" not in mod._BASELINE_APPROVED_IMAGES
    assert set(mod._BASELINE_APPROVED_IMAGES) < set(mod.APPROVED_IMAGES)


def test_an_extension_may_not_rebind_a_baseline_slug(monkeypatch, tmp_path):
    """Silently rebinding a slug that ships with the package would let an
    extension file redirect a known agent to an image of its choosing, which is
    the substitution the allowlist exists to stop."""
    mod = _reload_policy(monkeypatch)
    existing = next(iter(mod._BASELINE_APPROVED_IMAGES))

    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({existing: DIGEST_B}))

    with pytest.raises(mod.PolicyError, match="may not rebind|redefines"):
        _reload_policy(monkeypatch, extra)


def test_an_unpinned_entry_is_refused(monkeypatch, tmp_path):
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({"loose": "some-image:latest"}))
    from smadp.sandbox import policy as mod
    with pytest.raises(mod.PolicyError, match="not a pinned digest"):
        _reload_policy(monkeypatch, extra)


def test_a_missing_or_malformed_file_fails_loudly(monkeypatch, tmp_path):
    from smadp.sandbox import policy as mod
    with pytest.raises(mod.PolicyError, match="could not be read"):
        _reload_policy(monkeypatch, tmp_path / "absent.json")

    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(mod.PolicyError, match="not valid JSON"):
        _reload_policy(monkeypatch, bad)


def test_the_extension_is_cleaned_up_between_tests(monkeypatch):
    mod = _reload_policy(monkeypatch)
    assert mod.APPROVED_IMAGES == mod._BASELINE_APPROVED_IMAGES

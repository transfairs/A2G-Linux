# SPDX-License-Identifier: GPL-3.0-only
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import a2extras  # noqa: E402


def test_refresh_icon_cache_runs_the_tool(tmp_path):
    with mock.patch("shutil.which", return_value="/usr/bin/gtk-update-icon-cache"), mock.patch(
        "subprocess.run", return_value=mock.Mock(returncode=0)
    ) as run:
        a2extras.refresh_icon_cache(str(tmp_path))
    run.assert_called_once_with(["/usr/bin/gtk-update-icon-cache", "-q", "-t", "-f", str(tmp_path)], check=False)


def test_refresh_icon_cache_marks_the_cache_stale_without_the_tool(tmp_path):
    cache = tmp_path / "icon-theme.cache"
    cache.write_bytes(b"")
    os.utime(cache, (1000, 1000))
    os.utime(tmp_path, (1000, 1000))
    with mock.patch("shutil.which", return_value=None):
        a2extras.refresh_icon_cache(str(tmp_path))
    assert os.stat(tmp_path).st_mtime > os.stat(cache).st_mtime


def test_refresh_icon_cache_without_folder(tmp_path):
    with mock.patch("subprocess.run") as run:
        a2extras.refresh_icon_cache(str(tmp_path / "missing"))
    run.assert_not_called()


def test_every_installer_uses_a_known_slug():
    import glob
    import re

    root = os.path.join(os.path.dirname(__file__), "..")
    slugs = set()
    for f in glob.glob(os.path.join(root, "lutris.net", "*.yml")):
        slugs.update(re.findall(r"a2extras\.py\" --slug (\S+)", open(f).read()))
    assert slugs == {"anstoss-2-cd", "anstoss-2-2007", "anstoss-2-gog"}
    assert slugs <= set(a2extras.SUFFIXES)

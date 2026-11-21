# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""THIRD-PARTY-NOTICES.txt, which tools/notices.py writes into every bundle.

The real thing is checked where it is made: the spec writes it, and check_bundle asks every copy
of the bundle for it. These hold the rules that decide what goes in, against small distributions
made on disk for the purpose, so a change to the rules fails here rather than in a release.
"""

from __future__ import annotations

import hashlib
import subprocess
from importlib import metadata
from pathlib import Path

import pytest

from tools import notices

_REPO = Path(__file__).resolve().parent.parent


def _dist(site: Path, name: str, version: str, *, modules=(), licences=None,
          expression: str | None = "MIT") -> metadata.Distribution:
    """A distribution installed into ``site`` the way an installer leaves one: files, METADATA and
    a RECORD naming them, which is what the notices read ownership from."""
    info = site / f"{name.replace('-', '_')}-{version}.dist-info"
    (info / "licenses").mkdir(parents=True)
    record = []
    for module in modules:
        path = site / module
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# code\n", encoding="utf-8")
        record.append(module)
    for filename, text in (licences or {}).items():
        (info / "licenses" / filename).write_text(text, encoding="utf-8")
        record.append(f"{info.name}/licenses/{filename}")
    meta = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if expression:
        meta.append(f"License-Expression: {expression}")
    (info / "METADATA").write_text("\n".join(meta) + "\n", encoding="utf-8")
    record += [f"{info.name}/METADATA", f"{info.name}/RECORD"]
    (info / "RECORD").write_text("".join(f"{entry},,\n" for entry in record), encoding="utf-8")
    return metadata.PathDistribution(info)


def _render(found, **kwargs):
    kwargs.setdefault("app_version", "0.1.0")
    kwargs.setdefault("qt_version", "6.12.0")
    return notices.render(found, **kwargs)


def test_a_package_that_ships_is_credited_with_its_licence_and_its_source(tmp_path):
    site = tmp_path / "site"
    dist = _dist(site, "demo-pkg", "1.2.3", modules=["demo_pkg/__init__.py"],
                 licences={"LICENSE": "Copyright 2026 Demo\n\nPermission is hereby granted."})
    entries = [("demo_pkg", str(site / "demo_pkg" / "__init__.py"), "PYMODULE")]

    found = notices.inventory(entries, [dist], python=[])
    text = _render(found)

    assert list(found.distributions) == ["demo-pkg"]
    assert "demo-pkg 1.2.3" in text
    assert "Licencia: MIT" in text
    assert "https://pypi.org/project/demo-pkg/1.2.3/" in text
    assert "Copyright 2026 Demo" in text


def test_a_package_that_does_not_ship_is_not_credited(tmp_path):
    """The analysis decides, not what happens to be installed: pytest is in every dev venv and in
    no bundle."""
    site = tmp_path / "site"
    shipped = _dist(site, "shipped", "1.0", modules=["shipped.py"], licences={"LICENSE": "a"})
    _dist(site, "only-installed", "1.0", modules=["only_installed.py"], licences={"LICENSE": "b"})
    others = [shipped, metadata.PathDistribution(site / "only_installed-1.0.dist-info")]
    entries = [("shipped", str(site / "shipped.py"), "PYMODULE")]

    found = notices.inventory(entries, others, python=[])

    assert list(found.distributions) == ["shipped"]


def test_qt_comes_with_the_lgpl_the_gpl_and_directions_to_its_source(tmp_path):
    """What LGPL-3.0 section 4 asks of a program that ships Qt: a notice that it is used, the LGPL
    and the GPL it is written on, and, since the libraries go out as object code, clear directions
    to the source of those exact versions. The wheels carry no licence file, so none of that can
    come from them."""
    site = tmp_path / "site"
    qt = _dist(site, "PySide6_Essentials", "6.12.0", modules=["PySide6/Qt6Core.dll"],
               expression=None)
    entries = [("PySide6/Qt6Core.dll", str(site / "PySide6" / "Qt6Core.dll"), "BINARY")]

    found = notices.inventory(entries, [qt], python=[])
    text = _render(found)

    assert notices.missing_licences(found) == []
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text
    assert "                    GNU GENERAL PUBLIC LICENSE" in text
    assert "https://download.qt.io/archive/qt/6.12/6.12.0/single/" in text
    assert "PySide6-6.12.0-src" in text
    assert "The Qt Company" in text
    assert "_internal" in text and "PySide6" in text, "the notice has to say where the libraries are"


def test_a_package_without_a_licence_text_is_found_before_it_ships(tmp_path):
    """A hole in the notices with a known fix, so the build stops on it rather than writing a
    file that quietly leaves somebody out."""
    site = tmp_path / "site"
    bare = _dist(site, "bare", "0.1", modules=["bare.py"])
    entries = [("bare", str(site / "bare.py"), "PYMODULE")]

    found = notices.inventory(entries, [bare], python=[])

    assert notices.missing_licences(found) == ["bare"]


def test_the_same_licence_text_is_written_once(tmp_path):
    """The Apache licence arrives a dozen times word for word. Printing every copy buries the texts
    that differ, which are the ones carrying somebody's name."""
    site = tmp_path / "site"
    apache = "Apache License\nVersion 2.0, January 2004\n" + "terms\n" * 50
    one = _dist(site, "one", "1.0", modules=["one.py"], licences={"LICENSE": apache})
    two = _dist(site, "two", "1.0", modules=["two.py"], licences={"LICENSE": apache + "\n\n"})
    entries = [("one", str(site / "one.py"), "PYMODULE"), ("two", str(site / "two.py"), "PYMODULE")]

    text = _render(notices.inventory(entries, [one, two], python=[]))

    assert text.count("Version 2.0, January 2004") == 1
    assert "el mismo texto que en one" in text


def test_the_apps_own_files_and_the_builds_are_nobody_elses(tmp_path):
    src = tmp_path / "src"
    work = tmp_path / "build"
    for path in (src / "firmauy_desktop" / "app.py", work / "localpycs" / "struct.pyc"):
        path.parent.mkdir(parents=True)
        path.write_text("x", encoding="utf-8")
    entries = [("firmauy_desktop.app", str(src / "firmauy_desktop" / "app.py"), "PYMODULE"),
               ("struct", str(work / "localpycs" / "struct.pyc"), "PYMODULE")]

    found = notices.inventory(entries, [], own=[src], built=[work], python=[])

    assert found.distributions == {} and found.foreign == [] and found.python is False


def test_python_itself_is_credited_with_the_interpreters_own_licence(tmp_path):
    prefix = tmp_path / "python"
    (prefix / "lib").mkdir(parents=True)
    (prefix / "lib" / "json.py").write_text("x", encoding="utf-8")
    entries = [("json", str(prefix / "lib" / "json.py"), "PYMODULE")]

    found = notices.inventory(entries, [], python=[prefix])
    text = _render(found, python_version="3.14.9", python_licence="PSF LICENSE AGREEMENT text")

    assert found.python is True
    assert "Python 3.14.9" in text
    assert "https://www.python.org/ftp/python/3.14.9/" in text
    assert "PSF LICENSE AGREEMENT text" in text


def test_a_file_nobody_claims_is_listed_rather_than_dropped(tmp_path):
    """A library of the build machine that cannot be identified still ships, so the notices say
    so in so many words instead of acting as if it were not there."""
    stray = tmp_path / "usr" / "lib" / "libdemo.so.1"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"\x7fELF")
    entries = [("libdemo.so.1", str(stray), "BINARY")]

    found = notices.inventory(entries, [], python=[])
    text = _render(found, unidentified=found.foreign)

    assert found.foreign == [str(stray)]
    assert "Archivos sin identificar" in text and str(stray) in text


def test_a_debian_library_is_found_under_either_name_the_usr_merge_gives_it(tmp_path, monkeypatch):
    """Since the /usr merge /lib is /usr/lib, and dpkg still records whichever of the two each
    package was built with. Asking under one name only would leave half the libraries of an
    Ubuntu runner unidentified."""
    doc = tmp_path / "doc"
    (doc / "zlib1g").mkdir(parents=True)
    (doc / "zlib1g" / "copyright").write_text("zlib licence text", encoding="utf-8")
    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        if command[1] == "-S" and command[2] == "/lib/x86_64-linux-gnu/libz.so.1":
            return subprocess.CompletedProcess(command, 0, "zlib1g:amd64: /lib/x86_64-linux-gnu/libz.so.1\n", "")
        if command[1] == "-W":
            return subprocess.CompletedProcess(command, 0, "1:1.2.11.dfsg-2ubuntu9.2\tzlib\t1:1.2.11.dfsg-2ubuntu9.2", "")
        return subprocess.CompletedProcess(command, 1, "", "no path found")

    monkeypatch.setattr(notices.shutil, "which", lambda name: "/usr/bin/" + name)
    packages, unidentified = notices.debian_packages(
        ["/usr/lib/x86_64-linux-gnu/libz.so.1"], fake_run, doc=doc)

    assert unidentified == []
    assert packages["zlib1g"]["source"] == "zlib"
    assert packages["zlib1g"]["copyright"] == "zlib licence text"
    assert packages["zlib1g"]["files"] == ["libz.so.1"]
    text = _render(notices.Inventory(), system=packages, distro="ubuntu")
    assert "https://launchpad.net/ubuntu/+source/zlib/1:1.2.11.dfsg-2ubuntu9.2" in text
    assert "zlib licence text" in text


def test_the_binary_packages_of_one_source_are_one_entry():
    """libxcb reaches an Ubuntu bundle as five binary packages with one copyright file between
    them. Five entries saying the same thing is the index lying about how many projects there
    are."""
    same = "libxcb copyright text"
    system = {
        name: {"version": "1.14-3ubuntu3", "source": "libxcb", "source_version": "1.14-3ubuntu3",
               "copyright": same, "files": [f"{name}.so"]}
        for name in ("libxcb1", "libxcb-render0", "libxcb-shm0")
    }

    text = _render(notices.Inventory(), system=system, distro="ubuntu")

    assert text.count("libxcb 1.14-3ubuntu3 (sistema)") == 1
    assert text.count("libxcb 1.14-3ubuntu3, del sistema donde se construyó") == 1
    assert text.count(same) == 1
    assert "Paquetes: libxcb-render0, libxcb-shm0, libxcb1" in text


@pytest.mark.parametrize("platform, dpkg, fatal", [
    ("win32", None, True),          # nothing outside Python and its packages belongs there
    ("linux", "/usr/bin/dpkg-query", True),   # what CI builds on: dpkg names every library
    ("linux", None, False),         # a developer's Arch, say: nothing ships from it
])
def test_a_stranger_in_the_bundle_stops_the_build_where_owners_can_be_named(platform, dpkg, fatal):
    """The first Windows build that wrote these notices carried a Java 8 JDK's C runtime and
    MySQL's OpenSSL, because PATH led there. A warning in a log is how that went unseen."""
    assert notices.can_identify_everything(platform, lambda name: dpkg) is fatal


def test_without_dpkg_the_libraries_stay_unidentified(monkeypatch):
    monkeypatch.setattr(notices.shutil, "which", lambda name: None)

    packages, unidentified = notices.debian_packages(["/usr/lib/libz.so.1"])

    assert packages == {} and unidentified == ["/usr/lib/libz.so.1"]


def test_the_gnu_texts_are_the_fsfs_word_for_word():
    """The LGPL and the GPL may only be copied verbatim, and a tidy-up of whitespace in an editor
    would stop that being true without anything else noticing. These are the digests of
    https://www.gnu.org/licenses/lgpl-3.0.txt and gpl-3.0.txt.

    Taken with LF line endings, because a Windows checkout may hand them over with CRLF, which
    changes no word of either.
    """
    expected = {
        "LGPL-3.0.txt": "e3a994d82e644b03a792a930f574002658412f62407f5fee083f2555c5f23118",
        "GPL-3.0.txt": "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
    }

    actual = {name: hashlib.sha256((notices.LICENSES / name).read_bytes()
                                   .replace(b"\r\n", b"\n")).hexdigest()
              for name in expected}

    assert actual == expected
    assert set(notices.QT_TEXTS) == set(expected)


def test_the_notices_have_one_name_everywhere_it_is_written():
    """Written by the spec, asked for by both check_bundle scripts, pointed at by Acerca de, the
    README and both LEEMEs. A rename that reached only some of them is a check passing on a file
    nobody is told about, or an About box pointing at nothing."""
    from firmauy_desktop import dialogs

    assert dialogs.NOTICES_FILE == notices.FILENAME
    spec = (_REPO / "packaging" / "firmauy-desktop.spec").read_text(encoding="utf-8")
    assert "notices.FILENAME" in spec
    for relative in ("packaging/check_bundle.sh", "packaging/windows/check_bundle.ps1",
                     "packaging/linux/make_release.sh", "packaging/windows/make_release.ps1",
                     "README.md"):
        text = (_REPO / relative).read_text(encoding="utf-8-sig")
        assert notices.FILENAME in text, f"{relative} does not name {notices.FILENAME}"


def _shipped_closure() -> dict:
    """Every distribution the app's requirements reach, extras included, on this platform."""
    requirements = pytest.importorskip("packaging.requirements")
    reached: dict = {}
    pending = [("firmauy-desktop", frozenset())]
    while pending:
        name, extras = pending.pop()
        key = notices.normalize(name)
        if key in reached and extras <= reached[key]:
            continue
        reached[key] = reached.get(key, frozenset()) | extras
        dist = metadata.distribution(name)
        for line in dist.requires or ():
            requirement = requirements.Requirement(line)
            environments = [{"extra": extra} for extra in (reached[key] or {""})]
            if requirement.marker is None or any(requirement.marker.evaluate(environment)
                                                 for environment in environments):
                pending.append((requirement.name, frozenset(requirement.extras)))
    reached.pop(notices.SELF, None)
    return reached


def test_every_package_the_app_can_ship_brings_its_licence_text():
    """The build stops on a package without one, and this finds it first, in the test jobs, on
    both platforms. Windows matters on its own here: a few requirements exist only there."""
    missing = [name for name in _shipped_closure()
               if name not in notices.QT_DISTRIBUTIONS and name not in notices.SUPPLIED
               and not notices.licence_files(metadata.distribution(name))]
    always = [name for name in notices.ALWAYS
              if not notices.licence_files(metadata.distribution(name))]

    assert missing == [] and always == []

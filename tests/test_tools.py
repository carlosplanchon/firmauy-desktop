# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the development tools, and for the line between them and the app.

``tools/`` holds the storybook, the synthetic data and the card guard. None of it may ever reach
a user: the storybook drives screens by poking their internals, and the samples are fake results
that would be a lie if they showed up in the real app.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from firmauy_desktop import backend
from tools import cardguard, samples

_SRC = Path(__file__).resolve().parent.parent / "src" / "firmauy_desktop"


def test_the_package_never_imports_tools():
    """The only thing keeping the storybook out of a build is that nothing imports it.

    `packages.find where = ["src"]` means setuptools cannot package tools/ at all, and
    PyInstaller only follows imports from the entry point. Both guarantees rest on this.
    """
    offenders = []
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name == "tools" or name.startswith("tools.") for name in names):
                offenders.append(f"{path.relative_to(_SRC)}:{node.lineno}")

    assert offenders == []


def test_tools_lives_outside_the_packaged_tree():
    assert (_SRC.parent.parent / "tools").is_dir()
    assert not (_SRC / "tools").exists()


def test_the_core_is_only_ever_reached_through_its_public_api():
    """firmauy.api is the contract: dataclasses and typed errors, documented and versioned. Any
    other firmauy module is an internal this app would be pinning itself to by accident.

    The rule held everywhere except one import of SignAs from firmauy.constants, because the type
    of an argument of three public functions was not re-exported. firmauy 1.15.0 re-exports it, the
    exception went away, and the rule became something a test can hold instead of a habit.

    `firmauy_desktop` is not `firmauy`, which is why the match is on the module name and not on a
    prefix of the string.
    """
    offenders = []
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if (name == "firmauy" or name.startswith("firmauy.")) and name != "firmauy.api":
                    offenders.append(f"{path.relative_to(_SRC)}:{node.lineno} imports {name}")

    assert offenders == [], "the core has a public API, and these reach past it"


# --- the card guard ---------------------------------------------------------

def test_the_guard_covers_every_view_module():
    """A screen added without its entry here would reach the card from a test, which is the
    exact accident this whole mechanism exists to prevent."""
    modules = {path.stem for path in (_SRC / "views").glob("*_view.py")}
    assert modules == set(cardguard.REAL_WORK)


def test_the_guard_names_calls_that_really_exist():
    for names in cardguard.REAL_WORK.values():
        for name in names:
            assert callable(getattr(backend, name)), name


def test_the_guard_refuses_loudly():
    with pytest.raises(AssertionError, match="called the real backend"):
        cardguard._refuse("sign_view", "sign_file")()


# --- the samples ------------------------------------------------------------

def test_every_sample_returns_what_the_screens_expect():
    """The storybook is only useful if its data is the same shape the app renders."""
    assert isinstance(samples.identity(), backend.Identity)
    assert isinstance(samples.verify_valid(), backend.VerifyResult)
    assert isinstance(samples.verify_invalid(), backend.VerifyResult)
    assert isinstance(samples.doctor_healthy(), backend.DoctorResult)
    assert isinstance(samples.doctor_broken(), backend.DoctorResult)
    assert isinstance(samples.signed(), backend.SignResult)
    assert isinstance(samples.batch_partial(), backend.BatchSignResult)
    assert isinstance(samples.verify_batch_mixed(), backend.BatchVerifyResult)
    assert isinstance(samples.tokens(), backend.Result)
    assert isinstance(samples.certs(), backend.Result)
    assert isinstance(samples.ci_consistent(), backend.CiResult)


def test_the_long_value_samples_are_actually_long():
    """They exist to surface a layout that refuses to wrap. Short ones would prove nothing."""
    signer = samples.verify_long_values().signatures[0].signer
    assert len(signer.common_name) > 40
    assert len(samples.identity(long_values=True).full_name) > 40


def test_the_partial_batch_has_one_of_each_state():
    states = {item.status for item in samples.batch_partial().items}
    assert states == {"signed", "failed", "pending"}


def test_the_mixed_verify_batch_has_one_of_each_answer():
    """The batch states are only worth rendering if one of them walks every row shape."""
    items = samples.verify_batch_mixed().items
    indications = {item.result.indication for item in items if item.result.indication}
    assert indications == {"VALID", "INDETERMINATE", "INVALID"}
    kinds = {item.result.error_kind for item in items if item.result.error}
    assert kinds == {"needs_original", "other"}


def test_the_sensitive_doctor_sample_carries_the_flag():
    """The redaction test in Diagnóstico is worthless if no sample is ever marked."""
    marked = [c for c in samples.doctor_sensitive().checks if c.sensitive]
    assert [c.name for c in marked] == ["cédula token detected"]


def test_the_photo_is_generated_not_committed(qtbot):
    """No image of a person, real or otherwise, belongs in the repository."""
    data = samples.photo_bytes()
    assert data.startswith(b"\xff\xd8\xff")            # a JPEG
    assert not list((_SRC / "assets").glob("*.jpg"))


# --- the docs point at things that exist -------------------------------------

def _repo() -> Path:
    return Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("doc", ["README.md", "CONTRIBUTING.md"])
def test_every_local_link_and_image_in_the_docs_resolves(doc):
    """A broken image in a README is invisible in review and obvious to everybody else.

    Only repository-relative targets: an http link is somebody else's problem, and an anchor is
    not a file.
    """
    import re

    text = (_repo() / doc).read_text(encoding="utf-8")
    targets = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text)
    targets += re.findall(r'<img[^>]+src="([^"]+)"', text)
    # file:// is on this list because CONTRIBUTING quotes the hostile common name the app is
    # built to render inertly, and the regex found it inside a code span. Fitting, but not a link.
    schemes = ("http://", "https://", "file://", "mailto:", "#")
    missing = [t for t in targets
               if not t.startswith(schemes) and not (_repo() / t.split("#")[0]).exists()]
    assert missing == []


def test_the_readme_shows_the_app_as_it_is_now():
    """The screenshots are generated, so the only way they go stale is by not being regenerated.
    This does not check they are current, which no test can: it checks they are there at all."""
    shots = _repo() / "docs" / "screenshots"
    assert sorted(p.name for p in shots.glob("*.png")) == [
        "diagnostico.png", "firmar.png", "mi-cedula.png", "verificar.png",
    ]


def test_the_screenshot_tool_never_reaches_the_card():
    """It drives real screens with real handlers, which is exactly how the storybook once tried
    to call pcscd for a reader list."""
    source = (_repo() / "tools" / "screenshots.py").read_text(encoding="utf-8")
    assert "cardguard.block_card_calls()" in source


@pytest.mark.parametrize("tool", ["screenshots.py", "storybook.py"])
def test_the_tools_never_read_or_write_the_real_settings(tool):
    """They build the real screens, which read the store as they start and write it as they
    close: the README's images came out different on a machine with Avanzado on, and every
    screenshot run saved a window's geometry over the person's own."""
    source = (_repo() / "tools" / tool).read_text(encoding="utf-8")
    assert "sandbox.isolate_settings(" in source


def test_the_sandbox_is_a_store_of_its_own(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from firmauy_desktop import settings
    from tools import sandbox

    where = sandbox.isolate_settings(settings.Settings(advanced_mode=True))

    assert settings.load().advanced_mode is True
    assert QSettings().fileName().startswith(where)
    assert not where.startswith(str(tmp_path)), "it reused the suite's store instead of its own"


def test_the_docs_disclaim_the_same_thing():
    """SECURITY.md said "not officially certified (see the README)" and the README made no such
    claim, so the pointer resolved to nothing. Both say the same thing now.

    Whitespace is normalised first: a phrase wrapped across two lines of a Markdown paragraph is
    the same phrase, and a plain `in` says it is not.

    The Spanish half of the claim is checked where it lives, in test_theming.
    """
    import re

    def flat(path: str) -> str:
        return re.sub(r"\s+", " ", (_repo() / path).read_text(encoding="utf-8"))

    phrase = "official application of the Uruguayan State"
    assert phrase in flat("README.md")
    assert phrase in flat("SECURITY.md")        # so "(see the README)" points somewhere


def test_the_docs_do_not_disclaim_the_certificate():
    """"certified" beside a signing app points at the certificate, which is the card's and is
    not being disclaimed. What is disclaimed is the software."""
    import re

    security = re.sub(r"\s+", " ", (_repo() / "SECURITY.md").read_text(encoding="utf-8"))
    assert "officially certified" not in security


def test_nothing_the_policy_calls_unoffered_is_offered():
    """"Deliberately not offered" listed `tsa_ca` while Ajustes had a field for it, so the policy
    described some other app, and what it got wrong was not cosmetic: naming a stamping authority
    moves the moment firmauy judges the signer's certificate at, which is exactly what can turn an
    expired or revoked certificate into VÁLIDO.

    Every option that section names in backticks has to be absent from the package. When the answer
    for one of them changes, it moves to "Offered, and what it costs" instead of staying on a list
    that has quietly stopped being true.
    """
    import re

    text = (_repo() / "SECURITY.md").read_text(encoding="utf-8")
    section, marker, _ = text.partition("## Deliberately not offered")[2].partition(
        "Proposals to add any of these")
    assert marker, "the sentence delimiting 'these' moved, so this no longer knows where the list ends"

    names = re.findall(r"`([a-z_]{3,})`", section)
    assert names, "the section names no options at all, so this test would pass on nothing"

    source = "\n".join(p.read_text(encoding="utf-8") for p in sorted(_SRC.rglob("*.py")))
    offered = [n for n in names if n in source]
    assert offered == [], f"SECURITY.md says {offered} is not offered, and the app offers it"


def test_the_doctor_samples_only_use_strings_firmauy_emits():
    """A sample kinder than reality hides work instead of showing it.

    doctor_broken carried Spanish repair texts of its own invention, so the storybook and the
    README's screenshot showed a fully translated screen while the real one still had English in
    it. That is the opposite of what a sample is for.
    """
    import ast
    import inspect

    from firmauy import _shared

    emitted = set()
    for node in ast.walk(ast.parse(inspect.getsource(_shared))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            emitted.add(node.value)

    for name in ("doctor_broken", "doctor_healthy", "doctor_truncated", "doctor_sensitive"):
        for check in getattr(samples, name)().checks:
            if check.fix:
                assert check.fix in emitted, f"{name}: {check.fix!r} is not firmauy's"


def test_the_logo_ships_with_the_package():
    """It is shown in Acerca de, so it has to be inside the package rather than beside it: a
    PyInstaller bundle and an installed wheel both carry src/firmauy_desktop/assets and nothing
    from the repository root. It arrived at the root once, where the build would have dropped it
    and the dialog would have opened without its picture.
    """
    logo = _SRC / "assets" / "logo.png"

    assert logo.is_file(), "the logo is not where package-data can reach it"
    assert logo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not (_repo() / "assets").exists(), "a second assets/ outside the package"


def test_the_readme_shows_the_logo_that_ships():
    """The README points at the packaged copy rather than a second one beside it, so there is one
    file to replace when the artwork changes."""
    import re

    text = (_repo() / "README.md").read_text(encoding="utf-8")
    sources = re.findall(r'<img[^>]+src="([^"]+)"', text)

    assert "src/firmauy_desktop/assets/logo.png" in sources
    # The artwork carries the AGESIC disclaimer as part of the drawing, where a screen reader
    # cannot reach it. The alt text is the only place that says it to somebody who cannot see it.
    alt = re.search(r'logo\.png"[^>]*alt="([^"]*)"', text, re.S)
    assert alt and "AGESIC" in alt.group(1)


def test_the_badges_point_at_this_repository():
    """The badge block was copied from firmauy's README, and the copy that still says `firmauy`
    renders perfectly while reporting another project's build. Nothing about a wrong badge looks
    wrong, which is why it is asserted rather than read.

    The version badge is static on purpose. firmauy's reads pypi.org, and this is not published
    there, so the same URL would render "not found" forever.
    """
    import re

    text = (_repo() / "README.md").read_text(encoding="utf-8")
    badges = [line for line in text.splitlines() if line.startswith("[![")]
    assert len(badges) == 4, f"expected four badges, found {len(badges)}"

    for badge in badges:
        for url in re.findall(r"https?://[^)\s]+", badge):
            # firmauy, not followed by -desktop, is the copy that was never renamed. Written as a
            # negative lookahead: comparing against the end of the URL passes on the very
            # mutation this exists to catch, since no badge URL ends at the repo name.
            assert not re.search(r"/carlosplanchon/firmauy(?!-desktop)", url), (
                f"a badge still names firmauy: {url}")
            assert not url.startswith("https://img.shields.io/pypi/"), (
                "this repository publishes no package, so a pypi badge cannot resolve")

    # The CI badge has to name a workflow that is really there, or it renders as "no status".
    workflow = re.search(r"/actions/workflows/([\w.-]+)/badge\.svg", text)
    assert workflow, "no CI badge"
    assert (_repo() / ".github" / "workflows" / workflow.group(1)).is_file()


def test_dependabot_watches_what_the_binary_freezes():
    """The lock is what a packaged build carries, so what the lock pins is what people run.

    GHSA-g6cj-pr64-35w5 affected cryptography 44.0.0 through 49.0.0 and this lock pinned 49.0.0,
    which was caught by hand. Both ecosystems are asserted because dropping one is the silent way
    this stops working: the config still parses, Dependabot still opens pull requests, and the
    half nobody is watching goes quiet.
    """
    config = (_repo() / ".github" / "dependabot.yml")

    assert config.is_file(), "nothing watches the versions this repository freezes"
    text = config.read_text(encoding="utf-8")
    assert 'package-ecosystem: "uv"' in text, "the lock the PyInstaller build reads is unwatched"
    assert 'package-ecosystem: "github-actions"' in text, "a pinned action is a dependency too"


def test_the_app_can_say_where_it_came_from():
    """Somebody running the packaged build has never seen the README. Acerca de is the only place
    in the app that can point them at the project, and it said nothing.

    The security address is asserted against SECURITY.md rather than written twice, since the
    failure mode is the dialog quietly sending reports to an address nobody reads any more.
    """
    from firmauy_desktop import dialogs

    security = (_repo() / "SECURITY.md").read_text(encoding="utf-8")
    assert dialogs.SECURITY_CONTACT in security, "Acerca de names an address SECURITY.md does not"

    readme = (_repo() / "README.md").read_text(encoding="utf-8")
    assert dialogs.REPO in readme, "the dialog and the README disagree about where this lives"

    # A URL that wraps cannot be copied in one go, and copying is the only thing anybody does
    # with one. QMessageBox picks its own width, so the guard is on the length of the line.
    assert len(f"Contacto: {dialogs.SECURITY_CONTACT}") < 56


def test_only_the_about_box_renders_markup():
    """_box puts a file's name on screen for the two confirmation dialogs, and a file is named by
    whoever sent it: with markup enabled a name is a script tag. Acerca de is the one exception,
    it asks for it by name, and this is what keeps the exception from spreading by copy-paste.
    """
    import ast

    source = (_SRC / "dialogs.py").read_text(encoding="utf-8")
    asking = [node.lineno for node in ast.walk(ast.parse(source))
              if isinstance(node, ast.Call)
              for kw in node.keywords if kw.arg == "links"]

    assert len(asking) == 1, f"links=True is used at {len(asking)} call sites, expected one"


def test_a_hostile_file_name_cannot_become_markup(qtbot, monkeypatch):
    """The reason the exception is a parameter rather than the default."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    from firmauy_desktop import dialogs

    shown = {}
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.update(
        format=self.textFormat(), text=self.text()) or QMessageBox.StandardButton.No)
    # No slash anywhere in the name: a closing tag carries one, and Path().name would split the
    # payload on it, so the test would pass on a dialog that had rendered whatever was left.
    hostile = "<img src=x onerror=alert(1)>.pdf"
    dialogs.confirm_overwrite(None, f"/tmp/{hostile}")

    assert shown["format"] == Qt.TextFormat.PlainText
    assert hostile in shown["text"], "rendered as markup instead of shown as the name it is"


def test_the_about_links_are_escaped_before_they_are_linked(qtbot, monkeypatch):
    """Everything is escaped first and only the named substrings become anchors, so a value
    interpolated into that text cannot bring markup with it wherever it came from."""
    from firmauy_desktop import dialogs

    marked = dialogs._linked("versión <b>1.0</b>\nhttps://ejemplo.uy y hola@ejemplo.uy",
                             "https://ejemplo.uy", "hola@ejemplo.uy")

    assert "&lt;b&gt;" in marked and "<b>" not in marked
    assert '<a href="https://ejemplo.uy">' in marked
    assert '<a href="mailto:hola@ejemplo.uy">' in marked
    assert "<br>" in marked


def test_package_data_reaches_every_asset():
    """"assets/*" does not descend, so the seventeen SVGs of the icon set were absent from the
    wheel while a source checkout and a PyInstaller build both found them on disk. Nothing in the
    repository installs a wheel, so nothing noticed.

    Compared as sets rather than by naming the directories, so the next one added is covered the
    day it appears instead of the day somebody installs a release and finds blank icons.
    """
    import tomllib
    from pathlib import PurePosixPath

    patterns = tomllib.loads((_repo() / "pyproject.toml").read_text(encoding="utf-8"))[
        "tool"]["setuptools"]["package-data"]["firmauy_desktop"]
    shipped = [path.relative_to(_SRC) for path in (_SRC / "assets").rglob("*") if path.is_file()]

    assert shipped, "no assets at all, which cannot be right"
    # PurePath.match, not fnmatch: fnmatch's * crosses a directory separator and setuptools' does
    # not, so the first version of this test passed against the very pattern that was dropping
    # the icon set.
    missing = [path.as_posix() for path in shipped
               if not any(PurePosixPath(path.as_posix()).match(pattern) for pattern in patterns)]
    assert missing == [], f"package-data does not reach {missing}"


def test_the_version_says_the_same_thing_in_all_three_places():
    """One version, written by hand in three files that nothing ties together.

    `pyproject.toml` is what a wheel would carry, `__version__` is what Acerca De shows a person,
    and CFBundleShortVersionString is what macOS reads out of the app bundle. They agree today
    because they have never been changed. The first release changes all three, and the failure
    mode is silent: an About box claiming a version that was never published, and a bundle macOS
    considers older than the one already installed, so it declines to replace it.

    By regex rather than tomllib. The spec is a Python file, so one of the three was always going
    to be read as text.
    """
    import re

    def only(pattern: str, path: Path) -> str:
        found = re.findall(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
        assert len(found) == 1, f"{len(found)} coincidencias de {pattern!r} en {path.name}"
        return found[0]

    declared = {
        "pyproject.toml": only(r'^version = "([^"]+)"', _repo() / "pyproject.toml"),
        "__init__.py": only(r'^__version__ = "([^"]+)"', _SRC / "__init__.py"),
        "firmauy-desktop.spec": only(r'"CFBundleShortVersionString": "([^"]+)"',
                                     _repo() / "packaging" / "firmauy-desktop.spec"),
    }

    assert len(set(declared.values())) == 1, f"la versión no coincide: {declared}"


def test_the_software_centre_shows_this_versions_screenshots():
    """A fourth place the version is written. The AppStream images are fetched from the tag in
    their URLs, so that a catalogue does not follow the branch, and release.yml checks the
    <release> list but not these: a 0.2.0 would have gone out showing 0.1.0's screens.

    Each one also has to be a file in this tree, since the tag is cut from it. A URL naming an
    image nobody committed is a broken picture from the day of the release on.
    """
    import re
    import tomllib

    from firmauy_desktop.dialogs import REPO

    version = tomllib.loads(
        (_repo() / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    metainfo = (_repo() / "packaging" / "linux"
                / "com.firmauy.firmauydesktop.metainfo.xml").read_text(encoding="utf-8")
    images = re.findall(r"<image>([^<]+)</image>", metainfo)
    base = REPO.replace("https://github.com/", "https://raw.githubusercontent.com/") + f"/v{version}/"

    assert images, "el metainfo no tiene capturas"
    elsewhere = [url for url in images if not url.startswith(base)]
    assert elsewhere == [], f"capturas que no son de v{version}: {elsewhere}"
    missing = [url for url in images if not (_repo() / url.removeprefix(base)).is_file()]
    assert missing == [], f"capturas que no están en el repositorio: {missing}"


# --- the verify fixture ------------------------------------------------------

def test_the_fixture_verifies_against_its_own_anchor_and_not_without_one(tmp_path):
    """The property the bundle check rests on, held here so a change to either half is loud.

    Both halves matter. VALID with the anchor is what makes the check a check. INDETERMINATE
    without it is what says the anchor was actually consulted, rather than the file passing for
    some reason that would pass for anything.
    """
    from firmauy.api import verify
    from tools import verify_fixture

    pdf, ca = verify_fixture.write(tmp_path / "fx")

    assert verify(pdf, ca_file=ca).indication == "VALID"
    assert verify(pdf).indication == "INDETERMINATE"


def test_the_fixture_is_nobodys(tmp_path):
    """It exists because the alternative is a document signed with a real cédula. The certificate
    says what it is in the one field a person reads, so the file cannot be mistaken for one."""
    from cryptography import x509
    from tools import verify_fixture

    _pdf, ca = verify_fixture.write(tmp_path / "fx")
    cert = x509.load_pem_x509_certificate(ca.read_bytes())
    common_name = cert.subject.rfc4514_string()

    assert "NO ES UNA PERSONA" in common_name
    assert cert.issuer == cert.subject          # self signed: it reaches no real authority


def test_the_fixture_is_generated_and_never_committed(tmp_path):
    """A certificate has a validity window. One checked in today starts failing CI a year from
    now, on a commit that changed nothing, with a message about a signature rather than a clock.
    """
    committed = [str(path.relative_to(_repo())) for path in _repo().rglob("*.pdf")
                 if ".venv" not in path.parts and "dist" not in path.parts
                 and "build" not in path.parts]

    assert committed == [], f"un PDF vive en el repositorio: {committed}"


# --- the desktop identity ----------------------------------------------------

def test_the_application_id_says_the_same_thing_everywhere():
    """One name, in five places, and nothing but this holding them together.

    The id is what a compositor matches a window against, what the desktop entry is called, what
    AppStream files a component under and what a signature on macOS binds to. Two of them
    disagreeing is not a cosmetic problem: the window loses its icon under Wayland, a catalogue
    lists a second application, and an update refuses to replace what it cannot recognise.

    It is also permanent in a way most strings are not, since changing it after a release orphans
    whatever was installed under the old one.
    """
    import re

    from firmauy_desktop.settings import APP_ID

    linux = _repo() / "packaging" / "linux"
    assert (linux / f"{APP_ID}.desktop").is_file()
    assert (linux / f"{APP_ID}.metainfo.xml").is_file()

    metainfo = (linux / f"{APP_ID}.metainfo.xml").read_text(encoding="utf-8")
    assert f"<id>{APP_ID}</id>" in metainfo
    assert f"<launchable type=\"desktop-id\">{APP_ID}.desktop</launchable>" in metainfo

    spec = (_repo() / "packaging" / "firmauy-desktop.spec").read_text(encoding="utf-8")
    found = re.findall(r'bundle_identifier="([^"]+)"', spec)
    assert found == [APP_ID], f"macOS dice {found}, el resto dice {APP_ID!r}"

    for script in ("install.sh", "uninstall.sh"):
        text = (linux / script).read_text(encoding="utf-8")
        assert f'APP_ID="{APP_ID}"' in text, f"{script} tiene su propia copia del id"


def test_the_window_reports_which_desktop_entry_it_is(qapp):
    """Qt's own reason for this property: the windowing system needs it "without resorting to
    imprecise heuristics". The heuristics are what put a generic icon in the task switcher.

    Read back off the application rather than off the source, so a call that never runs, or one
    that runs before the name is set, fails here.
    """
    from firmauy_desktop.settings import APP_ID

    assert qapp.desktopFileName() == APP_ID


def test_the_desktop_entry_does_not_claim_files_the_app_cannot_open():
    """MimeType would put this in the "open with" list for PDFs, and the app opens no document
    handed to it on the command line, so a double click would raise an empty window and drop the
    file. The association belongs in the release where the app can act on what it is given.

    A test cannot tell whether that day has come, and the first version of this tried: it grepped
    app.py for sys.argv and matched the selftest flags, which is a rule about the wrong thing. So
    what is held here is the pair, which is checkable and is what would actually break. Adding
    MimeType or %F makes this fail, and that failure is the reminder to add the code with it.
    """
    from firmauy_desktop.settings import APP_ID

    entry = (_repo() / "packaging" / "linux" / f"{APP_ID}.desktop").read_text(encoding="utf-8")
    lines = [line for line in entry.splitlines() if not line.startswith("#")]

    assert "Exec=firmauy-desktop" in lines
    assert not [line for line in lines if line.startswith("MimeType=")]
    assert not [line for line in lines if line.startswith("Exec=") and "%" in line]


# --- who owns what gets installed ---------------------------------------------

def _fake_bundle(root: Path) -> Path:
    """The least make_release.sh and install.sh need: a binary, the icons the entry names, and a
    symbolic link like the 43 a real bundle carries."""
    bundle = root / "firmauy-desktop"
    assets = bundle / "_internal" / "firmauy_desktop" / "assets"
    assets.mkdir(parents=True)
    (assets / "icon.svg").write_text("<svg/>", encoding="utf-8")
    (assets / "icon.png").write_bytes(b"png")
    binary = bundle / "firmauy-desktop"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    (bundle / "_internal" / "enlace").symlink_to("firmauy_desktop")
    return bundle


@pytest.mark.skipif(sys.platform != "linux", reason="the release scripts are Linux's")
def test_the_release_archive_names_root_as_the_owner_of_everything(tmp_path):
    """Unpacked as root, GNU tar restores the owner an archive names. A plain tar named whoever
    built it, which on CI is the runner's uid and on another machine is whichever account has that
    number, and install.sh --system then carried that ownership into /opt."""
    import subprocess
    import tarfile

    script = _repo() / "packaging" / "linux" / "make_release.sh"
    subprocess.run(["bash", str(script), str(_fake_bundle(tmp_path)), str(tmp_path / "out"),
                    "9.9.9"], check=True, capture_output=True)

    with tarfile.open(tmp_path / "out" / "firmauy-desktop-9.9.9-linux-x86_64.tar.gz") as archive:
        owners = {(member.uid, member.gid, member.uname, member.gname)
                  for member in archive.getmembers()}

    assert owners == {(0, 0, "", "")}, f"el archivo nombra otros dueños: {owners}"


@pytest.mark.skipif(sys.platform != "linux", reason="the install scripts are Linux's")
@pytest.mark.skipif(os.geteuid() == 0 if hasattr(os, "geteuid") else True,
                    reason="what is held here is what happens without root")
@pytest.mark.parametrize("script, system_args", [("install.sh", ["--system"]),
                                                 ("uninstall.sh", ["--system"])])
def test_the_system_branch_asks_for_root_before_touching_anything(tmp_path, script,
                                                                  system_args):
    """Without root, the installer failed half way through /usr/local with one permission error
    per directory, and the uninstaller said "desinstalado." and exited 0 having removed nothing.
    Both now stop on the first line of the branch and say which command does work."""
    import subprocess

    args = [str(_fake_bundle(tmp_path))] if script == "install.sh" else []
    run = subprocess.run(["bash", str(_repo() / "packaging" / "linux" / script),
                          *args, *system_args], capture_output=True, text=True)

    assert run.returncode == 1
    assert "necesita root" in run.stderr and "sudo" in run.stderr
    assert run.stdout == "", "it did something before asking"


# --- the workflows ------------------------------------------------------------

def _workflows() -> list:
    """Every workflow, and never none: a loop over an empty glob passes whatever it asserts.

    That is how the two tests below went on passing in a copy of this repository that had no
    .github/ at all, while the ones reading a named file failed as they should.
    """
    found = sorted((_repo() / ".github" / "workflows").glob("*.yml"))
    assert found, "no hay workflows en .github/workflows"
    return found


def test_every_action_is_pinned_to_a_commit():
    """A tag is a name its owner can move, and moving it changes what runs here on the next push
    with nothing in the repository changing. GitHub's own guidance is to pin to a full commit,
    which is the only reference nobody can repoint.

    By regex rather than a YAML parser, so this needs no dependency the suite does not already
    have, and the shape it looks for is the one that matters: forty hexadecimal characters.
    """
    import re

    unpinned = []
    for workflow in _workflows():
        for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = re.search(r"uses:\s*(\S+)", line)
            if not match or match.group(1).startswith("./"):
                continue                       # a local action is this repository already
            ref = match.group(1).partition("@")[2]
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                unpinned.append(f"{workflow.name}:{number} {match.group(1)}")

    assert unpinned == [], f"sin fijar a un commit: {unpinned}"


def test_a_pinned_action_still_says_which_version_it_is():
    """Forty characters of hash say nothing a reviewer can act on. The tag beside it is what makes
    an upgrade something you can read, and it is a comment precisely so nothing resolves it."""
    import re

    naked = []
    for workflow in _workflows():
        for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"uses:\s*\S+@[0-9a-f]{40}", line) and "#" not in line:
                naked.append(f"{workflow.name}:{number}")

    assert naked == [], f"fijadas sin decir a qué versión: {naked}"


def test_the_release_runs_the_same_checks_as_the_everyday_build():
    """Two definitions of "this bundle is good" is one definition and one that drifts, and the one
    that drifts would be the build nobody verified before publishing it."""
    release = (_repo() / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    for script in ("packaging/check_bundle.sh", "packaging/linux/check_install.sh",
                   "packaging/linux/make_release.sh", "tools.verify_fixture"):
        assert script in release, f"el release no usa {script}"

    # Same floor as the everyday bundle job. A release built somewhere newer would run on fewer
    # machines than the one CI has been proving all along.
    ci = (_repo() / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-22.04" in release and "ubuntu-22.04" in ci


def test_no_workflow_may_quietly_relock():
    """The other half of "this artifact came from that commit".

    Measured: with pyproject.toml and uv.lock out of step, `uv sync` rewrote the lockfile and
    carried on, so a build can use a set of dependencies that exists in no commit. The release
    signs a statement naming a commit, and that statement is worth less than it looks if the
    lockfile it built from was written on the runner. UV_LOCKED turns the mismatch into exit 1
    with the file untouched, which was measured too.
    """
    for name in ("ci.yml", "release.yml"):
        text = (_repo() / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert 'UV_LOCKED: "1"' in text, f"{name} puede reescribir uv.lock durante el build"


def test_both_builds_install_into_opt_as_root():
    """Who owns /opt after install.sh --system is only visible by installing there as root, which
    a runner can afford and nobody's own machine should be asked to. Both builds ask for it: the
    everyday one, and the one that publishes what people will install."""
    for name in ("ci.yml", "release.yml"):
        text = (_repo() / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert 'CHECK_SYSTEM_INSTALL: "1"' in text, f"{name} no prueba install.sh --system"


def test_the_interpreter_that_ships_is_chosen_rather_than_resolved():
    """PyInstaller freezes the interpreter into the bundle, so it is part of the product and not
    part of the build. Unpinned, the version people run is whichever one uv resolved that day."""
    import re

    checked = 0
    for name in ("ci.yml", "release.yml"):
        text = (_repo() / ".github" / "workflows" / name).read_text(encoding="utf-8")
        # Split into jobs on the two-space keys under `jobs:`, so each block is one job and the
        # question can be asked of the ones that actually produce a bundle. The test matrix names
        # its own interpreters on purpose and is left alone.
        starts = [m.start() for m in re.finditer(r"^  [a-z][a-z0-9-]*:$", text, re.MULTILINE)]
        blocks = [text[a:b] for a, b in zip(starts, starts[1:] + [len(text)])]
        for job in blocks:
            if "pyinstaller" not in job:
                continue
            checked += 1
            assert re.search(r'python-version:\s*"[0-9.]+"', job), (
                f"{name}: un job construye un bundle sin decir con qué Python")

    assert checked == 2, f"esperaba dos jobs que construyan un bundle, encontré {checked}"


def _release_jobs() -> dict:
    """The release workflow split into its jobs, without a YAML parser.

    pyyaml is not a dependency of this project and adding one so a test can read a file it can
    already read would be the wrong trade. Jobs are the two-space keys under ``jobs:``.
    """
    import re

    text = (_repo() / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    body = text.partition("\njobs:\n")[2]
    starts = [(m.group(1), m.start()) for m in re.finditer(r"^  ([a-z][a-z0-9-]*):$", body,
                                                           re.MULTILINE)]
    ends = [start for _name, start in starts[1:]] + [len(body)]
    return {name: body[start:end] for (name, start), end in zip(starts, ends)}


def test_the_job_that_can_publish_runs_nothing_it_did_not_receive():
    """Least privilege, and the reason the release is two jobs rather than one.

    Publishing needs authority to speak for the repository: an OIDC token to sign the attestation
    against, and write access to create the release. Everything that builds needs none of it, and
    building is where somebody else's code runs, between the dependency tree, their install scripts
    and PyInstaller. Holding both at once means that code runs inside a job that could publish.

    So the halves are checked apart: the one that can publish does not check out this repository,
    does not run uv and does not run a script out of packaging/. It downloads bytes another job
    already checked and does the two things that need the authority.
    """
    jobs = _release_jobs()
    assert set(jobs) == {"build", "publish"}, list(jobs)

    build, publish = jobs["build"], jobs["publish"]

    assert "contents: read" in build
    for granted in ("id-token: write", "attestations: write", "contents: write"):
        assert granted not in build, f"el job que construye tiene {granted}"
        assert granted in publish, f"al job que publica le falta {granted}"

    for runs_code in ("actions/checkout", "uv run", "uv sync", "uvx ", "packaging/"):
        assert runs_code not in publish, f"el job que publica ejecuta {runs_code!r}"

    assert "needs: build" in publish, "publicar no espera a que el build haya pasado"

    # The checksum is written in one job and read in the other, and until it is read it is only a
    # file claiming to describe the archive beside it. Checked here, after the handoff and before
    # the digest is signed, so the pair that gets published was verified as a pair.
    assert "sha256sum -c" in publish, "nadie comprueba el checksum después del traspaso"


def test_the_release_says_the_same_thing_the_product_says():
    """Three files describe how finished this is, and a person meets the GitHub one first.

    The README says alpha and the AppStream release is typed development, so a release published
    as the latest stable one would be GitHub contradicting both. --verify-tag is here for a
    different reason: handed a tag that does not exist, gh creates one off the default branch, and
    this workflow publishes tags rather than making them.
    """
    release = (_repo() / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    # Only lines that are arguments. Searching the whole file found these three in the comment
    # above them explaining why they are there, so removing any of them changed nothing, which is
    # the same way a docstring once satisfied a rule about what the source may say.
    passed = {line.strip().rstrip(" \\") for line in release.splitlines()
              if line.strip().startswith("--")}
    for flag in ("--verify-tag", "--prerelease", "--latest=false"):
        assert flag in passed, f"gh release create sin {flag}"

    readme = (_repo() / "README.md").read_text(encoding="utf-8")
    metainfo = (_repo() / "packaging" / "linux"
                / "com.firmauy.firmauydesktop.metainfo.xml").read_text(encoding="utf-8")
    assert "Status: alpha" in readme
    assert 'type="development"' in metainfo


def test_the_readme_sends_people_to_releases_and_not_to_a_ci_artifact():
    """A CI artifact is one commit, kept for a week, and needs an account to download. It was the
    only channel there was when this section was written, and it is not any more."""
    readme = (_repo() / "README.md").read_text(encoding="utf-8")
    download = readme.partition("## Download it")[2].partition("## Install it")[0]

    assert download.strip(), "no hay sección de descarga"
    assert "/releases" in download
    assert "sha256sum -c" in download
    assert "gh attestation verify" in download


def test_the_release_refuses_a_version_the_metadata_does_not_declare():
    """AppStream carries a release entry per version, and a catalogue reads it. Publishing a tag
    the metadata says nothing about leaves the software centre describing the previous one."""
    release = (_repo() / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "<release version=" in release and "metainfo.xml" in release


def test_the_readme_does_not_promise_platforms_nothing_builds():
    """It described a PyInstaller matrix and code signing per platform, and every runner in every
    workflow is Ubuntu. Windows and macOS were mentioned in this repository only inside comments
    about why pyscard is built from source on Linux.

    The rule rather than the edit: if a workflow ever does build on another platform, the premise
    below stops holding and this stops asking. Until then, a reader is told what exists.
    """
    import re

    runners = set()
    for workflow in _workflows():
        runners |= set(re.findall(r"runs-on:\s*(\S+)", workflow.read_text(encoding="utf-8")))
    if any(not r.startswith("ubuntu") for r in runners):
        pytest.skip(f"ya se construye en algo que no es Linux: {sorted(runners)}")

    readme = (_repo() / "README.md").read_text(encoding="utf-8")
    assert "installers per platform" not in readme
    assert "code-signing" not in readme
    assert "no Windows or macOS builds yet" in readme

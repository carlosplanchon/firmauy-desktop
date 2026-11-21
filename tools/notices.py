# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""THIRD-PARTY-NOTICES.txt: whose work a build ships, under which licence, and where its source is.

A frozen build is mostly other people's code, and most of it comes with a condition on handing it
on. Qt and PySide6 are used under the LGPL version 3, which asks for a prominent notice that they
are in the program, a copy of the LGPL and of the GPL it is written on top of, and directions to
the source of the exact versions shipped. certifi's MPL asks for directions to its source, the
Apache licence for each package's NOTICE file, Python's licence for its own text to travel with
any copy, and the MIT and BSD ones for their copyright lines. None of it was next to the
executable.

So the list is read off the build instead of written down. PyInstaller's analysis says which file
it is about to copy and from where, and every installed distribution says which files are its own
in its RECORD, so the two together name each distribution that actually ships. A list kept by hand
goes out of date the first time a dependency moves, and wrong in the direction that matters:
something shipped and not credited.

The spec calls ``write`` once COLLECT is done, which leaves the file next to the executable in the
directory every artifact starts from: the zip, the tarball and both installers copy it whole, and
the check_bundle scripts ask each copy for it.

What it cannot place it does not guess at. On Linux the bundle also carries libraries of the
machine it was built on; on a Debian or Ubuntu builder, which is what CI is, dpkg names the
package and its copyright file goes in. Where owners can be named, a file without one stops the
build, because there it is something picked up off the machine rather than chosen; a Linux
without dpkg lists them as unidentified and says so out loud.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

FILENAME = "THIRD-PARTY-NOTICES.txt"

_REPO = Path(__file__).resolve().parent.parent
LICENSES = _REPO / "packaging" / "licenses"

# The two wheels that bring Qt. They carry no licence file of their own, and the terms are chosen
# here rather than read off them: they are offered as LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0,
# and this app takes the LGPL, whose text is written on top of the GPL's and needs both.
QT_DISTRIBUTIONS = ("pyside6-essentials", "shiboken6")
QT_TEXTS = ("LGPL-3.0.txt", "GPL-3.0.txt")

# Texts supplied from packaging/licenses for a distribution that ships none, by normalised name.
# Empty while every one of them carries its own: a package that arrives without stops the build
# (see ``missing_licences``) and the fix is an entry here, after reading what its project says.
SUPPLIED: dict[str, tuple[str, ...]] = {}

# In every build whatever the analysis says, because nothing in it names the bootloader, and the
# bootloader is the executable itself.
ALWAYS = ("pyinstaller",)

# The app. Its licence is LICENSE, beside the bundle in every artifact, not a third party's.
SELF = "firmauy-desktop"

_RULE = "=" * 78
_THIN = "-" * 78
_LICENCE_NAME = re.compile(r"^(licen[cs]e|copying|notice|copyright)", re.IGNORECASE)

_INTRO = (
    "FirmaUY Desktop es software libre bajo la Apache License 2.0, cuyo texto está en el "
    "archivo LICENSE (LICENSE.txt en Windows) que viene con el programa. Esta copia trae además "
    "programas y bibliotecas de otros proyectos, cada uno bajo su propia licencia. Para cada uno, "
    "abajo dice qué versión viaja en esta copia, bajo qué licencia, dónde está su código fuente "
    "y el texto de la licencia tal como lo publica el proyecto.",
    "Este archivo se escribe al construir el programa, a partir de lo que efectivamente quedó "
    "adentro, así que describe esta copia y no otra.",
)


def normalize(name: str) -> str:
    """The name pip, PyPI and every lockfile agree on (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _norm(path) -> str:
    return os.path.normcase(os.path.realpath(path))


def _within(path: str, roots) -> bool:
    return any(path == root or path.startswith(root.rstrip(os.sep) + os.sep) for root in roots)


def licence_files(dist) -> list:
    """Every licence file a distribution installed, in its own .dist-info and in any it vendors.

    PEP 639 puts them under ``.dist-info/licenses/``, older tools beside METADATA under the names
    below, and both are in use today. A vendored package's .dist-info, as setuptools carries a
    dozen, is the licence of code that ships inside this one, so it counts.
    """
    found = []
    for file in dist.files or ():
        parts = file.parts
        for index, part in enumerate(parts):
            if part.endswith(".dist-info"):
                inner = parts[index + 1:]
                if inner and (inner[0] == "licenses" or _LICENCE_NAME.match(inner[-1])):
                    found.append(file)
                break
    return sorted(found, key=lambda file: file.as_posix())


def _licence_label(file, key: str) -> str:
    """What a licence file is called in the notices: its path inside the .dist-info, without the
    licenses/ every PEP 639 one starts with, and the vendored package's name when it is not this
    distribution's own (setuptools carries a dozen)."""
    parts = file.parts
    index = next(index for index, part in enumerate(parts) if part.endswith(".dist-info"))
    inner = list(parts[index + 1:])
    if inner and inner[0] == "licenses" and len(inner) > 1:
        inner = inner[1:]
    owner = parts[index][: -len(".dist-info")]
    label = "/".join(inner)
    if normalize(owner.rsplit("-", 1)[0]) != key:
        return f"{owner.replace('-', ' ', 1)}, incluido: {label}"
    return label


def declared_licence(dist) -> str:
    """What the distribution says its licence is, in one line.

    The SPDX expression when there is one. The old License field otherwise, unless a project put
    the whole text in it, which some do; then the classifiers. A long line is still a summary and
    may be the only one that is right: PyInstaller's says GPL with the exception that matters
    here, where its classifier says plain GPLv2.
    """
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    text = (meta.get("License") or "").strip()
    if text and "\n" not in text:
        return text if len(text) <= 160 else text[:157] + "..."
    classifiers = [classifier.split(" :: ")[-1] for classifier in meta.get_all("Classifier") or ()
                   if classifier.startswith("License :: ") and classifier != "License :: OSI Approved"]
    if classifiers:
        return " / ".join(classifiers)
    return text.splitlines()[0][:80] if text else "sin declarar"


@dataclass
class Inventory:
    """Who the files PyInstaller collected belong to."""

    distributions: dict = field(default_factory=dict)   # normalised name -> Distribution
    directories: dict = field(default_factory=dict)     # normalised name -> top folders it fills
    python: bool = False
    foreign: list = field(default_factory=list)         # source paths no distribution claims


def _python_roots() -> list:
    """Where the interpreter and its standard library live.

    The whole installation when it is one of its own, as on Windows, under uv and on CI. A Python
    that lives in /usr is the exception: treating /usr as Python would credit every library of
    the system to the PSF, so there it is the standard library and libpython and nothing else.
    """
    if sys.platform == "win32":
        return [sys.base_prefix]
    paths = sysconfig.get_paths()
    roots = [paths["stdlib"], paths["platstdlib"]]
    prefix = os.path.realpath(sys.base_prefix)
    if prefix not in ("/", "/usr", "/usr/local"):
        roots.append(prefix)
    else:
        libdir = sysconfig.get_config_var("LIBDIR") or ""
        for name in {sysconfig.get_config_var("LDLIBRARY"), sysconfig.get_config_var("INSTSONAME")}:
            if libdir and name:
                roots.append(os.path.join(libdir, name))
    return roots


def inventory(entries, distributions=None, *, own=(), built=(), python=None) -> Inventory:
    """Map PyInstaller's ``(destination, source, typecode)`` entries to their owners.

    ``own`` is this repository's code and ``built`` the build's own scratch output, neither of
    which is anybody else's. ``python`` overrides where the interpreter is, for tests.
    """
    dists = [dist for dist in (metadata.distributions() if distributions is None else distributions)
             if dist.metadata["Name"]]
    owners: dict = {}
    for dist in dists:
        for file in dist.files or ():
            owners.setdefault(_norm(dist.locate_file(file)), []).append(dist)
    own = [_norm(root) for root in own]
    built = [_norm(root) for root in built]
    interpreter = [_norm(root) for root in (_python_roots() if python is None else python)]

    found = Inventory()
    foreign = []
    for entry in entries:
        destination, source, typecode = entry[0], entry[1], entry[2]
        # A symbolic link's source is the name it points at, not a file, and an option is not a
        # file at all.
        if typecode in ("SYMLINK", "OPTION") or not source:
            continue
        path = _norm(source)
        claimed = owners.get(path)
        if claimed:
            for dist in claimed:
                key = normalize(dist.metadata["Name"])
                if key == SELF:
                    continue
                found.distributions.setdefault(key, dist)
                if typecode in ("BINARY", "EXTENSION"):
                    top = destination.replace("\\", "/").split("/")[0]
                    found.directories.setdefault(key, set()).add(top)
            continue
        if _within(path, own) or _within(path, built):
            continue
        if _within(path, interpreter):
            found.python = True
            continue
        if os.path.isfile(path):
            foreign.append(source)
    for name in ALWAYS:
        dist = next((dist for dist in dists if normalize(dist.metadata["Name"]) == name), None)
        if dist is not None:
            found.distributions.setdefault(name, dist)
    found.foreign = sorted(set(foreign))
    return found


def missing_licences(found: Inventory) -> list:
    """Distributions that ship and bring no licence text, and that nothing here supplies one for."""
    return sorted(key for key, dist in found.distributions.items()
                  if key not in QT_DISTRIBUTIONS and key not in SUPPLIED
                  and not licence_files(dist))


# --- libraries of the machine the bundle was built on -------------------------------------------

def _aliases(path: str):
    """The names dpkg may know a file by. Since the /usr merge, /lib is /usr/lib, and the package
    database still records whichever of the two each package was built with."""
    for candidate in (path, os.path.realpath(path)):
        yield candidate
        if candidate.startswith("/usr/lib/"):
            yield candidate[len("/usr"):]
        elif candidate.startswith("/lib/"):
            yield "/usr" + candidate


def _dpkg_owner(path: str, run) -> str | None:
    tried = []
    for candidate in _aliases(path):
        if candidate in tried:
            continue
        tried.append(candidate)
        result = run(["dpkg-query", "-S", candidate], capture_output=True, text=True)
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            owner, separator, owned = line.partition(": ")
            if separator and owned.strip() == candidate and not owner.startswith("diversion"):
                return owner.split(",")[0].strip().split(":")[0]
    return None


def _distribution_id() -> str:
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return ""
    found = re.search(r'^ID="?([^"\n]+)"?$', text, re.MULTILINE)
    return found.group(1) if found else ""


def debian_packages(paths, run=subprocess.run, *, doc=Path("/usr/share/doc")):
    """Group the files by the Debian package that installed them, when dpkg is there to ask.

    Returns ``(packages, unidentified)``: for each package its version, its source package and
    the copyright file Debian policy puts every package's licence in.
    """
    if not paths:
        return {}, []
    if shutil.which("dpkg-query") is None:
        return {}, list(paths)
    packages: dict = {}
    unidentified = []
    for path in paths:
        name = _dpkg_owner(path, run)
        if name is None:
            unidentified.append(path)
            continue
        if name not in packages:
            result = run(["dpkg-query", "-W", "-f", "${Version}\t${source:Package}\t${source:Version}",
                          name], capture_output=True, text=True)
            fields = (result.stdout.split("\t") if result.returncode == 0 else []) + ["", "", ""]
            copyright_file = doc / name / "copyright"
            packages[name] = {
                "version": fields[0].strip(),
                "source": fields[1].strip() or name,
                "source_version": fields[2].strip() or fields[0].strip(),
                "copyright": (copyright_file.read_text(encoding="utf-8", errors="replace")
                              if copyright_file.is_file() else None),
                "files": [],
            }
        basename = os.path.basename(path)
        if basename not in packages[name]["files"]:
            packages[name]["files"].append(basename)
    return packages, unidentified


# --- the text -----------------------------------------------------------------------------------

def _clean(text: str) -> str:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.strip("\n").splitlines())


def _wrap(paragraph: str, width: int = 78) -> list:
    lines, line = [], ""
    for word in paragraph.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    return lines + ([line] if line else [])


class _Writer:
    """The file as a list of lines, with every licence text written once.

    The Apache licence, to name one, arrives a dozen times word for word. Printing it a dozen
    times hides the texts that differ, and the ones that differ are the point.
    """

    def __init__(self):
        self.lines: list = []
        self._seen: dict = {}

    def paragraph(self, *paragraphs: str) -> None:
        for text in paragraphs:
            self.lines += ["", *_wrap(text)]

    def component(self, title: str, details: list, texts: list, *, label: str = "") -> None:
        self.lines += ["", "", _RULE, title, *details, _THIN]
        for name, text in texts:
            body = _clean(text)
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            if digest in self._seen:
                self.lines += ["", f"[{name}: el mismo texto que en {self._seen[digest]}, más arriba.]"]
                continue
            self._seen[digest] = label or title
            if len(texts) > 1:
                self.lines += ["", f"--- {name} ---"]
            self.lines += ["", body]

    def text(self) -> str:
        return "\n".join(self.lines).strip("\n") + "\n"


def _qt_section(out: _Writer, found: Inventory, qt_version: str, contents: str) -> None:
    pyside = found.distributions.get("pyside6-essentials")
    shiboken = found.distributions.get("shiboken6")
    pyside_version = pyside.version if pyside else (shiboken.version if shiboken else qt_version)
    major_minor = ".".join(qt_version.split(".")[:2])
    folders = sorted(set().union(*(found.directories.get(name, set()) for name in QT_DISTRIBUTIONS)))
    where = " y ".join(f"{contents}{os.sep}{folder}" for folder in folders) or contents
    names = f"Qt {qt_version} y PySide6 {pyside_version}"
    if shiboken:
        names += f" (con shiboken6 {shiboken.version})"

    out.lines += ["", "", _RULE, names,
                  "Copyright © The Qt Company Ltd. y otros colaboradores.",
                  "Licencia: GNU Lesser General Public License, versión 3 (LGPL-3.0-only)", _THIN]
    out.paragraph(
        "FirmaUY Desktop usa Qt, a través de PySide6, bajo la GNU LGPL versión 3. Qt y PySide6 "
        "también se ofrecen bajo la GPL y bajo una licencia comercial; esta copia los usa bajo la "
        "LGPL. Más abajo están el texto de la LGPL versión 3 y el de la GPL versión 3, sobre la "
        "que la LGPL está escrita.",
        "Las bibliotecas de Qt y de PySide6 no están mezcladas con el programa: son archivos "
        f"aparte, que el programa carga al arrancar, en {where}. Se pueden reemplazar por otra "
        "compilación compatible con su interfaz, y el programa usa la que encuentre ahí.",
        "El código fuente de estas versiones exactas:",
    )
    out.lines += [
        "",
        f"  Qt {qt_version}:",
        f"    https://download.qt.io/archive/qt/{major_minor}/{qt_version}/single/",
        f"  PySide6 y shiboken6 {pyside_version}:",
        f"    https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{pyside_version}-src/",
        f"    https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v{pyside_version}",
    ]
    out.paragraph(
        "Qt incluye a su vez código de otros proyectos, cada uno con su propia licencia. La lista, "
        "módulo por módulo, está en https://doc.qt.io/qt-6/licenses-used-in-qt.html",
    )
    for name in QT_TEXTS:
        text = (LICENSES / name).read_text(encoding="utf-8")
        out.lines += ["", _THIN, "", _clean(text)]
        out._seen[hashlib.sha256(_clean(text).encode("utf-8")).hexdigest()] = "la sección de Qt"


def render(found: Inventory, *, app_version: str, qt_version: str | None = None,
           python_version: str | None = None, python_licence: str | None = None,
           system: dict | None = None, unidentified=(), contents: str = "_internal",
           distro: str = "") -> str:
    """The whole file, from an inventory and what the build knows about itself."""
    system = system or {}
    python_version = python_version or platform.python_version()
    out = _Writer()
    out.lines += [f"FirmaUY Desktop {app_version}: componentes de terceros"]
    out.paragraph(*_INTRO)

    qt = any(name in found.distributions for name in QT_DISTRIBUTIONS)
    packages = [(key, found.distributions[key]) for key in sorted(found.distributions)
                if key not in QT_DISTRIBUTIONS]

    index = []
    if qt:
        pyside = found.distributions.get("pyside6-essentials")
        index.append((f"Qt {qt_version or '?'} y PySide6 {pyside.version if pyside else '?'}",
                      "LGPL-3.0-only"))
    if found.python:
        index.append((f"Python {python_version}", "PSF-2.0"))
    for _key, dist in packages:
        index.append((f"{dist.metadata['Name']} {dist.version}", declared_licence(dist)))
    # By source package, which is what a licence belongs to: libxcb is one project whether it
    # arrives as one binary package or five.
    sources: dict = {}
    for name, info in sorted(system.items()):
        group = sources.setdefault((info["source"], info["source_version"]),
                                   {"packages": [], "files": [], "copyrights": []})
        group["packages"].append(name)
        group["files"] += [file for file in info["files"] if file not in group["files"]]
        if info["copyright"]:
            group["copyrights"].append((f"copyright de {name}", info["copyright"]))
    for source, version in sorted(sources):
        index.append((f"{source} {version} (sistema)", "ver su archivo de copyright"))
    if unidentified:
        index.append(("Archivos sin identificar", f"{len(unidentified)}, sin licencia acá"))
    out.lines += ["", "Contenido:", ""]
    width = max((len(name) for name, _ in index), default=0) + 2
    out.lines += [f"  {name.ljust(width)}{licence}" for name, licence in index]

    if qt:
        _qt_section(out, found, qt_version or "?", contents)

    if found.python:
        out.component(
            f"Python {python_version}",
            ["Licencia: PSF-2.0 (Python Software Foundation License, versión 2)",
             f"Código fuente: https://www.python.org/ftp/python/{python_version}/"],
            [("LICENSE.txt", python_licence)] if python_licence else [],
        )
        if not python_licence:
            out.lines += ["", "[No se encontró el LICENSE.txt de este intérprete al construir.]"]

    for key, dist in packages:
        texts = [(_licence_label(file, key),
                  Path(dist.locate_file(file)).read_text(encoding="utf-8", errors="replace"))
                 for file in licence_files(dist)]
        texts += [(name, (LICENSES / name).read_text(encoding="utf-8")) for name in SUPPLIED.get(key, ())]
        name = dist.metadata["Name"]
        out.component(
            f"{name} {dist.version}",
            [f"Licencia: {declared_licence(dist)}",
             f"Código fuente: https://pypi.org/project/{key}/{dist.version}/"],
            texts,
            label=name,
        )

    for (source, version), group in sorted(sources.items()):
        if distro == "ubuntu":
            where = f"https://launchpad.net/ubuntu/+source/{source}/{version}"
        elif distro == "debian":
            where = f"https://sources.debian.org/src/{source}/{version}/"
        else:
            where = f"el paquete fuente {source} {version} de la distribución"
        out.component(
            f"{source} {version}, del sistema donde se construyó",
            [f"Paquetes: {', '.join(group['packages'])}",
             f"Archivos: {', '.join(sorted(group['files']))}",
             f"Código fuente: {where}"],
            group["copyrights"],
            label=source,
        )

    if unidentified:
        out.lines += ["", "", _RULE, "Archivos sin identificar", _THIN]
        out.paragraph(
            "Vienen del sistema donde se construyó el programa y no se pudo averiguar de qué "
            "paquete son, así que este aviso no trae su licencia. Una copia para distribuir se "
            "construye donde eso sí se puede averiguar.",
        )
        out.lines += [""] + [f"  {path}" for path in unidentified]

    return out.text()


def _app_version() -> str:
    text = (_REPO / "src" / "firmauy_desktop" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE).group(1)


def _qt_version(found: Inventory) -> str:
    try:
        from PySide6.QtCore import qVersion
        return qVersion()
    except Exception:                       # no Qt to ask: PySide6's version is Qt's to the minor
        dist = found.distributions.get("pyside6-essentials")
        return dist.version if dist else "?"


def _python_licence() -> str | None:
    """The interpreter's own LICENSE.txt: in the library on POSIX, at the top on Windows.

    On a Windows build from python.org it also carries the licences of what that build bundles,
    OpenSSL and libffi among them, which is exactly what this file needs to say about them.
    """
    for candidate in (Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt",
                      Path(sys.base_prefix) / "LICENSE.txt"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return None


def can_identify_everything(platform: str | None = None, which=shutil.which) -> bool:
    """Whether every file a build collects should have an owner this module can name.

    On Windows anything that is not from a Python package or the interpreter is a stranger by
    definition: the first CI build that wrote these notices carried 45 such files, a Java 8 JDK's
    copy of the C runtime and MySQL's OpenSSL, collected because PATH led there. On Linux, dpkg
    names every library a Debian or Ubuntu builder has, and that builder is CI. A Linux without
    dpkg cannot, and nothing is distributed from one.
    """
    platform = sys.platform if platform is None else platform
    return platform == "win32" or which("dpkg-query") is not None


def write(path, entries, *, own=(), built=(), contents: str = "_internal") -> Inventory:
    """Write the notices for a build and say what it could not account for.

    Stops the build when a Python package ships without a licence text: that is a hole in the
    notices with a known fix (an entry in SUPPLIED), and finding it in CI beats finding it after a
    release. It also stops on a file nobody owns wherever owners can be named (see
    ``can_identify_everything``), because there such a file is something the build picked up off
    the machine rather than chose. Elsewhere it is a warning.
    """
    found = inventory(entries, own=own, built=built)
    missing = missing_licences(found)
    if missing:
        raise SystemExit(
            "ERROR: estos paquetes viajan en el bundle sin el texto de su licencia: "
            f"{', '.join(missing)}. Agregalo en packaging/licenses y en SUPPLIED, en "
            "tools/notices.py, después de leer qué dice el proyecto.")

    python_licence = _python_licence() if found.python else None
    system, unidentified = debian_packages(found.foreign)
    if unidentified and can_identify_everything():
        raise SystemExit(
            "ERROR: estos archivos viajan en el bundle y no son de ningún paquete de Python, del "
            "intérprete ni de la distribución, así que el build los levantó de la máquina: "
            f"{', '.join(unidentified)}. Sacalos en el spec, o decí de dónde vienen.")
    text = render(found, app_version=_app_version(), qt_version=_qt_version(found),
                  python_licence=python_licence, system=system, unidentified=unidentified,
                  contents=contents, distro=_distribution_id() if system else "")

    # Notepad is what opens it on Windows, so the same choice as the LEEME: CRLF and a BOM.
    windows = sys.platform == "win32"
    with open(path, "w", encoding="utf-8-sig" if windows else "utf-8",
              newline="\r\n" if windows else "\n") as handle:
        handle.write(text)

    if found.python and python_licence is None:
        print("::warning::no encontré el LICENSE.txt del intérprete: el aviso de Python va sin texto")
    for name, info in sorted(system.items()):
        if info["copyright"] is None:
            print(f"::warning::el paquete {name} no tiene /usr/share/doc/{name}/copyright")
    for item in unidentified:
        print(f"::warning::{item} viaja en el bundle y no sé de qué paquete es")
    print(f"notices: {path}: {len(found.distributions)} paquetes de Python"
          f"{', Python' if found.python else ''}, {len(system)} del sistema, "
          f"{len(unidentified)} sin identificar")
    return found

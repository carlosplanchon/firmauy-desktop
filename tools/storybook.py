# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Every screen in every state, without a cédula.

This app is hard to look at while building it: most of what a person sees only appears after a
card, a PIN and a real signature, and a wrong PIN spends one of the card's limited tries. So the
UI got built largely blind. This window fixes that. It builds each screen, drives it to a state
with synthetic data, and shows them side by side.

It lives outside ``src/`` on purpose. ``[tool.setuptools.packages.find] where = ["src"]`` makes
it structurally impossible to package, which is a stronger guarantee than an exclude list, and
PyInstaller only follows imports from the entry point, so nothing unimported is ever bundled.

    uv run python -m tools.storybook                          # look at it
    uv run python -m tools.storybook --shot shots/            # write a PNG per state
    uv run python -m tools.storybook --only verify            # just one screen's states
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen") if "--shot" in sys.argv else None

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from firmauy_desktop import settings  # noqa: E402
from firmauy_desktop.ui.theming import theme  # noqa: E402
from tools import cardguard, samples  # noqa: E402

# Before a single view is constructed. The whole point of this window is to iterate without
# touching the card, so the guarantee has to hold for the process, not per state.
cardguard.block_card_calls()

from firmauy_desktop.views import (  # noqa: E402
    advanced_view,
    doctor_view,
    identity_view,
    sign_view,
    verify_view,
)

_SHOT_SIZE = (900, 720)


@dataclass(frozen=True)
class State:
    key: str            # "verify.invalid", used by --only and as the file name
    title: str          # what the list shows
    build: Callable[[], QWidget]


def _patch(module, name: str, result) -> None:
    """Replace a backend call for good, in this process. The storybook is not a test: there is
    nothing to undo, and each state builds its own view."""
    setattr(module, name, lambda *a, **k: result)


# Two screens chain a second card call off the first one's result: Diagnóstico asks for the
# reader list once the checks come back, and Avanzado asks for the certificates once it has the
# token. Driving the first handler therefore starts the second call for real, so these two get a
# sample instead. Everything else is left to the guard on purpose: a state that forgets to set
# up its data should fail loudly rather than quietly render somebody else's sample.
_patch(doctor_view, "list_readers", samples.readers())
_patch(advanced_view, "list_certs", samples.certs())


# --- Firmar -----------------------------------------------------------------

def _sign(build: Callable[[sign_view.SignView], None]) -> Callable[[], QWidget]:
    def make() -> QWidget:
        view = sign_view.SignView()
        build(view)
        return view
    return make


def _sign_states() -> list[State]:
    def empty(view):
        pass

    def one_file(view):
        view.load("/home/ana/contrato.pdf")

    def several(view):
        view.load_many(samples.batch_paths(4))

    def signed(view):
        view.load("/home/ana/contrato.pdf")
        view._on_done(samples.signed())

    def wrong_pin_two(view):
        view.load("/home/ana/contrato.pdf")
        view._on_done(samples.wrong_pin(2))

    def wrong_pin_one(view):
        view.load("/home/ana/contrato.pdf")
        view._on_done(samples.wrong_pin(1))

    def batch_done(view):
        view.load_many(samples.batch_paths(3))
        view._on_done(samples.batch_all_signed(3))

    def batch_partial(view):
        view.load_many(samples.batch_paths(4))
        view._on_done(samples.batch_partial())

    def batch_warned(view):
        view.load_many(samples.batch_paths(3))
        view._on_done(samples.batch_warned())

    def batch_cancelled(view):
        view.load_many(samples.batch_paths(4))
        view._on_done(samples.batch_cancelled())

    def too_many(view):
        view.load_many([f"/home/ana/f{i}.pdf" for i in range(500)])

    def card_busy(view):
        view.load("/home/ana/contrato.pdf")
        view._card.acquire("leyendo la cédula")
        view._on_sign()

    return [
        State("sign.empty", "Firmar: vacío", _sign(empty)),
        State("sign.one", "Firmar: un archivo", _sign(one_file)),
        State("sign.several", "Firmar: cuatro archivos", _sign(several)),
        State("sign.signed", "Firmar: firmado", _sign(signed)),
        State("sign.pin2", "Firmar: PIN incorrecto, 2 intentos", _sign(wrong_pin_two)),
        State("sign.pin1", "Firmar: PIN incorrecto, 1 intento", _sign(wrong_pin_one)),
        State("sign.batch", "Firmar: lote completo", _sign(batch_done)),
        State("sign.batch-partial", "Firmar: lote parcial", _sign(batch_partial)),
        State("sign.batch-warned", "Firmar: lote con permisos pendientes", _sign(batch_warned)),
        State("sign.batch-cancelled", "Firmar: lote cancelado", _sign(batch_cancelled)),
        State("sign.too-many", "Firmar: demasiados archivos", _sign(too_many)),
        State("sign.card-busy", "Firmar: cédula ocupada", _sign(card_busy)),
    ]


# --- Verificar --------------------------------------------------------------

def _verify(result, *, details: bool = False) -> Callable[[], QWidget]:
    def make() -> QWidget:
        view = verify_view.VerifyView()
        # What load() would have done. Driving the handler straight skips it, and a shot of a
        # verdict with no file named is exactly the thing the app refuses to do.
        view._path = "/home/ana/contrato.pdf.p7s"
        view._drop.show_files([view._path])
        view._refresh_input()
        # _on_done fills the scope itself now: the view was built fresh, so _asked_revocation is
        # False and the "no consultada" claim comes out of the same code the app runs. The two
        # lines that used to write it by hand here were exactly the kind of sample the guard
        # exists to forbid, a screen showing words the code cannot produce.
        view._on_done(result)
        if details:
            view._details_box.set_expanded(True)
        return view
    return make


def _verify_batch(result, *, select: "int | None" = None,
                  stop_after: "int | None" = None) -> Callable[[], QWidget]:
    """A batch outcome, driven through the handlers like _verify does.

    Never through load_many, which would start the runner and meet the card guard's refusal:
    the storybook's whole point is screens without real work behind them. ``stop_after``
    replays that many per-file reports and presses "Dejar de esperar"; ``select`` picks a row,
    which is what makes the drill-down render.
    """
    def make() -> QWidget:
        view = verify_view.VerifyView()
        paths = [item.path for item in result.items]
        view._paths = list(paths)
        view._drop.show_files(paths)
        view._refresh_input()
        view._files.set_paths(paths)
        view._batch_total = len(paths)
        if stop_after is not None:
            for item in result.items[:stop_after]:
                view._on_batch_progress(item)
            view._on_stop()
        else:
            view._on_done(result)
        if select is not None:
            view._files.setCurrentRow(select)
        return view
    return make


def _verify_states() -> list[State]:
    return [
        State("verify.empty", "Verificar: vacío", verify_view.VerifyView),
        State("verify.valid", "Verificar: VÁLIDO", _verify(samples.verify_valid())),
        State("verify.valid-2", "Verificar: VÁLIDO, dos firmantes",
              _verify(samples.verify_valid(2))),
        State("verify.indeterminate", "Verificar: INDETERMINADO",
              _verify(samples.verify_indeterminate())),
        State("verify.invalid", "Verificar: INVÁLIDO", _verify(samples.verify_invalid())),
        # The only place a CheckList appears on a real screen, and it is folded away by default,
        # so without this state it never gets looked at.
        State("verify.details", "Verificar: detalles técnicos",
              _verify(samples.verify_indeterminate(), details=True)),
        State("verify.details-2", "Verificar: detalles, dos firmantes",
              _verify(samples.verify_valid(2), details=True)),
        State("verify.long", "Verificar: valores largos", _verify(samples.verify_long_values())),
        # The signer card grows two rows and a paragraph of law here, which is the most it ever
        # holds, and the broken one is the state where the word above and the row below disagree
        # on purpose: every signature check passes and the file is still not VÁLIDO.
        State("verify.timestamp", "Verificar: con sello de tiempo",
              _verify(samples.verify_timestamped())),
        State("verify.timestamp-broken", "Verificar: sello de tiempo roto",
              _verify(samples.verify_broken_timestamp())),
        State("verify.timestamp-details", "Verificar: sello roto, detalles",
              _verify(samples.verify_broken_timestamp(), details=True)),
        State("verify.needs-original", "Verificar: falta el original",
              _verify(samples.verify_needs_original())),
        State("verify.error", "Verificar: error", _verify(samples.verify_error())),
        State("verify.batch", "Verificar: lote todo VÁLIDO",
              _verify_batch(samples.verify_batch_all_valid(3))),
        State("verify.batch-mixed", "Verificar: lote mixto",
              _verify_batch(samples.verify_batch_mixed())),
        State("verify.batch-row", "Verificar: lote, fila elegida",
              _verify_batch(samples.verify_batch_mixed(), select=2)),
        State("verify.batch-original", "Verificar: lote, falta un original",
              _verify_batch(samples.verify_batch_mixed(), select=3)),
        State("verify.batch-stopped", "Verificar: lote detenido",
              _verify_batch(samples.verify_batch_mixed(), stop_after=2)),
    ]


# --- Mi cédula --------------------------------------------------------------

def _identity(build: Callable[[identity_view.IdentityView], None]) -> Callable[[], QWidget]:
    def make() -> QWidget:
        view = identity_view.IdentityView()
        build(view)
        return view
    return make


def _identity_states() -> list[State]:
    def read(view):
        view._on_done(samples.identity_read(photo=True))

    def read_long(view):
        view._on_done(samples.identity_read(photo=True, long_values=True))

    def no_photo(view):
        view._on_done(samples.identity_read())

    def no_card(view):
        view._on_done(samples.identity_no_card())

    def ci_ok(view):
        view._ci_input.setText("12345672")

    def ci_bad(view):
        view._ci_input.setText("12345679")

    def ci_partial(view):
        view._ci_input.setText("1234567")

    return [
        State("identity.empty", "Mi cédula: vacío", identity_view.IdentityView),
        State("identity.read", "Mi cédula: leída", _identity(read)),
        State("identity.long", "Mi cédula: nombre largo", _identity(read_long)),
        State("identity.no-photo", "Mi cédula: sin foto", _identity(no_photo)),
        State("identity.no-card", "Mi cédula: sin tarjeta", _identity(no_card)),
        State("identity.ci-ok", "Mi cédula: CI consistente", _identity(ci_ok)),
        State("identity.ci-bad", "Mi cédula: CI inconsistente", _identity(ci_bad)),
        State("identity.ci-partial", "Mi cédula: CI a completar", _identity(ci_partial)),
    ]


# --- Diagnóstico ------------------------------------------------------------

def _doctor(build: Callable[[doctor_view.DoctorView], None]) -> Callable[[], QWidget]:
    def make() -> QWidget:
        view = doctor_view.DoctorView()
        build(view)
        return view
    return make


def _doctor_states() -> list[State]:
    def healthy(view):
        view._on_checked(samples.doctor_healthy())
        view._on_readers(samples.readers())

    def broken(view):
        view._on_checked(samples.doctor_broken())

    def truncated(view):
        view._on_checked(samples.doctor_truncated())

    def sensitive(view):
        view._pkcs11.setChecked(True)
        view._on_checked(samples.doctor_sensitive())

    def cas(view):
        view._on_checked(samples.doctor_healthy())
        view._cas_log.show()
        view._cas_log.appendPlainText("Bajando los certificados...")
        view._on_cas_progress(
            "ca.minterior.gub.uy no responde (HTTP 503); probando con crt.sh...")
        view._on_cas_done(samples.cas_refreshed())

    return [
        State("doctor.empty", "Diagnóstico: sin revisar", doctor_view.DoctorView),
        State("doctor.healthy", "Diagnóstico: todo en orden", _doctor(healthy)),
        State("doctor.broken", "Diagnóstico: con problemas", _doctor(broken)),
        State("doctor.truncated", "Diagnóstico: lista truncada", _doctor(truncated)),
        State("doctor.sensitive", "Diagnóstico: PKCS#11 con nombre", _doctor(sensitive)),
        State("doctor.cas", "Diagnóstico: CA actualizadas", _doctor(cas)),
    ]


# --- Avanzado ---------------------------------------------------------------

def _advanced(build: Callable[[advanced_view.AdvancedView], None]) -> Callable[[], QWidget]:
    def make() -> QWidget:
        view = advanced_view.AdvancedView()
        build(view)
        return view
    return make


def _advanced_states() -> list[State]:
    def module_row(view):
        """What _on_read puts there. Driving the handlers straight skips it, and a shot missing a
        row the real screen always shows is a shot that cannot be reviewed."""
        from firmauy_desktop.ui import components as c
        view._module.set_rows([c.Row("Módulo", "el que trae firmauy por defecto")])

    def read(view):
        module_row(view)
        view._on_tokens(samples.tokens())
        view._on_certs(samples.certs())

    def no_token(view):
        module_row(view)
        view._on_tokens(samples.no_tokens())
        view._on_certs(backend_empty())

    def error(view):
        module_row(view)
        view._on_tokens(samples.module_error())

    def backend_empty():
        from firmauy_desktop import backend
        return backend.Result(True, [])

    return [
        State("advanced.empty", "Avanzado: sin leer", advanced_view.AdvancedView),
        State("advanced.read", "Avanzado: token y certificado", _advanced(read)),
        State("advanced.no-token", "Avanzado: sin token", _advanced(no_token)),
        State("advanced.error", "Avanzado: módulo que no carga", _advanced(error)),
    ]


# --- the component gallery --------------------------------------------------

def _gallery() -> QWidget:
    """Every component at once, before any screen uses one.

    Cheap insurance: these are about to be wired into five screens, and a component that looks
    wrong is much easier to see here than to spot inside a converted view.
    """
    from firmauy_desktop.ui import components as c

    page = QWidget()
    column = QVBoxLayout(page)

    column.addWidget(c.label("Título de pantalla", role="title"))
    column.addWidget(c.label("Subtítulo", role="subtitle"))
    column.addWidget(c.label("Texto normal, que es lo que se lee casi siempre."))
    column.addWidget(c.Note("Letra chica que explica algo sin ser un aviso."))
    column.addWidget(c.label("96ccc62287f54cfa28c8ec24c6f960b7", role="mono"))

    verdicts = QHBoxLayout()
    for indication, meaning in (("VALID", "El documento no se modificó."),
                                ("INDETERMINATE", "No se puede afirmar que sea válida."),
                                ("INVALID", "No confíes en este archivo.")):
        verdict = c.Verdict()
        verdict.set_indication(indication, meaning)
        verdicts.addWidget(verdict)
    column.addLayout(verdicts)

    card = c.Card("Firmante")
    rows = c.KeyValueList()
    rows.set_rows([
        c.Row("Nombre", "MARÍA DE LOS ÁNGELES RODRÍGUEZ FERNÁNDEZ DE LA CUESTA"),
        c.Row("Cédula", "DNI12345672"),
        c.Row("Huella", samples._SHA256, role="mono"),
        c.Row("Cadena de confianza", "llega a la raíz nacional", mark=True),
        c.Row("Otra cosa", "no llega", mark=False),
    ])
    card.add(rows)
    column.addWidget(card)

    checks = c.CheckList()
    checks.set_checks([
        c.CheckItem("PASS", "signature cryptographically valid"),
        c.CheckItem("WARN", "pcscd running", "installed but not running",
                    "sudo systemctl start pcscd"),
        c.CheckItem("FAIL", "certificate chain to trusted root", "no path to a trusted root",
                    "Actualizá los certificados desde Diagnóstico."),
        c.CheckItem("PASS", "some future check", "un nombre que firmauy agregó después"),
    ])
    column.addWidget(checks)

    for tone, text in (("ok", "Los archivos ya firmados quedaron guardados."),
                       ("warn", "Esto usa internet y puede demorar."),
                       ("bad", "No se pudo leer el módulo PKCS#11.")):
        banner = c.Banner()
        banner.show_message(text, tone=tone)
        column.addWidget(banner)

    column.addStretch()
    return page


def _long_values() -> QWidget:
    """The same rows at the narrowest the app ever gets.

    Named risk number one of this conversion, and every fixture in the repo is short, so it would
    never show up on its own. The width is pinned rather than left to the window: what needs
    reviewing is the grid at the app's minimum, not the grid at whatever size the storybook
    happens to be.
    """
    from firmauy_desktop.ui import components as c

    page = QWidget()
    column = QVBoxLayout(page)

    card = c.Card("Al ancho mínimo de la ventana")
    card.setFixedWidth(416)
    rows = c.KeyValueList()
    rows.set_rows([
        c.Row("Nombre", "MARÍA DE LOS ÁNGELES RODRÍGUEZ FERNÁNDEZ DE LA CUESTA"),
        c.Row("Emisor", "CN=Autoridad Certificadora Raíz Nacional de Uruguay, "
                        "O=Presidencia de la República, C=UY"),
        c.Row("Huella", samples._SHA256, role="mono"),
        c.Row("Serie", "5f:2a:c1:00:9b:3e:47:d8:12:aa:6c:90:31:be:04:77", role="mono"),
        c.Row("Cadena de confianza", "llega a la raíz nacional", mark=True),
    ])
    card.add(rows)
    column.addWidget(card)
    column.addStretch()
    return page


def all_states() -> list[State]:
    return ([State("components", "Componentes", _gallery),
             State("components-largos", "Componentes: valores largos", _long_values)]
            + _sign_states() + _verify_states() + _identity_states()
            + _doctor_states() + _advanced_states())


# --- the window -------------------------------------------------------------

class Storybook(QMainWindow):
    def __init__(self, states: list[State]) -> None:
        super().__init__()
        self.setWindowTitle("FirmaUY Desktop, estados")
        self.resize(1180, 780)

        self._nav = QListWidget()
        self._nav.setMaximumWidth(280)
        self._stack = QStackedWidget()
        self._views: list[QWidget] = []

        for state in states:
            self._nav.addItem(state.title)
            page = QWidget()
            layout = QVBoxLayout(page)
            heading = QLabel(state.key)
            heading.setEnabled(False)
            layout.addWidget(heading)
            view = state.build()
            self._views.append(view)
            layout.addWidget(view)
            self._stack.addWidget(page)

        self._nav.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._nav.setCurrentRow(0)

        central = QWidget()
        row = QHBoxLayout(central)
        row.addWidget(self._nav)
        row.addWidget(self._stack, stretch=1)
        self.setCentralWidget(central)

    def closeEvent(self, event) -> None:
        for view in self._views:
            shutdown = getattr(view, "shutdown", None)
            if shutdown is not None:
                shutdown()
        super().closeEvent(event)


def shoot(states: list[State], out: Path) -> int:
    """Render each state to a PNG. Also the strongest construction check the project has: it
    builds every screen in every state, headless, and a component that cannot survive an empty
    list fails here rather than in front of somebody."""
    out.mkdir(parents=True, exist_ok=True)
    for state in states:
        view = state.build()
        view.resize(*_SHOT_SIZE)
        view.grab().save(str(out / f"{state.key}.png"))
        shutdown = getattr(view, "shutdown", None)
        if shutdown is not None:
            shutdown()
    return len(states)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shot", metavar="DIR", help="write a PNG per state and exit")
    parser.add_argument("--only", metavar="PREFIX", default="",
                        help="only the states whose key starts with this")
    parser.add_argument("--scheme", choices=("light", "dark", "both"), default="light",
                        help="which colour scheme to render")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    settings.apply_identity(app)
    # The defaults, as a fresh CI runner has them, rather than whatever the person running this
    # chose: a state is a fixture, and the screens read the settings as they are built.
    from tools import sandbox
    sandbox.isolate_settings()
    app.setStyle(os.environ.get("FIRMAUY_STYLE", "Fusion"))
    theme.apply(app, "light" if args.scheme == "both" else args.scheme)

    states = [s for s in all_states() if s.key.startswith(args.only)]
    if not states:
        print(f"ningún estado empieza con {args.only!r}", file=sys.stderr)
        return 2

    if args.shot:
        schemes = ("light", "dark") if args.scheme == "both" else (args.scheme,)
        written = 0
        for scheme in schemes:
            theme.set_preference(scheme)
            written += shoot(states, Path(args.shot) / scheme)
        print(f"{written} estados en {args.shot}")
        return 0

    window = Storybook(states)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

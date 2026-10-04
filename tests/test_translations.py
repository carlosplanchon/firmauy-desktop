# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Qt's own words, in Spanish.

The app names every string it draws. Qt draws a few of its own, the right-click menu of a text
field above all, and those come from a translation file that has to be loaded on purpose.

Every test that installs it takes it out again: the application is shared by the whole suite, and
test_dialogs needs Qt's untranslated words to tell a named button from one left to Qt.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QLineEdit

from firmauy_desktop import app


def _menu() -> list[str]:
    """The entries of a text field's right-click menu, without their shortcuts."""
    field = QLineEdit()
    menu = field.createStandardContextMenu()
    return [action.text().split("\t")[0] for action in menu.actions() if action.text()]


def test_without_it_the_menu_is_english(qapp):
    """The premise, held here so that a Qt speaking Spanish on its own would show up."""
    assert "Select All" in _menu()


def test_once_installed_qts_own_words_are_spanish(qapp):
    translator = app.install_qt_translations(qapp)
    try:
        assert translator is not None, "PySide6 ships qtbase_es, so this should have found it"
        words = _menu()
        assert "Seleccionar todo" in words and "&Copiar" in words, words
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "Cancelar"
    finally:
        if translator is not None:
            qapp.removeTranslator(translator)


def test_a_missing_translation_is_no_reason_not_to_start(qapp, tmp_path):
    """A Qt without its translation files: English menus, and nothing half installed."""
    assert app.install_qt_translations(qapp, folder=str(tmp_path)) is None
    assert "Select All" in _menu()


def test_the_app_installs_it_before_it_builds_the_window():
    """The function is half of it. main() not calling it is what a refactor loses without any
    other test noticing, and the frozen build's selftest calls the function, not main()."""
    import ast
    import inspect

    calls = sorted((node.lineno, node.func.id)
                   for node in ast.walk(ast.parse(inspect.getsource(app.main)))
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name))
    order = [name for _line, name in calls]

    assert "install_qt_translations" in order
    assert order.index("install_qt_translations") < order.index("MainWindow")


def test_the_translations_selftest_passes_from_source(qapp, capsys, monkeypatch):
    """The check a frozen build runs, exercised here so the check itself cannot rot."""
    monkeypatch.setattr(app, "QApplication", lambda argv: qapp)

    assert app._selftest_translations() == 0
    assert "en castellano" in capsys.readouterr().out
    assert "Select All" in _menu(), "the selftest left its translator installed"


def test_the_translations_selftest_fails_when_the_file_is_missing(qapp, capsys, monkeypatch,
                                                                    tmp_path):
    """Otherwise it is a check that always says yes, which is worse than no check at all."""
    real = app.install_qt_translations
    monkeypatch.setattr(app, "QApplication", lambda argv: qapp)
    monkeypatch.setattr(app, "install_qt_translations", lambda a: real(a, folder=str(tmp_path)))

    assert app._selftest_translations() == 1
    assert "no encontrado" in capsys.readouterr().out

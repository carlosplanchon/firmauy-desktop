# Copyright 2026 Carlos Andrés Planchón Prestes
# Licensed under the Apache License, Version 2.0

"""Tests for the Spanish the app says for firmauy's English vocabulary.

What used to be here was a suite about escaping: eight tests proving that a signer's name
carrying `<img src="file:///etc/passwd">` came out inert. They are gone along with the module
they tested. Nothing renders markup any more, so there is no escaping to get right, and the
replacement claim lives beside each component that shows the value: the hostile name arrives
**intact**, which is a stronger thing to be able to say.

What survives is the part that was never about markup, and it is the part that matters: firmauy
is free to add a check, and a name nobody has translated yet has to come out in English rather
than vanish from the list.
"""

from __future__ import annotations

import inspect

import pytest

from firmauy_desktop import labels


@pytest.mark.parametrize("name", ["pcscd running", "certificate chain to trusted root"])
def test_a_known_check_is_glossed(name):
    assert labels.check_label(name) != name


def test_an_unknown_check_falls_back_to_the_raw_name():
    """A check firmauy adds later must degrade to English, not disappear. This is the reason no
    logic anywhere in the app switches on a check name."""
    assert labels.check_label("some future check") == "some future check"


def test_the_indications_are_the_three_words_the_app_says():
    assert labels.indication_label("VALID") == "VÁLIDO"
    assert labels.indication_label("INDETERMINATE") == "INDETERMINADO"
    assert labels.indication_label("INVALID") == "INVÁLIDO"


def test_an_unknown_indication_falls_back():
    assert labels.indication_label("SOMETHING_NEW") == "SOMETHING_NEW"
    assert labels.indication_label("") == "?"


def test_this_is_content_and_not_part_of_the_visual_system():
    """It moved out of theme.py for a reason. Wording belongs next to the other things the app
    says, not next to the colours it says them in.

    Asserted on what the module depends on rather than on what it mentions: the first version of
    this test failed on its own docstring, which is a good reminder that grepping source text is
    not the same as checking a dependency.
    """
    imports = [line for line in inspect.getsource(labels).splitlines()
               if line.startswith(("import ", "from "))]

    assert not [line for line in imports if "PySide6" in line]
    assert not [line for line in imports if "firmauy_desktop.ui" in line]


@pytest.mark.parametrize("detail, spanish", [
    ("installed but not running", "instalado pero no está corriendo"),
    ("not found", "no se encontró"),
])
def test_a_known_detail_is_glossed(detail, spanish):
    assert labels.check_detail(detail) == spanish


@pytest.mark.parametrize("detail", [
    "9.9.9 (Python 3.14.6)",           # a version, any version: it falls through as data
    "ACS ACR38U-CCID 00 00",           # a reader's name
    "/usr/lib/pkcs11/libgclib.so",     # a module path
    "algo que firmauy dirá mañana",
])
def test_a_detail_that_is_data_comes_through_untouched(detail):
    """The common case, and the reason this falls through rather than demanding a translation:
    most details are not English at all, and translating a path would be wrong."""
    assert labels.check_detail(detail) == detail


def _doctor_strings() -> tuple[set[str], set[str]]:
    """Every literal detail and fix firmauy's doctor can put on the screen.

    Walked with ast rather than grepped. A regex over part of the file is how "none found" was
    missed, and then removed from a fixture for being imaginary when it was not.
    """
    import ast
    import inspect

    from firmauy import _shared

    details, fixes = set(), set()
    for node in ast.walk(ast.parse(inspect.getsource(_shared))):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "add"):
            continue
        if len(node.args) >= 3:
            found = _detail_text(node.args[2])
            if found is not None:
                details.add(found)
        for keyword in node.keywords:
            # Only these two. add() also takes sensitive=, and a bare `else` swept True into the
            # set of things that need translating.
            if keyword.arg not in ("detail", "fix"):
                # add() also takes sensitive=, and a bare else swept True into the set of things
                # that need translating.
                continue
            found = _detail_text(keyword.value)
            if found is not None:
                (details if keyword.arg == "detail" else fixes).add(found)
    return details, fixes


def _detail_text(node) -> str | None:
    """The English a detail carries, whether it is written out or built.

    firmauy sends ``f"not found: {pkcs11_lib}"`` as one f-string, so the English half is not a
    literal anywhere and the first version of this walk could not see it. That made a test named
    for completeness blind to exactly the kind of string a table of glosses cannot hold.
    """
    import ast

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # The leading literal of an f-string, up to where the data starts.
        head = node.values[0] if node.values else None
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value.removesuffix(": ").strip() or None
    return None


def test_every_detail_the_doctor_can_show_is_glossed():
    """Completeness, which the "is it real" test below cannot say anything about.

    Diagnóstico is the screen where English shows through most, and its set is closed: firmauy
    builds these checks in one function with literal strings.
    """
    details, _fixes = _doctor_strings()
    assert details - set(labels.CHECK_DETAIL) == set()


def test_every_repair_the_doctor_can_suggest_is_glossed():
    """These are instructions somebody is meant to follow, and they were all in English."""
    _details, fixes = _doctor_strings()
    assert fixes - set(labels.CHECK_FIX) == set()


def test_the_repairs_keep_their_commands_verbatim():
    """A shell command is not prose. Translating one is how somebody ends up pasting a line that
    does nothing."""
    for english, spanish in labels.CHECK_FIX.items():
        for command in ("sudo systemctl enable --now pcscd", "sudo pacman -S pcsclite ccid",
                        "yay -S cedula-uruguay-pkcs11"):
            if command in english:
                assert command in spanish, english


def test_the_glossed_details_are_ones_firmauy_actually_emits():
    """Read out of firmauy rather than guessed. A gloss for a string it never sends is dead
    weight that reads as coverage."""
    import pathlib

    import firmauy

    root = pathlib.Path(firmauy.__file__).parent
    corpus = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                       for p in root.rglob("*.py"))
    missing = [detail for detail in labels.CHECK_DETAIL if detail not in corpus]
    assert missing == []


@pytest.mark.parametrize("detail, spanish", [
    # firmauy sends this one as an f-string, so the English half is in no table anywhere.
    ("not found: /usr/lib/pkcs11/libgclib.so", "no se encontró: /usr/lib/pkcs11/libgclib.so"),
])
def test_a_built_detail_gets_its_prefix_glossed(detail, spanish):
    assert labels.check_detail(detail) == spanish


@pytest.mark.parametrize("detail", [
    "GemP15-1: algo",                   # a token label can hold a colon
    "algo desconocido: con dato",
])
def test_a_colon_alone_does_not_earn_a_translation(detail):
    """Only a prefix that is actually in the table. Otherwise any string with a colon in it
    becomes a guess about which half is English."""
    assert labels.check_detail(detail) == detail


# --- the timestamp ----------------------------------------------------------

def test_the_names_firmauy_uses_for_a_timestamp_are_the_ones_glossed():
    """Against firmauy's own constants, not against a copy of their text. These two are strings
    in a released core: retyping them here is how a gloss silently stops matching."""
    from firmauy.verify_common import TS_PRESENT, TS_TRUSTED

    assert labels.check_label(TS_PRESENT) != TS_PRESENT
    assert labels.check_label(TS_TRUSTED) != TS_TRUSTED


@pytest.mark.parametrize("detail, expected", [
    ("genTime 2026-07-30T14:32:11+00:00 (asserted by the TSA, not verified)",
     "genTime 2026-07-30T14:32:11+00:00 (lo afirma la TSA, sin verificar)"),
    ("genTime 2026-07-30T14:32:11+00:00 (trusted)",
     "genTime 2026-07-30T14:32:11+00:00 (de confianza)"),
    # No parenthesised half at all, which is the shape firmauy would send if it ever stopped
    # qualifying the time.
    ("genTime 2026-07-30T14:32:11+00:00", "genTime 2026-07-30T14:32:11+00:00"),
])
def test_a_gen_time_detail_keeps_its_instant_and_translates_the_rest(detail, expected):
    """The ISO stamp comes through byte for byte. It is the one number on the screen somebody
    might paste into a mail, and this is the technical fold, where exactness beats prettiness."""
    assert labels.check_detail(detail) == expected


def test_an_unknown_aside_on_a_gen_time_survives():
    assert labels.check_detail("genTime 2026-07-30T14:32:11+00:00 (something new)") == (
        "genTime 2026-07-30T14:32:11+00:00 (something new)")


def test_a_gen_time_is_shown_in_the_readers_own_clock():
    """RFC 3161 puts the instant in UTC. Rendering 14:32 to somebody whose clock says 11:32 is
    the one place in the app where that is not a detail: the date is the whole point of the row."""
    from datetime import datetime, timedelta, timezone

    utc = datetime(2026, 7, 30, 14, 32, 11, tzinfo=timezone.utc)
    said = labels.timestamp_when(utc)

    local = utc.astimezone()
    assert f"{local:%d/%m/%Y %H:%M}" in said
    assert "hora local" in said

    # The same instant in another zone is the same instant, and must read the same.
    assert labels.timestamp_when(utc.astimezone(timezone(timedelta(hours=9)))) == said


def test_a_naive_gen_time_is_read_as_utc_and_not_as_local_time():
    """The bug this closes: astimezone() on a naive value assumes the machine's zone, which would
    shift a UTC instant by the offset and report a time that is simply wrong."""
    from datetime import datetime, timezone

    naive = datetime(2026, 7, 30, 14, 32, 11)
    aware = naive.replace(tzinfo=timezone.utc)

    assert labels.timestamp_when(naive) == labels.timestamp_when(aware)


def test_no_time_says_nothing():
    assert labels.timestamp_when(None) == ""


class _Stamp:
    """A backend.Timestamp in the shape timestamp_value reads, without importing Qt through it."""

    def __init__(self, *, intact=True, valid=True, trusted=None, gen_time=None, detail=""):
        self.intact, self.valid, self.trusted = intact, valid, trusted
        self.gen_time, self.detail = gen_time, detail

    @property
    def sound(self):
        return bool(self.intact and self.valid)


def _when():
    from datetime import datetime, timezone
    return datetime(2026, 7, 30, 14, 32, 11, tzinfo=timezone.utc)


def test_no_stamp_is_said_plainly_and_is_not_called_a_problem():
    assert labels.timestamp_value(None) == labels.NO_TIMESTAMP
    for word in ("error", "falla", "inválid", "roto"):
        assert word not in labels.NO_TIMESTAMP.lower()


def test_a_sound_stamp_is_never_called_trusted():
    """The distinction firmauy went to the trouble of restoring, spent. With no anchors the TSA
    chain was never evaluated, so the row attributes the date rather than vouching for it."""
    said = labels.timestamp_value(_Stamp(gen_time=_when(), trusted=None))

    assert "según la TSA" in said
    assert "confianza" not in said


def test_a_stamp_whose_chain_did_reach_a_root_drops_the_hedge():
    said = labels.timestamp_value(_Stamp(gen_time=_when(), trusted=True))

    assert said == labels.timestamp_when(_when())
    assert "según la TSA" not in said


def test_a_chain_that_was_looked_at_and_failed_says_so():
    """False is a different claim from None, and this is where the two stop looking alike."""
    said = labels.timestamp_value(_Stamp(gen_time=_when(), trusted=False))

    assert "no llega a una raíz de confianza" in said
    assert labels.timestamp_when(_when()) in said        # the date is still reported


def test_a_broken_stamp_reports_why_in_spanish():
    """The specific reason, not a generic one. firmauy 1.13.0 stopped sending "the timestamp token
    is broken" from the PDF and CMS paths and sends what actually failed instead, which is the
    difference between a row somebody can act on and one they can only be alarmed by."""
    said = labels.timestamp_value(_Stamp(intact=False, valid=False, gen_time=_when(),
                                         detail="timestamp token signature is invalid"))

    assert said == "la firma del sello de tiempo no es válida"


def test_a_broken_stamp_never_offers_its_date():
    """A token that does not hold up asserts nothing, and its genTime is whatever an attacker
    felt like putting there. Printing it beside a cross would be handing over the number anyway."""
    said = labels.timestamp_value(_Stamp(intact=True, valid=False, gen_time=_when(),
                                         detail="timestamp token signature is invalid"))

    assert "30/07/2026" not in said


def test_a_broken_stamp_with_no_detail_still_says_something():
    assert labels.timestamp_value(_Stamp(intact=False, valid=False)) != ""


def test_a_stamp_with_no_readable_time_does_not_pretend_to_have_one():
    said = labels.timestamp_value(_Stamp(gen_time=None, trusted=None))

    assert "sin fecha legible" in said


def test_the_law_is_quoted_by_number_and_names_no_provider():
    """Naming today's accredited providers would be wrong the day the UCE accredits a third, and
    a firmauy fixture naming a real one would read as an endorsement."""
    assert "18.600" in labels.TIMESTAMP_MEANING
    assert "UCE" in labels.TIMESTAMP_MEANING
    for provider in ("Abitab", "Antel", "DigiCert"):
        assert provider not in labels.TIMESTAMP_MEANING


def test_the_unexpected_failure_points_where_the_detail_actually_is():
    """The record is on, so the message says where to look rather than what to switch on."""
    said = labels.unexpected("La firma", recorded=True)

    assert said.startswith("La firma falló de una forma inesperada.")
    assert "registro de actividad" in said and "Ajustes" in said
    assert "activá" not in said                  # already on: nothing to turn on


def test_the_unexpected_failure_offers_the_record_when_there_is_none():
    """Off is the shipped default, so this is the branch most people meet. There is nothing to
    read yet, and the useful advice is how to have something next time."""
    said = labels.unexpected("La firma", recorded=False)

    assert said.startswith("La firma falló de una forma inesperada.")
    assert "activá el registro de actividad en Ajustes" in said


def test_the_unexpected_failure_works_without_a_subject():
    """One screen writes it into a log pane where the sentence has no room for a subject."""
    for recorded in (True, False):
        said = labels.unexpected(recorded=recorded)
        assert said.startswith("Falló de una forma inesperada.")


def test_no_screen_sends_anybody_to_a_console_the_bundle_does_not_have():
    """The claim this replaced, kept as a rule rather than as six edits.

    ``packaging/firmauy-desktop.spec`` builds with ``console=False``, which is the reason the
    activity record exists at all: on a packaged build the traceback PySide6 prints has nowhere
    to go. Six screens told the person to go read it there anyway. Nothing asserted on those
    strings, so they were free to say anything, and what they said was false in the product.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src"
    guilty = []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Docstrings are excluded, and deliberately: prose about the rule can quote the very
        # sentence it forbids, and a quote inside an explanation is not a message. What the
        # rule is about is text on its way to a screen.
        #
        # By node identity, not by value. Equal strings can be one interned object, so comparing
        # what they say would let a real message hide behind a docstring that happened to match.
        docstrings = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))

        guilty += [f"{path.relative_to(src)}:{node.lineno}" for node in ast.walk(tree)
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)
                   and "la consola" in node.value and id(node) not in docstrings]

    assert guilty == [], f"todavía mandan a la consola: {guilty}"

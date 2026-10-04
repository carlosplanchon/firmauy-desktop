# Contributing to FirmaUY Desktop

Bug reports, questions and pull requests are welcome. This document covers the mechanics. Running
from source and packaging a bundle are in the [README](README.md).

For security problems, do not open an issue: see [SECURITY.md](SECURITY.md).

## Developer Certificate of Origin (required)

This app puts a national ID card's signing key in front of people who are not developers, so the
provenance of its code matters. Every commit must be signed off under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/):

```bash
git commit -s
```

That adds a `Signed-off-by: Your Name <your@email>` trailer, certifying that you wrote the change or
otherwise have the right to submit it under the project's license (Apache-2.0). Use your real name
and a working email. Pull requests with unsigned commits will be asked to add the sign-off:

```bash
git commit --amend --no-edit -s     # fix the last commit
```

Signing your commits cryptographically (`git commit -s -S`) is welcome on top of that, but not
required.

## What not to break

- **The PIN is asked for last.** firmauy checks the reader, the card and the certificate before the
  app prompts, so a setup that cannot sign never costs one of the card's limited tries. The prompt
  is driven by a `pin_provider` callback for exactly that reason. Do not go back to collecting the
  PIN up front, and do not keep it after handing it over. `pinflow.PinHandshake` owns that round
  trip and its tests are the ones to read first.
- **Card work stays off the UI thread.** Signing and reading the card block for seconds. They run in
  a `QThread` through `tasks.TaskRunner`, and the PIN dialog is opened by the UI thread through a
  signal, because Qt forbids touching widgets from a worker.
- **A running thread outlives whatever started it.** Letting Python collect a live `QThread` aborts
  the process. `tasks.py` holds every started task until its thread really ends, every screen has a
  `shutdown()`, and `MainWindow.closeEvent` calls them. Do not remove any of the three.
- **One lock for the card.** firmauy cannot read the cédula while a signing session is open on the
  same card: both go through pcscd and conflict. Screens that touch the reader take
  `tasks.CardLock` from the window and release it when their work settles.
- **`backend.py` is the only seam.** The views never import `firmauy` directly: the backend calls
  `firmauy.api` and turns results and typed errors into small dataclasses and Spanish messages the
  views render. Keeping that seam is what makes the app testable without a card.
- **Every failure carries a tag.** `backend._kind` returns a stable `error_kind`, so the UI branches
  on a string like `needs_original` rather than on the wording of a Spanish sentence.
- **Untrusted text is never markup.** A signer's name comes out of a certificate inside a file
  somebody else sent the user. The app used to escape it by hand on the way into a RichText label,
  which works until somebody forgets. Every label is built by `ui/components.py` now and is
  `PlainText`, so there is nothing to escape and nothing to forget: a name that says
  `<img src="file:///etc/passwd">` is a name that says that. Do not set `TextFormat.RichText` on
  anything, and reach for `components.label()` before building a `QLabel` by hand. A tooltip is
  the exception that has no format to set: Qt guesses, and anything that looks like markup is
  markup, so a tooltip carrying a file name or anything else from outside goes through
  `components.plain_tooltip()`. Qt's ready-made dialogs are the other trap: `QInputDialog` draws
  its prompt in a label of its own on AutoText, which is why the PIN prompt, whose text names the
  file being signed, is built in `dialogs.py` instead.
- **Colour comes from the stylesheet.** Set an `objectName` or a `tone`/`role` property and let
  `assets/app.qss` decide. No hex value belongs outside `ui/tokens.py`, and no widget carries its
  own `setStyleSheet`: there is exactly one in the app, inside `theme.apply()`, and a test that
  keeps it that way. A property set after a widget is polished changes nothing until it is
  repolished, which is what `components.set_tone` is for.
- **Never switch on a verification check's name.** The set differs per format and firmauy is free
  to add more, so render them generically and let an unknown one through in English. The Spanish
  gloss lives in `labels.py` and always falls back to the raw name.

## The visual system

Nothing about how a screen looks is decided in the screen.

| Where | What lives there |
| --- | --- |
| `ui/tokens.py` | Colours, spacing, radii, the type scale, icon sizes. No Qt, so it is testable as data. The **only** place a hex value belongs. |
| `ui/theming.py` | The runtime: which scheme is active, building and applying the stylesheet, one colour lookup. |
| `assets/app.qss` | The stylesheet, as a `string.Template`. Qt has no variables and no `em`, so the tokens are substituted in and the type scale is computed in Python against the platform's own font size. |
| `ui/components.py` | The widgets screens are built from: `Screen`, `Card`, `Banner`, `KeyValueList`, `CheckList`, `Verdict`, `Note`, `label()`. |
| `ui/icons.py`, `assets/icons/` | Hand-written SVG, tinted to a token at draw time. |
| `labels.py` | The Spanish for firmauy's English. Content, not appearance. |

Adding something:

- **A screen**: subclass `components.Screen`, which brings the title, the one line saying what the
  screen is for, and the scrolling body capped at a readable width. Add it to `_SCREENS` in
  `main_window.py`, which is the one list that decides order, labels and icons.
- **A colour**: add a token to *both* schemes in `tokens.py`. A token that exists only in light is
  a stylesheet that only builds in light, and a test says so.
- **An icon**: hand-write the SVG. **Qt renders SVG Tiny 1.2**: no `<style>` block, no CSS classes,
  no filters, no masks, no `currentColor`. A file using any of them renders as a blank image and
  raises nothing at all, which is why the test counts opaque pixels.
- **A status icon**: give it an entry in `STATUS_TONE`, `STATUS_ICON` *and* `STATUS_SPOKEN`. The
  last one is not optional: an icon that carries the answer without saying it is the same failure
  as colour alone.

Two traps worth knowing before you hit them:

- A dynamic property set after a widget has been polished changes nothing until it is repolished.
  Use `components.set_tone` / `set_role`, never a bare `setProperty`.
- A `$typo` in the stylesheet is invisible: Qt drops the rule it cannot parse without a word. The
  template uses `substitute`, not `safe_substitute`, so a typo raises at startup instead.

## Looked at by eye, per change

The suite checks contrast, that every icon draws something, that no label is left on AutoText and
that every control can be reached with a keyboard. It cannot check whether the result looks right.
For anything that touches a screen:

```bash
uv run python -m tools.storybook --shot shots/ --scheme both   # every state, both schemes
uv run python -m tools.storybook                               # or interactively
```

Then look at:

- **Both schemes**, side by side from that folder. A token missing from dark shows up nowhere else.
- **The window at its minimum and very wide.** The reading column is capped, so wide is about what
  happens to the space beside it.
- **150%**: `QT_SCALE_FACTOR=1.5 uv run firmauy-desktop`.
- **Long real strings.** Every fixture is short and will not show a wrapping problem. There is a
  storybook state for this (`components-largos`), and `verify.long` and `identity.long`.
- **A keyboard, only.** Tab through it. Anything you can reach with a mouse and not with Tab is a
  bug even if the screenshot is perfect.

Once per release, with a screen reader, listen to the verdict on Verificar and one failing check
on Diagnóstico. Those are the two places where the answer is carried by an icon.

## Pull requests

- Run the suite and the linter before pushing:

  ```bash
  uv sync
  QT_QPA_PLATFORM=offscreen uv run pytest
  uvx ruff check src/ tests/
  ```

- **Tests must never reach the card.** A conftest fixture replaces every card-touching backend call
  in every view module with one that fails loudly, and a test opts in by replacing what it means to
  exercise through `fake_backend`. That net exists because a test once took an unanticipated code
  path into the real backend and ran a signature against a real cédula with a made-up PIN, which
  spends one of the card's limited tries. If it fires, read it as a bug in the screen before
  reading it as a bug in the test.
- Build screens with the `make_view` fixture, which shuts their workers down the way
  `MainWindow.closeEvent` does.
- Check widget visibility with `isHidden()`: `isVisible()` is always False when no window is shown,
  so it would pass for the wrong reason.
- Never include real personal data: no names, document numbers, MRZ data, photos, certificates or
  unredacted output, in code, fixtures, screenshots, or the pull request itself.
- The interface is in Spanish, since it is for people in Uruguay. Code, comments, commit messages
  and docs are in English. What Qt draws on its own, like the right-click menu of a text field,
  comes from Qt's Spanish translation, which `app.py` loads at start. Still name every button in a
  dialog: a verb says more than Qt's "Sí", and `tests/test_dialogs.py` holds it.
- If a screen changed how it looks, rebuild the README's images so they do not drift from the app:

  ```bash
  uv run python -m tools.screenshots
  ```

  Raising the `firmauy` floor in `pyproject.toml` counts as a change, even though no screen moved:
  Diagnóstico shows the core's version, so the committed image keeps claiming the app runs on
  whatever was installed the day it was last rebuilt. `tools/samples.py` reads that version from
  the installed package rather than carrying a copy of it, which is what makes a rebuild enough.

- If `assets/icon.svg` changed, rebuild the containers Windows and macOS read, which are generated
  from it and are otherwise a committed binary quietly out of date with its source:

  ```bash
  uv run python -m tools.make_icons          # --check to see what would change
  ```

## Checked by hand, once per release

Nothing below can run in CI, and every item is there because getting it wrong costs a card try or
worse:

- The PIN prompt appears only after the card is confirmed, and **exactly once** for a batch of N.
- A deliberately wrong PIN: the "Te quedan N intentos" text is right and N drops by exactly **1**.
  A drop of 2 would mean a double verify, which is the failure this check exists to catch.
- Cancelling the PIN dialog leaves the card usable with its retry counter untouched, and a
  successful signature does not change it either.
- Reading "Mi cédula" while a signature is in flight is refused by the app, not by pcscd.
- PKCS#11 mode against the real middleware: the Avanzado screen lists the token and certificate,
  and `attempts_remaining` is None on that path (the middleware does not report it).
- A batch where one file fails: the ones before it are signed, listed, and said to be valid.
- Cancelling a long batch: it stops after the file it was on, not instantly, and says which
  files were kept. firmauy only checks between files, so a batch of one large PDF has no
  Cancelar button at all.
- Unplug the reader and run Diagnóstico: the check list comes back short, because firmauy returns
  early, and nothing assumes a fixed number of rows.

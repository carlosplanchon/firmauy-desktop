# Security Policy

This app signs documents with the Uruguayan national ID card and handles the card's PIN. Security
reports are taken seriously, within the limits of a community project. Thank you for reporting
responsibly.

## Reporting a vulnerability

Please do **not** open a public issue or pull request for a security problem.

Email **carlosplanchon@cognitialabs.com** with `[SECURITY]` in the subject. Include what you can: a
description, steps to reproduce, a proof of concept, the affected version and your assessment of the
impact. Reports in Spanish or English are equally welcome.

## What counts

The app is a front-end: most of the cryptography, and all of the card protocol, live in
[FirmaUY](https://github.com/carlosplanchon/firmauy). What belongs here is everything the graphical
layer adds on top:

- **PIN handling.** Any path that writes the PIN to disk, a log, a crash report, a window title, an
  environment variable or a subprocess, or that keeps it in memory after the signature is done.
- **Signing something other than what the user saw.** A file swapped between the moment it is
  chosen and the moment it is signed, a status message that reports a signature that did not
  happen, or an output written somewhere the user did not choose.
- **Leaking the cardholder's data.** The "Mi cédula" screen reads personal data and a photo, and
  the Avanzado screen reads the certificate. Any path that persists or transmits them without the
  user asking is a finding. Two places deserve particular attention: the settings store, which
  deliberately holds nothing personal and no recent-files list, and "Copiar diagnóstico", which
  redacts the detail of every check firmauy flags as able to carry the holder's own name (some
  PKCS#11 modules use it as the token label). A check with no flag is treated as sensitive.
  A third place joins them: the activity record, which is off unless the person turns it on and
  writes the shape of an operation rather than its subject. The rule is about where a value came
  from and not about what it looks like: anything reaching it that identifies a document the app
  handled, a cardholder, or a certificate is a finding, and so is anything written while it is
  off. Two things are deliberately not findings, and both are about the app rather than about the
  person using it: a count, since how many files a batch signed is what the record is for, and
  the name of one of this program's own source files, since a crash is recorded as the line it
  came from.
- **Rendering untrusted text as markup.** The verification screens display names taken from a
  certificate inside a file somebody else sent the user, and the app shows file names, which on
  Linux can contain anything. None of it is meant to be read as markup. Every label, every
  confirmation dialog and the PIN prompt, which names the file about to be signed, are plain
  text. A tooltip, which Qt reads as markup whenever the text looks like it, takes a value from
  outside only through `components.plain_tooltip()`. The one place that renders HTML is Acerca
  de, so its links can be clicked, and it escapes everything before linking anything. A value
  from outside that ends up rendered as markup anywhere is a finding, even if it only breaks the
  layout.
- **The packaged build.** Anything about the PyInstaller bundle that lets code outside the bundle
  run inside it (a hijacked import path, a writable location on the search path).

## Deliberately not offered

Some of firmauy's options are reachable from the library and not from this app, because a graphical
front-end is where they stop being useful and start being dangerous:

- **A custom anchor for the signer's chain** (`ca_file`). A dialog that accepts a CA file turns
  "install this certificate" into a working attack: a forged signature would then render as VÁLIDO
  to somebody who had no way to tell. Verification uses the anchors firmauy ships, refreshable from
  Diagnóstico against the official sources with pinned fingerprints. The anchors for a *timestamp's*
  chain are a different decision and this app does offer them, under "Offered, and what it costs".
- **Skipping the chain check** (`no_trust`). It can only turn VALID into INDETERMINATE, so it is a
  debugging switch with no use here.
- **A PIN for listing certificates.** Cédula tokens do not gate that list, and prompting would
  spend the card's limited tries to read public data.

Proposals to add any of these are welcome as issues, not as quiet pull requests.

Out of scope here (report upstream instead):

- Signing, verification, the card protocol and the PIN retry guards:
  [FirmaUY](https://github.com/carlosplanchon/firmauy/security).
- The cédula card, AGESIC services, the official validator, and the proprietary PKCS#11 middleware.
- The cédula driver inside OpenSC: [OpenSC's security process](https://github.com/OpenSC/OpenSC/security).
- Issues that require an already-compromised machine, since the app runs with the user's own
  privileges and reads the card the user inserted.

## Offered, and what it costs

One option of that same family is reachable, and naming it here is better than a policy that
describes some other app:

- **A custom anchor for a timestamp's chain** (`tsa_ca`, "Certificado de la TSA" in Ajustes). The
  same shape of decision as `ca_file`, offered anyway, because refusing it would mean a stamp from
  an accredited Uruguayan provider can never be validated, and that is the stamp
  [Ley 18.600 art. 6](https://www.impo.com.uy/bases/leyes/18600-2009/6) makes legally meaningful.
  Its root is in no public bundle, since it arrives with the subscription.

What accepting a stamping authority buys whoever handed over the PEM, stated exactly: firmauy judges
the signer's certificate at the time the stamp asserts rather than at now, so a signature made with
an **expired or revoked** certificate can read VÁLIDO. That is the whole of the exposure. It cannot
make a broken signature verify, or a forged chain trusted, because signer anchors and TSA anchors
are separate validation contexts that never contaminate each other. Both halves are stated and
tested upstream as invariants 4 and 5 of
[firmauy's timestamp invariants](https://github.com/carlosplanchon/firmauy/blob/main/docs/security-invariants.md).

Two locks stand in front of it, and a path that reaches `tsa_ca` without both is a finding. It does
nothing until "comprobar de dónde viene el sello" is turned on in Verificar, which is off by default
because nobody has said they accept the bundled public roots as timestamping authorities. And an
empty field means those bundled roots, never the operating system's own store.

A second option is about where the app may connect rather than whom it trusts:

- **Reaching the local network** (`allow_private_network`, "Permitir servidores de la red local"
  in Ajustes). firmauy sends the timestamp request and the revocation lookups to public addresses
  only, so a URL cannot carry a request into the network the computer sits on. Offered because a
  TSA or a CRL/OCSP mirror inside that network is a real setup, and without the option the app
  cannot use one.

What it costs, stated exactly: while it is on, those requests can reach a loopback or private
address. For the timestamp that is the URL the person typed. For revocation it is whatever the
certificates in the file say, and the file came from somebody else, so with revocation turned on in
Verificar a file can make the app send requests to machines on the person's network. A link-local
address, where cloud metadata services answer, stays refused either way, by firmauy. The option is
off by default, and a path that reaches a private address with it off is a finding.

## What to expect

This is a community project with a single maintainer, so the process is honest rather than
corporate:

- Acknowledgment within **7 days**.
- An assessment and, when confirmed, a fix released as soon as practical, coordinated with you.
- Public disclosure once a fix is available, with credit to the reporter unless you prefer
  otherwise.

Only the **latest release** receives security fixes. The app is experimental and not an official
application of the Uruguayan State (see the README), which does not lower the bar: anything
touching the PIN is treated as critical.

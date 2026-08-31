# Security Policy

## Reporting a vulnerability

Use GitHub's private **Report a vulnerability** flow when it is enabled for this
repository. If it is unavailable, open a minimal issue asking the maintainer for
a private contact channel without including vulnerability details. Do not put
credential exposure, account-safety bypasses, unsafe file deletion, or
package-integrity details in a public issue.

Never include Apple-ID passwords, two-factor codes, ipatool session material,
device UDIDs, or copyrighted IPA files in a report. A minimal redacted log and
reproduction steps are sufficient for initial triage.

## Security boundary

appfit delegates App Store authentication and signed requests to ipatool. Its
own config stores device-to-email pairings, account-free compatibility metadata,
downloaded encrypted IPAs, and managed-helper metadata; ipatool owns the login
session. appfit does not decrypt apps, bypass FairPlay, or make third-party IPA
distribution safe or supported.

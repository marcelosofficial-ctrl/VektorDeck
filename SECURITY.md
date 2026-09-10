# Security Policy

VektorDeck is a local-first workstation tool. Security issues that could expose local files, execute unintended commands, weaken loopback-only boundaries, mishandle runtime ownership, or disclose sensitive diagnostics are treated as high priority.

## Supported version

Security fixes target the latest public release and the current `main` branch.

## Reporting a vulnerability

Please do **not** open a public issue for a vulnerability that could put users at risk.

Report it privately to **MarcelosOfficial@gmail.com** with the subject `VektorDeck security report` and include:

- affected version or commit
- operating system and relevant runtime details
- clear reproduction steps
- expected versus observed behavior
- impact you believe is possible
- logs or screenshots only when they do not contain secrets or personal data

I will acknowledge a reproducible report as quickly as practical, investigate it before discussing details publicly, and coordinate disclosure after a fix is available when appropriate.

## Scope

Examples of useful reports include:

- command or argument injection
- unsafe process ownership or termination behavior
- unintended non-loopback network exposure
- arbitrary file access or path-traversal behavior
- sensitive data written to logs or diagnostics
- update or repair flows that can execute untrusted content

General bugs, feature requests, and performance problems can use normal GitHub issues.
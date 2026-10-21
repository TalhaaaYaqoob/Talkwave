# Security Policy

## Supported versions

Security fixes are released for the latest version on the `main` branch. Please upgrade to the latest release before reporting an issue.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Report them privately by opening a [private security advisory](../../security/advisories/new) on GitHub.

Please include as much of the following as you can:

- the type of issue (for example authentication bypass, SSRF, injection, or data exposure),
- the affected file paths, endpoints, or versions,
- step-by-step instructions to reproduce it,
- a proof of concept, if you have one,
- the impact, and how an attacker might exploit it.

## What to expect

| Step | Target time |
| --- | --- |
| Acknowledgement of your report | 3 business days |
| Initial assessment and severity | 7 days |
| Fix or mitigation for critical and high issues | 30 days |

We will keep you updated, credit you in the release notes if you want, and coordinate the disclosure date with you. Please give us a reasonable chance to fix the issue before disclosing it publicly.

## Scope

In scope: the code in this repository, including the backend API, the web UI, and the Docker deployment files.

Out of scope: vulnerabilities in third-party providers (Clerk, Twilio, Stripe, model providers) themselves, denial-of-service from high traffic volume, and issues that require a compromised host or leaked credentials.

## Hardening self-hosted deployments

- Use strong, unique values for every password and secret in `.env`, and set `WS_TICKET_SECRET` explicitly.
- Keep Postgres, Redis, and MinIO bound to localhost or a private network, as the default `docker-compose.yaml` does.
- Put the UI and API behind HTTPS in production.
- Set `CORS_ALLOWED_ORIGINS` to your own domains only.
- Rotate provider API keys immediately if you suspect they have leaked.

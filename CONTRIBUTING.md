# Contributing to TalkWave

Thanks for taking the time to contribute! This guide explains how to propose changes and what we look for in a pull request.

By participating you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a bug** — open a [bug report](../../issues/new?template=bug_report.yml) with steps to reproduce.
- **Suggest a feature** — open a [feature request](../../issues/new?template=feature_request.yml) describing the problem it solves.
- **Improve docs** — typo fixes and clarifications are always welcome, no issue needed.
- **Write code** — look for issues labelled [`good first issue`](../../labels/good%20first%20issue) or [`help wanted`](../../labels/help%20wanted).

For large changes (new providers, schema changes, new pages), please open an issue first so we can agree on the approach before you invest time.

## Development setup

Follow [Local development](README.md#local-development) in the README to run the stack. In short:

| Part | Stack | Location |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic, Pipecat | `api/talkwave-backend/` |
| Frontend | Node 20, Next.js 15, React 19, Tailwind, shadcn/ui | `ui/` |

## Making a change

1. Fork the repository and create a branch from `main`:
   ```bash
   git checkout -b feat/short-description
   ```
2. Make your change, keeping it focused on one thing.
3. Add or update tests where it makes sense.
4. Run the checks below.
5. Commit using [Conventional Commits](https://www.conventionalcommits.org/) (see below).
6. Open a pull request and fill in the template.

### Checks to run before opening a PR

**Backend** (from `api/talkwave-backend/`, with `PYTHONPATH` set as in the README):

```bash
ruff check .
ruff format --check .
pytest
```

**Frontend** (from `ui/`):

```bash
npm run lint
npm run build
```

CI runs the same checks on every pull request.

### Database migrations

Schema changes need an Alembic migration:

```bash
cd api/talkwave-backend
alembic revision --autogenerate -m "describe the change"
```

Review the generated file by hand — autogenerate misses some changes — and make sure `alembic upgrade heads` and `alembic downgrade -1` both work.

### API client

The frontend's typed API client in `ui/src/client/` is generated from the backend's OpenAPI schema. After changing backend routes or schemas, run the backend locally and regenerate it:

```bash
cd ui
npm run generate-client
```

## Commit messages

We use Conventional Commits so the changelog can be generated automatically:

```text
feat(workflow): add retry option to HTTP tool node
fix(telephony): handle Twilio status callback without CallSid
docs: clarify Clerk setup for self-hosting
```

Common types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`.

## Pull request guidelines

- Keep PRs small and focused; split unrelated changes into separate PRs.
- Describe **what** changed and **why**, and link the issue it resolves.
- Include screenshots or a short recording for UI changes.
- Never commit secrets, API keys, `.env` files, or customer data. CI scans for secrets and will fail the build.
- Be responsive to review feedback; maintainers may push small fixes to your branch.

## Adding a provider

New LLM, STT, TTS, or telephony providers are very welcome. A good provider PR:

- registers the provider in `api/talkwave-backend/services/configuration/registry.py`,
- wires it into `api/talkwave-backend/services/pipecat/service_factory.py`,
- documents its environment variables in `api/talkwave-backend/env.template`,
- keeps the provider optional, so TalkWave still starts without its key.

## License

By contributing, you agree that your contributions will be licensed under the project's [BSD 2-Clause License](LICENSE).

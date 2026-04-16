# aisecurity

This repository is connected to `https://github.com/taopaokuzi/aisecurity`.

## Documents

- [Agent Identity & Permission PRD](docs/agent-identity-permission-prd.md)
- [Agent Identity & Permission SRS](docs/agent-identity-permission-srs.md)
- [Agent Identity & Permission Technical Design](docs/agent-identity-permission-technical-design.md)
- [Agent Identity & Permission Development Guide](docs/agent-identity-permission-development-guide.md)

## Task 1

Task 1 completed the initial repository scaffold for the project:

- Added the monorepo skeleton for `apps/`, `packages/`, `migrations/`, `tests/`, and `docker/`
- Added baseline project configuration files including `.gitignore`, `pyproject.toml`, `package.json`, and `apps/web/package.json`
- Marked `TASK-001` as `DONE` and `PASS` in `docs/tasks/TODO.md`

This gives the follow-up tasks a stable directory layout and shared project entry points.

## Task 2

Task 2 added the first runnable service entries and health checks:

- Added the FastAPI runtime entry with root metadata and `GET /health`
- Added the Celery worker bootstrap, registered starter tasks, and a CLI health check
- Added the minimal Next.js app shell and `GET /api/health`
- Updated the root scripts and dependencies so API, Worker, and Web can be started from the repository

## Getting Started

Add your project files here, then commit and push them:

```bash
git add .
git commit -m "init"
git push -u origin main
```

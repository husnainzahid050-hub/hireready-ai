---
competency: cloud_devops
title: Cloud and DevOps Basics
levels: [junior, mid]
---

# Cloud and DevOps Basics

## What interviewers evaluate

- Containers with Docker: images, containers, Dockerfiles, and why they help.
- CI/CD: automated tests and deployments on every change.
- Deployment basics: environments, environment variables, secrets, logs.
- Cloud service models: serverless vs servers vs managed services, and their tradeoffs.
- For mid level: observability, scaling, rollbacks, infrastructure as code.

## Question bank

### Junior

#### What is Docker and why is it useful?

**Strong answer includes:** packages an application with its dependencies into an image that runs the
same everywhere; a container is a running instance of an image; solves "works on my machine";
a Dockerfile describes the build; lighter than virtual machines because containers share the host
kernel.

**Common weak answers:** "Docker is a virtual machine."

**Red flags:** bakes secrets into images.

#### What is CI/CD?

**Strong answer includes:** continuous integration runs lint, type checks, and tests automatically on
every push or pull request so problems are caught early; continuous delivery/deployment
automatically ships passing builds to staging or production; tools like GitHub Actions.

**Common weak answers:** "Automatic deployment" with no mention of tests.

**Red flags:** deploys by copying files to a server manually with no tests.

#### How should an application handle configuration and secrets?

**Strong answer includes:** read config from environment variables (twelve-factor app), keep secrets
out of the code and Git, use the platform's secret store, use separate values per environment, and
validate required config at startup.

**Common weak answers:** "Put them in a config file."

**Red flags:** hard-codes API keys in source code.

### Mid

#### Serverless functions vs a long-running server: what are the tradeoffs?

**Strong answer includes:** serverless scales automatically and costs nothing when idle, but has cold
starts, execution time limits, payload limits, and no in-memory state between requests (state must
live in a database or cache); long-running servers allow WebSockets, background work, and warm
caches but need capacity management.

**Common weak answers:** "Serverless means no servers."

**Red flags:** stores session state in memory on serverless.

#### A deployment broke production. What do you do?

**Strong answer includes:** roll back to the last good version first to restore service; then
investigate with logs, metrics, and request IDs; find the root cause, add a test or check that would
have caught it, and write a short blameless postmortem.

**Common weak answers:** "Fix the bug quickly and redeploy."

**Red flags:** debugs in production while users are down instead of rolling back.

## Scoring anchors

Example question: "How would you deploy a FastAPI app with a database?"

### Score 1/5

"Run it on my laptop and share the link." Not a deployment.

### Score 3/5

"Put it in Docker and deploy to a cloud service." Plausible, but no config, secrets, or CI.

### Score 5/5

"Containerize or use a platform with a Python runtime, use a managed Postgres, pass the DB URL and
keys as environment secrets, run migrations as a deploy step, add a health endpoint, set up CI to
lint and test before deploy, and monitor logs and errors. Keep a rollback path." Complete and
operationally aware.

## Resources

- [Docker: Get started](https://docs.docker.com/get-started/): official introduction.
- [GitHub Actions documentation](https://docs.github.com/en/actions): official CI/CD docs.
- [The Twelve-Factor App](https://12factor.net/): principles for deployable apps.

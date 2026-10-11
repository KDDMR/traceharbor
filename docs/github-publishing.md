# Publish this repository to GitHub

The repository is ready to publish after replacing `YOUR-GITHUB-USERNAME` in `README.md`.

## GitHub web interface

1. Create an empty **public** repository named `traceharbor` without a generated README, license or `.gitignore`.
2. In this local repository, run:

```bash
git remote add origin https://github.com/YOUR-GITHUB-USERNAME/traceharbor.git
git push -u origin main
```

3. Add the short description: `A production-minded telemetry ingest service and zero-dependency Python SDK.`
4. Add topics: `python`, `observability`, `telemetry`, `error-monitoring`, `developer-tools`.
5. Enable Issues and the repository's private vulnerability reporting.

Use the public repository URL for the application field. The portfolio write-up can be linked directly as:

```text
https://github.com/YOUR-GITHUB-USERNAME/traceharbor/blob/main/docs/portfolio-writeup.md
```

Before submitting, verify that GitHub Actions is green and that no generated database files are tracked.


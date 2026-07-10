# GitHub Actions

The repository uses three workflow entrypoints:

- `unit-tests.yml`: syntax and test validation
- `build_docker.yml`: Docker image build and optional publish
- `build_all.yml`: source package generation and release orchestration

The workflow file names intentionally follow the existing project convention.

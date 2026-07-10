# Runtime Arguments Details

The runtime is intentionally simple.

Application behavior is controlled through:

- environment variables in `docker/.env`
- FastAPI entrypoint selection through `uvicorn src.BenchAutomations:app`
- mounted host volumes for `config` and `data`

This keeps local execution and Docker execution aligned.

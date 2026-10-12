# Contributing

## Layout

```
spec/openapi.json      copy of the public contract (https://api.bytnode.com/openapi.json)
codegen/               reads the contract, writes the generated code of both SDKs
  model.py             contract -> language-neutral description (routes, params, models)
  emit_python.py       -> python/src/bytnode/_generated/
  emit_typescript.py   -> typescript/src/generated/
  overrides.json       what the contract does not say in machine-readable form
python/                the `bytnode` package on PyPI
typescript/            the `bytnode` package on npm
```

**Never edit a `_generated/` or `generated/` file by hand**: change the generator or
`codegen/overrides.json`, then regenerate. The CI fails when the generated code is out of date.

## Common tasks

```bash
make setup            # Python venv + npm install
make update-spec      # download the public contract into spec/openapi.json
make generate         # regenerate both SDKs from spec/openapi.json
make check            # lint, type-check and test both SDKs (offline)
make test-live        # read-only tests against production (needs BYTNODE_API_KEY)
```

When the API changes: `make update-spec generate check`, read the diff of the generated code,
add a line to `CHANGELOG.md`, open a pull request.

## Rules

- Every route method exists in both languages, with the same name (snake_case in Python,
  camelCase path segments in TypeScript) and the same behaviour.
- A model never breaks on an unknown field: unknown keys are kept, a mismatch warns instead of
  raising.
- Every request the tests make is offline, against a fake transport or a local WebSocket server,
  except the `live` suites — which only read, and space their requests.
- No API key in the repository, ever (`git grep cb_live_` must only find fake keys).

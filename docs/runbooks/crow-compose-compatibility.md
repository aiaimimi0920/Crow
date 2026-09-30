# Crow Compose configuration compatibility

Use `tools/crow_compose.py` when supplying `CROW_*` configuration to the existing
Compose templates. The templates retain legacy interpolation keys, service names,
image names and volume identities for compatibility with existing installations.
This is a configuration adapter, not a data migration or deployment instruction.

A read-only validation example:

```sh
python tools/crow_compose.py --check -- --env-file env.worker.local -f docker-compose.worker-node.yml config
```

The adapter validates alias groups before forwarding an explicitly requested
Compose command. With no arguments it runs `config --quiet`; `--check` stops after
configuration validation. It never creates or moves runtime-data directories.
Existing direct `docker compose` invocations using the legacy configuration remain
supported. Passing new names directly to old templates does not activate alias
resolution; use the Crow adapter.

## Sources and paths

- An explicit `--data-root-host` overrides the corresponding process/env-file group
- Process configuration overrides the same logical key from env files, regardless
  of whether the source spells it `CROW_*` or `FAPAI_*`
- Both explicit spellings in the selected source must agree; path keys compare
  lexically without following links. Distinct roots fail closed
- Blank `DATA_ROOT_HOST` follows the management-root selector's fallback rule;
  other empty inputs remain explicit and retain Compose's `:-` / `:?` behavior
- `DATA_ROOT` and `DATA_ROOT_HOST` keep their original, context-specific meanings;
  the adapter does not convert a collection subdirectory into a management root

Supported global selectors precede the command: `-f FILE`, `-fFILE`, `-f=FILE`,
`--file FILE`, `--file=FILE`, `--env-file FILE`/`=FILE`, and one
`--project-directory DIR`/`=DIR`. Multiple files preserve order; the first selects
the project root unless an explicit project directory is supplied. Project-name,
profile, parallelism, ANSI and progress value options plus compatibility/dry-run/
all-resources flags are recognized. Unknown globals, missing values, repeated
project directories, stdin/remote file selection and global options after the
command fail closed. Do not place overloaded `-f`/`-p` options after a command.

Use explicit `-f` and `--env-file` options instead of indirect `COMPOSE_FILE` or
`COMPOSE_ENV_FILES` selection. These indirect selection variables are rejected
when their matching explicit option is missing, so path comparison cannot use
an unintended project directory.

## Parsing and validation boundary

Docker Compose itself parses env files in an inert, config-only model with no
volumes. Its JSON output and diagnostics are captured; preparation errors contain
key names or a fixed error code, never configuration values. The adapter writes
no rendered env files. It supplies missing alias names for interpolation without
feeding a file's own definitions back into themselves; alias interpolation cycles
fail closed.

The ordinary Linux CI gate runs actual `docker compose config` with synthetic
configuration. It compares old-only, new-only and equal dual-name service models,
including bind sources, images and service identities, and verifies quoted dollar
values, cross-alias references and conflicts. No image builds, pulls, container
starts or data migration occur in that gate. Local runs without Docker explicitly
skip that integration gate; `CROW_TEST_COMPOSE=1` makes missing Compose a failure.

The saved configuration, public Python reader tests and original entrypoint tests
continue to exercise legacy keys. See [the naming inventory](crow-naming-inventory.md)
for remaining independent operator-script and protocol boundaries.

## Collection mode entrypoints

The continuous-collection, seed-only and detail-analysis-only PowerShell scripts
now call this adapter for Compose operations. Seed/detail modes validate the
selected environment before changing Docker restart policies. Their explicit
`DataRoot` parameter remains the management-root override.

Their existing `Set-EnvLine` / `Ensure-EnvLine` interfaces use a shared scoped
writer. Explicit settings update both aliases together; defaults leave either
existing spelling untouched, including empty values. Conflicting existing aliases
are not resolved by inserting a default: adapter validation rejects them.
Unrelated lines and existing file permissions are retained. The writer accepts
literal single-line mode settings; unsupported quoting/interpolation or multiline
target definitions fail with key names only. It does not rewrite other settings
or create a second deployment configuration. Tests use temporary synthetic files
and extracted writer functions, never execute the operational script bodies.

## Container environment layering

Before forwarding a command (also for `--check`), the adapter renders the final
configuration with the same validated global selectors and checks each service's
resolved environment aliases. It captures JSON/diagnostics without saving or
echoing environment values. A conflicting Crow env-file key and fixed legacy
`service.environment` key fail before the requested Docker operation.

Container env files, template environment names and Docker build arguments retain
legacy wire names deliberately. They are a different boundary from host Crow
inputs. Use the corresponding legacy env-file key where a service overrides that
setting; do not assume renaming the file's keys preserves Compose layer priority.
The adapter validates the final model and never rewrites those layers.

# prosapia documentation

New here? The [README](../README.md) has the pitch, installation, and a quick
start. These pages go deeper.

## Start here

- **[Architecture](architecture.md)** — the shared database and the two-phase
  SLURM driver.
- **[Running a tool](running-a-tool.md)** — the `sapia run` flags and how they
  map to a SLURM array job.
- **[Collecting a tool](collecting-a-tool.md)** — the `sapia collect` phase that
  writes a tool's outputs back into the database.
- **[Using labels](using-labels.md)** — `--dir-label` and `--db-label` for
  same-tool variants and forking the lineage.
- **[Lineage & databases](lineage-and-databases.md)** — `create` vs. `update`,
  roots, the lineage tree, and `lookup`.
- **[Configuration](configuration.md)** — binding tools via activation scripts,
  the environment-variable reference, and tool discovery.
- **[Writing a tool](writing-a-tool.md)**, **[Writing a build-manifest
  function](writing-a-build-manifest-function.md)**, and **[Writing a collect
  function](writing-a-collect-function.md)** — build your own tool, or customize
  a bundled one.
- **[Writing a filter function](writing-a-filter-function.md)** — subset or
  sample designs at submit time with `-f/--filter`.

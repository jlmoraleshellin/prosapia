# prosapia documentation

New here? The [README](../README.md) has the pitch, installation, and a quick start. These pages go deeper.

## Start here

- **[Architecture](architecture.md)** — the shared table and the two-phase SLURM driver.
- **[Lineage & tables](lineage-and-tables.md)** — `create` vs. `update`, roots, the lineage tree, and `lookup`.
- **[Using labels](using-labels.md)** — `--dir-label` and `--table-label` for same-tool variants and forking the lineage.
- **[Configuration](configuration.md)** — binding tools via activation scripts, the environment-variable reference, and tool discovery.
- **[Running a tool](running-a-tool.md)** — the `sapia run` flags and how they map to a SLURM array job.
- **[Collecting a tool](collecting-a-tool.md)** — the `sapia collect` phase that writes a tool's outputs back into the table.
- **[Using RFdiffusion](tools/rfdiffusion.md)** and **[Using ProteinMPNN](tools/proteinmpnn.md)** — guides to the two bundled tools with their own expression languages.
- **[Writing a tool](writing-a-tool.md)**, **[Writing a build-manifest function](writing-a-build-manifest-function.md)**, and **[Writing a collect function](writing-a-collect-function.md)** — build your own tool, or customize a bundled one.
- **[Writing a filter function](writing-a-filter-function.md)** — subset or sample designs at submit time with `-f/--filter`.

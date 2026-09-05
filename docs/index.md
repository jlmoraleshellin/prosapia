# prosapia documentation

**A shared workbench for protein-design tools on HPC.** `prosapia` gives many heterogeneous protein-design tools one bench to work on: a **shared database** every tool reads from and writes back to, and a **two-phase SLURM driver** that runs them on the cluster. Each tool sets its results on the bench and picks up what earlier tools left — so you bring the tools, and prosapia supplies the data format, the runner, and the lineage bookkeeping that ties their outputs together. It is meant to be used as a **library, not just a data store**: the core functions the bundled tools are built from are yours to import, so you can bolt your own tool onto the bench in two small functions.

This is **not a pipeline framework.** There is no DAG to declare and no fixed order of steps — only a *consensus data format* (the database) and tools that consume and produce it. You compose a workflow by pointing the next tool at a database, forking and back-tracking as the science demands.

## Start here

- **New to prosapia?** The [README](../README.md) has installation and a quick start.
- **Want the mental model?** Read [Architecture](architecture.md), then
  [Lineage & databases](lineage-and-databases.md).
- **Setting up tools?** See [Configuration](configuration.md).
- **Building your own tool?** Follow [Writing a tool](writing-a-tool.md) and
  [Writing a collect function](writing-a-collect-function.md).
- **Hacking on prosapia itself?** See [Development](development.md).

## The one-sentence model

A design is a **row**, a database is a **table**, a tool contributes **columns** —
and when a protein diverges in sequence or structure, a **new database** is born.
Everything else follows from that.

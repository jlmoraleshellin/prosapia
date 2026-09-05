# prosapia documentation

**A data layer for protein design on HPC.** `prosapia` gives many heterogeneous
protein-design tools a single way to exchange results: a **shared database** that
every tool reads from and writes back to. You bring the tools; the package
supplies the data format, the two-phase SLURM driver that runs them, and the
lineage bookkeeping that ties their outputs together.

This is **not a pipeline framework.** There is no DAG to declare and no fixed
order of steps — only a *consensus data format* (the database) and tools that
consume and produce it. You compose a workflow by pointing the next tool at a
database, forking and back-tracking as the science demands.

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

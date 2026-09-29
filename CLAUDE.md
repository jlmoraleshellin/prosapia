# Where are you?
This is a WIP shared workbench for protein-design tools on HPC: a shared table plus a two-phase runner (SLURM or Modal executors), packaged as an importable library (package `prosapia`, CLI `sapia`) so users can wrap their own tools or use the bundled ones. The goal is to give users easy access to all protein design softwares (tools) in an HPC environment.

# Project structure
This project is a single Python package (`prosapia`), managed with `uv` (run tasks via `uv run`). Its `pyproject.toml` defines the package and the `sapia` CLI entrypoint (`prosapia.cli.cli:main`). Layout: `src/prosapia/core/` (drivers + data layer), `src/prosapia/cli/`, `src/prosapia/tools/` (bundled tools), `src/prosapia/utils/`.

# Architecture:
- Design workflows live inside a unique run_dir. Every tool needs a run_dir. `sapia new_run` spawns a new one.
- The `prosapia.core` package (`src/prosapia/core/`) provides the two drivers, the tool definition types, and the data layer. Tools are thin: they supply metadata + two hooks + scripts, and plug into the drivers:
    - `tool.py`
        - `Tool` is the dataclass that binds a tool together: its `ToolMetadata` and its two hooks (`BuildManifestFn`, `CollectFn`)
        - `ToolMetadata` is declarative identity: `name`, `action`, `description`, and `default_input_column`. The `action` selects how the drivers resolve the destination table.
    - `base_sbatch.py`
        - `run_from_args(metadata, build_manifest_fn, args)` is the submit-phase driver, shared by all tools. A tool customizes it by passing its `ToolMetadata` and its `BuildManifestFn` hook. On each invocation it:
            1. opens a `DataManager` to load the input table;
            2. calls `resolve_output_table` to reserve the destination table (a new child/root for `create`, or the source table for `update`);
            3. invokes the tool's `build_manifest` hook to write the manifest `.txt`;
            4. hands the manifest to the executor chosen by `--executor` (`core/executors/`: `slurm` array job or `modal` containers), which runs the tool's `.sh` once per manifest line.
        - Defines the `BuildManifestFn` hook contract that tools implement.
    - `base_collect.py`
        - `collect_from_args(metadata, collect_fn, args)` is the collect-phase driver, shared by all tools. Customized by passing `ToolMetadata` and the `CollectFn` hook. On each invocation it:
            1. opens a `DataManager`;
            2. invokes the tool's `collect` hook to turn on-disk output into `CollectResult` rows;
            3. writes those rows into the destination table (creating it for `create`, annotating it in place for `update`) and updates the registry.
        - Defines the `CollectorFactory` hook contract that tools implement.
    - `data_manager.py`
        - `DataManager` is a context manager that owns the run's tables and registry, both handled uniformly as DataFrames through a pluggable I/O backend (TSV default). It:
            - creates and modifies tables and the registry;
            - resolves cross-table lineage (linking child rows to a parent via `parent_name`/`parent_table`/`gen`);
            - exposes a read-only `lookup` that walks the lineage chain to fetch ancestor values.
    - `cli.py` (`src/prosapia/cli/`): the `sapia` CLI entrypoint. Discovers tools (built-ins first, then `$PROSAPIA_TOOLS_DIR`) and builds a `run`/`collect` subcommand pair per tool.
    - `sapia modal-shell` (`cli/modal_shell.py`) opens the Modal workstation (`core/executors/workstation.py`): a small prosapia container with the runs Volume mounted, where `sapia` runs so run_dirs live only on the Volume.
- A tool is a composition of declarative metadata, two behavioral hooks, and scripts. It carries no orchestration logic of its own, the drivers supply that. Components:
    - metadata: ToolMetadata -> name, action, description, default_input_column
    - build_manifest_fn: BuildManifestFn -> returns the manifest rows (the per-task inputs for the .sh task script); the driver writes them to a .txt manifest
    - collect_fn: CollectFn -> reads tool output structure and returns a CollectorFactory.
    - tool.sh: the per-task script file, shared by every executor. Receives the manifest and the out_dir as positional arguments in that respective order; the prelude resolves its line from `SAPIA_TASK_ID` and `sapia_activate` sources the user's activation script (skipped under modal).
    - (optional) modal_image.py: the tool's Modal image (`image()`, optional `RESOURCES` / `volumes()`), used by `--executor modal`.
    - (optional) tool_worker.py: performs extra python actions necessary before running the tool. If the per-design step is a simple shell command, put it directly in tool.sh instead.
- Execution model: a tool runs in two phases against a `run_dir`. The drivers own the flow; the tool's hooks fill in the variable steps.
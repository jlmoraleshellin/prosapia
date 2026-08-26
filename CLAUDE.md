# Where are you?
This is a WIP protein design pipeline that aims to give users easy access to all protein design softwares (tools) in an HPC environment.

# Project structure
This project is a monorepo that uses pixi as a package manager for tasks and scripts but also contains a pyproject.toml for pipeline-core package.

# Architecture:
- Design workflows live inside a unique run_dir. Every tool needs a run_dir. new_run_dir spawns a new one.
- The pipeline-core package provides the two drivers, the tool definition types, and the data layer. Tools are thin: they supply metadata + two hooks + scripts, and plug into the drivers:
    - `tool.py`
        - `Tool` is the dataclass that binds a tool together: its `ToolMetadata` and its two hooks (`BuildManifestFn`, `CollectFn`)
        - `ToolMetadata` is declarative identity: `name`, `description`, and `action`. The `action` selects how the drivers resolve the destination db.
    - `base_sbatch.py`
        - `run_from_args(metadata, build_manifest_fn, args)` is the submit-phase driver, shared by all tools. A tool customizes it by passing its `ToolMetadata` and its `BuildManifestFn` hook. On each invocation it:
            1. opens a `DataManager` to load the input db;
            2. calls `resolve_output_db` to reserve the destination db (a new child for `create`, a new root for `root`, or the source db for `update`);
            3. invokes the tool's `build_manifest` hook to write the manifest `.txt`;
            4. submits the SLURM array job, whose `.sbatch` consumes that manifest.
        - Defines the `BuildManifestFn` hook contract that tools implement.
    - `base_collect.py`
        - `collect_from_args(metadata, collect_fn, args)` is the collect-phase driver, shared by all tools. Customized by passing `ToolMetadata` and the `CollectFn` hook. On each invocation it:
            1. opens a `DataManager`;
            2. invokes the tool's `collect` hook to turn on-disk output into `CollectResult` rows;
            3. writes those rows into the destination db (creating it for `create`/`root`, annotating it in place for `update`) and updates the registry.
        - Defines the `CollectFn` hook contract that tools implement.
    - `data_manager.py`
        - `DataManager` is a context manager that owns the run's databases and registry, both handled uniformly as DataFrames through a pluggable I/O backend (TSV default). It:
            - creates and modifies databases and the registry;
            - resolves cross-db lineage (linking child rows to a parent via `parent_name`/`parent_db`/`gen`);
            - exposes a read-only `lookup` that walks the lineage chain to fetch ancestor values.
    - `cli.py`: pipeline entrypoint.
- A tool is a composition of declarative metadata, two behavioral hooks, and scripts. It carries no orchestration logic of its own, the drivers supply that. Components:
    - metadata: ToolMetadata -> name, description and action
    - build_manifest_fn: BuildManifestFn -> writes a .txt manifest containing the inputs for the .sbatch script. It
    - collect_fn: CollectFn -> reads tool output structure and returns a CollectResult dict to append to a database
    - tool.sbatch: the per-array-task script file. Receives the manifest and the out_dir as positional arguments in that respective order.
    - (optional) tool_worker.py: performs extra python actions necessary before running the tool. If the per-design step is a simple shell command, put it directly in tool.sbatch instead.
- Execution model: a tool runs in two phases against a `run_dir`. The drivers own the flow; the tool's hooks fill in the variable steps.

# Future plans
- Packaging of this project as a protein design pipeline management API. Users should be able to import this package into their pipeline project to handle their data and wrap their tools (or use the prebundled ones) with the core logic.
- Prebundle standard and common tools with the package. Make them as general as possible.
- Make tools a single pluggable file with two separate functions as script entrypoints defined in the pyproject.toml scripts.
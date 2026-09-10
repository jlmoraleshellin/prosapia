# Writing a filter function

A **filter** is an optional Python module you point `sapia run` at with `-f/--filter`. It exposes a single `apply_filter(df) -> df`, and the driver applies it to the source table **before the manifest is built**. This way you can subset, sample, threshold, or reorder designs at submit time without touching the table itself.

```bash
sapia run <tool> <run_dir> -t <table> -f path/to/filter.py
```

## The contract

The module must define exactly one function, named `apply_filter` (the driver raises an error if it's missing):

```python
from pandas import DataFrame

def apply_filter(df: DataFrame) -> DataFrame:
    ...
    return df
```

- **Input:** the source table as a pandas `DataFrame` — one row per design,   keyed by the design `name`, with each tool's outputs as columns.
- **Output:** a `DataFrame`, typically a subset of the rows. Anything you can do   with pandas (and anything importable) is fair game.

## When it runs

The filter runs at **submit time, in the `sapia` driver** (not on the cluster), and **before the manifest is computed**. So the framework's own filtering — the `--input-column` presence check and the resume skip (`<leaf>_status == "OK"`) applies *on top of* the frame you return. It sees the full source table. (For a root `create` run with no `-t`, there's no source table, so the frame is empty.)

If your filter returns an empty frame, the run prints `No designs to submit.` and exits without submitting anything.

## Example

The bundled [`examples/filters/test_filter.py`](../examples/filters/test_filter.py) keeps a random sample of the designs:

```python
import os

from pandas import DataFrame

# Configurable via env vars so the fixed apply_filter(df) signature stays intact:
#   TEST_SAMPLE_N     -> number of structures to keep (default 5)
#   TEST_SAMPLE_SEED  -> RNG seed for a reproducible sample (default 0)
SAMPLE_N = int(os.environ.get("TEST_SAMPLE_N", 5))
SAMPLE_SEED = int(os.environ.get("TEST_SAMPLE_SEED", 0))


def apply_filter(df: DataFrame) -> DataFrame:
    total = len(df)
    n = min(SAMPLE_N, total)
    sampled = df.sample(n=n, random_state=SAMPLE_SEED)
    print(f"Test sample: {len(sampled)} / {total} (seed={SAMPLE_SEED})")
    return sampled
```

Note the **env-var pattern**: the `apply_filter(df)` signature is fixed, so a filter takes its parameters from the environment rather than function arguments. Set them in `.env` or inline:

```bash
TEST_SAMPLE_N=20 sapia run rfdiffusion "$RUN_DIR" -f examples/filters/test_filter.py -l test
```

Value-based filtering is just as direct — keep only the designs that clear a
threshold on a column an earlier tool wrote:

```python
def apply_filter(df: DataFrame) -> DataFrame:
    return df[df["plddt"] > 80]
```

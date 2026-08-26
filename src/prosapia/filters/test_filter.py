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

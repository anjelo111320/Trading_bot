"""Forecast the next candles with Kronos, from a CSV of closed candles.

Run with Kronos's own environment, never the backend's. The backend calls it through
trading_intel.forecasting.kronos, or it can be run by hand:
  vendor/Kronos/.venv/bin/python backend/scripts/kronos_forecast.py IN.csv OUT.json

Kronos (vendor/Kronos, MIT, arXiv 2508.02739) is a pretrained model that samples possible
future candle paths. Its output is a spread of possibilities, not a price to trade on.
Runs are seeded and use a fixed thread count, so the same input gives the same paths.
The CSV needs: timestamp (open time, UTC), open, high, low, close, volume, amount.
"""

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vendor" / "Kronos"))
from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402

COLUMNS = ["open", "high", "low", "close", "volume", "amount"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candles")
    parser.add_argument("output")
    parser.add_argument("--paths", type=int, default=30)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--context", type=int, default=400)
    parser.add_argument("--model", default="NeoQuasar/Kronos-small")
    parser.add_argument("--model-revision", default=None)
    parser.add_argument("--tokenizer", default="NeoQuasar/Kronos-Tokenizer-base")
    parser.add_argument("--tokenizer-revision", default=None)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    frame = pd.read_csv(args.candles, parse_dates=["timestamp"]).tail(args.context)
    stamps = frame["timestamp"].reset_index(drop=True)
    step = stamps.iloc[-1] - stamps.iloc[-2]
    if not (stamps.diff().dropna() == step).all():
        raise SystemExit("candles must be evenly spaced, with no gaps")
    future = pd.Series([stamps.iloc[-1] + step * (i + 1) for i in range(args.horizon)])

    torch.set_num_threads(args.threads)
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    tokenizer = KronosTokenizer.from_pretrained(args.tokenizer, revision=args.tokenizer_revision)
    model = Kronos.from_pretrained(args.model, revision=args.model_revision)
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
    inputs = frame[COLUMNS].reset_index(drop=True)
    predictions = predictor.predict_batch(
        [inputs] * args.paths,
        [stamps] * args.paths,
        [future] * args.paths,
        pred_len=args.horizon,
        T=1.0,
        top_p=0.9,
        sample_count=1,
        verbose=False,
    )
    paths = [p[["open", "high", "low", "close"]].to_numpy().round(6).tolist() for p in predictions]
    Path(args.output).write_text(
        json.dumps(
            {
                "model": args.model,
                "model_revision": args.model_revision,
                "tokenizer": args.tokenizer,
                "tokenizer_revision": args.tokenizer_revision,
                "seed": args.seed,
                "threads": args.threads,
                "torch": torch.__version__,
                "context_candles": len(frame),
                "last_input": stamps.iloc[-1].isoformat(),
                "last_close": float(frame["close"].iloc[-1]),
                "timestamps": [t.isoformat() for t in future],
                "paths": paths,
            }
        )
    )
    print(f"wrote {len(paths)} paths of {args.horizon} candles to {args.output}")


if __name__ == "__main__":
    main()

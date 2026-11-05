"""Forecast the next candles with Kronos, from a CSV of closed candles.

Run with Kronos's own environment, never the backend's:
  vendor/Kronos/.venv/bin/python backend/scripts/kronos_forecast.py IN.csv OUT.json

Kronos (vendor/Kronos, MIT, arXiv 2508.02739) is a pretrained model that samples possible
future candle paths. Its output is a spread of possibilities, not a price to trade on, and it
cannot be backtested honestly on years inside its training data. Runs are seeded.
The CSV needs: timestamp, open, high, low, close, volume, amount.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vendor" / "Kronos"))
from model import Kronos, KronosPredictor, KronosTokenizer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candles")
    parser.add_argument("output")
    parser.add_argument("--paths", type=int, default=30)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--context", type=int, default=400)
    parser.add_argument("--model", default="NeoQuasar/Kronos-small")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    frame = pd.read_csv(args.candles, parse_dates=["timestamp"]).tail(args.context)
    columns = ["open", "high", "low", "close", "volume", "amount"]
    stamps = frame["timestamp"].reset_index(drop=True)
    step = stamps.iloc[-1] - stamps.iloc[-2]
    future = pd.Series([stamps.iloc[-1] + step * (i + 1) for i in range(args.horizon)])

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    model = Kronos.from_pretrained(args.model)
    predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
    inputs = frame[columns].reset_index(drop=True)
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
                "seed": args.seed,
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

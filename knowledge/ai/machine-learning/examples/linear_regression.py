"""Three synthetic points, half-MSE, and full-batch gradient descent.

Run from the repository root. Uses only the Python standard library.
"""

import argparse
import json

DATA = ((1.0, 3.0), (2.0, 5.0), (3.0, 7.0))


def loss_and_grad(w, b, data=DATA):
    errors = [w * x + b - y for x, y in data]
    n = len(data)
    loss = sum(e * e for e in errors) / (2 * n)
    dw = sum(e * x for e, (x, _) in zip(errors, data)) / n
    db = sum(errors) / n
    return loss, dw, db


def train(learning_rate=0.1, steps=2000):
    w, b = 1.0, 0.0
    history = []
    for step in range(steps + 1):
        loss, dw, db = loss_and_grad(w, b)
        history.append({"step": step, "w": w, "b": b, "loss": loss})
        if step < steps:
            # Both gradients come from the same old (w, b).
            w, b = w - learning_rate * dw, b - learning_rate * db
    return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--json", action="store_true", help="Print the full trace.")
    args = parser.parse_args()
    if args.lr <= 0 or args.steps < 0:
        parser.error("--lr must be positive and --steps must be nonnegative")
    history = train(args.lr, args.steps)
    if args.json:
        print(json.dumps(history, allow_nan=False))
        return
    for row in history:
        if row["step"] in {0, 1, 10, 100, 1000, args.steps}:
            print(f'step={row["step"]:4d} w={row["w"]:.6f} '
                  f'b={row["b"]:.6f} J={row["loss"]:.9g}')
    final = history[-1]
    print(f'prediction at x=4: {final["w"] * 4 + final["b"]:.6f}')


if __name__ == "__main__":
    main()

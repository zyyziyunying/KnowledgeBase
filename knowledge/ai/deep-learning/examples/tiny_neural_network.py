"""A 1 -> 2 ReLU -> 1 regressor with explicit forward/backward calculations.

All seven parameters are trained on five synthetic y=abs(x) points.
Uses only the Python standard library; no automatic differentiation.
"""

import argparse
import json

DATA = tuple((float(x), float(abs(x))) for x in (-2, -1, 0, 1, 2))
INITIAL = (0.8, 0.1, -0.6, 0.1, 0.7, 0.8, 0.0)
PARAMETER_NAMES = ("w1", "b1", "w2", "b2", "v1", "v2", "c")


def forward(p, x):
    w1, b1, w2, b2, v1, v2, c = p
    z1, z2 = w1 * x + b1, w2 * x + b2
    h1, h2 = max(0.0, z1), max(0.0, z2)
    return v1 * h1 + v2 * h2 + c, (z1, z2, h1, h2)


def loss_and_grad(p, data=DATA):
    loss = 0.0
    gradients = [0.0] * 7
    for x, y in data:
        prediction, (z1, z2, h1, h2) = forward(p, x)
        error = prediction - y
        loss += 0.5 * error * error
        # ReLU's derivative at 0 is taken as 0 in this implementation.
        delta1 = error * p[4] * (1.0 if z1 > 0 else 0.0)
        delta2 = error * p[5] * (1.0 if z2 > 0 else 0.0)
        sample_grad = (delta1 * x, delta1, delta2 * x, delta2,
                       error * h1, error * h2, error)
        for i, g in enumerate(sample_grad):
            gradients[i] += g
    n = len(data)
    return loss / n, [g / n for g in gradients]


def gradient_check(p, data, epsilon=1e-6):
    """Central differences; callers must avoid ReLU's nondifferentiable kink."""
    _, analytic = loss_and_grad(p, data)
    numerical = []
    for i in range(len(p)):
        plus, minus = list(p), list(p)
        plus[i] += epsilon
        minus[i] -= epsilon
        numerical.append((loss_and_grad(plus, data)[0]
                          - loss_and_grad(minus, data)[0]) / (2 * epsilon))
    return max(abs(a - b) for a, b in zip(analytic, numerical))


def train(learning_rate=0.05, steps=5000):
    p = list(INITIAL)
    history = []
    for step in range(steps + 1):
        loss, gradients = loss_and_grad(p)
        history.append({"step": step, "parameters": list(p), "loss": loss})
        if step < steps:
            # Finish all gradients before changing any parameter.
            p = [value - learning_rate * g for value, g in zip(p, gradients)]
    return history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lr", type=float, default=0.05)
    parser.add_argument("--steps", type=int, default=5000)
    parser.add_argument("--json", action="store_true", help="Print the full trace.")
    args = parser.parse_args()
    if args.lr <= 0 or args.steps < 0:
        parser.error("--lr must be positive and --steps must be nonnegative")
    history = train(args.lr, args.steps)
    if args.json:
        print(json.dumps(history, allow_nan=False))
        return
    hand_parameters = (1.0, 1.0, -1.0, 1.0, 1.0, 2.0, 0.0)
    hand_data = ((2.0, 5.0),)
    print("hand example loss, gradients:", loss_and_grad(hand_parameters, hand_data))
    print(f'gradient check max error: {gradient_check(hand_parameters, hand_data):.3g}')
    for row in history:
        if row["step"] in {0, 1, 10, 100, 1000, args.steps}:
            print(f'step={row["step"]:4d} J={row["loss"]:.9g}')
    p = history[-1]["parameters"]
    print("trained parameters:", dict(zip(PARAMETER_NAMES, p)))
    for x in (-1.5, -0.5, 0.0, 0.5, 1.5):
        print(f'x={x:4.1f} target={abs(x):.1f} prediction={forward(p, x)[0]:.6f}')


if __name__ == "__main__":
    main()

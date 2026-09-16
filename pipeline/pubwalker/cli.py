"""uv run pubwalker <step|all> <doi> [--n 40] [--seed 1]. Steps are idempotent and cached."""
import argparse

from . import analyze, export, fetch, passages

STEPS = {
    "fetch": lambda a: fetch.run(a.doi),
    "passages": lambda a: passages.run(a.doi, n=a.n, seed=a.seed),
    "roles": lambda a: analyze.roles(a.doi),
    "synth": lambda a: analyze.synth(a.doi),
    "structure": lambda a: analyze.structure(a.doi),
    "compare": lambda a: analyze.compare(a.doi),
    "export": lambda a: export.run(a.doi),
}


def main():
    p = argparse.ArgumentParser(prog="pubwalker", description=__doc__)
    p.add_argument("step", choices=[*STEPS, "all"])
    p.add_argument("doi")
    p.add_argument("--n", type=int, default=40, help="citers sampled per time window")
    p.add_argument("--seed", type=int, default=1)
    a = p.parse_args()
    for name in (STEPS if a.step == "all" else [a.step]):
        print(f"== {name}")
        STEPS[name](a)


if __name__ == "__main__":
    main()

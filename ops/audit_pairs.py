"""F0: revisa os pares fundidos/rejeitados do cluster.

Uso:
    BALANCO_AUDIT=state/audit/pairs-local.jsonl python app.py --body --body-cap 40
    python ops/audit_pairs.py --run state/audit/pairs-local.jsonl --top 30

Imprime os `top` fundidos menos similares e os `top` rejeitados mais similares,
para revisão manual (semente do F1).
"""
import argparse
import json


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()
    recs = load(args.run)
    fused = sorted([r for r in recs if r["decision"] == "fused"],
                   key=lambda r: (r["cos"], len(r.get("shared", []))))
    rej = sorted([r for r in recs if r["decision"] == "rejected"],
                 key=lambda r: (-r["cos"], -len(r.get("shared", []))))
    print(f"pares: {len(recs)} (fundidos {len(fused)}, rejeitados {len(rej)})")
    print(f"\n== {args.top} fundidos menos similares ==")
    for r in fused[:args.top]:
        print(f"  cos={r['cos']} rule={r['rule']} shared={','.join(r['shared'][:6])}")
        print(f"    A [{r['source_a']}/{r['section_a']}] {r['a'][:90]}")
        print(f"    B [{r['source_b']}/{r['section_b']}] {r['b'][:90]}")
    print(f"\n== {args.top} rejeitados mais similares ==")
    for r in rej[:args.top]:
        print(f"  cos={r['cos']} rule={r['rule']} shared={','.join(r['shared'][:6])}")
        print(f"    A [{r['source_a']}/{r['section_a']}] {r['a'][:90]}")
        print(f"    B [{r['source_b']}/{r['section_b']}] {r['b'][:90]}")


if __name__ == "__main__":
    main()

"""Ask the graph how things relate. Tolerates typos and short names.
  python _system/graph.py "riverside detal" "acme"   -> every link between the two, plus paths through documents
  python _system/graph.py "acme"                     -> everything connected to one thing"""
import csv, difflib, pathlib, sys
from collections import defaultdict, deque

ROOT = pathlib.Path(__file__).resolve().parent.parent
edges = [r for r in csv.DictReader(open(ROOT / "04_graph/triples.csv", encoding="utf-8"))]
nodes = {e["subject"] for e in edges} | {e["object"] for e in edges}
adj = defaultdict(list)
for e in edges:
    adj[e["subject"]].append((e["relation"], e["object"], "out", e["count"]))
    adj[e["object"]].append((e["relation"], e["subject"], "in", e["count"]))

# vendor aliases from the master list count as names too
alias = {}
for l in (ROOT / "_shared/vendors.md").read_text(encoding="utf-8").splitlines()[3:]:
    if l.startswith("|"):
        c = [x.strip() for x in l.strip("|").split("|")]
        for a in c[1].split(";"):
            if a.strip(): alias[a.strip().lower()] = c[0]

def resolve(q):
    """Best node for a loose name: exact > alias > word-prefix > substring > fuzzy. Entities beat document nodes."""
    ql = q.lower().strip()
    ents = [n for n in nodes if "/" not in n]
    for pool in (ents, nodes):
        for n in pool:
            if n.lower() == ql: return n, 1.0
    if ql in alias and alias[ql] in nodes: return alias[ql], 1.0
    for a, v in alias.items():  # "amzn" -> "amzn mktp us" -> Amazon
        if v in nodes and len(ql) >= 3 and a.startswith(ql): return v, 0.95
    words = ql.split()
    for pool in (ents, list(nodes)):  # whole-text match first ("inv-1001"), then typo-tolerant word starts ("riverside detal")
        hits = [n for n in pool if ql in n.lower()]
        if hits: return min(hits, key=len), 0.9
    for pool in (ents, list(nodes)):
        hits = [n for n in pool if all(any(w2.startswith(w[:4]) for w2 in n.lower().replace("/", " ").split()) for w in words)]
        if hits: return min(hits, key=len), 0.85
    best = max(nodes, key=lambda n: difflib.SequenceMatcher(None, ql, n.lower()).ratio())
    return best, round(difflib.SequenceMatcher(None, ql, best.lower()).ratio(), 2)

def show(n, rel, other, d, c):
    s = f"{n} --{rel}--> {other}" if d == "out" else f"{other} --{rel}--> {n}"
    return s + (f"  (x{c})" if c not in ("1", 1) else "")

def paths(a, b, maxlen=3):
    out, q = [], deque([[a]])
    while q:
        p = q.popleft()
        if len(p) > maxlen + 1: continue
        for rel, nxt, d, c in adj[p[-1]]:
            if nxt in p: continue
            if nxt == b: out.append(p + [nxt])
            elif "/" in nxt or len(p) == 1: q.append(p + [nxt])  # only travel through documents, not other companies
    return out

args = sys.argv[1:]
if not args: raise SystemExit(__doc__)
found = [resolve(x) for x in args]
for x, (n, sc) in zip(args, found):
    print(f'"{x}" -> {n}' + ("" if sc >= 0.85 else f"   (low confidence {sc} - check this is what you meant)"))
print()
if len(found) == 1:
    n = found[0][0]
    for rel, other, d, c in sorted(adj[n]): print(show(n, rel, other, d, c))
else:
    a, b = found[0][0], found[1][0]
    direct = [show(a, r, o, d, c) for r, o, d, c in adj[a] if o == b]
    print("Direct links:" if direct else "Direct links: none")
    for x in direct: print(f"  {x}")
    # documents that touch both sides, with the labelled links on each side
    shared = []
    for doc in sorted({o for r, o, d, c in adj[a] if "/" in o}):
        to_b = [(r, d) for r, o, d, c in adj[doc] if o == b]
        if to_b:
            to_a = [(r, d) for r, o, d, c in adj[doc] if o == a]
            fmt = lambda links, who: "; ".join(f"{r} {who}" if d == "out" else f"{who} {r} it" for r, d in links)
            shared.append(f"  {doc}: {fmt(to_a, a)} | {fmt(to_b, b)}")
    print(f"\nShared documents ({len(shared)}):" if shared else "\nShared documents: none")
    for x in shared[:40]: print(x)
    if not direct and not shared:  # only then fall back to longer chains
        ps = [p for p in paths(a, b) if len(p) > 2]
        print(f"\nLonger chains ({len(ps)}):" if ps else "\nNo connection found within 3 steps.")
        for p in ps[:15]: print("  " + "  ->  ".join(p))

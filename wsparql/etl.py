"""Minimal ETL: csv/*.csv + tbox.ttl -> abox.ttl. Convention, the TBOX is the schema and its IRIs are opaque: file stem =
class label, column = property label, a reference cell = TBOX individual label or CSV row `id`, `id` = IRI local name,
`|` separates several values in a cell, empty cell = no triple. Names are compared as slugs (`expenseDate` = `expense date`).
The TBOX decides whether a column is a reference (owl:ObjectProperty) or a literal and its datatype (rdfs:range).
No inference: a relation is stored once, in one direction, and queries walk it with an explicit join."""
import csv
from pathlib import Path

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace

from wsparql.tags import slug, words

SEP = "|"


def build(path):
    """Graph of path/csv/*.csv typed by path/tbox.ttl; ValueError on an unknown file or column, an empty id,
    an ill-typed value or a dangling reference."""
    path = Path(path)
    tbox = Graph().parse(path / "tbox.ttl")
    name = lambda nodes: {slug(words(n, tbox)): n for n in nodes}  # label -> term; opaque IRIs carry no name
    classes = name(tbox.subjects(RDF.type, OWL.Class))
    prefix, ns, _ = tbox.compute_qname(next(iter(classes.values())))  # the profile prefix is the one the TBOX classes use (ex, c3po)
    ns = Namespace(ns)
    objs = set(tbox.subjects(RDF.type, OWL.ObjectProperty))
    rng = {p: tbox.value(p, RDFS.range) for p in tbox.subjects(RDF.type, OWL.DatatypeProperty)}
    props = name(objs | set(rng))
    # ponytail: a CSV row id that slugs like a TBOX individual label (a supplier called Travel) resolves to the individual
    individuals = name(i for i, c in tbox.subject_objects(RDF.type) if (c, RDF.type, OWL.Class) in tbox)
    g = Graph(bind_namespaces="core")
    g.bind(prefix, ns)
    for f in sorted((path / "csv").glob("*.csv")):
        if (cls := classes.get(slug(f.stem))) is None:
            raise ValueError(f"{f.name}: no class of tbox.ttl is labeled {f.stem}")
        with f.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            cols = reader.fieldnames or []
            if "id" not in cols:
                raise ValueError(f"{f.name}: no id column")
            if unknown := [c for c in cols if c != "id" and slug(c) not in props]:
                raise ValueError(f"{f.name}: {', '.join(unknown)} is not a property of tbox.ttl")
            for row in reader:
                if not (rid := row.pop("id")):
                    raise ValueError(f"{f.name} line {reader.line_num}: empty id")
                s = ns[rid]
                g.add((s, RDF.type, cls))
                for col, cell in row.items():
                    p = props[slug(col)]
                    for v in filter(None, (cell or "").split(SEP)):
                        if p in objs:
                            g.add((s, p, individuals.get(slug(v), ns[v])))
                        else:  # ponytail: xsd:string -> plain literal, what hand-written Turtle produces
                            lit = Literal(v, datatype=None if rng[p] == XSD.string else rng[p])
                            if lit.ill_typed:
                                raise ValueError(f"{f.name} {rid}.{col}: {v!r} is not a valid {rng[p].fragment}")
                            g.add((s, p, lit))
    known = set(g.subjects()) | set(tbox.subjects())  # TBOX individuals (expense categories) are valid references
    if dangling := {o for p in objs for o in g.objects(None, p)} - known:
        raise ValueError("unknown references: " + ", ".join(sorted(o.fragment for o in dangling)))
    return g


def write(path):
    """Build and write path/abox.ttl; returns (file path, triple count)."""
    g = build(path)
    out = Path(path) / "abox.ttl"
    out.write_text(g.serialize(format="turtle"), encoding="utf-8")
    return out, len(g)

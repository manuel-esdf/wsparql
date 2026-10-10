"""Load a POC profile directory: ontology + data graph, catalog, queries, test questions."""
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from rdflib import RDF, RDFS, XSD, Graph, Literal, URIRef


def camel(label):
    """'charged to work package' -> 'chargedToWorkPackage', 'European project' -> 'EuropeanProject'."""
    w = label.split()
    return w[0] + "".join(x.capitalize() for x in w[1:])


def literal(value):
    """Query parameter value -> RDF literal."""
    # ponytail: typed by value shape; declare types in the catalog if a non-date typed param appears
    value = str(value)
    return Literal(value, datatype=XSD.date) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else Literal(value)


def norm(v):
    """Numbers at 6 decimals (the ETL types `0` as `0.0`; summation order moves the 28th digit of a SUM), else as is."""
    try:
        return f"{Decimal(v):.6f}"
    except InvalidOperation:
        return v


class Profile:
    def __init__(self, path):
        path = Path(path)
        self.name = path.name
        self.version = (path / "VERSION").read_text().strip()
        self.graph = Graph()
        self.graph.parse(path / "tbox.ttl")
        self.graph.parse(path / "abox.ttl")
        catalog = yaml.safe_load((path / "query-catalog.yaml").read_text())
        self.min_confidence = catalog.get("min-confidence", 0.4)
        self.parameter_min_confidence = catalog.get("parameter-min-confidence", self.min_confidence)
        for name, value in (("min-confidence", self.min_confidence),
                            ("parameter-min-confidence", self.parameter_min_confidence)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError(f"{path}/query-catalog.yaml: {name} must be a number between 0 and 1")
        self.catalog = catalog["queries"]
        # {param: what fills it}: a property label (one of its ABOX values), a list (one of those words) or date (from/to)
        self.parameters = catalog.get("parameters", {})
        self.queries = {p.stem: p.read_text() for p in sorted((path / "queries").glob("*.rq"))}
        # ponytail: selection reads the SPARQL text and the IRIs are opaque, so it gets the labels in their place
        # (ex:P14 -> ex:amount, ex:C02 -> ex:EuropeanProject); labeled subjects are the TBOX terms, ABOX rows have none.
        # Indentation and blank lines are dropped: one choice over every query must fit the model's context (winnow:
        # 8192 tokens; the 29 c3po queries came to 8213 as written). The PREFIX lines stay: dropping them instead cost
        # eu-expense 3 answers. A bigger catalog may require selecting among fewer queries
        nm = self.graph.namespace_manager
        names = {nm.normalizeUri(s): nm.normalizeUri(s).split(":")[0] + ":" + camel(str(l)) for s, l in self.graph.subject_objects(RDFS.label)}
        term = re.compile("|".join(map(re.escape, names)) + r"\b")
        strip = lambda q: re.sub(r"(?m)^[ \t]+|\n(?=\n)", "", q)
        self.readable = {qid: term.sub(lambda m: names[m.group()], strip(q)) for qid, q in self.queries.items()}
        # ponytail: profile-specific labels in code: a question naming a reporting period gets its dates as from/to
        # (c3po); eu-expense has no such period and keeps the quarter/month/year regex
        by = lambda label: self.graph.value(predicate=RDFS.label, object=Literal(label))
        name, start, end = by("reporting period display name"), by("reporting period start date"), by("reporting period end date")
        self.periods = {str(n): (str(self.graph.value(s, start)), str(self.graph.value(s, end)))
                        for s, n in self.graph.subject_objects(name)} if name else {}
        self._values = {}
        # [{q_id, question, expected_query?}]; expected_query = catalog id or "none", absent = not evaluated
        self.test_questions = yaml.safe_load((path / "tests/test-questions.yaml").read_text())["questions"]
        # [{q_id, query, params, rows, expected}]: the draft's expected values per competency question, [] when absent
        exp = path / "tests/expected.json"
        self.expected = json.loads(exp.read_text()) if exp.exists() else []
        self.db_path = path.parent / "profile.db"  # shared evaluation results, one folder up, git-ignored

    def property(self, label):
        p = self.graph.value(predicate=RDFS.label, object=Literal(label))
        if p is None:
            raise ValueError(f"{self.name}: no property of tbox.ttl is labeled {label!r}")
        return p

    def values(self, label):
        """The distinct ABOX values of the property labeled `label`, sorted (the choices of a query parameter)."""
        if label not in self._values:
            self._values[label] = sorted({str(v) for v in self.graph.objects(None, self.property(label))})
        return self._values[label]

    def noun(self, label):
        """What the values of the property labeled `label` name: the label of its rdfs:domain, else of the class of a
        subject carrying it ('acronym' -> 'European project'), else the label itself."""
        p = self.property(label)
        c = self.graph.value(p, RDFS.domain) or next((c for s in self.graph.subjects(p) for c in self.graph.objects(s, RDF.type)), None)
        return str(self.graph.value(c, RDFS.label) or label) if c is not None else label

    def run(self, query_id, bindings=None):
        """Run one catalog query with its parameters bound (rdflib initBindings, no templating; an unbound optional
        parameter leaves its variable free); returns (column names, rows of display strings)."""
        res = self.graph.query(self.queries[query_id], initBindings={k: literal(v) for k, v in (bindings or {}).items()})
        nm = self.graph.namespace_manager
        cell = lambda c: "" if c is None else c.n3(nm) if isinstance(c, URIRef) else str(c)
        return [str(v) for v in res.vars], [[cell(c) for c in row] for row in res]

    def check_expected(self):
        """Run every tests/expected.json case; yields (case, row count, expected values not among the returned cells).
        Raw graph.query, so IRIs compare in full; a merged query may return more columns than the draft's."""
        for c in self.expected:
            rows = list(self.graph.query(self.queries[c["query"]], initBindings={k: literal(v) for k, v in c["params"].items()}))
            got = {norm(str(x)) for row in rows for x in row if x is not None}
            yield c, len(rows), sorted({norm(v) for v in c["expected"]} - got)

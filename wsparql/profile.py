"""Load a POC profile directory: ontology + data graph, tags, catalog, queries, test questions."""
import re
from pathlib import Path

import yaml
from rdflib import XSD, Graph, Literal, URIRef


def literal(value):
    """Query parameter value -> RDF literal."""
    # ponytail: typed by value shape; declare types in the catalog if a non-date typed param appears
    value = str(value)
    return Literal(value, datatype=XSD.date) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else Literal(value)


class Profile:
    def __init__(self, path):
        path = Path(path)
        self.name = path.name
        self.version = (path / "VERSION").read_text().strip()
        self.graph = Graph()
        self.graph.parse(path / "tbox.ttl")
        self.graph.parse(path / "abox.ttl")
        self.tags = yaml.safe_load((path / "tags.yaml").read_text())["tags"]
        self.catalog = yaml.safe_load((path / "query-catalog.yaml").read_text())["queries"]
        self.queries = {p.stem: p.read_text() for p in sorted((path / "queries").glob("*.rq"))}
        # ponytail: profile-specific IRI in code; move to a params file when a second profile appears
        self.acronyms = sorted(str(r[0]) for r in self.graph.query(
            "SELECT DISTINCT ?a WHERE { ?p <https://example.org/eu-expense#acronym> ?a }"))
        # [{q_id, question, expected_query?}]; expected_query = catalog id or "none", absent = not evaluated
        self.test_questions = yaml.safe_load((path / "tests/test-questions.yaml").read_text())["questions"]
        self.db_path = path.parent / "profile.db"  # shared tag cache, one folder up, git-ignored

    def run(self, query_id, bindings=None):
        """Run one catalog query with its parameters bound (rdflib initBindings, no templating);
        returns (column names, rows of display strings)."""
        res = self.graph.query(self.queries[query_id], initBindings={k: literal(v) for k, v in (bindings or {}).items()})
        nm = self.graph.namespace_manager
        cell = lambda c: "" if c is None else c.n3(nm) if isinstance(c, URIRef) else str(c)
        return [str(v) for v in res.vars], [[cell(c) for c in row] for row in res]

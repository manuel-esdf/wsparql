"""Load a POC profile directory: ontology + data graph, tags, catalog, queries, test questions."""
from pathlib import Path

import yaml
from rdflib import Graph, URIRef


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
        # [{q_id, question, expected_query?}]; expected_query = catalog id or "none", absent = not evaluated
        self.test_questions = yaml.safe_load((path / "tests/test-questions.yaml").read_text())["questions"]
        self.db_path = path.parent / "profile.db"  # shared tag cache, one folder up, git-ignored

    def run(self, query_id):
        """Run one catalog query; returns (column names, rows of display strings)."""
        res = self.graph.query(self.queries[query_id])
        nm = self.graph.namespace_manager
        cell = lambda c: "" if c is None else c.n3(nm) if isinstance(c, URIRef) else str(c)
        return [str(v) for v in res.vars], [[cell(c) for c in row] for row in res]

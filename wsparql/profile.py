"""Load a POC profile directory: ontology + data graph, tags, catalog, queries, demo questions."""
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
        self.demo_questions = yaml.safe_load((path / "demo-questions.yaml").read_text())["questions"]
        self.queries = {p.stem: p.read_text() for p in sorted((path / "queries").glob("*.rq"))}
        self.tag_questions = [q.strip() for q in (path / "tests/tag-questions.txt").read_text().splitlines() if q.strip()]
        self.db_path = path / "profile.db"

    def run(self, query_id):
        """Run one catalog query; returns (column names, rows of display strings)."""
        res = self.graph.query(self.queries[query_id])
        nm = self.graph.namespace_manager
        cell = lambda c: "" if c is None else c.n3(nm) if isinstance(c, URIRef) else str(c)
        return [str(v) for v in res.vars], [[cell(c) for c in row] for row in res]

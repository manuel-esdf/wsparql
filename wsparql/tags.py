"""Tag dictionary derived from the ontology (see GENERATE-TAGS-FROM-ONTOLOGY.md):
classes with data, individuals declared in the TBOX, boolean/numeric/date datatype properties, plus fixed intent tags."""
import re
from pathlib import Path

from rdflib import OWL, RDF, RDFS, XSD, Graph

# ponytail: question-shape intents exist in no ontology; one list for every profile, edit here
INTENT = {
    "total": "The user wants a total amount",
    "breakdown": "The user wants a breakdown by dimension",
    "comparison": "The user wants to compare several entities or values",
    "ranking": "The user wants entities ordered by amount",
    "list": "The user wants individual records listed",
    "trend": "The user wants evolution over time",
    "month": "The question concerns monthly aggregation",
    "date-range": "The question specifies or implies a period",
}
TIME = ("time", "The question includes a temporal dimension")  # one tag for all xsd:date properties
NUMERIC = {XSD.decimal, XSD.integer, XSD.float, XSD.double}
DATES = {XSD.date, XSD.dateTime}
MIN_INDIVIDUALS = 2  # ponytail: a class with fewer individuals (Company) cannot discriminate questions


def words(node, g):
    """Human words for a node: rdfs:label, else the IRI local name split on camelCase ('OtherGoodsServices' -> 'other goods services')."""
    label = g.value(node, RDFS.label) or re.split(r"[#/]", str(node))[-1]
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(label)).lower()


def slug(text):
    """'European project' / 'EuropeanProject' -> 'european-project'."""
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text).lower()).strip("-")


def generate(path):
    """[(tag, description, source)] from path/tbox.ttl + path/abox.ttl; description = rdfs:comment when present, else a template.
    First rule wins on a name clash."""
    path = Path(path)
    tbox = Graph().parse(path / "tbox.ttl")
    g = Graph().parse(path / "tbox.ttl").parse(path / "abox.ttl")
    qn = tbox.namespace_manager.normalizeUri
    out = {}

    def add(tag, node, default, source):
        out.setdefault(tag, (str(tbox.value(node, RDFS.comment) or default), source))

    # R1: classes with enough individuals in TBOX + ABOX
    for c in sorted(tbox.subjects(RDF.type, OWL.Class)):
        if len(set(g.subjects(RDF.type, c))) >= MIN_INDIVIDUALS:
            add(slug(words(c, tbox)), c, f"The question concerns: {words(c, tbox)}", f"class {qn(c)}")
    # R2: individuals declared in the TBOX are controlled vocabulary (ABOX individuals are parameter values, not tags)
    for i, c in sorted(tbox.subject_objects(RDF.type)):
        if (c, RDF.type, OWL.Class) in tbox:
            add(slug(words(i, tbox)), i, f"The question concerns: {words(i, tbox)} ({words(c, tbox)})", f"individual {qn(i)}")
    # R3: datatype properties by range; dates collapse into one `time` tag; strings are identity values, skipped
    for p in sorted(tbox.subjects(RDF.type, OWL.DatatypeProperty)):
        r = tbox.value(p, RDFS.range)
        if r == XSD.boolean or r in NUMERIC:
            add(slug(words(p, tbox)), p, f"The question concerns: {words(p, tbox)}", f"property {qn(p)}")
        elif r in DATES:
            out.setdefault(TIME[0], (TIME[1], "property xsd:date"))
    # R4: intents
    for tag, desc in INTENT.items():
        out.setdefault(tag, (desc, "intent"))
    return [(tag, desc, source) for tag, (desc, source) in out.items()]

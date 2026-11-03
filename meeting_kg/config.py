import os
from pathlib import Path

from dotenv import load_dotenv
from rdflib import Graph, Namespace

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

SCHEMA_FILE = ROOT / "ontology" / "schema.ttl"
SHAPES_FILE = ROOT / "ontology" / "shapes.ttl"
REFERENCE_FILE = ROOT / "data" / "reference.ttl"
SAMPLES_DIR = ROOT / "samples"
ANSWER_KEY_FILE = SAMPLES_DIR / "answer_key.toml"
EXTRACTED_DIR = ROOT / "extracted"
OUTPUT_DIR = ROOT / "output"
QUERIES_DIR = ROOT / "queries"
RULES_FILE = ROOT / "rules" / "checks.dl"
GRAPH_FILE = OUTPUT_DIR / "graph.ttl"
INFERRED_FILE = OUTPUT_DIR / "graph_inferred.ttl"

ONT = Namespace("https://example.org/ontology-study/ont#")
EX = Namespace("https://example.org/ontology-study/id/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")

UPSTAGE_BASE_URL = "https://api.upstage.ai/v1"
UPSTAGE_MODEL = os.getenv("UPSTAGE_MODEL", "solar-pro4")
UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")


def bind_prefixes(graph: Graph) -> Graph:
    graph.bind("ont", ONT)
    graph.bind("ex", EX)
    graph.bind("skos", SKOS)
    return graph

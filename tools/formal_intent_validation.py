"""Tool backing the `formal-intent-validation` skill.

Validates a TM Forum intent (JSON or Turtle) against the InTrust SHACL shapes
and returns a structured conformance report.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ONTOLOGY_DIR = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "skills"
    / "ontology"
)
SHAPES_CANDIDATES = ["intrust-shapes.ttl", "intrust.ttl"]

_shapes_graph_cache: Dict[str, Any] = {}


def _resolve_shapes_path(override: Optional[str]) -> Path:
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = ONTOLOGY_DIR / path
        return path
    for name in SHAPES_CANDIDATES:
        candidate = ONTOLOGY_DIR / name
        if candidate.exists():
            return candidate
    return ONTOLOGY_DIR / SHAPES_CANDIDATES[0]


def _load_shapes_graph(shapes_path: Path):
    cache_key = str(shapes_path.resolve()) if shapes_path.exists() else str(shapes_path)
    if cache_key in _shapes_graph_cache:
        return _shapes_graph_cache[cache_key]

    from rdflib import Graph

    if not shapes_path.exists():
        raise FileNotFoundError(
            f"SHACL shapes file not found at {shapes_path}. "
            "Place shapes in 'intrust-shapes.ttl' or alongside the ontology in 'intrust.ttl'."
        )

    graph = Graph()
    graph.parse(shapes_path, format="turtle")
    _shapes_graph_cache[cache_key] = graph
    return graph


def _ontology_base_iri(shapes_graph) -> Optional[str]:
    from rdflib import OWL, RDF

    for subject in shapes_graph.subjects(RDF.type, OWL.Ontology):
        iri = str(subject)
        return iri if iri.endswith(("#", "/")) else iri + "#"
    for prefix, namespace in shapes_graph.namespaces():
        if prefix == "":
            return str(namespace)
    return None


def _data_graph_from_payload(payload: Dict[str, Any], shapes_graph):
    from rdflib import Graph

    data_graph = Graph()

    if "intent_ttl" in payload and payload["intent_ttl"]:
        data_graph.parse(data=payload["intent_ttl"], format="turtle")
        return data_graph

    intent = payload.get("intent")
    if intent is None:
        raise ValueError("payload must contain either 'intent' or 'intent_ttl'")
    if not isinstance(intent, dict):
        raise ValueError("'intent' must be a JSON object")

    context = payload.get("context")
    if context is None:
        base = _ontology_base_iri(shapes_graph) or "urn:intrust:"
        context = {"@vocab": base}

    document = dict(intent)
    document["@context"] = context
    if "@id" not in document and "intentId" in document:
        document["@id"] = f"urn:intent:{document['intentId']}"

    data_graph.parse(data=json.dumps(document), format="json-ld")
    return data_graph


def _format_violations(report_graph) -> List[Dict[str, Any]]:
    from rdflib.namespace import SH

    violations: List[Dict[str, Any]] = []
    for result in report_graph.subjects(predicate=SH.resultSeverity, object=None):
        def _val(predicate):
            value = report_graph.value(result, predicate)
            return str(value) if value is not None else None

        violations.append(
            {
                "focus_node": _val(SH.focusNode),
                "result_path": _val(SH.resultPath),
                "source_shape": _val(SH.sourceShape),
                "source_constraint_component": _val(SH.sourceConstraintComponent),
                "severity": _val(SH.resultSeverity),
                "value": _val(SH.value),
                "message": _val(SH.resultMessage),
            }
        )
    return violations


def validate_formal_intent(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a TM Forum intent against the InTrust SHACL shapes.

    Expected payload:
        {
            "intent": {...}          | "intent_ttl": "@prefix ...",
            "context": {...},        # optional JSON-LD context override
            "shapes_ttl_path": "..." # optional override
        }
    """
    try:
        from pyshacl import validate
    except ImportError:
        return {
            "status": "FAILED",
            "error": (
                "pyshacl is required for formal-intent-validation; "
                "add 'pyshacl>=0.25' to requirements.txt"
            ),
        }

    shapes_path = _resolve_shapes_path(payload.get("shapes_ttl_path"))

    try:
        shapes_graph = _load_shapes_graph(shapes_path)
    except FileNotFoundError as exc:
        return {"status": "FAILED", "error": str(exc)}
    except Exception as exc:
        return {"status": "FAILED", "error": f"failed to parse shapes: {exc}"}

    try:
        data_graph = _data_graph_from_payload(payload, shapes_graph)
    except ValueError as exc:
        return {"status": "FAILED", "error": str(exc)}
    except Exception as exc:
        return {"status": "FAILED", "error": f"failed to build data graph: {exc}"}

    try:
        conforms, report_graph, report_text = validate(
            data_graph=data_graph,
            shacl_graph=shapes_graph,
            ont_graph=shapes_graph,
            inference="rdfs",
            advanced=True,
            meta_shacl=False,
            debug=False,
        )
    except Exception as exc:
        return {"status": "FAILED", "error": f"SHACL validation error: {exc}"}

    violations = _format_violations(report_graph) if not conforms else []

    return {
        "status": "SUCCESS",
        "conforms": bool(conforms),
        "violation_count": len(violations),
        "violations": violations,
        "report_text": report_text,
        "shapes_source": str(shapes_path),
    }

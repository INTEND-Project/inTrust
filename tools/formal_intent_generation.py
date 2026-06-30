"""Tool backing the `formal-intent-generation` skill.

Loads the InTrust ontology (Turtle) once and returns the classes / properties
relevant to TM Forum intent authoring, so the calling LLM can compose a
formal intent JSON grounded in the ontology vocabulary.
"""

from pathlib import Path
from typing import Any, Dict, Optional

ONTOLOGY_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "skills"
    / "ontology"
    / "intrust.ttl"
)

_graph = None  # cached rdflib.Graph after first successful load


def _load_ontology():
    global _graph
    if _graph is not None:
        return _graph

    try:
        from rdflib import Graph
    except ImportError as exc:
        raise RuntimeError(
            "rdflib is required for formal-intent-generation; "
            "add 'rdflib>=7.0' to requirements.txt"
        ) from exc

    if not ONTOLOGY_PATH.exists():
        raise FileNotFoundError(
            f"Ontology file not found at {ONTOLOGY_PATH}. "
            "Place the InTrust Turtle ontology there."
        )

    graph = Graph()
    graph.parse(ONTOLOGY_PATH, format="turtle")
    _graph = graph
    return graph


def _summarize(graph) -> Dict[str, Any]:
    from rdflib import RDF, RDFS, OWL

    def _str(node) -> Optional[str]:
        return str(node) if node is not None else None

    classes = []
    seen_classes = set()
    for class_type in (OWL.Class, RDFS.Class):
        for subject in graph.subjects(RDF.type, class_type):
            iri = str(subject)
            if iri in seen_classes:
                continue
            seen_classes.add(iri)
            classes.append(
                {
                    "iri": iri,
                    "label": _str(graph.value(subject, RDFS.label)),
                    "comment": _str(graph.value(subject, RDFS.comment)),
                }
            )

    properties = []
    seen_props = set()
    for prop_type, kind in (
        (OWL.ObjectProperty, "object"),
        (OWL.DatatypeProperty, "datatype"),
        (RDF.Property, "rdf"),
    ):
        for subject in graph.subjects(RDF.type, prop_type):
            iri = str(subject)
            if iri in seen_props:
                continue
            seen_props.add(iri)
            properties.append(
                {
                    "iri": iri,
                    "label": _str(graph.value(subject, RDFS.label)),
                    "comment": _str(graph.value(subject, RDFS.comment)),
                    "domain": _str(graph.value(subject, RDFS.domain)),
                    "range": _str(graph.value(subject, RDFS.range)),
                    "kind": kind,
                }
            )

    classes.sort(key=lambda c: c["iri"])
    properties.sort(key=lambda p: p["iri"])
    return {"classes": classes, "properties": properties}


def build_formal_intent(intent_request: Dict[str, Any]) -> Dict[str, Any]:
    """Return the ontology schema the caller should use to compose a TMF intent.

    Expected input shape:
        {
            "description": "<natural-language intent description>",
            "requestedBy": { ... },     # optional, passed through
            "targetHint":  "...",       # optional, passed through
            "criteria":    [ ... ],     # optional, passed through
            "dueBy":       "..."        # optional, passed through
        }

    The caller (the LLM agent) is expected to use the returned ontology
    fragments to emit a complete TM Forum intent JSON in its next turn.
    """
    description = intent_request.get("description") or intent_request.get(
        "intent_description"
    )
    if not description:
        return {
            "status": "FAILED",
            "error": "missing required field: 'description'",
        }

    try:
        graph = _load_ontology()
    except (RuntimeError, FileNotFoundError) as exc:
        return {"status": "FAILED", "error": str(exc)}
    except Exception as exc:
        return {
            "status": "FAILED",
            "error": f"failed to parse ontology: {exc}",
        }

    ontology = _summarize(graph)

    passthrough = {
        key: intent_request[key]
        for key in ("requestedBy", "targetHint", "criteria", "dueBy")
        if key in intent_request
    }

    return {
        "status": "SUCCESS",
        "description": description,
        "passthrough": passthrough,
        "ontology": ontology,
        "ontology_source": str(ONTOLOGY_PATH),
        "instructions": (
            "Compose a TM Forum intent JSON object using the classes and "
            "properties above as the authoritative vocabulary. Required "
            "top-level fields: intentId, intentType, description, target, "
            "assessment (focus + assessmentType + parameters), criteria, "
            "output, lifecycle.state='Created'. Prefer ontology IRIs over "
            "free strings when the ontology defines a term. If the "
            "description is missing information the ontology marks as "
            "required, ask one clarifying question instead of inventing it."
        ),
    }

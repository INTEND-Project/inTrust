"""Tool backing the `formal-report-generation` skill.

Loads the InTrust ontology and returns the report-relevant classes /
properties so the calling LLM can compose a TM Forum-aligned assessment
report grounded in the ontology vocabulary.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ONTOLOGY_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "skills"
    / "ontology"
    / "intrust.ttl"
)
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

REPORT_CLASS_HINTS = (
    "report",
    "assessmentreport",
    "tmfintentreport",
)

_graph = None


def _load_ontology():
    global _graph
    if _graph is not None:
        return _graph

    try:
        from rdflib import Graph
    except ImportError as exc:
        raise RuntimeError(
            "rdflib is required for formal-report-generation; "
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


def _local_name(iri: str) -> str:
    for sep in ("#", "/"):
        if sep in iri:
            return iri.rsplit(sep, 1)[-1]
    return iri


def _is_report_class(iri: str, label: Optional[str]) -> bool:
    needle = (label or _local_name(iri)).lower()
    return any(hint in needle for hint in REPORT_CLASS_HINTS)


def _collect_report_classes(graph) -> List[Dict[str, Any]]:
    from rdflib import RDF, RDFS, OWL

    seen: Set[str] = set()
    classes: List[Dict[str, Any]] = []
    for class_type in (OWL.Class, RDFS.Class):
        for subject in graph.subjects(RDF.type, class_type):
            iri = str(subject)
            if iri in seen:
                continue
            seen.add(iri)
            label = graph.value(subject, RDFS.label)
            label_str = str(label) if label is not None else None
            if not _is_report_class(iri, label_str):
                continue
            comment = graph.value(subject, RDFS.comment)
            classes.append(
                {
                    "iri": iri,
                    "local_name": _local_name(iri),
                    "label": label_str,
                    "comment": str(comment) if comment is not None else None,
                }
            )
    classes.sort(key=lambda c: c["iri"])
    return classes


def _properties_for_classes(graph, class_iris: Set[str]) -> List[Dict[str, Any]]:
    from rdflib import RDF, RDFS, OWL, URIRef

    if not class_iris:
        return []

    domains = {URIRef(iri) for iri in class_iris}
    seen: Set[str] = set()
    properties: List[Dict[str, Any]] = []

    for prop_type, kind in (
        (OWL.ObjectProperty, "object"),
        (OWL.DatatypeProperty, "datatype"),
        (RDF.Property, "rdf"),
    ):
        for subject in graph.subjects(RDF.type, prop_type):
            iri = str(subject)
            if iri in seen:
                continue
            domain_node = graph.value(subject, RDFS.domain)
            if domain_node is None or domain_node not in domains:
                continue
            seen.add(iri)
            label = graph.value(subject, RDFS.label)
            comment = graph.value(subject, RDFS.comment)
            range_node = graph.value(subject, RDFS.range)
            properties.append(
                {
                    "iri": iri,
                    "local_name": _local_name(iri),
                    "label": str(label) if label is not None else None,
                    "comment": str(comment) if comment is not None else None,
                    "domain": str(domain_node),
                    "range": str(range_node) if range_node is not None else None,
                    "kind": kind,
                }
            )
    properties.sort(key=lambda p: p["iri"])
    return properties


def _resolve_skill_report_class(intent: Dict[str, Any]) -> Optional[str]:
    """If the intent identifies an executing skill, read its metadata.json
    for an optional `report_class` hint."""
    skill_id = (
        intent.get("skillId")
        or intent.get("skill_id")
        or intent.get("assessment", {}).get("plugin", {}).get("name")
    )
    if not skill_id:
        return None
    skill_id = str(skill_id).strip().lower().replace("_", "-")
    metadata_path = SKILLS_DIR / skill_id / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return metadata.get("report_class")


def _select_class(
    classes: List[Dict[str, Any]], requested: Optional[str]
) -> Optional[Dict[str, Any]]:
    if not requested:
        return None
    requested_norm = requested.strip().lower()
    for cls in classes:
        if cls["iri"].lower() == requested_norm:
            return cls
        if cls["local_name"].lower() == requested_norm:
            return cls
        if cls["label"] and cls["label"].lower() == requested_norm:
            return cls
    return None


def build_formal_report(intent_request: Dict[str, Any]) -> Dict[str, Any]:
    """Return the ontology schema the caller should use to compose a TMF report.

    Expected input shape:
        {
            "intent":       { ... original TM Forum intent JSON ... },
            "raw_result":   { ... assessment tool output ... },
            "report_class": "PrivacyAssessmentReport"   # optional
        }
    """
    intent = intent_request.get("intent")
    raw_result = intent_request.get("raw_result")
    if intent is None or raw_result is None:
        return {
            "status": "FAILED",
            "error": "missing required fields: 'intent' and 'raw_result'",
        }

    try:
        graph = _load_ontology()
    except (RuntimeError, FileNotFoundError) as exc:
        return {"status": "FAILED", "error": str(exc)}
    except Exception as exc:
        return {"status": "FAILED", "error": f"failed to parse ontology: {exc}"}

    report_classes = _collect_report_classes(graph)

    requested_class = (
        intent_request.get("report_class")
        or _resolve_skill_report_class(intent)
    )
    selected = _select_class(report_classes, requested_class)
    selected_iris = {selected["iri"]} if selected else {c["iri"] for c in report_classes}
    report_properties = _properties_for_classes(graph, selected_iris)

    return {
        "status": "SUCCESS",
        "intent": intent,
        "raw_result": raw_result,
        "ontology": {
            "report_classes": report_classes,
            "report_properties": report_properties,
        },
        "selected_report_class": selected["local_name"] if selected else None,
        "ontology_source": str(ONTOLOGY_PATH),
        "instructions": (
            "Compose a tmfIntentReport.v1 JSON object using the classes and "
            "properties above as the authoritative vocabulary. Set "
            "\"@type\": \"AssessmentReport\" so the report validates against "
            "the InTrust SHACL shapes. Required top-level fields: intentId "
            "(carried from the intent), reportType, status (one of SUCCESS, "
            "FAILED, INCONCLUSIVE), summary, findings, recommendations, "
            "provenance, lifecycle.state. Map raw_result fields onto ontology "
            "properties; parse unstructured raw_result content (CSV, free "
            "text) into the metrics named by the ontology before assigning "
            "datatype-ranged properties. Prefer ontology IRIs over free "
            "strings when the ontology defines a term."
        ),
    }

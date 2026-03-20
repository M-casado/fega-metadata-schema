"""
rdf_utils.py - RDF and JSON-LD utilities for FEGA tools
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from rdflib import Graph
except ImportError as exc:
    raise ImportError(
        "rdflib is required. Install with: pip install rdflib"
    ) from exc

try:
    from pyshacl import validate as shacl_validate
except ImportError as exc:
    raise ImportError(
        "pyshacl is required. Install with: pip install pyshacl"
    ) from exc

logger = logging.getLogger(__name__)

# -------
# JSON-LD to RDF conversion
# -------

def jsonld_to_rdf_graph(
    jsonld_document: Dict[str, Any],
    base_uri: Optional[str] = None
) -> Graph:
    """Convert a JSON-LD document to an RDF graph.

    Args:
        jsonld_document: Dictionary containing the JSON-LD data with @context, @type, etc.
        base_uri: Optional base URI for resolving relative references.

    Returns:
        An rdflib Graph containing the RDF representation.

    Raises:
        ValueError: If the JSON-LD document cannot be converted.
    """
    try:
        # Create a graph and parse the JSON-LD
        graph = Graph()
        graph.parse(
            data=json.dumps(jsonld_document),
            format="json-ld",
            base=base_uri or "http://example.org/data/"
        )
        return graph
    except Exception as exc:
        raise ValueError(f"Failed to convert JSON-LD to RDF: {exc}") from exc

# -------
# SHACL validation
# -------

def validate_against_shacl(
    data_graph: Graph,
    shapes_graph: Graph,
    shape_focus: Optional[str] = None
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate a data graph against SHACL shapes.

    Args:
        data_graph: The RDF graph to validate.
        shapes_graph: The RDF graph containing SHACL shape definitions.
        shape_focus: Optional specific shape to validate against (defaults to all).

    Returns:
        A tuple of (conforms: bool, report_text: str, report_dict: dict).
        The report_dict contains detailed violation information.
    """
    try:
        conforms, results_graph, results_text = shacl_validate(
            data_graph=data_graph,
            shacl_graph=shapes_graph,
            focus_nodes=[shape_focus] if shape_focus else None,
            inference="rdfs",
            abort_on_first=False
        )
        
        # Convert results_graph to a dict-like structure for easier inspection
        report_dict = {
            "conforms": conforms,
            "violations": extract_violations_from_graph(results_graph)
        }
        
        return conforms, results_text, report_dict
    except Exception as exc:
        raise ValueError(f"SHACL validation failed: {exc}") from exc

# -------
# RDF graph utilities
# -------

def load_rdf_from_file(filepath: Path) -> Graph:
    """Load an RDF graph from a file (TTL, RDF/XML, N-Triples, JSON-LD, etc.).

    Args:
        filepath: Path to the RDF file.

    Returns:
        An rdflib Graph containing the RDF data.

    Raises:
        ValueError: If the file cannot be parsed.
    """
    try:
        graph = Graph()
        # Auto-detect format from file extension
        fmt = _guess_rdf_format(filepath)
        graph.parse(str(filepath), format=fmt)
        return graph
    except Exception as exc:
        raise ValueError(f"Failed to load RDF from {filepath}: {exc}") from exc

def _guess_rdf_format(filepath: Path) -> str:
    """Guess the RDF serialization format from file extension."""
    suffix = filepath.suffix.lower()
    format_map = {
        ".ttl": "turtle",
        ".rdf": "xml",
        ".xml": "xml",
        ".jsonld": "json-ld",
        ".json-ld": "json-ld",
        ".nt": "nt",
        ".n3": "n3",
    }
    return format_map.get(suffix, "turtle")  # Default to turtle

def extract_types_from_graph(graph: Graph) -> Set[str]:
    """Extract all rdf:type values from a graph.

    Args:
        graph: The RDF graph to inspect.

    Returns:
        A set of IRIs representing the types found.
    """
    from rdflib import RDF
    
    types = set()
    for obj in graph.objects(predicate=RDF.type):
        types.add(str(obj))
    return types

def extract_violations_from_graph(results_graph: Graph) -> List[Dict[str, Any]]:
    """Extract SHACL violation details from a results graph.

    Args:
        results_graph: The RDF graph containing SHACL validation results.

    Returns:
        A list of dictionaries, each describing a violation.
    """
    from rdflib import Namespace, Literal
    
    SH = Namespace("http://www.w3.org/ns/shacl#")
    violations = []
    
    for result in results_graph.subjects(predicate=None):  # Get all result nodes
        # Extract violation details
        violation_info = {}
        
        # Get the focus node (what was validated)
        for focus in results_graph.objects(subject=result, predicate=SH.focusNode):
            violation_info["focusNode"] = str(focus)
            
        # Get the property shape
        source_shape = None
        for prop_shape in results_graph.objects(subject=result, predicate=SH.sourceShape):
            source_shape = prop_shape
            violation_info["sourceShape"] = str(prop_shape)
            
        # Get the severity
        for severity in results_graph.objects(subject=result, predicate=SH.severity):
            violation_info["severity"] = str(severity)
            
        # Get the message - try result message first, then source shape message
        message = None
        for msg in results_graph.objects(subject=result, predicate=SH.resultMessage):
            message = str(msg)
            violation_info["message"] = message
            break
        
        # If no result message, try to get message from the source shape
        if not message and source_shape:
            for shape_msg in results_graph.objects(subject=source_shape, predicate=SH.message):
                if isinstance(shape_msg, Literal):
                    message = str(shape_msg)
                    violation_info["message"] = message
                    break
        
        # Get the path (property)
        for path in results_graph.objects(subject=result, predicate=SH.resultPath):
            violation_info["resultPath"] = str(path)
            
        # Get the constraint component for better identification
        for component in results_graph.objects(subject=result, predicate=SH.sourceConstraintComponent):
            violation_info["constraint_type"] = str(component).split("#")[-1] if "#" in str(component) else str(component)
            break
            
        if violation_info:
            violations.append(violation_info)
    
    return violations

# -------
# Utilities for batch operations
# -------

def collect_candidate_rdf(paths: List[Path]) -> List[Path]:
    """Collect all RDF files from the given paths.

    Supports: *.ttl, *.rdf, *.xml, *.jsonld, *.nt, *.n3

    Args:
        paths: List of file or directory paths to search.

    Returns:
        A sorted list of RDF file paths found.
    """
    
    files: Set[Path] = set()
    rdf_extensions = {".ttl", ".rdf", ".xml", ".jsonld", ".json-ld", ".nt", ".n3"}
    
    for p in paths:
        if not p.exists():
            logger.warning(f"Path not found: {p}")
            continue
            
        if p.is_dir():
            for fp in p.rglob("*"):
                if fp.is_file() and fp.suffix.lower() in rdf_extensions:
                    files.add(fp.resolve())
        elif p.is_file() and p.suffix.lower() in rdf_extensions:
            files.add(p.resolve())
        else:
            logger.debug(f"Ignoring non-RDF path: {p}")
    
    return sorted(files)

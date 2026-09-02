# SPDX-FileCopyrightText: Copyright DB InfraGO AG and the capellambse-context-diagrams contributors
# SPDX-License-Identifier: Apache-2.0
"""Collector for the realization view diagram."""

from __future__ import annotations

import collections.abc as cabc
import copy
import re
import typing as t

import capellambse.model as m
from capellambse.metamodel import cs, fa, oa

from .. import _elkjs, context
from ..builders import _makers

try:
    from capellambse.extensions.reqif import requirements as req_mod
    from capellambse.extensions.reqif.capellarequirements import (
        CapellaIncomingRelation,
        CapellaOutgoingRelation,
    )

    HAS_REQUIREMENTS = True
except ImportError:
    HAS_REQUIREMENTS = False

RE_LAYER_PTRN = re.compile(r"([A-Z]?[a-z]+)")
LAYER_ORDER: t.Final = ("Operational", "System", "Logical", "Physical")
REQUIREMENTS_LAYER: t.Final = "Requirements"
REQUIREMENTS_LAYER_ID: t.Final = "__requirements_layer__"


def collector(
    diagram: context.RealizationViewDiagram, params: dict[str, t.Any]
) -> tuple[_elkjs.ELKInputData, list[_elkjs.ELKInputEdge]]:
    """Return the class tree data for ELK."""
    del params
    data = _makers.make_diagram(diagram)
    layout_options: _elkjs.LayoutOptions = copy.deepcopy(
        _elkjs.RECT_PACKING_LAYOUT_OPTIONS  # type:ignore[arg-type]
    )
    layout_options["elk.contentAlignment"] = "V_CENTER H_CENTER"
    del layout_options["widthApproximation.targetWidth"]
    data.layoutOptions = layout_options
    _collector = COLLECTORS[diagram._search_direction]
    lay_to_els = _collector(
        diagram.target, diagram._depth, diagram._include_requirements
    )
    layer_layout_options: _elkjs.LayoutOptions = layout_options | {  # type: ignore[operator]
        "nodeSize.constraints": "[NODE_LABELS,MINIMUM_SIZE]",
    }
    edges: list[_elkjs.ELKInputEdge] = []
    seen_edge_ids: set[str] = set()
    for layer in (*LAYER_ORDER, REQUIREMENTS_LAYER):
        if not (elements := lay_to_els.get(layer)):
            continue

        labels = _makers.make_label(layer)
        width, height = _makers.calculate_height_and_width(labels)
        layer_box_id = (
            REQUIREMENTS_LAYER_ID
            if layer == REQUIREMENTS_LAYER
            else elements[0]["layer"].uuid
        )
        layer_box = _elkjs.ELKInputChild(
            id=layer_box_id,
            children=[],
            height=width,
            width=height,
            layoutOptions=layer_layout_options,
        )
        children: dict[str, _elkjs.ELKInputChild] = {}
        for elt in elements:
            assert elt["element"] is not None
            element_is_req = HAS_REQUIREMENTS and isinstance(
                elt["element"], req_mod.Requirement
            )
            origin_is_req = (
                HAS_REQUIREMENTS
                and elt["origin"] is not None
                and isinstance(elt["origin"], req_mod.Requirement)
            )
            is_requirement_edge = element_is_req or origin_is_req
            if elt["origin"] is not None:
                if is_requirement_edge:
                    req_obj = elt["element"] if element_is_req else elt["origin"]
                    other_obj = (
                        elt["origin"] if element_is_req else elt["element"]
                    )
                    # An incoming relation originates from the Requirement
                    # (REQ -> object); an outgoing relation originates from
                    # the object (object -> REQ). This mirrors the actual
                    # relation, regardless of whether the hop was found
                    # going ABOVE or BELOW.
                    if elt.get("relation_kind") == "outgoing":
                        edge_source, edge_target = other_obj, req_obj
                    else:
                        edge_source, edge_target = req_obj, other_obj
                else:
                    edge_source, edge_target = elt["origin"], elt["element"]

                edge_id = f"{edge_source.uuid}_{edge_target.uuid}"
                if edge_id not in seen_edge_ids:
                    seen_edge_ids.add(edge_id)
                    edges.append(
                        _elkjs.ELKInputEdge(
                            id=edge_id,
                            sources=[edge_source.uuid],
                            targets=[edge_target.uuid],
                            **(
                                {"styleclass": "RequirementRelation"}
                                if is_requirement_edge
                                else {}
                            ),
                        )
                    )

            if elt.get("reverse", False):
                source = elt["element"]
                target = elt["origin"]
            else:
                source = elt["origin"]
                target = elt["element"]

            if HAS_REQUIREMENTS and isinstance(target, req_mod.Requirement):
                if target.uuid not in children:
                    req_box = _makers.make_box(target, no_symbol=True)
                    children[target.uuid] = req_box
                    layer_box.children.append(req_box)
                continue

            if not (element_box := children.get(target.uuid)):
                element_box = _makers.make_box(target, no_symbol=True)
                children[target.uuid] = element_box
                layer_box.children.append(element_box)
                index = len(layer_box.children) - 1

                if diagram._show_owners:
                    owner = target.owner
                    if not isinstance(
                        owner, fa.AbstractFunction | cs.Component
                    ):
                        continue

                    if not (owner_box := children.get(owner.uuid)):
                        owner_box = _makers.make_box(
                            owner,
                            no_symbol=True,
                            layout_options=_makers.DEFAULT_LABEL_LAYOUT_OPTIONS,
                        )
                        owner_box.height += element_box.height
                        children[owner.uuid] = owner_box
                        layer_box.children.append(owner_box)

                    del layer_box.children[index]
                    owner_box.children.append(element_box)
                    owner_box.width += element_box.width
                    for label in owner_box.labels:
                        label.layoutOptions.update(
                            _makers.DEFAULT_LABEL_LAYOUT_OPTIONS
                        )

                    if (
                        source is not None
                        and not (
                            HAS_REQUIREMENTS
                            and isinstance(source, req_mod.Requirement)
                        )
                        and source.owner is not None
                        and source.owner.uuid in children
                        and owner.uuid in children
                    ):
                        eid = f"{source.owner.uuid}_{owner.uuid}"
                        edges.append(
                            _elkjs.ELKInputEdge(
                                id=eid,
                                sources=[source.owner.uuid],
                                targets=[owner.uuid],
                            )
                        )

        data.children.append(layer_box)
    return data, edges


def collect_realized(
    start: m.ModelElement, depth: int, include_requirements: bool = False
) -> dict[LayerLiteral, list[dict[str, t.Any]]]:
    """Collect all elements from ``realized_`` attributes up to depth."""
    return collect_elements(
        start,
        depth,
        "ABOVE",
        "realized",
        include_requirements=include_requirements,
    )


def collect_realizing(
    start: m.ModelElement, depth: int, include_requirements: bool = False
) -> dict[LayerLiteral, list[dict[str, t.Any]]]:
    """Collect all elements from ``realizing_`` attributes down to depth."""
    return collect_elements(
        start,
        depth,
        "BELOW",
        "realizing",
        include_requirements=include_requirements,
    )


def collect_all(
    start: m.ModelElement, depth: int, include_requirements: bool = False
) -> dict[LayerLiteral, list[dict[str, t.Any]]]:
    """Collect all elements in both ABOVE and BELOW directions."""
    above = collect_realized(start, depth, include_requirements)
    below = collect_realizing(start, depth, include_requirements)
    merged: dict[LayerLiteral, list[dict[str, t.Any]]] = {}
    for layer, elts in above.items():
        merged.setdefault(layer, []).extend(elts)
    for layer, elts in below.items():
        merged.setdefault(layer, []).extend(elts)
    return merged


def _requirement_neighbors(
    start: m.ModelElement,
    exclude: m.ModelElement | None,
    arrived_via: str | None,
) -> list[tuple[m.ModelElement, str]]:
    """Return ``(neighbor, relation_kind)`` pairs linking ``start`` to
    Requirements.

    For an ordinary element, every ``CapellaIncomingRelation``/
    ``CapellaOutgoingRelation`` touching it is followed -- both incoming
    and outgoing relations are checked, regardless of the ABOVE/BELOW
    search direction.

    For a Requirement (i.e. we're continuing the chain *from* a
    Requirement we already reached), only the relation *opposite* to
    ``arrived_via`` is followed. A Requirement is commonly referenced by
    several unrelated elements; without this restriction, every other
    element sharing that Requirement -- a "sibling" of the one we came
    from, not an ancestor/descendant -- would be pulled in as noise.
    """
    is_req = HAS_REQUIREMENTS and isinstance(start, req_mod.Requirement)
    neighbors: list[tuple[m.ModelElement, str]] = []
    for rel in start.requirements_relations:
        if isinstance(rel, CapellaIncomingRelation):
            kind = "incoming"
        elif isinstance(rel, CapellaOutgoingRelation):
            kind = "outgoing"
        else:
            continue
        if is_req and arrived_via is not None and kind == arrived_via:
            continue
        other = rel.target if rel.source == start else rel.source
        if other is None or other == exclude:
            continue
        neighbors.append((other, kind))
    return neighbors


def collect_elements(
    start: m.ModelElement,
    depth: int,
    direction: str,
    attribute_prefix: str,
    origin: m.ModelElement | None = None,
    include_requirements: bool = False,
    relation_kind: str | None = None,
) -> dict[LayerLiteral, list[dict[str, t.Any]]]:
    """Collect elements based on the specified direction and attribute name."""
    is_requirement = HAS_REQUIREMENTS and isinstance(
        start, req_mod.Requirement
    )
    if is_requirement:
        layer_obj, layer = None, REQUIREMENTS_LAYER
    else:
        layer_obj, layer = find_layer(start)

    collected_elements: dict[LayerLiteral, list[dict[str, t.Any]]] = {}
    if direction == "ABOVE" or origin is None:
        collected_elements = {
            layer: [
                {
                    "element": start,
                    "origin": origin,
                    "layer": layer_obj,
                    "relation_kind": relation_kind,
                }
            ]
        }
    elif direction == "BELOW" and origin is not None:
        collected_elements = {
            layer: [
                {
                    "element": origin,
                    "origin": start,
                    "layer": layer_obj,
                    "reverse": True,
                    "relation_kind": relation_kind,
                }
            ]
        }

    if depth == 0:
        return collected_elements

    if not is_requirement:
        at_boundary = (direction == "ABOVE" and layer == "Operational") or (
            direction == "BELOW" and layer == "Physical"
        )
        if not at_boundary:
            if isinstance(start, fa.AbstractFunction):
                attribute_name = f"{attribute_prefix}_functions"
            elif isinstance(start, oa.OperationalActivity):
                attribute_name = f"{attribute_prefix}_system_functions"
            else:
                assert isinstance(start, cs.Component)
                attribute_name = f"{attribute_prefix}_components"

            for element in getattr(start, attribute_name, []):
                sub_collected = collect_elements(
                    element,
                    depth - 1,
                    direction,
                    attribute_prefix,
                    origin=start,
                    include_requirements=include_requirements,
                )
                for sub_layer, sub_elements in sub_collected.items():
                    collected_elements.setdefault(sub_layer, []).extend(
                        sub_elements
                    )

    if include_requirements and HAS_REQUIREMENTS:
        for neighbor, kind in _requirement_neighbors(
            start, origin, relation_kind
        ):
            sub_collected = collect_elements(
                neighbor,
                depth - 1,
                direction,
                attribute_prefix,
                origin=start,
                include_requirements=include_requirements,
                relation_kind=kind,
            )
            for sub_layer, sub_elements in sub_collected.items():
                collected_elements.setdefault(sub_layer, []).extend(
                    sub_elements
                )

    return collected_elements


LayerLiteral = (
    t.Literal["Operational"]
    | t.Literal["System"]
    | t.Literal["Logical"]
    | t.Literal["Physical"]
    | t.Literal["Requirements"]
)


def find_layer(
    obj: m.ModelElement,
) -> tuple[cs.ComponentArchitecture, LayerLiteral]:
    """Return the layer object and its literal.

    Return either one of the following:
      * ``Operational``
      * ``System``
      * ``Logical``
      * ``Physical``
    """
    parent: m.ModelElement = obj
    while not isinstance(parent, cs.ComponentArchitecture):
        parent = t.cast(m.ModelElement, parent.parent)
    if not (match := RE_LAYER_PTRN.match(type(parent).__name__)):
        raise ValueError("No layer was found.")
    return parent, match.group(1)  # type:ignore[return-value]


Collector = cabc.Callable[
    [m.ModelElement, int, bool], dict[LayerLiteral, list[dict[str, t.Any]]]
]
COLLECTORS: dict[str, Collector] = {
    "ALL": collect_all,
    "ABOVE": collect_realized,
    "BELOW": collect_realizing,
}
"""The functions to receive the diagram elements for every layer."""

# SPDX-FileCopyrightText: Copyright DB InfraGO AG and the capellambse-context-diagrams contributors
# SPDX-License-Identifier: Apache-2.0
"""Collector for Requirement ContextDiagrams.

This collector is used to collect context data for Requirements, showing
their relationships to other requirements and to model elements.
"""

from __future__ import annotations

import collections.abc as cabc
import typing as t

import capellambse.model as m

from .. import context

if t.TYPE_CHECKING:
    from capellambse.extensions.reqif import requirements as req_mod


def collector(
    diagram: context.ContextDiagram,
) -> cabc.Iterator[m.ModelElement]:
    """Collect context data for a Requirement.

    This collector gathers:
    - Relations to other requirements (InternalRelation objects)
    - Related requirements
    - Related model elements (Components, Functions, etc.)
    """
    req: req_mod.Requirement = diagram.target  # type: ignore[assignment]
    
    # Collect all relations
    if hasattr(req, 'relations'):
        for relation in req.relations:
            yield relation
    
    # Collect related requirements
    if hasattr(req, 'related'):
        for related_req in req.related:
            yield related_req
    
    # Collect related Capella elements
    if hasattr(req, 'related_capella_elements'):
        try:
            for element in req.related_capella_elements:
                yield element
        except Exception:
            # Some models may not have this attribute or it may fail
            pass

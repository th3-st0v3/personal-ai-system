"""Deterministic engineering model planning used when AI tools are unavailable."""
from __future__ import annotations

import re

import calculation_catalog
import simulation_library


_DISCIPLINE_HINTS = {
    "petroleum engineering": ("well", "wellbore", "reservoir", "drilling", "mud", "formation", "production", "porosity", "saturation"),
    "mechanical engineering": ("stress", "strain", "beam", "shaft", "spring", "thermal", "heat", "conduction", "mechanical"),
    "electrical engineering": ("voltage", "current", "resistance", "circuit", "capacitor", "power", "electrical"),
    "chemical engineering": ("reaction", "reactor", "concentration", "heat transfer", "mass balance", "chemical"),
    "civil engineering": ("beam", "column", "structure", "soil", "hydrology", "pipe", "civil"),
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9-]+", text.casefold()))


def _discipline(tokens: set[str]) -> str:
    scores = {name: sum(hint in tokens for hint in hints) for name, hints in _DISCIPLINE_HINTS.items()}
    return max(scores, key=scores.get) if max(scores.values(), default=0) else "General Engineering"


def build_model_plan(prompt: str) -> dict[str, object]:
    clean = " ".join(prompt.split())
    if not clean:
        raise ValueError("A modeling prompt is required.")
    tokens = _tokens(clean)
    discipline = _discipline(tokens)
    catalog_matches = calculation_catalog.search(clean)
    simulations = [simulation for simulation in simulation_library.list_simulations() if any(token in simulation.description.casefold() or token in simulation.name.casefold() for token in tokens)]
    if not simulations and any(word in tokens for word in {"model", "simulate", "simulation", "dynamic"}):
        simulations = list(simulation_library.list_simulations())[:1]
    calculations = []
    seen = set()
    for item in catalog_matches:
        if item.key not in seen:
            seen.add(item.key)
            calculations.append({"key": item.key, "name": item.name, "equation": item.equation, "categories": list(item.categories)})
        if len(calculations) >= 6:
            break
    variables = sorted({token for token in tokens if token in {"pressure", "depth", "density", "diameter", "velocity", "viscosity", "temperature", "conductivity", "area", "thickness", "stress", "strain", "voltage", "current", "resistance", "power"}})
    assumptions = ["Use SI units unless the user supplies another coherent unit system.", "Keep each deterministic calculation auditable and preserve its assumptions.", "Do not infer missing design constraints as facts; surface them as questions."]
    questions = []
    if not variables:
        questions.append("What are the governing quantities, boundary conditions, and desired output?")
    if discipline == "General Engineering":
        questions.append("Which engineering discipline or physical domain should govern the model?")
    return {
        "objective": clean,
        "discipline": discipline,
        "calculations": calculations,
        "simulations": [{"key": s.key, "name": s.name, "discipline": s.discipline, "parameters": list(s.parameters)} for s in simulations],
        "candidate_variables": variables,
        "assumptions": assumptions,
        "open_questions": questions,
        "next_step": "Supply missing variables, then execute the selected calculation or simulation and review its trace before using the result.",
    }


__all__ = ["build_model_plan"]

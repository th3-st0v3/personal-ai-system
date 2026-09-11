"""Generate richer UI-ready calculation working without duplicating formulas."""
from __future__ import annotations

import math
from dataclasses import replace

from calculation_library import CalculationTrace


def _input_step(trace: CalculationTrace) -> str:
    return "Inputs: " + "; ".join(f"{name} = {value:g}" for name, value in trace.inputs.items())


def expand_trace(trace: CalculationTrace) -> CalculationTrace:
    v = trace.inputs
    details: tuple[str, ...] = ()
    if trace.key == "hydrostatic_pressure":
        gradient = v["density"] * v["gravity"]
        details = (f"Pressure-gradient term: rho*g = {gradient:g}", f"Column pressure: P = ({gradient:g})({v['depth']:g})")
    elif trace.key == "darcy_weisbach_pressure_loss":
        ratio = v["pipe_length"] / v["pipe_diameter"]
        dynamic = v["density"] * v["velocity"] ** 2 / 2
        details = (f"Geometry ratio: L/D = {ratio:g}", f"Dynamic-pressure term: rho*v^2/2 = {dynamic:g}", f"Pressure loss: f*(L/D)*q = ({v['friction_factor']:g})({ratio:g})({dynamic:g})")
    elif trace.key == "reynolds_number":
        numerator = v["density"] * v["velocity"] * v["diameter"]
        details = (f"Numerator: rho*v*D = {numerator:g}", f"Viscous denominator: mu = {v['dynamic_viscosity']:g}", f"Reynolds ratio = {numerator:g}/{v['dynamic_viscosity']:g}")
    elif trace.key == "annular_area":
        outer_sq, inner_sq = v["outer_diameter"] ** 2, v["inner_diameter"] ** 2
        details = (f"Outer diameter squared: Do^2 = {outer_sq:g}", f"Inner diameter squared: Di^2 = {inner_sq:g}", f"Area difference: Do^2-Di^2 = {outer_sq-inner_sq:g}")
    elif trace.key == "annular_velocity":
        area = math.pi * (v["outer_diameter"] ** 2 - v["inner_diameter"] ** 2) / 4
        details = (f"Annular area: A = {area:g}", f"Mean velocity: v = Q/A = {v['flow_rate']:g}/{area:g}")
    elif trace.key == "hydraulic_power":
        details = (f"Hydraulic power: Ph = DeltaP*Q = ({v['pressure_drop']:g})({v['volumetric_flow_rate']:g})",)
    elif trace.key == "equivalent_circulating_density":
        loss_density = v["annular_pressure_loss"] / (v.get("gravity", 9.80665) * v["true_vertical_depth"])
        details = (f"Circulating-density increment: Delta rho = {loss_density:g}", f"ECD = rho + Delta rho = {v['density']:g} + {loss_density:g}")
    elif trace.key == "porosity":
        details = (f"Pore-volume ratio: Vp/Vb = {v['pore_volume']:g}/{v['bulk_volume']:g}",)
    elif trace.key == "water_saturation":
        details = (f"Water-filled pore ratio: Vw/Vp = {v['water_volume']:g}/{v['pore_volume']:g}",)
    elif trace.key == "formation_volume_factor":
        details = (f"Reservoir/standard volume ratio: B = {v['reservoir_volume']:g}/{v['standard_volume']:g}",)
    elif trace.key == "productivity_index":
        drawdown = v["average_reservoir_pressure"] - v["flowing_bottomhole_pressure"]
        details = (f"Pressure drawdown: pr-pwf = {drawdown:g}", f"Productivity index: J = q/drawdown = {v['flow_rate']:g}/{drawdown:g}")
    elif trace.key == "radial_reservoir_flow_rate":
        drawdown = v["pressure_outer"] - v["pressure_well"]
        radial_term = math.log(v["outer_radius"] / v["wellbore_radius"]) + v["skin"]
        numerator = 2 * math.pi * v["permeability"] * v["thickness"] * drawdown
        denominator = v["viscosity"] * v["formation_volume_factor"] * radial_term
        details = (f"Pressure drawdown: pe-pw = {drawdown:g}", f"Radial resistance term: ln(re/rw)+s = {radial_term:g}", f"Flow numerator = {numerator:g}", f"Flow denominator = {denominator:g}")
    else:
        details = (_input_step(trace),)
    steps = (trace.steps[0], _input_step(trace), trace.steps[1], *details, trace.steps[2], f"Result: {trace.result:g} {trace.result_unit}", f"Assumptions reviewed: {len(trace.assumptions)}", f"Limitations reviewed: {len(trace.limitations)}")
    return replace(trace, steps=steps)


__all__ = ["expand_trace"]

"""Human-readable deterministic explanations for engineering calculations."""


def explain(model_key, inputs, result):
    def f(name):
        return inputs[name]

    explanations = {
        "hydrostatic_pressure": {
            "steps": [
                f"Compute the pressure gradient: {f('density')} kg/m^3 * {f('gravity')} m/s^2 = {f('density') * f('gravity')} Pa/m.",
                f"Multiply the gradient by depth: {f('density') * f('gravity')} Pa/m * {f('depth')} m = {result} Pa.",
            ],
            "interpretation": "The result is the pressure contribution from the specified fluid column at the specified depth.",
        },
        "darcy_weisbach_pressure_loss": {
            "steps": [
                f"Compute the dynamic-pressure term: {f('density')} kg/m^3 * ({f('velocity')} m/s)^2 / 2.",
                f"Apply the friction factor and length-to-diameter ratio: {f('friction_factor')} * ({f('pipe_length')} m / {f('pipe_diameter')} m).",
                f"The resulting frictional pressure loss is {result} Pa.",
            ],
            "interpretation": "The result represents frictional pressure loss for the supplied pipe-flow conditions.",
        },
        "pipe_cross_sectional_area": {
            "steps": [f"Square the diameter and apply A = pi * D^2 / 4 using D = {f('pipe_diameter')} m."],
            "interpretation": "The result is the internal circular flow area available to the fluid.",
        },
        "volumetric_flow_rate": {
            "steps": [f"Calculate pipe area from D = {f('pipe_diameter')} m.", f"Multiply area by mean velocity {f('velocity')} m/s to obtain Q = {result} m^3/s."],
            "interpretation": "The result is the volumetric flow passing the selected pipe cross-section per unit time.",
        },
        "fluid_velocity": {
            "steps": [f"Calculate pipe area from D = {f('pipe_diameter')} m.", f"Divide flow rate {f('flow_rate')} m^3/s by area to obtain v = {result} m/s."],
            "interpretation": "The result is the cross-sectional mean fluid velocity.",
        },
        "reynolds_number": {
            "steps": [f"Multiply density, mean velocity, and diameter: {f('density')} * {f('velocity')} * {f('pipe_diameter')}.", f"Divide by dynamic viscosity {f('dynamic_viscosity')} Pa*s to obtain Re = {result}."],
            "interpretation": "Reynolds number compares inertial and viscous effects and is commonly used when characterizing internal flow regime.",
        },
        "hydrostatic_pressure_gradient": {
            "steps": [f"Multiply density {f('density')} kg/m^3 by gravity {f('gravity')} m/s^2 to obtain dP/dh = {result} Pa/m."],
            "interpretation": "This is the pressure increase per unit vertical depth for the specified constant-density fluid.",
        },
        "hydraulic_power": {
            "steps": [f"Multiply pressure drop {f('pressure_drop')} Pa by flow rate {f('flow_rate')} m^3/s.", f"Hydraulic power = {result} W."],
            "interpretation": "This is ideal fluid hydraulic power across the specified pressure differential before pump or motor efficiency losses.",
        },
        "api_gravity_to_specific_gravity": {
            "steps": [f"Add 131.5 to API gravity: {f('api_gravity')} + 131.5.", "Divide 141.5 by that denominator using SG = 141.5 / (API + 131.5).", f"Specific gravity = {result}."],
            "interpretation": "Specific gravity is the petroleum-liquid density ratio implied by the supplied API gravity at the reference condition.",
        },
    }
    explanation = explanations.get(model_key)
    if explanation is None:
        raise ValueError(f"No explanation is registered for calculation model: {model_key}")
    return explanation

# Engineering AI OS Runtime

## Direction

The project is an Engineering AI OS/platform hosted on Linux rather than a replacement kernel. The systems layer coordinates trusted engineering backends while preserving stable application and data interfaces.

## Core layers

```text
Linux
  -> Engineering Systems Runtime
  -> Workload / resource / permission scheduler
  -> Engineering data plane
  -> Physics / CAD / simulation / numerical backends
  -> AI / agents / V&V
  -> Engineering workspace / canvas / XR
```

## Primary domains

Robotics, electronics/electrical engineering, computer engineering, and petroleum/subsurface engineering share common numerical, physical, geometric, data, and verification infrastructure.

## Backend strategy

Prefer mature engines where they provide validated capabilities. Integrate them behind `EngineeringBackend` rather than exposing solver-specific APIs throughout the application.

Potential integrations include MuJoCo/MJX, JAX, OpenFOAM, preCICE, FEniCSx, FiPy, OPM Flow, PETSc/SLEPc, Open CASCADE, OpenUSD, NeuralOperator, SPICE implementations, ROS 2/Fast DDS, Yosys/OpenROAD, and future HPC schedulers. Each candidate requires license, correctness, performance, portability, security, and maintenance evaluation before adoption.

## Workload model

Every expensive operation should become a `WorkloadSpec` containing:

- kind and inputs
- CPU/memory/accelerator requirements
- eligible execution tiers
- network and remote permissions
- deterministic/checkpoint requirements
- approval requirements
- software version and stable fingerprint

A `RunManifest` records backend, status, timestamps, and result identity so simulations can be reproduced and compared.

## Verification

Verification is independent from AI. Initial primitives cover scalar balance checks and three-level mesh-convergence screening. Domain-specific verification can be added without coupling it to a particular solver or model provider.

## Security boundary

AI and external project data are untrusted. Backends receive only explicitly authorized workloads. Remote/network access is denied unless the workload policy grants it. Future code-execution adapters must run inside a dedicated sandbox with filesystem, network, CPU, memory, and runtime limits.

## Development loop

```text
Discovery
  -> Feasibility Check
  -> Development
  -> Guardrail Testing
  -> Telemetry & Shadow Mode
  -> Optimization
  -> repeat
```

Shadow mode must compare new methods with an authoritative reference before automated promotion. Performance claims are benchmark results, not assumptions.

# Engineering AI OS Architecture

Status: architecture baseline for beta-to-research development
Branch: `beta-foundation`

## 1. Decision summary

The project should evolve into an **Engineering AI OS platform**, but it should not begin by replacing the Linux kernel or putting a physics engine inside privileged kernel space.

The first implementation target is a **Linux-native engineering runtime** with a small systems substrate and a strongly typed engineering data plane. Physics solvers, CAD geometry, meshing, AI models, agents, V&V, and visualization run as isolated user-space components that communicate through canonical in-memory/out-of-core representations and bounded service APIs.

This preserves the core idea of an engineering OS—engineering workloads become first-class schedulable resources—without taking on kernel maintenance, driver development, memory-safety, and hardware-support costs before they create product value.

### Primary engineering domains

1. Robotics
2. Electronics / electrical engineering
3. Computer engineering / computer architecture
4. Petroleum / subsurface engineering

Scientific computing, mathematics, physics, chemistry, CAD, embedded systems, and general software engineering are cross-cutting foundations rather than separate silos.

### Primary workflow model

Cross-domain workflows are first-class. Each domain also has its own workspace and tool catalog.

Example:

```text
Petroleum reservoir model
        ↓
downhole sensor requirements
        ↓
electronics + thermal model
        ↓
computer-engineered edge processor
        ↓
robotic inspection / intervention system
        ↓
combined digital twin + verification evidence
```

The architecture therefore supports both independent domain workspaces and a shared system graph.

## 2. The six-stage development loop

Every major capability follows the same loop:

```text
[1 Discovery]
      ↓
[2 Feasibility Check]
      ↓
[3 Development]
      ↓
[4 Guardrail Testing]
      ↓
[5 Telemetry & Shadow]
      ↓
[6 Optimization]
      └──────────────→ Discovery
```

### 1. Discovery

Identify the engineering problem, required data, candidate libraries, algorithms, standards, hardware targets, and existing open-source solutions.

The project should prefer mature components when integration provides better reliability. Reinvention is justified when an internal abstraction provides a meaningful capability, performance, interoperability, security, or learning advantage.

### 2. Feasibility Check

Classify each proposal as:

- ship now
- prototype behind an interface
- research track
- future hardware track
- reject / defer

Measure CPU/GPU requirements, numerical stability, licensing, portability, determinism, security, data formats, and maintenance cost before adopting a dependency.

### 3. Development

Implement the smallest canonical abstraction that can support the intended future path. Avoid fake APIs that merely rename external tools.

New functionality must have tests and an explicit ownership boundary.

### 4. Guardrail Testing

Test numerical correctness, security, access control, malformed inputs, resource exhaustion, nondeterminism, simulation convergence, AI tool permissions, data provenance, and cross-project isolation.

For safety-relevant engineering results, distinguish numerical validity from engineering certification. The system must never claim that a model is certified merely because automated checks passed.

### 5. Telemetry & Shadow

Before an automated optimizer or agent is allowed to influence important workflows, run it in shadow mode where it proposes actions and records predicted outcomes without mutating authoritative state.

Collect:

- runtime
- memory usage
- accelerator utilization
- solver iterations
- convergence failures
- numerical residuals
- V&V results
- model confidence / uncertainty where available
- agent tool calls
- rejected actions
- user approvals / overrides
- provenance

### 6. Optimization

Optimize only after correctness is established. Optimize data movement before micro-optimizing Python. Use profiling and measured workload traces to decide whether computation belongs on CPU, GPU, local accelerator, or remote HPC.

## 3. Platform layers

```text
┌──────────────────────────────────────────────────────────────┐
│ Engineering Desktop / Canvas / Chat / Code / 3D / XR       │
├──────────────────────────────────────────────────────────────┤
│ Engineering AI Layer                                        │
│ model router · context graph · agents · V&V · explainability│
├──────────────────────────────────────────────────────────────┤
│ Workflow / Simulation Orchestration                          │
│ DAGs · parameter sweeps · optimization · UQ · AMR · HIL     │
├──────────────────────────────────────────────────────────────┤
│ Canonical Engineering Data Plane                             │
│ geometry · mesh · fields · circuits · states · materials    │
│ units · provenance · versions · results · evidence           │
├──────────────────────────────────────────────────────────────┤
│ Domain Engines                                              │
│ robotics · EEE · computer engineering · petroleum           │
├──────────────────────────────────────────────────────────────┤
│ Numerical / Physics Runtime                                 │
│ ODE/DAE · FEM · FVM · FDTD · rigid body · EM · CFD · porous │
│ media · optimization · autodiff · neural operators          │
├──────────────────────────────────────────────────────────────┤
│ Compute Runtime                                             │
│ CPU · CUDA · HIP/ROCm · distributed execution · HPC         │
├──────────────────────────────────────────────────────────────┤
│ Systems Substrate                                           │
│ Linux · process isolation · storage · scheduling · drivers  │
└──────────────────────────────────────────────────────────────┘
```

The **systems substrate** is intentionally small. The phrase "engineering kernel" describes the platform behavior and resource model, not a requirement to fork Linux immediately.

## 4. Engineering resource model

The core scheduler should eventually treat these as first-class resources:

- CPU compute
- GPU / accelerator compute
- memory
- persistent storage bandwidth
- simulation state
- geometry
- mesh partitions
- solver licenses or external providers
- model inference capacity
- remote HPC allocations
- agent permissions
- data access scopes

A workload should declare a resource profile and constraints instead of directly choosing a device whenever possible.

Example conceptual request:

```text
workload = CFD transient solve
priority = interactive
accuracy = engineering-grade
memory = large
accelerator = preferred
remote_execution = allowed
checkpoint = required
network = restricted
```

The runtime then selects a legal execution target based on policy, available resources, and measured performance.

## 5. Canonical engineering data plane

Avoid moving giant pandas/dataframe objects between subsystems. The shared representation should be typed, chunkable, versionable, and capable of zero-copy or near-zero-copy exchange when the underlying runtime permits it.

Core object families:

```text
EngineeringProject
├── GeometryAsset
├── MaterialSet
├── CoordinateFrame
├── UnitSystem
├── Mesh
├── Field
├── BoundaryCondition
├── InitialCondition
├── SolverConfiguration
├── SimulationRun
├── ResultSet
├── ParameterStudy
├── OptimizationStudy
├── UncertaintyStudy
├── SurrogateModel
├── TestCase
├── VerificationRecord
├── ValidationRecord
└── EvidenceRecord
```

Every object should carry provenance and a stable content/version identifier.

A result must be traceable to:

```text
inputs → transforms → solver/version → hardware/runtime → output → checks
```

## 6. Unified physics runtime

### 6.1 Differentiable physics

Differentiability is a service capability, not a privileged-kernel requirement.

The runtime should expose an interface similar to:

```python
result = physics.solve(problem)
grad = physics.gradient(result, wrt=["material_density", "geometry"])
```

Backends can use analytical derivatives, automatic differentiation, adjoints, finite differences, or specialized differentiable solvers.

MuJoCo is a useful robotics reference because its computation stack includes analytical derivatives for portions of the dynamics and MJX provides accelerator-oriented implementations. The current documentation also shows that differentiability and maximum accelerator feature parity do not necessarily coincide, which is exactly why the OS should keep a backend-neutral interface. 

### 6.2 Multiphysics coupling

Use a coupling graph rather than forcing every solver into one monolithic implementation.

```text
[CFD field]
     │ pressure / heat flux
     ▼
[structure solver]
     │ displacement / stress
     ▼
[geometry update]
     │ updated domain
     └────────────→ [CFD remesh]
```

Coupling contracts must explicitly define:

- units
- coordinate frames
- time basis
- interpolation
- conservation requirements
- convergence criterion
- rollback/checkpoint behavior

The first implementation should support sequential coupling and shared field exchange; tightly coupled monolithic solvers can be added later where numerical performance justifies them.

### 6.3 Geometry engine

Do not make OpenUSD the geometric kernel. Use a proper B-Rep/CAD kernel and expose OpenUSD as a scene and interchange layer.

The geometry abstraction should support:

- solids
- surfaces
- curves
- topology
- boolean operations
- constraints
- transforms
- tessellation
- healing
- mass properties
- feature history where available
- mesh generation hooks

STEP/AP242 remains an interoperability path rather than the internal memory representation.

## 7. Robotics subsystem

First-class libraries and services:

- rigid-body kinematics
- forward/inverse dynamics
- Jacobians
- trajectory generation
- motion planning
- collision detection
- contact/friction models
- state estimation
- sensor fusion
- LiDAR/radar/camera/IMU simulation
- SLAM
- manipulation
- legged locomotion
- reinforcement learning environments
- sim-to-real domain randomization
- hardware-in-the-loop
- embedded-controller testing
- safety envelopes

Robot models must share geometry, transforms, materials, sensors, controllers, and simulation state instead of maintaining independent copies in each application.

## 8. Electronics / electrical subsystem

Core capabilities:

- DC and AC circuit solving
- SPICE-compatible nonlinear devices
- transient / AC / DC operating points
- power electronics
- electromagnetic field solving
- PCB geometry and parasitics
- signal integrity / power integrity
- thermal-electrical coupling
- EMI/EMC analysis
- component tolerance / yield analysis
- Monte Carlo and sensitivity analysis
- battery / power system models
- controls and embedded interfaces

AI surrogate models should never silently replace the authoritative numerical solver. A surrogate result must identify itself as surrogate-derived and expose training/domain-of-validity metadata.

## 9. Computer engineering subsystem

Capabilities:

- RTL generation assistance
- Verilog/SystemVerilog/VHDL analysis
- synthesis workflow integration
- timing / power / area analysis
- FPGA workflows
- CPU/GPU/accelerator architecture modeling
- cache and memory hierarchy simulation
- ISA emulation
- instruction tracing
- digital logic simulation
- hardware/software co-design
- HIL firmware validation
- automated test generation

The AI layer can generate and modify RTL, but compile/simulation/formal verification remain authoritative gates.

## 10. Petroleum / subsurface subsystem

Core capabilities:

- Darcy flow
- black-oil models
- compositional simulation
- thermal reservoir models
- PVT handling
- relative permeability
- capillary pressure
- well models
- nodal analysis
- pressure-transient analysis
- material balance
- history matching
- uncertainty quantification
- geomechanics
- hydraulic fracturing models
- seismic processing
- inversion workflows
- CO2 storage
- hydrogen storage
- geothermal workflows
- production optimization
- surface network coupling

Reservoir workflows should support multiple fidelities: fast analytical estimates, reduced-order models, classical numerical simulation, and HPC-scale simulation.

## 11. Neural operators, PINNs, and surrogates

Surrogate models are a separate execution class.

```text
Authoritative solver
      ↓
training dataset
      ↓
validation / domain coverage
      ↓
surrogate candidate
      ↓
shadow comparison
      ↓
approved surrogate
      ↓
fast inference path
```

Never encode a universal speedup such as "10,000x" as a product guarantee. Measure speedup per problem class, hardware, fidelity, and error tolerance.

JAX is a viable experimental backend for array programs, automatic differentiation, compilation, and accelerator execution; it provides both forward- and reverse-mode differentiation and supports CPU/GPU/TPU execution. The runtime should nevertheless hide the framework choice behind a backend interface so JAX is replaceable. 

## 12. Adaptive mesh refinement

AMR is a solver service with explicit error indicators.

The first implementation should support deterministic indicators such as:

- residual/error estimates
- gradient magnitude
- curvature
- shock indicators
- stress concentration indicators
- solution interpolation error

AI-based refinement policies can be added as a proposal layer, but the solver retains a deterministic safety bound and can reject invalid mesh changes.

## 13. Uncertainty and optimization

Native study types:

- Monte Carlo
- Latin Hypercube
- Sobol / sensitivity analysis
- parameter sweeps
- Bayesian optimization
- design of experiments
- reliability analysis
- robust optimization
- multi-objective optimization

Each study produces a reproducible manifest containing seed, parameter distributions, software versions, solver settings, and hardware/runtime information.

## 14. Compute and memory management

The desired behavior is a **logical unified data plane**, not a fictional physically unified memory pool.

CPU/GPU/accelerator memory has different performance and access properties. The scheduler should make placement and transfer explicit while allowing backends to optimize it.

NVIDIA CUDA Unified Memory and AMD ROCm/HIP provide useful hardware-specific primitives, but their semantics and performance characteristics differ. The platform should therefore expose portable allocation and placement concepts and let backend adapters exploit native features.

Initial tiers:

```text
Tier 0  local CPU
Tier 1  local accelerator
Tier 2  local multi-device
Tier 3  workstation / lab cluster
Tier 4  remote HPC
Tier 5  cloud accelerator
```

The scheduler selects a tier based on constraints and policy.

Neuromorphic and quantum execution should be modeled as future backend contracts, not implemented as fake schedulers before hardware-specific workloads justify them.

## 15. Simulation Data Management

Simulation versioning should extend the existing workspace/versioning foundation rather than replace Git.

A simulation branch should be able to reference immutable objects:

```text
branch/design-a
  ├── geometry@hash
  ├── mesh@hash
  ├── materials@hash
  ├── boundary-conditions@hash
  ├── solver-config@hash
  └── results@hash
```

Changing one input should create a new immutable version and a new lineage edge rather than mutating historical evidence.

## 16. OpenUSD and CAD interoperability

OpenUSD should be the scene-graph/interchange foundation where appropriate. It is not a replacement for a CAD B-Rep kernel.

The internal representation should preserve engineering semantics and expose adapters to:

- OpenUSD
- STEP/AP242
- common mesh formats
- image/texture formats
- point clouds
- simulation-specific field formats

The current OpenUSD documentation describes it as a system for composing and reading hierarchical scene descriptions with extensible schemas. That makes it a strong candidate for the visualization/scene layer, while engineering topology remains owned by the CAD subsystem.

## 17. Cognitive / agentic layer

Agents should operate against typed engineering tools instead of raw shell access.

Recommended hierarchy:

```text
User
 ↓
Engineering LMM router
 ↓
Planner
 ↓
Typed tool policy
 ↓
Specialist agents
 ├── CAD
 ├── simulation
 ├── controls
 ├── electronics
 ├── reservoir
 ├── verification
 ├── security
 └── research
 ↓
Execution sandbox
 ↓
Results + evidence
 ↓
V&V gate
 ↓
Human decision
```

Agent capabilities should be represented as explicit scopes:

```text
read_project
write_draft
run_simulation
modify_geometry_draft
run_tests
request_hpc
publish_result
external_action
```

The current architecture's allowlisted AI tools and bounded context are the correct foundation. Higher autonomy should be added only through additional policy layers, not by giving an LMM arbitrary shell access.

## 18. Verification and validation

V&V becomes a first-class subsystem.

Verification asks: **did we solve the stated mathematical/computational problem correctly?**

Examples:

- unit consistency
- conservation checks
- residual thresholds
- solver convergence
- mesh convergence
- time-step convergence
- manufactured solutions
- analytical benchmark comparison
- regression tests
- dimensional analysis

Validation asks: **does the model adequately represent the real system for the intended use?**

Validation requires experimental or trusted reference evidence and must remain distinguishable from verification.

AI-generated designs and simulation plans inherit the same V&V gates as human-authored work.

## 19. Multimodal engineering canvas

The canonical UI should eventually support:

- natural-language chat
- code blocks
- parameter panels
- plots
- tables
- 2D/3D geometry
- circuit schematics
- system block diagrams
- simulation timelines
- result overlays
- evidence/lineage
- diff views
- notifications
- command palette

The current web workspace remains the shell foundation. The 3D/CAD canvas should be added as a separate client subsystem rather than forcing the existing file browser to become a 3D application.

## 20. Development roadmap

### Phase A — Beta foundation

Already present or substantially present:

- workspace hierarchy
- file/note storage
- project scoping
- deterministic calculation registry
- engineering evidence
- simulation API foundation
- auth
- bounded AI tool access
- bounded error surface
- basic web workspace

### Phase B — Engineering runtime foundation

Next:

1. typed units and quantities
2. engineering data model
3. simulation run manifests
4. reproducible execution records
5. workload/job abstraction
6. resource profiles
7. backend adapter interface
8. richer simulation catalog
9. result storage/lineage
10. V&V record model

### Phase C — Numerical backends

Add backend adapters and reference implementations for:

- ODE/DAE
- rigid-body robotics
- circuit simulation
- FEM
- FVM / CFD
- porous-media flow
- optimization/UQ

External mature solvers should be integrated before custom replacements are attempted.

### Phase D — Geometry + mesh

Add:

- B-Rep adapter
- parametric geometry model
- topology-aware operations
- meshing abstraction
- field-to-geometry visualization
- OpenUSD bridge
- STEP/AP242 bridge

### Phase E — AI engineering layer

Add:

- engineering context graph
- source/provenance retrieval
- model routing
- typed tool schemas
- specialist agents
- design optimization planner
- surrogate-model registry
- shadow mode
- V&V agent

### Phase F — HPC and heterogeneous execution

Add:

- device discovery
- local CPU/GPU scheduling
- zero-copy opportunities
- distributed jobs
- checkpoint/restart
- remote HPC adapters
- cloud adapters
- cost-aware scheduling

### Phase G — advanced research

Research tracks:

- differentiable multiphysics
- learned AMR
- neural operators
- digital twins
- HIL robotics
- XR
- neuromorphic backends
- quantum workflows

## 21. What we should not build yet

The following ideas are valid long-term goals but are poor first implementation targets:

- a new general-purpose operating-system kernel
- custom GPU drivers
- pretending cluster RAM and VRAM are one physically coherent memory pool
- a universal monolithic physics solver
- an in-kernel CAD engine
- autonomous real-world control without approval gates
- automatic certification claims
- opaque AI replacement of authoritative numerical solvers
- quantum/neuromorphic scheduling without real target hardware/workloads

These stay on the architecture map while interfaces are designed so they can be added later.

## 22. Direct answers to the earlier architecture questions

### What engineering domain comes first?

Robotics, electronics, computer engineering, and petroleum engineering are co-primary. The implementation should start with shared foundations that immediately serve all four, then add domain-specific solver depth. Cross-domain workflows are a core differentiator, not an afterthought.

### What hardware comes first?

Linux workstations are the first-class target: CPU-only must work, discrete GPU acceleration is preferred when available, and multi-device/HPC execution is additive. Edge robotics and remote HPC are later tiers.

### Distro/software layer or scratch-built kernel?

Software-layer first. Keep Linux underneath. Build a reusable engineering runtime, scheduler, data plane, and UI. Only consider deeper OS/kernel work after workload measurements show a concrete bottleneck that cannot be solved at user level.

### Independent workspaces or cross-domain workflows?

Both, with cross-domain workflows as the system-level architecture. A project can be domain-specific while its engineering objects remain composable with other domains.

### Kernel API or AI workflow first?

Build both, but the **typed execution API comes first**. The AI workflow layer must call deterministic capabilities through that API. This makes the AI replaceable and keeps physical computation authoritative.

## 23. Initial API direction

A language-neutral model should resemble:

```text
engineering.create_project()
engineering.geometry.create()
engineering.mesh.generate()
engineering.problem.define()
engineering.run.submit()
engineering.run.status()
engineering.result.open()
engineering.vv.verify()
engineering.optimization.study()
engineering.surrogate.train()
engineering.agent.plan()
engineering.lineage.explain()
```

Rust is the preferred systems/runtime language for new performance-sensitive core services. Python remains the primary research/orchestration language. C/C++ bindings are acceptable where required by mature numerical/CAD/HPC libraries.

Every backend must be replaceable behind the same contract.

## 24. Engineering truth model

The platform should explicitly separate:

```text
Measured data
Trusted reference
Deterministic calculation
Numerical simulation
Surrogate prediction
AI inference
Engineering judgment
Hypothesis
Unverified claim
```

These should remain visible in results, reports, and agent explanations.

## 25. Definition of done for an Engineering AI OS capability

A capability is not considered complete merely because its UI exists.

It must have:

- explicit interface
- deterministic or documented nondeterministic behavior
- provenance
- unit semantics
- validation tests
- resource limits
- security policy
- failure handling
- observability
- reproducibility where practical
- replaceable implementation boundary
- user-visible explanation of assumptions and limitations

This is the standard for the next development sweeps.

# Personal AI System

A modular, security-conscious personal AI and technical intelligence system designed to continuously improve learning, research, engineering capability, career opportunities, software development, and legitimate income generation.

The system is designed to start as a free-first foundation and progressively become more sophisticated without becoming unnecessarily complex, fragile, or dependent on any single model, vendor, framework, or platform.

## Mission

Build a system that helps me:

- Learn difficult technical subjects
- Develop real engineering and software skills
- Conduct high-quality research
- Build technical projects
- Discover useful software and open-source tools
- Discover jobs, internships, research opportunities, and legitimate income opportunities
- Monitor important developments in science, technology, energy, and finance
- Build a strong technical portfolio
- Eventually design and build my own software, tools, and systems
- Continuously improve the system itself

The system should increase my independent capability rather than simply automate everything for me.

## Long-Term Goals

### Engineering

- Petroleum Engineering
- Computer Engineering
- Computer Science / Software Engineering
- Scientific Computing
- Robotics
- CAD
- Engineering Simulation
- Numerical Methods

### Science and Mathematics

- Mathematics
- Physics
- Chemistry
- Statistics
- Quantum Mechanics
- Applied Mathematics

### Computing and AI

- Python
- Software Engineering
- Algorithms and Data Structures
- Artificial Intelligence
- Machine Learning
- Deep Learning
- Data Engineering
- Systems Programming
- Computer Architecture
- Embedded Systems
- Hardware / Software Integration

### Research

- Scientific research
- Technical literature review
- Research discovery
- Research project development
- Experimentation and simulation
- Reproducible technical work

### Business and Finance

- Entrepreneurship
- Business
- Economics
- Finance
- Investing education
- Energy and commodity intelligence
- Market research

### Career and Income

- Jobs
- Internships
- Research positions
- Freelance opportunities
- Technical projects
- Portfolio development
- Legitimate business opportunities
- Income-generating technical work

## Core Principles

### Evidence Over Hype

GitHub projects, social-media recommendations, videos, AI outputs, external agents, and online communities are discovery sources rather than automatically trusted authorities.

Important claims should be independently verified when practical.

### Modular Architecture

Major components should have clear responsibilities and interfaces.

Components should be replaceable without requiring unrelated parts of the system to be rewritten.

### Free-First, Value-Driven Spending

Use free and open-source solutions when they provide sufficient capability.

Paid tools should be introduced when their measurable value justifies their cost.

### Security by Default

Unknown software, repositories, agents, plugins, MCP servers, packages, scripts, and external inputs must be treated as untrusted until evaluated.

Never unnecessarily expose:

- API keys
- passwords
- SSH keys
- browser sessions
- private documents
- financial credentials
- unrelated filesystem data

### Human Control

Humans remain the final authority over consequential actions.

AI may recommend, analyze, research, simulate, and prepare actions.

Important real-world actions should use appropriate permission boundaries and human approval.

### Financial Safety

Financial functionality is currently information-only.

Allowed:

- Market monitoring
- Economic information
- Energy-market information
- Company research
- Derivatives education
- Historical analysis
- Simulations
- Backtesting
- Alerts
- Research

Not allowed by the current architecture:

- Autonomous trading
- Brokerage access
- Order execution
- Order modification
- Margin control
- Options execution
- Money transfers

### Learn, Don't Only Automate

Automation should improve understanding and capability rather than create dependence on AI.

Whenever appropriate, the system should encourage:

- Active problem solving
- Testing
- Explanation
- Practice
- Independent implementation
- Verification

### Existing Tools vs. Building Our Own

Before building a major capability from scratch:

1. Search for mature existing solutions.
2. Evaluate them.
3. Compare them against our requirements.
4. Determine whether integration is better than reinvention.

However, the system should also help me understand, reproduce, improve, and eventually build my own versions of important tools when that provides meaningful value.

### No Permanent Sacred Components

Technologies such as:

- OmniRoute
- TheAgency
- OpenClaw
- Hermes
- Claude Code
- Moltbook
- MCP servers
- Model providers
- Databases
- Knowledge systems

are candidates rather than permanent commitments.

If a better solution appears, the system should be able to evaluate and replace the existing component.

## Core Capabilities

### Learning Intelligence

Tracks:

- Subjects
- Concepts
- Prerequisites
- Mastery
- Weaknesses
- Assessments
- Projects
- Review schedules
- Learning progress

The system should identify high-value next skills rather than maximize content consumption.

### Research Intelligence

Discovers and analyzes:

- Papers
- Technical developments
- Researchers
- Technologies
- Companies
- Research opportunities
- Open questions

Important research should preserve source provenance.

The system should distinguish:

- Fact
- Source
- Inference
- Hypothesis
- Opinion
- Unverified Claim

### Tool Discovery Intelligence

Continuously discovers potentially useful:

- GitHub repositories
- AI tools
- Agent frameworks
- MCP servers
- Coding tools
- Automation tools
- Research tools
- Engineering tools
- Data tools
- Model infrastructure
- Open-source projects

Workflow:

```text
DISCOVER
   ↓
FILTER
   ↓
EVALUATE
   ↓
SECURITY REVIEW
   ↓
SANDBOX
   ↓
TEST
   ↓
BENCHMARK
   ↓
ADOPT / REJECT
   ↓
MONITOR
   ↓
RE-EVALUATE
```

## Current Draft Beta Web Shell

The current draft beta is a real, browser-accessible technical workspace rather than a static mockup. It uses a replaceable WSGI web boundary over the application services and keeps deterministic engineering calculations separate from UI logic.

### Local startup

The supported local server defaults to:

```text
http://127.0.0.1:8000
```

Start it directly from the repository with:

```bash
python3 scripts/serve_web.py
```

`scripts/serve_web.py` adds `src` to the module path itself, so an externally configured `PYTHONPATH` is no longer required. The older form remains valid:

```bash
PYTHONPATH=src python3 scripts/serve_web.py
```

The port is intentionally still `8000`; pass `--port <number>` only when a different local port is actually needed.

### Python environment

The repository requires the dependencies declared in `requirements.txt`, including `pypdf` for PDF ingestion. Install them in the active environment before running the complete test suite:

```bash
python3 -m pip install -r requirements.txt
```

A project-local virtual environment is recommended:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Ubuntu/WSL, `python3` is the distribution-provided command. To make the `python` command consistently resolve to the same interpreter across new terminals, install the standard compatibility package once:

```bash
sudo apt update
sudo apt install -y python-is-python3
```

Then verify both entry points:

```bash
python --version
python3 --version
```

They should report the same Python installation family.

### Workspace capabilities

The browser workspace supports:

- Project creation and selection
- Arbitrarily nested folders
- Notes and note editing
- File upload, download, replacement, and deletion
- Rename, copy/paste, duplicate, move, and drag/drop-style movement
- Multi-selection and contextual actions
- Breadcrumbs and recursive search
- Sorting
- Archive/invalidate/delete lifecycle controls
- Properties and export-oriented actions
- Project-scoped clipboard validation

### Engineering capabilities

Engineering projects expose requirements, sources, evidence, design cases, and decisions through a project-scoped API. The beta supports:

- Source search
- Public GitHub file import
- PDF import and text extraction
- Source/chunk search and retrieval
- Add-evidence and evidence invalidation workflows
- Requirement-to-evidence test plans and reports
- Calculation-linked evidence
- Project isolation checks at the API boundary

### Calculations and simulations

Deterministic calculations are registered by stable keys and expose parameter metadata, equations, assumptions, limitations, units, and auditable solution traces. Saved calculation records preserve model/method identity for reproducibility.

The beta also exposes a deterministic simulation catalog and controlled simulation-run boundary with traceable steps, assumptions, limitations, and policy checks.

### Experiment Lab

The browser workspace now has an **Experiment Lab** for live engineering experimentation. It can observe host utilization and unrelated processes, build deterministic model plans, run bounded seeded fuzz campaigns, show hardware-aware Easy/Standard/Performance/Max workload profiles, and expose provider/model setup in one place.

Host observation is separate from host mutation. RAM/swap profiles require an explicit host-control permission and currently use delegated Linux cgroup v2 where the operating system permits it. PASI does not fall back to arbitrary shell commands when the host cannot safely provide that capability. The selected process does not need to belong to a PASI project.

Local and hosted model routes remain provider-neutral. Ollama/local execution can be used through the existing provider router, while hosted APIs can be registered without putting credentials in browser localStorage. A registered provider is not treated as executable until its execution adapter is actually available.


### Chat and integrations

Persisted project chat supports rename, pin/unpin, move, share-oriented UI actions, delete, retry, branching, and feedback. The integration bridge provides controlled connections/plugins and source retrieval without turning external content into trusted instructions.

### Testing

Run the complete Python suite:

```bash
python3 -m unittest discover -s src -p 'test_*.py' -v
```

Run the type checker used by CI:

```bash
npx --yes pyright@latest src scripts
```

Run the frontend/backend contract check:

```bash
python3 scripts/frontend_contract_test.py
```

Run the deterministic beta smoke test:

```bash
python3 scripts/smoke_test_beta.py
```

Validate browser JavaScript syntax:

```bash
for file in web/*.js; do node --check "$file"; done
```

CI also starts the local server on port 8000 and performs Browser/API smoke checks, so the documented runtime boundary and the browser contract are continuously exercised.

The shell is still intentionally a foundation rather than a final visual product. Its storage, application, engineering, calculation, simulation, and policy boundaries are designed to support richer editors, command palettes, tabs, panes, previews, plots, simulation views, AI assistance, and future engineering canvas features without forcing core rewrites.

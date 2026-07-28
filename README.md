# Spatial Query Rig

**Author:** Craig C. Cline
**Location:** Clyde, North Carolina
**Site:** seeitwith.org

---

# Research Question

Does accumulated spatial and relational observation of a persistent physical environment improve an AI model's performance on spatial reasoning and context-dependent language tasks compared with a stateless baseline?

---

# Abstract

Most AI language models answer queries using information available within the current interaction, with limited or no persistent knowledge of the user's physical environment. The Spatial Query Rig investigates whether repeated stereo observations of a fixed environment provide measurable advantages during inference.

The experiment compares two conditions:

**Condition A:** A stateless model receiving a text-only query.

**Condition B:** A model receiving the same query while also having access to accumulated stereo observations, structured scene representations, and synchronized dialogue from the same physical environment acquired over multiple sessions.

Performance is evaluated using objective criteria including spatial reference accuracy, contextual relevance, ambiguity resolution, temporal consistency, and relational understanding.

---

# Hypothesis

An AI model provided with accumulated spatial observations and a persistent relational model of a physical environment will outperform a stateless baseline on tasks requiring spatial reference, contextual disambiguation, temporal continuity, and interpretation of context-dependent language.

The purpose of this project is to test this hypothesis under controlled experimental conditions rather than assume its validity.

---

# Operational Definition of Grounding

Within this project, **grounding** refers to repeated stereo observations of the same physical environment acquired over time and made available during inference.

Grounding consists of two complementary components:

### Spatial Grounding

Persistent knowledge of the physical geometry of the observed environment.

### Relational Grounding

Persistent knowledge of the relationships among people, objects, and locations as those relationships evolve through time.

This definition is specific to environmental grounding and does not imply robotic embodiment, reinforcement learning, or physical agency.

---

# Scene Representation

The physical environment is represented as an evolving structured scene model derived from stereo observations.

Each observation contributes to a persistent representation containing identifiable entities and their relationships.

Objects are classified according to their functional role within the environment:

* **Active Objects** — entities capable of initiating actions or changing environmental state (for example, the human participant).

* **Movable Objects** — objects whose position or orientation may change between observations.

* **Fixed Objects** — architectural features and stable environmental landmarks that establish a consistent spatial reference frame.

These entities are represented within a structured scene graph (implemented as JSON) that is continuously updated as new observations are acquired.

The scene representation is an internal computational model derived from physical observations rather than the grounding itself.

---

# Temporal Context

The Spatial Query Rig treats each observation as part of a continuous sequence rather than as an independent image.

Each capture session extends the existing scene model by recording:

* newly observed objects
* changes in object position
* changes in object relationships
* human activity
* environmental continuity

This accumulated history allows queries to reference observations that occurred earlier within the session or across previous sessions.

---

# Dialogue Association

All spoken dialogue during a capture session is time-synchronized with the corresponding stereo observations.

Consequently, conversational references such as:

* "that chair"
* "the book beside me"
* "move it over there"

can be interpreted relative to the physical scene existing at the moment those statements were made.

Conversation therefore becomes an event embedded within a persistent physical environment rather than an isolated sequence of text.

The central hypothesis is that synchronized spatial observations and dialogue provide additional contextual information that reduces ambiguity during inference.

---

# Experimental Design

## Control Variables

* Same physical environment
* Same observer
* Same capture equipment
* Same query
* Same evaluation protocol

## Independent Variable

Availability of accumulated spatial observations and relational scene history during inference.

## Dependent Variables

Performance is evaluated using measurable criteria including:

* Accuracy of spatial reference
* Resolution of ambiguous language
* Contextual relevance
* Consistency across sequential interactions
* Recall of previously observed environmental features
* Interpretation of relational language
* Temporal continuity across observations

---

# Data Flow

The experimental pipeline is defined as:

Physical Environment

↓

Stereo Observations

↓

Object Detection and Tracking

↓

Structured Scene Graph (JSON)

↓

Temporal Synchronization

↓

Dialogue Association

↓

Inference

Each stage records information without altering the original observations, preserving a traceable relationship between measured data and generated responses.

---

# The Rig

The Sentinel consists of twin global-shutter stereo cameras mounted on a motorized pan/tilt platform with a 3-5/16" interocular baseline.

The system captures synchronized 1920 × 1080 stereo imagery from a fixed environment in Clyde, North Carolina.

Hardware specifications are documented in:

`rig/specifications.md`

---

# Repository Structure

```
rig/
    Hardware specifications
    Camera geometry
    Calibration

methodology/
    Experimental protocols
    Evaluation procedures
    Evaluation metrics

sessions/
    Sequential stereo capture sessions
    Time-synchronized dialogue
    Scene histories

scene_graph/
    Persistent JSON object models
    Relationship definitions
    Object classifications

results/
    Comparative analyses
    Condition A vs. Condition B

research/
    Literature review
    Experimental notes
    Future investigations
```

---

# Current Status

Early-stage research.

Current efforts focus on establishing a repeatable methodology, validating measurement procedures, and collecting baseline datasets for comparison between stateless and spatially grounded inference.

Future work will expand the corpus, refine scene representations, automate object tracking, and evaluate performance across increasingly complex spatial and conversational tasks.

---

# Research Principle

The Spatial Query Rig is an experimental instrument designed to investigate whether persistent spatial and relational context measurably improves AI reasoning.

Its purpose is not to demonstrate a predetermined conclusion but to collect reproducible evidence under controlled conditions.

Measurements are recorded independently of interpretation.

Interpretation follows from the accumulated evidence.

---

*"The instrument records observations.*

*The scene model preserves relationships.*

*The dialogue provides intent.*

*The analysis evaluates evidence.*

*Conclusions follow from the data."*

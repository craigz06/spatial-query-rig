# Spatial Query Rig

**Author:** Craig C. Cline  
**Location:** Clyde, North Carolina  
**Site:** seeitwith.org  

---

## The Question

Does a grounded AI see more clearly than a stateless one?

An AI with no body, no location, and no persistent memory 
answers every question from nowhere. This project tests a 
different condition: an AI that has repeatedly viewed a known 
physical environment in stereo sequential frames — same room, 
same geometry, same human — and receives new queries from 
inside that accumulated spatial context.

The hypothesis is simple. Grounded seeing produces richer 
understanding than stateless inference. The Rig exists to 
prove it.

---

## The Experiment

Same question. Same environment. Same moment.

**Condition A:** Text query to a stateless model.  
**Condition B:** Stereo sequential frame query with accumulated 
session history from the same physical environment.

Output is compared on specific criteria: accuracy of spatial 
reference, contextual relevance, resolution of ambiguity.

---

## The Rig

The Sentinel — a beam-splitter stereo camera at 152mm baseline 
mounted on a motorized pan/tilt, capturing 1920x1080 stereo 
frames from a fixed known environment in  Clyde, North Carolina.

See `rig/specifications.md` for full hardware details.

---

## Repository Structure

- `rig/` — hardware specifications and environment reference
- `methodology/` — query protocols and evaluation criteria  
- `sessions/` — accumulated capture sessions, growing corpus
- `results/` — comparative outputs, condition A vs condition B

---

## Status

Active. Early stage. Methodology being established.

*The instrument states what it sees.  
The analyst has the final word.*

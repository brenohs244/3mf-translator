# Codex Geometry AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional Codex analysis of safe settings, orientation and support evidence.

**Architecture:** A local evidence builder creates a text-only payload. A Codex CLI adapter returns schema-constrained JSON. Existing validators and slicer checks gate every applicable recommendation; Tkinter handles consent and review.

**Tech Stack:** Python, Tkinter, Codex CLI, unittest, ELEGOO Slicer CLI, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-11-11-codex-geometry-ai-design.md`

## Global Constraints

- Never pass 3MF, mesh, G-code, image, file path or credential to AI.
- Never apply AI output without user review and real slicer validation.
- Keep Gemini available.

## Task 1: Evidence and Codex adapter

- [ ] Test an allowlisted payload and rejection of identifiers and geometry.
- [ ] Implement evidence builder and subprocess adapter with ephemeral, read-only, isolated Codex execution and strict JSON parsing.
- [ ] Test missing CLI, timeout, cancellation and malformed output.

## Task 2: Recommendation gates

- [ ] Test that only known, sliced orientation IDs and safe support keys can be proposed.
- [ ] Implement local comparison and re-slice proposed support settings before marking verified.
- [ ] Keep unverified ideas descriptive and non-applicable.

## Task 3: UI and release

- [ ] Test consent denial causes no Codex invocation and front/profile changes invalidate prior analysis.
- [ ] Add provider selection, visible payload review, progress and approved-application flow.
- [ ] Run full suite, real ELEGOO Slicer validation, Graphify, Understand Anything, code review, Windows build, EXE smoke and ZIP integrity.

<div align="center">

# Carrot Seed Planting Validation System

Real-Time Seed Detection and Validation for Precision Agriculture

</div>


## Overview

The **Carrot Seed Planting Validation System** is a real-time computer vision and data analytics solution designed to detect, count, and validate carrot seeds as they travel through planter tubes during planting operations.

This project is sponsored by Bolthouse Fresh Foods. The current planting process lacks real-time validation of seed distribution, which can result in over-seeding, under-seeding, or clumping. These issues directly impact crop yield, spacing uniformity, and production efficiency.

Our system aims to provide real-time feedback to planting crews by detecting seed counts (0, 1, 2, >2) per drop event and visualizing distribution patterns through an interactive dashboard.

## Problem Statement & Motivation

Current carrot planting systems do not provide reliable real-time validation of seed distribution. As a result, over-seeding, under-seeding, and seed clumping may occur without immediate detection. These issues can reduce crop yield, waste product, and increase operational costs.

The motivation of this project is to create a real-time validation system that enables planting crews to monitor performance and make immediate adjustments to improve efficiency and yield.

### Goals

- Detect carrot seeds in-flight using computer vision.
- Classify seed drop events into 0, 1, 2, or >2 seeds.
- Achieve at least 97% detection accuracy.
- Provide real-time feedback to operators.
- Log structured data for analysis.
- Visualize seed distribution using dashboard analytics.

## Requirements

### Functional Requirements
- Capture video input from planter tubes.
- Detect and count seeds per drop event.
- Store detection data per tube and timestamp.
- Display seed distribution metrics and visualizations.

### Non-Functional Requirements
- Real-time processing capability.
- High accuracy (≥97%).
- Operate in field conditions with limited internet access.
- Compatible with field power supply (15–24V).
- Scalable across multiple planting tubes.

## Team Members and Roles

Team Number: CSE-326
Discussion Section: 03L

- **Nitya Narahari** – Team Lead, UI Designer, Front-End Developer, Full-Stack Developer
- **Anthony Gonzalez** – Team Moderator, Computer Vision Engineer, Data Engineer
- **Huy Hoang** – Notetaker, Computer Vision Engineer, Data Engineer, DevOps Engineer
- **Ryan Lee** – Notetaker, UI Designer, Front-End Developer

### Features

- [x] Synthetic seed simulation pipeline
- [x] Initial OpenCV detection prototype
- [ ] Real-time hardware deployment
- [ ] Interactive dashboard visualization
- [ ] Field validation testing

### Software Stack / Technologies Used

- Language: Python
- Computer Vision: OpenCV
- Machine Learning (optional): PyTorch / YOLO
- Backend Framework: FastAPI
- Frontend (planned): NiceGUI or React
- Data Processing: Pandas
- Version Control: Git & GitHub
- Hardware (planned): Raspberry Pi

## Quickstart

Summary for developers with links to setup, build, test instructions in wiki or docs.

### Instructions

1. Click "Use this template" on GitHub to create your private repository.
2. Clone your repo locally.
3. Fill in the metadata table above.
4. Create an initial branch (e.g., `setup`), never commit directly to `main` (unless instructed).
5. Open an Issue for each lab / feature before starting work.
6. Use Pull Requests to merge changes (each PR should reference at least one Issue).

## Structure

Include: what constitutes passing (e.g., all tests green, coverage threshold).

Passing criteria:
- All tests passing.
- CI pipeline green.
- Core detection prototype functional.
- Pull Requests reviewed and properly merged.

## Coding & Collaboration Conventions

- Use semantic commit messages (see `CONTRIBUTING.md` for full details).
- Open an Issue for every distinct unit of work (lab task, feature, bug, refactor, research).
- Create branches from `main` named after the Issue: `<type>/short-kebab` (e.g., `feat/scheduler-phase1`).
- Commit changes incrementally with semantic commit messages.
- Open a Pull Request early (draft) and link the Issue.
- Request peer review (if required) before merging.
- Squash merge or rebase to keep `main` linear (unless told otherwise).

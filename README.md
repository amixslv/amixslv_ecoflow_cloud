# EcoFlow Cloud for Home Assistant (WIP)

This is an unofficial EcoFlow Cloud integration for Home Assistant.  
The project is currently **under active development**, with the main focus on:

- Implementing the EcoFlow Cloud API protocol (`protocol/`)
- Building a stable communication layer (`api/`)
- Designing the entity architecture (`entities/`, `sensor.py`, `switch.py`, `number.py`, `select.py`)
- Mapping devices and parameters (`supported_devices.py`)

## ⚠️ Status: Work in Progress

The integration is **not ready for daily use**.

The following areas are still incomplete:
- **Correct and consistent entity generation**
- Automatic entity mapping based on the EcoFlow Cloud protocol
- Multi‑device support with dynamic configuration

The structure is already prepared to support:
- Protocol‑first architecture
- Automatic entity generation from protocol data models
- Minimal manual maintenance when adding new EcoFlow models

## 📁 Project Structure

The project is organized into several logical layers:

- `protocol/` — EcoFlow Cloud protocol definitions  
- `api/` — API client and authentication  
- `core/` — integration business logic  
- `entities/` — base entity classes  
- `sensor.py`, `switch.py`, `number.py`, `select.py` — Home Assistant platform entities  
- `supported_devices.py` — device and parameter mapping  

## 🧪 Testing

The integration is currently intended for development and testing only.  
Functionality may change at any time.

## 📌 Goal

The main goal is to build:
- a **protocol‑first** architecture  
- **automatic entity generation**  
- **minimal manual work** when adding new EcoFlow devices  

## 📬 Feedback

Pull requests and suggestions are welcome, especially regarding:
- improving entity generation  
- structuring protocol data models  

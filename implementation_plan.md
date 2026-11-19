# LuminaStay (formerly StayBD AI): AI-Powered Hotel Recommendation System

This document outlines the implementation plan for **LuminaStay**, an AI-powered hotel recommendation and booking system tailored for Bangladesh (BD) but with an international, premium standard. 

## Finalizing the Name
You mentioned wanting a proper, international-style name. While your mockups show **StayBD AI**, I suggest we go with **LuminaStay** or **NovaStay**. For this plan, we will proceed with **LuminaStay** as it feels premium, modern, and perfectly suited for an AI travel assistant that brings "light" to travel planning. 

## UI/UX & Dark Mode Strategy

> [!NOTE]
> **Design Reviewed:** I have reviewed the PNGs in the `ui ux design` folder (e.g., `Home 1440w light.png` and `AI Recommendations 1440w light.png`). The current light mode uses a beautiful deep green accent (`#112A26` approximately) with clean, rounded cards. 
> 
> **Making it "More Better" with Dark Mode:** To elevate this to a premium international standard, we will implement a robust Dark Mode toggle in the React frontend. In dark mode, the stark white backgrounds will transition to a sleek slate-gray or deep onyx (`#0F172A`), allowing the hotel images and AI recommendation badges (like the `96% Match` circle) to pop dynamically. We will also add smooth micro-animations on hover states for the hotel cards.

## Open Questions

> [!WARNING]
> 1. **Initial Data Source:** Since we are collecting from "many datasets", do you have access to any specific datasets right now (e.g., CSVs of BD hotels), or should I write web scrapers / API integration scripts for sources like Google Places, Agoda, and local tourism boards?
> 2. **LLM Provider:** The architecture mentions "Claude/LLM reasoning". We can use Gemini, OpenAI, or Claude. Which API key will you be providing for the backend LLM calls?

---

## 1. Architecture & Tech Stack

Based on your approved diagram, we will implement a decoupled, microservice-like architecture:

1. **React Frontend:** Handles browsing, searching, booking UI, and the AI chat interface. We will use a modern framework like **Vite + React** (or Next.js) styled with **Tailwind CSS** to achieve the premium dark mode UI.
2. **Django REST API (Backend):** Manages core business logic, user authentication (JWT), hotel CRUD operations, and booking state.
3. **PostgreSQL Database:** The central truth for Hotels, Rooms, Bookings, and Users. We will also enable the `pgvector` extension for semantic search capabilities.
4. **LangGraph AI Agent:** An autonomous AI agent service that processes natural language queries. It has access to "tool calls" that can query the PostgreSQL database to fetch live availability and hotel details.
5. **LLM Reasoning Engine:** The brain of the LangGraph agent (e.g., Gemini / Claude), which evaluates user preferences against database results to formulate personalized recommendations.

---

## 2. Multi-Dataset Collection Strategy

To build a rich recommendation engine for BD, we will ingest and normalize data from multiple sources:

### A. Core Hotel Datasets
- **Source 1: Global OTAs (Booking.com, Agoda):** Scrape or use APIs to get baseline data (Hotel Name, Location in BD, Star Rating, Base Amenities, Images).
- **Source 2: Google Maps API:** Gather geospatial data, proximity to BD landmarks (e.g., Inani Beach, Ratargul Swamp Forest), and aggregate rating scores.
- **Source 3: Local BD Datasets:** Ingest any available local tourism data for boutique or eco-resorts that aren't well-represented on global OTAs.

### B. Unstructured & Contextual Datasets
- **Reviews Dataset:** Collect user reviews from various platforms. We will generate vector embeddings of these reviews so the AI can answer queries like, "Which hotel has the best complimentary deshi breakfast?"
- **Contextual Data:** Incorporate seasonal data (e.g., monsoon vs. winter travel in BD) to feed into the LangGraph reasoning engine.

---

## 3. Step-by-Step Implementation Plan

### Phase 1: Project Setup & Database Foundation
- Initialize a Monorepo structure (`/frontend` and `/backend`).
- Set up **Django** with Django REST Framework (DRF).
- Configure **PostgreSQL** with `pgvector`.
- Create core Django models: `User`, `Hotel`, `Room`, `Booking`, and `Review`.

### Phase 2: Data Ingestion Pipeline
- Write Python scripts to ingest mock or scraped data from multiple datasets.
- Normalize the data into our PostgreSQL schema.
- Run an embedding script to convert hotel descriptions and top reviews into vector embeddings for semantic search.

### Phase 3: LangGraph AI Agent Service
- Set up a LangGraph state machine.
- Define tools for the agent (e.g., `search_hotels_by_location`, `check_room_availability`, `semantic_search_reviews`).
- Create the main Chat API endpoint in Django that interfaces with the LangGraph agent.

### Phase 4: React Frontend & UI/UX Development
- Initialize the React application.
- Implement a comprehensive design system using Tailwind CSS based on your PNGs, ensuring a premium **Dark Mode** toggle.
- Build the AI Chat Interface, Hotel Listing, and Booking Checkout flows.
- Integrate the frontend with the Django REST API.

### Phase 5: Integration & Polish
- Connect the booking flow so the React frontend creates a real booking in PostgreSQL via Django.
- Ensure the LangGraph agent can accurately reference real-time availability.
- Polish animations, responsiveness, and overall user experience.

## Verification Plan

### Automated Tests
- Unit tests for Django REST API endpoints (Auth, Booking, Hotel list).
- Integration tests for LangGraph tool calls to ensure the agent retrieves correct DB records.

### Manual Verification
- Test the chat interface: Ask the React frontend for a "family friendly hotel in Sylhet under 5000 BDT".
- Verify that the resulting recommendation exists in the PostgreSQL database and the booking flow works end-to-end.
- Validate Dark Mode persistence and styling aesthetics across the application.

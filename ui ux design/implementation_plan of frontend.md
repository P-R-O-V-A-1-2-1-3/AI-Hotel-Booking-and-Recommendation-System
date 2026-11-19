# LuminaStay: Frontend Implementation Plan

This document outlines the detailed technical plan for building the **LuminaStay** frontend based on your provided UX designs. Our goal is to create a stunning, premium, and highly responsive web application with a flawless Dark Mode experience.

## Open Questions

> [!WARNING]
> 1. **Framework Preference:** I plan to use **Vite + React (TypeScript)** as it is lightning fast for single-page applications and pairs perfectly with a Django REST API. Are you comfortable with this, or do you strictly prefer Next.js?
> 2. **Assets:** The designs include background images and icons. For now, I will use high-quality placeholder images (via Unsplash) and `lucide-react` icons until you can provide the specific exported assets. Is this acceptable?

---

## 1. Technology Stack

- **Core Framework:** React 18 initialized via Vite (using TypeScript for robust code quality).
- **Styling:** Tailwind CSS for rapid, utility-first styling and built-in dark mode support.
- **Routing:** `react-router-dom` for seamless navigation between pages.
- **Icons:** `lucide-react` (clean, modern, and highly customizable).
- **Animations:** `framer-motion` (optional, for smooth page transitions and micro-animations to achieve that "premium" feel).

## 2. Design System & Theming

Based on the `Home 1440w light.png` and `AI Recommendations 1440w light.png`, we will establish a robust design system in `tailwind.config.js` and `index.css`.

### Color Palette
- **Primary Accent (Brand):** Deep Forest Green (approx. `#112A26`). Used for buttons, headers, and active states.
- **AI Accent:** Gold/Yellow (approx. `#EAB308`). Used for the "AI Picks", "96% Match" badges, and star ratings.
- **Light Mode:** White (`#FFFFFF`) and off-white (`#F9FAFB`) backgrounds. Text will be dark slate (`#1E293B`).
- **Dark Mode:** Deep Onyx (`#0F172A`) or Charcoal (`#121212`) backgrounds. Cards will have subtle borders (`#334155`) with slight glassmorphism. Text will be soft white (`#F8FAFC`).

### Typography
- We will use **Inter** or **Outfit** (via Google Fonts) for a crisp, modern, and highly legible interface.

## 3. Component Architecture

To ensure code reusability and clean architecture, we will build the following core components first:

1. `Navbar`: Contains the LuminaStay logo, navigation links, Profile avatar, and the **Dark Mode Toggle**.
2. `HeroSearchForm`: The complex search bar seen on the Home page (Destination, Dates, Guests).
3. `HotelCard`: A versatile card component used in "Popular Destinations", "Featured Hotels", and "AI Recommendations". It will feature image carousels, pricing, and the AI match badge.
4. `AIReasoningBanner`: The expanded area on the AI Recommendation cards explaining *why* the hotel was chosen (e.g., "Oceanview room matches 3 of your past bookings").

## 4. Execution Steps

I will execute the frontend development in the following order:

### Step 1: Project Initialization
- Create the `/frontend` directory using `npx create-vite@latest`.
- Install Tailwind CSS, React Router, and Lucide Icons.
- Setup the global `index.css` with CSS variables for seamless light/dark mode switching.

### Step 2: Foundational Layout
- Build the persistent `Navbar` and `Footer`.
- Implement the Dark Mode toggle logic so we can test both themes simultaneously as we build.

### Step 3: The Home Page (Landing)
- Build the Hero section with the background image and the Search interface.
- Implement the "Popular Destinations" and "Featured Hotels" grid layouts.

### Step 4: AI Recommendations Page
- Build the "Your AI-picked hotels" header and preference filter tags (Oceanview, Spa & wellness, etc.).
- Construct the detailed `HotelCard` variant that includes the AI match circle and reasoning checklist.

## Verification Plan

### Manual Verification
- Ensure the UI matches the layout and vibe of the provided PNGs perfectly.
- Toggle between Light and Dark mode on every page to ensure no text or icons become invisible.
- Test responsiveness across mobile, tablet, and desktop viewports.

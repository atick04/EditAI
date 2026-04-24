#Edit AI – Real‑Time AI Video Editing Engine

#Project Overview
MontagEdit AI is a fully autonomous AI‑agent that can add graphics, subtitles, B‑Roll, and any visual effect to a video in real time without re‑encoding the whole clip.

Key features

✅	Feature
Incremental rendering	Each edit is rendered as a separate overlay; the original video is never fully rebuilt.
Hyperframes compositions	Graphics are generated as pure HTML + CSS + GSAP (no external <img> tags).
Precise timestamps	data‑start / data‑duration let you place animations down to the millisecond.
Live log streaming	The agent writes a step‑by‑step log to the chat while it works.
Remotion support	Ready‑to‑use React templates (TechBlueprint, CinematicDark).
Cross‑platform	Works on Windows, macOS, Linux (Docker‑compatible).

Prerequisites
Tool	Minimum version
Python	3.12+ (3.13 recommended)
Node.js	20.x
npm	10.x
FFmpeg	6.0+ (must be on PATH)
Git	any

# 1️⃣ Clone the repo
git clone https://github.com/your-org/montage-ai.git
cd montage-ai

# 2️⃣ Python dependencies (recommended inside a venv)
python -m venv .venv
.\.venv\Scripts\activate   # PowerShell / cmd
pip install -r backend/requirements.txt

# 3️⃣ Node dependencies for the frontend
cd frontend
npm ci                     # or npm install
cd ..

# 4️⃣ Install Remotion (for the React templates)
cd remotion
npm ci
cd ..

# 5️⃣ Initialise the Hyperframes studio (run once)
cd hyperframes_studio
npx --yes hyperframes init .
cd ..

# 6️⃣ Environment variables
# Copy the example and add your GROQ key
cp .env.example .env
# Edit .env → set GROQ_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx


# Backend
GROQ_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Optional: custom port
API_PORT=8000


# Backend
GROQ_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
# Optional: custom port
API_PORT=8000


Contributing
Fork the repository.
Create a branch feature/your‑feature.
Write tests (see backend/tests/).
Open a Pull Request with a clear description of the change.
When you modify LLM prompts in nodes.py, also update the corresponding unit test in tests/test_nodes.py.

MIT – feel free to use, modify, and distribute.  

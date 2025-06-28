"""Example: KiboStudio development server.

Launches the web UI on port 8000 for observability, prompt
management, evaluation, discovery and feature flags.

Run:
    uv run python examples/studio_example.py

Then open http://127.0.0.1:8000 in your browser.
"""

from kiboup.studio import KiboStudio

studio = KiboStudio(db_path="kibostudio.db", debug=True)

if __name__ == "__main__":
    studio.run(host="0.0.0.0", port=8000, reload=True)

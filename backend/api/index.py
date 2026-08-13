"""Vercel serverless entrypoint.

Vercel's Python runtime loads this module and looks for an ASGI callable named
`app`. The deployment root is not reliably on sys.path when the entrypoint sits
under api/, so add it explicitly before importing the FastAPI application.

This exists alongside the Dockerfile — the same backend can run either as a
long-lived container (Render, Fly, local) or as a Vercel function.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402

__all__ = ["app"]

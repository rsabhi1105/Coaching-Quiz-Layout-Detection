"""
Borrow CoachingQuiz's Django instead of modelling the books tables again.

Django owns the schema (see AGENTS.md). A second description of those tables in this
folder would be a second thing to keep in step, and the one that silently drifts is
always the copy. So this module puts the backend on `sys.path`, starts Django with the
backend's own settings, and re-exports the real model classes.

**No model is defined here. That is the whole point of the file.**

Because of that, a field renamed or dropped in
`CoachingQuiz-Ai-Plateform-v2/django-service/apps/books/models.py` breaks this tool
rather than quietly writing to nothing — which is the failure mode worth having.

The DB host comes from `books_layout.config`, which already resolves `localhost:5433`
on a laptop versus `postgres:5432` inside docker. Django's own settings read the same
env vars, so importing config first is what points Django at the right port.
"""

import os
import sys

from .config import get_settings

_ready = False


def setup():
    """Start Django once. Safe to call repeatedly."""
    global _ready
    if _ready:
        return

    settings = get_settings()          # also loads the shared .env files into os.environ
    django_dir = settings.backend_dir / "django-service"
    if not django_dir.is_dir():
        raise RuntimeError(
            f"Backend not found at {django_dir}. Set BACKEND_DIR in books-layout-detection/.env "
            f"if the platform lives somewhere else."
        )

    # `shared` is imported as a top-level package by the backend, from the platform root.
    for path in (str(django_dir), str(settings.backend_dir)):
        if path not in sys.path:
            sys.path.insert(0, path)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    try:
        import django
    except ModuleNotFoundError as exc:                      # pragma: no cover - setup error
        raise RuntimeError(
            "Django is not installed in this tool's venv. Run:\n"
            "  .venv/Scripts/python -m pip install -r requirements.txt"
        ) from exc

    django.setup()
    _ready = True


def models():
    """The platform's model classes, after Django is up."""
    setup()
    from apps.books.models import Book, BookBlock, BookChapter, Language, Visibility
    from apps.master_data.models import Board, EducationalLevel, LevelSubject
    from apps.organizations.institutes.models import Institute

    return {
        "Book": Book,
        "BookChapter": BookChapter,
        "BookBlock": BookBlock,
        "Language": Language,
        "Visibility": Visibility,
        "Board": Board,
        "EducationalLevel": EducationalLevel,
        "LevelSubject": LevelSubject,
        "Institute": Institute,
    }


def media_root():
    """The one media folder the whole product shares, resolved the backend's way."""
    setup()
    from shared.media_paths import media_root as _root

    return _root()

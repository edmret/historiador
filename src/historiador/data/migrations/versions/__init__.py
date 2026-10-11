"""Alembic revision scripts.

Alembic loads these by file path, not by import, so this marker exists purely so that
``mypy --strict src/historiador/data`` resolves the revisions under a single, stable
module name instead of finding them twice.
"""

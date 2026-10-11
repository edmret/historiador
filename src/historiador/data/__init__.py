"""Persistence layer: typed ORM, repositories, session/unit-of-work, and migrations.

This module is an explicit package marker rather than a PEP 420 namespace package:
without it, ``mypy --strict src/historiador/data`` resolves ``repo/`` under two
different module names ("Source file found twice") and refuses to check the tree.
"""

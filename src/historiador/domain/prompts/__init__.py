"""Versioned, hot-reloadable prompt templates for Historiador's six domain agents.

WHY the prompts live in ``.txt`` files next to this module
    The daemon watches ``domain/prompts/`` and hot-swaps the registry when a file
    changes (ARCHITECTURE.md §8). Prompts embedded in Python string literals would
    need an interpreter restart to take effect, which kills the whole point: an
    operator tuning the writer's tone mid-session must see the next run pick it up.

WHY every prompt carries a declarative :class:`PromptSpec`
    Downstream agents parse model output for sentinels (``[SCOPING_COMPLETE]``) and
    for exact JSON keys. An edit that drops a sentinel or renames ``key_points``
    would not fail loudly - it would produce runs that stall or silently lose
    fields. So each prompt declares the variables it may use and the literal markers
    it must keep, and :meth:`PromptRegistry.load` rejects a violating file *before*
    it can reach a run. A bad hot-reload is a loud error at swap time, never a
    corrupt history an hour later.

WHY ``{{double_brace}}`` placeholders instead of ``str.format`` or ``string.Template``
    Every one of these prompts contains literal JSON examples. ``str.format`` would
    force each of those braces to be doubled, turning a human-editable prompt into
    an escaping puzzle - and the files exist precisely so that humans edit them.
    ``$name`` collides with nothing here today but reads poorly next to prose. A
    doubled brace cannot occur in the JSON we show, so it is unambiguous.

WHY templates are content-hashed
    A history is only reproducible if you know which prompt produced it. Every
    template exposes a ``version`` derived from its content, so the runtime can
    stamp a run with the exact prompt revision that generated it - a hash, not a
    file mtime, because two daemons must agree on the identity of the same text.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Final

__all__ = [
    "PROMPT_SPECS",
    "MissingPromptVariableError",
    "PromptError",
    "PromptNotFoundError",
    "PromptRegistry",
    "PromptSpec",
    "PromptTemplate",
    "PromptValidationError",
]

#: A placeholder: ``{{name}}``, optionally padded (``{{ name }}``).
_PLACEHOLDER_RE: Final = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

#: Any ``{{`` left after the valid placeholders are removed is a typo, not prose.
_OPEN_BRACES: Final = "{{"

_PROMPT_SUFFIX: Final = ".txt"


# ── errors ────────────────────────────────────────────────────────────────────
#
# These deliberately do not inherit from KeyError/ValueError: a caller catching
# KeyError around a dict lookup should not silently swallow a prompt failure, and
# KeyError's repr-quoting mangles multi-line, human-readable messages.


class PromptError(Exception):
    """Base class for every failure raised by the prompt registry."""


class PromptNotFoundError(PromptError):
    """A prompt was requested by a name the registry does not know."""

    def __init__(self, name: str, available: Iterable[str]) -> None:
        self.name = name
        self.available: tuple[str, ...] = tuple(sorted(available))
        known = ", ".join(self.available) or "(none loaded)"
        super().__init__(f"unknown prompt {name!r}; loaded prompts: {known}")


class PromptValidationError(PromptError):
    """A template file violates its spec, so it must not be served to a run."""

    def __init__(self, name: str, reason: str, *, path: Path | None = None) -> None:
        self.name = name
        self.reason = reason
        self.path = path
        where = f" ({path})" if path is not None else ""
        super().__init__(f"prompt {name!r} is invalid{where}: {reason}")


class MissingPromptVariableError(PromptError):
    """Render was called without a value for a required placeholder.

    Raised instead of leaving the raw ``{{tone}}`` in the text: a prompt that ships
    an unsubstituted placeholder to a model produces plausible-looking garbage that
    no downstream check would catch.
    """

    def __init__(self, name: str, missing: Iterable[str], provided: Iterable[str]) -> None:
        self.name = name
        self.missing: tuple[str, ...] = tuple(dict.fromkeys(missing))
        self.provided: tuple[str, ...] = tuple(sorted(provided))
        given = ", ".join(self.provided) or "(nothing)"
        super().__init__(
            f"prompt {name!r} needs a non-empty value for: {', '.join(self.missing)}; got: {given}"
        )


# ── spec + template ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class PromptSpec:
    """The contract a prompt file must satisfy to be loadable.

    ``markers`` is the part that earns its keep: it pins the sentinels and JSON keys
    that other modules parse, so an otherwise reasonable prompt rewrite cannot
    quietly break the pipeline.
    """

    name: str
    purpose: str
    required: frozenset[str] = frozenset()
    defaults: Mapping[str, str] = field(default_factory=dict)
    markers: tuple[str, ...] = ()

    @property
    def allowed(self) -> frozenset[str]:
        """Variables the template may reference: required ones plus defaulted ones."""
        return self.required | frozenset(self.defaults)

    @property
    def filename(self) -> str:
        return f"{self.name}{_PROMPT_SUFFIX}"


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """One validated prompt, pinned to the exact text it was loaded from."""

    name: str
    text: str
    path: Path
    sha256: str
    spec: PromptSpec
    variables: frozenset[str]

    @property
    def version(self) -> str:
        """Short content hash, e.g. ``"a1b2c3d4e5f6"``.

        Stamped onto runs and histories so a finished artifact can always be traced
        back to the prompt revision that produced it.
        """
        return self.sha256[:12]

    def render(self, **values: object) -> str:
        """Substitute placeholders, or raise :class:`MissingPromptVariableError`.

        Values that are ``None`` or blank fall back to the spec's default; a
        required variable with no default and no usable value is an error rather
        than an empty hole, because a silently degraded prompt is indistinguishable
        from a working one until the output is already wrong.

        Extra keyword arguments are ignored on purpose: callers commonly splat a
        wider context dict across several prompts, and rejecting the surplus would
        buy nothing - a mistyped name still surfaces as a *missing* variable.
        """
        missing: list[str] = []

        def substitute(match: re.Match[str]) -> str:
            key = match.group(1)
            raw = values.get(key)
            text = "" if raw is None else str(raw)
            if text.strip():
                return text
            fallback = self.spec.defaults.get(key)
            if fallback is not None:
                return fallback
            missing.append(key)
            return ""

        rendered = _PLACEHOLDER_RE.sub(substitute, self.text)
        if missing:
            raise MissingPromptVariableError(self.name, missing, values)
        return rendered


# ── the six prompts ───────────────────────────────────────────────────────────


def _spec(
    name: str,
    purpose: str,
    *,
    required: Iterable[str] = (),
    defaults: Mapping[str, str] | None = None,
    markers: Iterable[str] = (),
) -> PromptSpec:
    return PromptSpec(
        name=name,
        purpose=purpose,
        required=frozenset(required),
        defaults=MappingProxyType(dict(defaults or {})),
        markers=tuple(markers),
    )


PROMPT_SPECS: Final[Mapping[str, PromptSpec]] = MappingProxyType(
    {
        spec.name: spec
        for spec in (
            _spec(
                "scoping",
                "Interviews the user to turn a rough topic into a researchable brief.",
                required=["topic_title"],
                defaults={"max_rounds": "5"},
                markers=(
                    "[SCOPING_COMPLETE]",
                    "ONE question",
                    '"refined_title"',
                    '"description"',
                    '"suggested_subtopics"',
                    '"title"',
                    '"time_period"',
                    '"geographic_focus"',
                    '"target_audience"',
                ),
            ),
            _spec(
                "research",
                "Produces the web search queries for one subtopic.",
                required=["subtopic_title"],
                defaults={
                    "subtopic_description": "(none supplied)",
                    "context": "(none supplied)",
                    "max_queries": "3",
                },
                markers=("JSON array",),
            ),
            _spec(
                "compiler",
                "Synthesises research sources into a section outline for the writer.",
                required=["tone", "audience"],
                defaults={"target_length": "medium"},
                markers=(
                    '"title"',
                    '"sections"',
                    '"heading"',
                    '"key_points"',
                    '"estimated_length"',
                    '"source_count"',
                ),
            ),
            _spec(
                "writer",
                "Writes the finished history as markdown narrative prose.",
                required=["tone", "audience", "length"],
                defaults={"style_notes": "(none supplied)"},
                markers=("Markdown", "Never invent"),
            ),
            _spec(
                "editor",
                "Reviews a draft (JSON verdict) or refines it against feedback (prose).",
                required=["mode"],
                defaults={
                    "tone": "neutral",
                    "audience": "general",
                    "style_notes": "(none supplied)",
                },
                markers=(
                    '"review"',
                    '"refine"',
                    '"score"',
                    '"strengths"',
                    '"issues"',
                    '"suggestions"',
                    '"verdict"',
                ),
            ),
            _spec(
                "profile",
                "Interviews the user to build a reusable writing profile.",
                defaults={"max_questions": "5"},
                markers=(
                    "[PROFILE_COMPLETE]",
                    "ONE question",
                    '"name"',
                    '"description"',
                    '"tone"',
                    '"audience"',
                    '"preferred_length"',
                    '"style_notes"',
                ),
            ),
        )
    }
)


# ── registry ──────────────────────────────────────────────────────────────────


class PromptRegistry:
    """Loads, validates, and serves the prompt templates in a directory.

    Instances are safe to share across threads: :meth:`load` builds a complete new
    mapping and swaps it in under a lock, so a reader never observes a half-loaded
    registry, and a *failed* reload leaves the previous, known-good prompts in place
    rather than taking the daemon's prompts down with it.
    """

    def __init__(
        self,
        directory: Path | None = None,
        *,
        specs: Mapping[str, PromptSpec] | None = None,
    ) -> None:
        # Default to this package's own directory: it is what the daemon watches and
        # what ships in the wheel. An explicit directory exists for tests and for an
        # operator-owned override tree.
        self._directory = (
            Path(directory) if directory is not None else Path(__file__).resolve().parent
        )
        self._specs: Mapping[str, PromptSpec] = MappingProxyType(
            dict(specs) if specs is not None else dict(PROMPT_SPECS)
        )
        self._templates: Mapping[str, PromptTemplate] = MappingProxyType({})
        self._lock = threading.RLock()

    # -- introspection --------------------------------------------------------

    @property
    def directory(self) -> Path:
        """Where templates are read from - the path the file watcher must watch."""
        return self._directory

    @property
    def is_loaded(self) -> bool:
        return len(self._templates) > 0

    def names(self) -> tuple[str, ...]:
        """Names of every loaded template, sorted."""
        return tuple(sorted(self._ensure_loaded()))

    def versions(self) -> Mapping[str, str]:
        """``name -> version`` for the whole registry.

        Recorded alongside a run so a history can be replayed against, or blamed on,
        the precise prompt set that produced it.
        """
        return MappingProxyType(
            {name: tpl.version for name, tpl in sorted(self._ensure_loaded().items())}
        )

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._ensure_loaded()

    def __iter__(self) -> Iterator[PromptTemplate]:
        templates = self._ensure_loaded()
        return iter([templates[name] for name in sorted(templates)])

    def __len__(self) -> int:
        return len(self._ensure_loaded())

    # -- access ---------------------------------------------------------------

    def get(self, name: str, /) -> PromptTemplate:
        """Return one validated template, loading the registry on first use."""
        templates = self._ensure_loaded()
        try:
            return templates[name]
        except KeyError:
            raise PromptNotFoundError(name, templates) from None

    def render(self, name: str, /, **values: object) -> str:
        """Render a prompt by name.

        ``name`` is positional-only so that a template may legitimately take a
        variable called ``name`` (the profile prompt does).
        """
        return self.get(name).render(**values)

    # -- loading --------------------------------------------------------------

    def load(self) -> tuple[str, ...]:
        """Read and validate every declared template; swap the result in atomically.

        Returns the names whose content changed (all of them on a first load), which
        is what the daemon reports in its ``config.changed`` event. Raises
        :class:`PromptValidationError` without mutating state if any file is bad.
        """
        with self._lock:
            loaded = {name: self._read(spec) for name, spec in self._specs.items()}
            self._reject_undeclared_files()
            previous = self._templates
            changed = tuple(
                sorted(
                    name
                    for name, template in loaded.items()
                    if name not in previous or previous[name].sha256 != template.sha256
                )
            )
            self._templates = MappingProxyType(loaded)
            return changed

    def reload(self) -> tuple[str, ...]:
        """Re-read from disk after a file change; the file watcher's entry point.

        Identical to :meth:`load` - named separately because the watcher's intent
        ("something on disk moved") is not the caller's intent at startup, and
        because the failure contract matters more here: on a bad edit this raises
        and the previously loaded prompts keep serving.
        """
        return self.load()

    # -- internals ------------------------------------------------------------

    def _ensure_loaded(self) -> Mapping[str, PromptTemplate]:
        """Load on first access.

        Lazy rather than eager in ``__init__`` so that merely importing a module
        that constructs a registry cannot fail on disk I/O, while a caller that
        forgets ``load()`` still gets prompts instead of a confusing empty registry.
        """
        if not self._templates:
            with self._lock:
                if not self._templates:
                    self.load()
        return self._templates

    def _read(self, spec: PromptSpec) -> PromptTemplate:
        path = self._directory / spec.filename
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PromptValidationError(spec.name, "template file is missing", path=path) from exc
        except OSError as exc:
            raise PromptValidationError(spec.name, f"unreadable: {exc}", path=path) from exc

        # Normalise line endings and trim edge whitespace so the content hash is
        # stable across editors and platforms rather than tracking a stray newline.
        text = raw.replace("\r\n", "\n").replace("\r", "\n").strip()
        variables = _validate(spec, text, path)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return PromptTemplate(
            name=spec.name,
            text=text,
            path=path,
            sha256=digest,
            spec=spec,
            variables=variables,
        )

    def _reject_undeclared_files(self) -> None:
        """Fail on a ``.txt`` with no spec.

        Almost always a misnamed file (``wrtier.txt``) whose real prompt is then
        silently never used - better caught at load than debugged from a bad run.
        """
        for path in sorted(self._directory.glob(f"*{_PROMPT_SUFFIX}")):
            if path.stem not in self._specs:
                raise PromptValidationError(
                    path.stem,
                    "template file has no declared PromptSpec",
                    path=path,
                )


def _validate(spec: PromptSpec, text: str, path: Path) -> frozenset[str]:
    """Check a template against its spec, returning the placeholders it uses."""
    if not text:
        raise PromptValidationError(spec.name, "template is empty", path=path)

    found = frozenset(match.group(1) for match in _PLACEHOLDER_RE.finditer(text))

    unknown = found - spec.allowed
    if unknown:
        raise PromptValidationError(
            spec.name,
            f"references undeclared variable(s): {', '.join(sorted(unknown))}",
            path=path,
        )

    absent = spec.required - found
    if absent:
        raise PromptValidationError(
            spec.name,
            f"never uses required variable(s): {', '.join(sorted(absent))}",
            path=path,
        )

    # A `{{` surviving placeholder removal is a malformed placeholder (`{{ 2bad }}`,
    # `{{tone}`), which would otherwise reach the model verbatim.
    if _OPEN_BRACES in _PLACEHOLDER_RE.sub("", text):
        raise PromptValidationError(
            spec.name,
            "contains a malformed placeholder (stray '{{')",
            path=path,
        )

    lost = [marker for marker in spec.markers if marker not in text]
    if lost:
        raise PromptValidationError(
            spec.name,
            "dropped contract marker(s) that downstream parsing depends on: "
            + ", ".join(repr(marker) for marker in lost),
            path=path,
        )

    return found

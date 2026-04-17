from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Mapping

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent
DEFAULT_PROMPT_DIR = PACKAGE_DIR / "templates"


class PromptError(RuntimeError):
    """Base prompt loading error."""


class PromptNotFoundError(PromptError):
    """Raised when a prompt template file does not exist."""


class PromptRenderError(PromptError):
    """Raised when a prompt template cannot be rendered."""


@dataclass(slots=True, frozen=True)
class PromptTemplate:
    name: str
    path: Path
    content: str


class PromptLoader:
    def __init__(self, base_dir: str | Path | None = None, *, suffix: str = ".md") -> None:
        self.base_dir = self._resolve_base_dir(base_dir)
        self.suffix = suffix

    def load(self, name: str) -> PromptTemplate:
        prompt_name = self._normalize_name(name)
        prompt_path = self._resolve_prompt_path(prompt_name)
        if not prompt_path.is_file():
            raise PromptNotFoundError(
                f"Prompt template '{prompt_name}' was not found under '{self.base_dir}'."
            )

        content = prompt_path.read_text(encoding="utf-8")
        if not content.strip():
            raise PromptRenderError(f"Prompt template '{prompt_name}' is empty.")
        return PromptTemplate(name=prompt_name, path=prompt_path, content=content)

    def render(
        self,
        name: str,
        variables: Mapping[str, Any] | None = None,
    ) -> PromptTemplate:
        template = self.load(name)
        values = {
            key: self._stringify(value)
            for key, value in (variables or {}).items()
        }

        try:
            content = Template(template.content).substitute(values)
        except KeyError as exc:
            missing_key = exc.args[0]
            raise PromptRenderError(
                f"Prompt template '{template.name}' is missing variable '{missing_key}'."
            ) from exc

        return PromptTemplate(name=template.name, path=template.path, content=content)

    def _resolve_base_dir(self, base_dir: str | Path | None) -> Path:
        if base_dir is None:
            return DEFAULT_PROMPT_DIR.resolve()

        candidate = Path(base_dir)
        if not candidate.is_absolute():
            candidate = (REPO_ROOT / candidate).resolve()
        return candidate

    def _resolve_prompt_path(self, name: str) -> Path:
        filename = name if name.endswith(self.suffix) else f"{name}{self.suffix}"
        candidate = (self.base_dir / filename).resolve()
        try:
            candidate.relative_to(self.base_dir)
        except ValueError as exc:
            raise PromptNotFoundError(f"Prompt template '{name}' is outside the prompt directory.") from exc
        return candidate

    def _normalize_name(self, name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise PromptNotFoundError("Prompt template name must not be empty.")
        return normalized

    def _stringify(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

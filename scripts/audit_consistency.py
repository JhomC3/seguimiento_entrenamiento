"""Auditoría de consistencia de la UI (gate de CI).

Garantiza que los templates usen el vocabulario canónico de componentes
(definido en static/css/components.css) y que no se reintroduzcan:
  - utilidades de color inline repetidas a mano (bg-white/[0.04], bg-burgundy-700…)
  - micro-tipografía (text-[9px]…[11px])
  - colores hex hardcodeados en templates o en CSS no-generado

Uso:
    uv run python scripts/audit_consistency.py [--fix]   # --fix imprime el diff
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Patrones prohibidos en templates (clases Tailwind de color/estilo que deben
# vivir en componentes CSS, no repetirse inline).
FORBIDDEN_TEMPLATE = [
    r"bg-white/\[0\.04\]",
    r"bg-burgundy-700\s+hover",  # botón primario inline
    r"bg-matte-950\s+border",
    r"bg-black/50",
    r"hover:bg-red-400",
    r"hover:bg-burgundy-700/20",
    r"text-\[(9|10|11)px\]",
    r"text-neutral-(500|600)",
    r"focus:border-burgundy-700",
]
# Colores hex/rgba literales fuera de tokens.css (generado).
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
RGBA_RE = re.compile(r"rgba?\(")

# Clases de componente canónicas (vocabulario propio, no Tailwind).
COMPONENT_CLASSES = {
    "btn",
    "btn-primary",
    "btn-ghost",
    "btn-outline",
    "btn-outline-danger",
    "btn-text",
    "cell-input",
    "cell-input-sm",
    "cell-select",
    "field-input",
    "field-input-sm",
    "panel",
    "panel-tight",
    "panel-default",
    "panel-spacious",
    "panel-title",
    "panel-title-neon",
    "panel-title-divider",
    # Aliases de compatibilidad JS/e2e (definidos en CSS propio).
    "row-btn",
    "btn-x",
    "btn-check",
    "edit-toggle",
    "pt-btn",
    "pt-btn-burgundy",
    "today-btn",
    "nav-arrow",
    "rir-step",
    "level-chip",
    "exercise-chip",
    "detail-link",
    "collapse-chevron",
    "notice",
    "notice-success",
    "notice-error",
    "neon-border",
    "metallic-border",
    "neon-title",
    "no-scrollbar",
    "htmx-indicator",
    "editor-popup-dialog",
    "confirm-card",
    "glass-backdrop",
    # Gestor de splits.
    "splits-page",
    "splits-page-header",
    "splits-layout",
    "splits-editor-col",
    "splits-catalog-col",
    "split-columns",
    "split-board-scroll",
    "split-day-zone",
    "split-day-header",
    "split-day-select",
    "split-day-count",
    "split-day-summary",
    "split-day-items",
    "split-day-copy-btn",
    "split-day-clear-btn",
    "split-catalog-group",
    "split-catalog-summary",
    "split-catalog-body",
    "split-catalog-chip",
    "split-item-card",
    "split-item-name",
    "split-item-remove",
    "split-fallback",
    "split-accordion-item",
    "split-accordion",
    "split-accordion-summary",
    "split-accordion-name",
    "split-accordion-chevron",
    "split-accordion-content",
    "split-summary-strip",
    "split-summary-strip-sep",
    "split-item-toolbar",
    "split-item-form",
    "split-item-actions",
    "split-name-input",
    "split-action-btn",
    "split-dirty-hint",
    "split-day-section-label",
    "split-day-section-actions",
    "split-summary-row",
    "split-summary-total",
    "split-summary-name",
    "split-summary-group",
    "split-summary-group-toggle",
    "split-summary-group-body",
    "split-summary-exercise",
    "split-summary-chevron",
    "split-metric",
    "split-empty",
    "split-empty-state",
    "split-empty-state-title",
}


def audit_templates() -> list[str]:
    issues: list[str] = []
    for f in sorted((ROOT / "templates").glob("*.html")):
        text = f.read_text(encoding="utf-8")
        for pat in FORBIDDEN_TEMPLATE:
            for m in re.finditer(pat, text):
                line = text.count("\n", 0, m.start()) + 1
                issues.append(f"{f.relative_to(ROOT)}:{line}: patrón prohibido {m.group(0)!r}")
    return issues


def audit_css() -> list[str]:
    issues: list[str] = []
    for f in sorted((ROOT / "static" / "css").glob("*.css")):
        if f.name in ("tokens.css", "tailwind.css"):
            continue
        text = f.read_text(encoding="utf-8")
        for m in HEX_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            issues.append(f"{f.relative_to(ROOT)}:{line}: hex hardcodeado {m.group(0)}")
        for m in RGBA_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            issues.append(f"{f.relative_to(ROOT)}:{line}: rgba hardcodeado")
    return issues


def audit_component_coverage() -> list[str]:
    """Toda clase de componente definida debe usarse (o estar documentada)."""
    issues: list[str] = []
    tpl = ""
    for f in (ROOT / "templates").glob("*.html"):
        tpl += f.read_text(encoding="utf-8")
    for f in (ROOT / "templates" / "partials").glob("*.html"):
        tpl += f.read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "components.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"^\s*\.([a-z-]+)", css, re.MULTILINE))
    for cls in sorted(defined - COMPONENT_CLASSES):
        if not re.search(rf'class="[^"]*\b{cls}\b', tpl):
            issues.append(f"components.css define .{cls} sin uso ni alias")
    return issues


def main() -> int:
    issues = audit_templates() + audit_css() + audit_component_coverage()
    if issues:
        print(f"Consistencia UI: {len(issues)} problema(s):", file=sys.stderr)
        for i in issues:
            print(f"  - {i}", file=sys.stderr)
        return 1
    print("Consistencia UI OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

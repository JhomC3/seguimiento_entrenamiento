"""Server-owned OOB fragment rendering.

User-supplied values must only reach the browser as Jinja context (autoescaped).
Request-derived strings are never concatenated into HTML in this module or in
app.py. The only `| safe` content allowed here is a pre-rendered, server-owned
Jinja fragment (e.g. the session editor or a Plotly chart body).
"""

import json

from fastapi import Request
from fastapi.templating import Jinja2Templates

NOTICE_TARGETS = ("notice-container", "editor-notice")
NOTICE_KINDS = ("notice-success", "notice-error")

# Fragment wrappers: inner_html must be a server-rendered fragment; targets are
# allow-listed so no caller can inject arbitrary element ids.
OOB_FRAGMENT_TARGETS = (
    "session-editor-wrap",
    "exercise-create",
    "plantillas-section",
    "unified-chart-header",
    "unified-chart-data",
    "unified-chart-empty",
    "date-navigator",
    "session-history",
    "nutrition-editor-wrap",
    "alimento-create",
    "nutrition-templates-section",
    "popup-body",
    "cardio-day",
    "cascade-row",
    "ejercicios-row",
    "splits-section",
    "split-board",
    "history-section",
    "period-summary-wrap",
    "dashboard-catalog-list",
)

STATIC_MARKERS = {
    "outcome_ok": '<div id="save-outcome" hx-swap-oob="outerHTML" data-ok="1" hidden></div>',
    "outcome_fail": '<div id="save-outcome" hx-swap-oob="outerHTML" data-ok="0" hidden></div>',
    "plantilla_applied": '<div id="plantilla-applied" hidden></div>',
    "undo_result_empty": '<div id="undo-result" hx-swap-oob="outerHTML" data-fecha="" data-has-data="0" hidden></div>',
}


def render_fragment(
    templates: Jinja2Templates, request: Request, name: str, **context: object
) -> str:
    return bytes(
        templates.TemplateResponse(request=request, name=name, context=context).body
    ).decode()


def notice_oob(
    templates: Jinja2Templates,
    request: Request,
    *,
    target: str,
    message: str,
    kind: str = "notice-success",
    dismiss: int = 3000,
) -> str:
    if target not in NOTICE_TARGETS:
        raise ValueError(f"target de aviso no permitido: {target!r}")
    if kind not in NOTICE_KINDS:
        raise ValueError(f"kind de aviso no permitido: {kind!r}")
    return render_fragment(
        templates,
        request,
        "partials/oob_notice.html",
        target=target,
        kind=kind,
        dismiss=dismiss,
        message=message,
    )


def editor_state_oob(
    templates: Jinja2Templates, request: Request, *, readonly: int = 1, has_data: int = 1
) -> str:
    return render_fragment(
        templates,
        request,
        "partials/oob_editor_state.html",
        readonly=readonly,
        has_data=has_data,
    )


def editor_wrap_oob(templates: Jinja2Templates, request: Request, editor_html: str) -> str:
    """Wraps the server-rendered editor fragment. editor_html must be Jinja output."""
    return render_fragment(
        templates,
        request,
        "partials/oob_editor_wrap.html",
        editor_html=editor_html,
    )


def nutrition_editor_wrap_oob(
    templates: Jinja2Templates, request: Request, editor_html: str
) -> str:
    """Wraps the server-rendered nutrition editor fragment."""
    return render_fragment(
        templates,
        request,
        "partials/oob_nutrition_editor_wrap.html",
        editor_html=editor_html,
    )


def app_config_oob(app_config_json: dict) -> str:
    """Replaces the #app-config script tag (server-built JSON payload).

    Escapes <, > and & like Jinja's tojson so user-provided names cannot break
    out of the JSON script block.
    """
    payload = (
        json.dumps(app_config_json)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return (
        f'<script id="app-config" hx-swap-oob="outerHTML" '
        f'type="application/json">{payload}</script>'
    )


def undo_result_oob(
    templates: Jinja2Templates,
    request: Request,
    fecha_iso: str,
    has_data: str,
    kind: str = "",
) -> str:
    return render_fragment(
        templates,
        request,
        "partials/oob_undo_result.html",
        fecha_iso=fecha_iso,
        has_data=has_data,
        kind=kind,
    )


def fragment_oob(
    templates: Jinja2Templates,
    request: Request,
    target: str,
    inner_html: str,
    *,
    swap: str = "innerHTML",
) -> str:
    """Generic OOB wrapper for a server-owned fragment (editor, exercise form,
    plantillas list, plotly chart body). inner_html must never contain raw
    request-derived strings."""
    if target not in OOB_FRAGMENT_TARGETS:
        raise ValueError(f"target OOB no permitido: {target!r}")
    return f'<div id="{target}" hx-swap-oob="{swap}">{inner_html}</div>'


def chart_header_oob(title: str) -> str:
    """OOB for the chart panel header (title + ciclo). outerHTML swap."""
    return (
        '<div id="unified-chart-header" hx-swap-oob="outerHTML" '
        'class="flex items-baseline gap-2 min-w-0 pl-3 mb-3">'
        '<h2 class="text-sm font-black tracking-[0.2em] text-burgundy-400 uppercase neon-title truncate">Rendimiento</h2>'
        "</div>"
    )


def chart_data_oob(fig_json: str) -> str:
    """OOB for the chart data div (inert JSON text). innerHTML swap.

    fig_json must be pre-escaped with _json_for_inline. The div is hidden in
    the shell; the client reads its textContent and JSON.parses it.
    """
    return f'<div id="unified-chart-data" hx-swap-oob="innerHTML">{fig_json}</div>'


def chart_empty_oob(visible: bool, message: str = "Sin datos") -> str:
    """OOB for the chart empty-state div. outerHTML swap.

    visible=False renders hidden; visible=True renders the message.
    """
    hidden = "" if visible else " hidden"
    return (
        f'<div id="unified-chart-empty" hx-swap-oob="outerHTML"'
        f' class="chart-empty"{hidden}>'
        f"{message}</div>"
    )


def summary_oob(html: str) -> str:
    """OOB del panel derecho de resumen (Fase 2). outerHTML swap.

    ``html`` es el render completo de period_summary_panel.html con
    oob=True: su raíz ya trae id + hx-swap-oob. Se valida contra la raíz
    esperada para nunca inyectar un target fuera de la allow-list.
    """
    marker = 'id="period-summary-wrap"'
    if marker not in html:
        raise ValueError("summary_oob requiere el render del parcial del panel")
    return html

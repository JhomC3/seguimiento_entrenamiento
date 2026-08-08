"""Server-owned OOB fragment rendering.

User-supplied values must only reach the browser as Jinja context (autoescaped).
Request-derived strings are never concatenated into HTML in this module or in
app.py. The only `| safe` content allowed here is a pre-rendered, server-owned
Jinja fragment (e.g. the session editor or a Plotly chart body).
"""

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
    "unified-chart",
    "date-navigator",
    "session-history",
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


def undo_result_oob(
    templates: Jinja2Templates, request: Request, fecha_iso: str, has_data: str
) -> str:
    return render_fragment(
        templates,
        request,
        "partials/oob_undo_result.html",
        fecha_iso=fecha_iso,
        has_data=has_data,
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


def chart_oob_wrapper(chart_html: str) -> str:
    """Trusted wrapper for the Plotly fragment.

    chart_html comes from `src/dashboard_service.chart_html()`: a server-owned
    block with the figure JSON inside an inert <script type="application/json">
    plus the #unified-chart-plot render div (client renders with Plotly). It
    must never be built from request-derived strings; this wrapper exists so
    the trust boundary is a named, documented function rather than a scattered
    f-string.
    """
    return f'<div id="unified-chart" hx-swap-oob="innerHTML">{chart_html}</div>'

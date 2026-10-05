"""Non-Qualified Calls: module placeholder, hidden from every user until it is activated.

When the module produces reports, it registers a Reporting artifact provider with
``core.register_report_artifact_provider`` so Reporting Jobs can include them.
"""

from typing import Any


def install_non_qualified_calls_routes(core: Any) -> None:
    from fastapi import Depends, Request
    from fastapi.responses import HTMLResponse

    @core.app.get('/non-qualified-calls', response_class=HTMLResponse)
    def non_qualified_calls_page(request: Request, user=Depends(core.current_user)):
        return core.render_template(request, 'non_qualified_calls.html', {'user': user})

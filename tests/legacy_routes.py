"""
Scaffolding for the legacy suites that reach the nine old turn routes over HTTP
(tests/step0_capture/test_capture.py, test_capture_token.py). After the M1b cutover
those routes answer 410, so a suite that still wants to exercise the legacy HANDLERS
removes the 410 router from its own in-process app first. Production never does this.
These suites, and this file, are deleted at M4 with the handlers.
"""


def enable_legacy_routes(app):
    from executor.cutover import ROUTE_NAME_PREFIX, router

    def is_cutover(route):
        # newer FastAPI wraps an included router in one node; older copies its routes
        return getattr(route, "original_router", None) is router or str(getattr(route, "name", "")).startswith(ROUTE_NAME_PREFIX)

    before = len(app.router.routes)
    app.router.routes[:] = [r for r in app.router.routes if not is_cutover(r)]
    assert len(app.router.routes) < before, "the cutover router was not found on the app"
    return app

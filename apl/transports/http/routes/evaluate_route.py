import time

from aiohttp import web

from apl.composition import VerdictComposer
from apl.serialization import event_from_wire, to_wire


class EvaluateRouteHandler:
    def __init__(self):
        self._composer = VerdictComposer()

    async def handle(self, request: web.Request) -> web.Response:
        server = request.app["server"]
        metrics = request.app.get("metrics")
        logger = request.app.get("logger")

        start = time.perf_counter()

        data = await request.json()

        if "type" not in data:
            return web.json_response(
                {"error": "Missing required field: type"},
                status=400,
            )

        event = event_from_wire(data)

        if logger:
            logger.event_received(event.type.value, event.id)

        verdicts = await server.evaluate(event)
        elapsed_ms = (time.perf_counter() - start) * 1000

        if logger:
            for v in verdicts:
                logger.policy_evaluated(
                    v.policy_name or "unknown",
                    v,
                    v.evaluation_ms,
                )

        composed = self._composer.compose(verdicts)

        if metrics:
            metrics.record_request(
                event.type.value,
                composed.decision.value,
                elapsed_ms,
            )

        if logger:
            logger.composition_result(
                len(verdicts),
                composed.decision,
                elapsed_ms,
            )

        return web.json_response(
            {
                "event_id": event.id,
                "verdicts": [to_wire(v) for v in verdicts],
                "composed_verdict": to_wire(composed),
                "evaluation_ms": elapsed_ms,
            }
        )


_handler = EvaluateRouteHandler()
handle_evaluate = _handler.handle

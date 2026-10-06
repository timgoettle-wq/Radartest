import asyncio
import unittest

from starlette.websockets import WebSocketDisconnect

from web import app as web_app


class FakeController:

    def get_latest_measurement(self):
        return {"sequence": 1, "scenario_done": False}

    def is_measurement_running(self):
        return True


class DisconnectingWebSocket:
    """Simuliert einen Browser, der während des Sendens verschwindet."""

    def __init__(self):
        self.sent = []
        self.closed = False

    async def accept(self):
        pass

    async def send_json(self, data):
        if self.closed:
            raise RuntimeError('Cannot call "send" once a close message has been sent.')
        self.sent.append(data)
        self.closed = True
        raise WebSocketDisconnect(code=1006)

    async def close(self):
        self.closed = True


class WebSocketDisconnectTest(unittest.TestCase):

    def setUp(self):
        self.old_controller = web_app.controller
        web_app.controller = FakeController()

    def tearDown(self):
        web_app.controller = self.old_controller

    def test_no_send_after_client_disconnect(self):
        websocket = DisconnectingWebSocket()

        asyncio.run(web_app.static_measurement_websocket(websocket))

        self.assertEqual(len(websocket.sent), 1)
        self.assertEqual(websocket.sent[0]["type"], "measurement")


if __name__ == "__main__":
    unittest.main()

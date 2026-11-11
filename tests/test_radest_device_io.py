import socket
import threading
import time
import unittest
from unittest import mock

from radest import device as radest_device
from radest.device import RadestBusyError, RadestDevice


class FakeRadest:
    """Kleiner TCP-Server, der SCPI-Befehle wie der RadEsT beantwortet."""

    def __init__(self, answer_idn=True, trigger_delay_s=0.0):
        self.answer_idn = answer_idn
        self.trigger_delay_s = trigger_delay_s
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            connection, _ = self.server.accept()
        except OSError:
            return
        with connection:
            buffer = b""
            while True:
                try:
                    data = connection.recv(256)
                except OSError:
                    return
                if not data:
                    return
                buffer += data
                while b"\0" in buffer:
                    command, buffer = buffer.split(b"\0", 1)
                    command = command.decode()
                    if command == "*IDN?":
                        if not self.answer_idn:
                            continue
                        answer = "FAKE,RADEST"
                    elif command == "SCENARIO:TRIGGER":
                        time.sleep(self.trigger_delay_s)
                        answer = "SCENARIO DONE"
                    else:
                        answer = f"OK {command}"
                    try:
                        connection.sendall(answer.encode())
                    except OSError:
                        return

    def close(self):
        self.server.close()


class RadestDeviceIoTest(unittest.TestCase):

    def test_connect_fails_when_radest_does_not_answer(self):
        server = FakeRadest(answer_idn=False)
        self.addCleanup(server.close)
        radest = RadestDevice("127.0.0.1", server.port)

        with mock.patch.object(radest_device, "IDENTIFY_TIMEOUT_S", 0.2):
            self.assertFalse(radest.connect())

        self.assertIsNone(radest.socket)

    def test_second_thread_does_not_steal_scenario_answer(self):
        server = FakeRadest(trigger_delay_s=0.6)
        self.addCleanup(server.close)
        radest = RadestDevice("127.0.0.1", server.port)
        self.assertTrue(radest.connect())
        self.addCleanup(radest.disconnect)

        results = {}

        def trigger():
            results["trigger"] = radest.send_scpi_and_print_answer(
                "SCENARIO:TRIGGER", timeout_s=5
            )

        thread = threading.Thread(target=trigger)
        thread.start()
        time.sleep(0.1)

        with mock.patch.object(radest_device, "BUSY_WAIT_S", 0.1):
            with self.assertRaises(RadestBusyError):
                radest.send_scpi_and_print_answer("TARGET:GET:DISTANCE?")

        thread.join(timeout=5)
        self.assertEqual(results["trigger"], "SCENARIO DONE")
        # Danach ist der RadEsT wieder frei.
        self.assertEqual(
            radest.send_scpi_and_print_answer("TARGET:GET:DISTANCE?"),
            "OK TARGET:GET:DISTANCE?",
        )

    def test_disconnect_wakes_waiting_command(self):
        server = FakeRadest(trigger_delay_s=5)
        self.addCleanup(server.close)
        radest = RadestDevice("127.0.0.1", server.port)
        self.assertTrue(radest.connect())

        done = threading.Event()

        def trigger():
            try:
                radest.send_scpi_and_print_answer("SCENARIO:TRIGGER", timeout_s=30)
            except Exception:
                pass
            done.set()

        threading.Thread(target=trigger, daemon=True).start()
        time.sleep(0.1)
        radest.disconnect()

        self.assertTrue(done.wait(2))


if __name__ == "__main__":
    unittest.main()

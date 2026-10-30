import os
import unittest


class TestUIBlinkingAndWebSocketLoop(unittest.TestCase):
    """Verifies that static/js/app.js contains robust safeguards against UI blinking

    and WebSocket reconnection churn in Socket.IO.
    """

    def setUp(self):
        js_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            self.app_js = f.read()

    def test_websocket_transports_and_reconnection_loop_safeguards(self):
        """Ensure Socket.IO uses polling first, graceful WS upgrade, and pins to polling on error."""
        self.assertIn("transports: ['polling', 'websocket']", self.app_js, "Socket.IO must use polling first for reliable connection")
        self.assertIn("upgrade: true", self.app_js, "Socket.IO must support upgrade to WebSocket")
        self.assertIn("reconnection: true", self.app_js, "Socket.IO must allow auto-reconnection")
        self.assertIn("connect_error", self.app_js, "Socket.IO must handle connect_error")
        self.assertIn("waSocket.io.opts.transports = ['polling']", self.app_js, "On connect_error, must fallback to polling to prevent reconnect loop")

    def test_auto_poll_throttling_when_socket_connected(self):
        """Ensure background HTTP polling is relaxed when Socket.IO is actively receiving real-time events."""
        self.assertIn("waSocket && waSocket.connected", self.app_js)
        self.assertIn("waLastBackgroundPollTime", self.app_js)

    def test_render_whatsapp_web_ui_smart_diffing(self):
        """Ensure renderWhatsAppWebUI implements signature caching to prevent DOM blinking."""
        self.assertIn("convSignature", self.app_js, "Must compute conversation list signature")
        self.assertIn("convList._lastSignature", self.app_js, "Must cache conversation list signature")
        self.assertIn("streamSignature", self.app_js, "Must compute message stream signature")
        self.assertIn("msgStream._lastSignature", self.app_js, "Must cache message stream signature")

    def test_active_audio_playback_preservation(self):
        """Ensure active voice note playback is preserved and re-synchronized across renders."""
        self.assertIn("playingId = (waCurrentAudio && !waCurrentAudio.paused)", self.app_js)
        self.assertIn("waPlayBtn_${playingId}", self.app_js)
        self.assertIn("waAudioProg_${playingId}", self.app_js)
        self.assertIn("waAudioTime_${playingId}", self.app_js)


if __name__ == "__main__":
    unittest.main()

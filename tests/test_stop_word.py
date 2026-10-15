"""Stop detections must not consume commands or leak across playback sessions."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from reachy_mini_home_assistant.audio.stop_word import StopWordDetector


class StopModel:
    id = "stop"

    def __init__(self):
        self.stale_detection = True
        self.resets = 0
        self.inputs = []

    def reset(self):
        self.stale_detection = False
        self.resets += 1

    def process_streaming(self, feature):
        self.inputs.append(feature)
        return self.stale_detection or feature == "stop"


class StopWordTests(unittest.TestCase):
    def setUp(self):
        self.detector = StopWordDetector()
        self.model = StopModel()
        self.satellite = SimpleNamespace(
            is_streaming_audio=False,
            _pipeline_active=True,
            _pending_voice_request=None,
            _timer_finished=False,
            stop=Mock(),
        )
        self.state = SimpleNamespace(
            stop_word=self.model,
            satellite=self.satellite,
            active_wake_words={"okay_nabu"},
            is_muted=False,
            tts_player=SimpleNamespace(is_playing=False),
        )

    def arm_playback(self):
        self.state.active_wake_words.add("stop")
        self.state.tts_player.is_playing = True

    def test_two_wake_chimes_and_commands_are_not_cancelled(self):
        for _ in range(2):
            self.state.tts_player.is_playing = True
            self.satellite._pending_voice_request = ("okay_nabu", "conversation")
            self.detector.process(self.state, ["stop"])
            self.satellite._pending_voice_request = None
            self.state.tts_player.is_playing = False
            self.satellite.is_streaming_audio = True
            self.detector.process(self.state, ["stop"])
            self.satellite.is_streaming_audio = False
        self.satellite.stop.assert_not_called()
        self.assertEqual(self.model.inputs, [])
        self.assertEqual(self.state.active_wake_words, {"okay_nabu"})

    def test_streaming_capture_is_protected_even_with_stale_playback_flags(self):
        self.arm_playback()
        self.satellite.is_streaming_audio = True
        self.detector.process(self.state, ["stop"])
        self.satellite.stop.assert_not_called()
        self.assertEqual(self.model.inputs, [])

    def test_pending_wake_request_is_protected_even_with_stale_arming(self):
        self.arm_playback()
        self.satellite._pending_voice_request = ("okay_nabu", "conversation")
        self.detector.process(self.state, ["stop"])
        self.satellite.stop.assert_not_called()

    def test_old_detection_does_not_cancel_the_next_reply(self):
        self.arm_playback()
        self.detector.process(self.state, ["silence", "silence"])
        self.satellite.stop.assert_not_called()
        self.assertEqual(self.model.resets, 1)
        self.detector.process(self.state, ["stop", "stop"])
        self.satellite.stop.assert_called_once()
        self.assertEqual(self.model.resets, 1)

    def test_new_playback_resets_model_after_disarming(self):
        self.arm_playback()
        self.detector.process(self.state, ["silence"])
        self.state.active_wake_words.discard("stop")
        self.detector.process(self.state, ["stop"])
        self.model.stale_detection = True
        self.arm_playback()
        self.detector.process(self.state, ["silence"])
        self.assertEqual(self.model.resets, 2)
        self.satellite.stop.assert_not_called()

    def test_timer_can_be_stopped_between_ring_sounds(self):
        self.state.active_wake_words.add("stop")
        self.satellite._timer_finished = True
        self.detector.process(self.state, ["stop"])
        self.satellite.stop.assert_called_once()

    def test_muted_microphone_cannot_stop_playback(self):
        self.arm_playback()
        self.state.is_muted = True
        self.detector.process(self.state, ["stop"])
        self.satellite.stop.assert_not_called()
        self.assertEqual(self.model.inputs, [])

    def test_missing_model_or_disconnected_satellite_is_safe(self):
        self.state.stop_word = None
        self.detector.process(self.state, ["stop"])
        self.state.stop_word = self.model
        self.state.satellite = None
        self.detector.process(self.state, ["stop"])
        self.satellite.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()

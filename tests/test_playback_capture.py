"""Playback must preserve the microphone in the SDK's shared audio pipeline."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from reachy_mini_home_assistant.audio.audio_player import AudioPlayer


class SharedAudioBackend:
    """Model the public SDK 1.11 GStreamer stop/flush semantics."""

    def __init__(self):
        self.capturing = True
        self.queued_output = [b"old audio"]
        self.flushes = 0

    def clear_player(self):
        self.queued_output.clear()
        self.flushes += 1

    def clear_output_buffer(self):
        self.queued_output.clear()


class SharedMedia:
    def __init__(self):
        self.audio = SharedAudioBackend()
        self.sounds = []

    def stop_playing(self):
        # SDK 1.11 sets the single recording/playback pipeline to NULL.
        self.audio.capturing = False
        self.audio.queued_output.clear()

    def play_sound(self, path):
        # The SDK uses a separate playbin; this does not restart capture.
        self.sounds.append(path)

    def is_playing(self):
        return False


class PlaybackCaptureTests(unittest.TestCase):
    def setUp(self):
        self.media = SharedMedia()
        self.player = AudioPlayer(SimpleNamespace(media=self.media))
        self.soundfile = SimpleNamespace(info=lambda _: SimpleNamespace(frames=0, samplerate=16000))
        self.soundfile_patch = patch.dict("sys.modules", {"soundfile": self.soundfile})
        self.soundfile_patch.start()
        self.addCleanup(self.soundfile_patch.stop)

    def test_two_wake_sounds_finish_with_capture_still_running(self):
        for _ in range(2):
            done = threading.Event()
            self.player.play("wake.wav", done_callback=done.set)
            self.assertTrue(done.wait(1), "wake sound callback did not start the voice request")
            self.player._playback_thread.join(timeout=1)
            self.assertTrue(self.media.audio.capturing, "wake playback stopped microphone capture")
        self.assertEqual(self.media.sounds, ["wake.wav", "wake.wav"])
        self.assertFalse(self.media.audio.queued_output)

    def test_stop_discards_output_and_playlist_without_stopping_capture(self):
        self.player._playlist = ["next.wav"]
        self.player.is_playing = True
        self.player.stop()
        self.assertTrue(self.media.audio.capturing)
        self.assertFalse(self.media.audio.queued_output)
        self.assertFalse(self.player._playlist)
        self.assertFalse(self.player.is_playing)
        self.assertTrue(self.player._stop_flag.is_set())

    def test_pause_keeps_capture_and_playlist(self):
        self.player._playlist = ["next.wav"]
        self.player.pause()
        self.assertTrue(self.media.audio.capturing)
        self.assertFalse(self.media.audio.queued_output)
        self.assertEqual(self.player._playlist, ["next.wav"])

    def test_local_file_timeout_keeps_capture(self):
        with patch("reachy_mini_home_assistant.audio.audio_player_local.time.monotonic", side_effect=[0, 61]):
            self.player._play_local_file("wake.wav")
        self.assertTrue(self.media.audio.capturing)
        self.assertFalse(self.media.audio.queued_output)

    def test_cancelled_local_file_keeps_capture(self):
        self.player._stop_flag.set()
        self.player._play_local_file("wake.wav")
        self.assertTrue(self.media.audio.capturing)
        self.assertFalse(self.media.audio.queued_output)

    def test_sendspin_stop_keeps_capture(self):
        self.player._sendspin_playback_started = True
        self.player._stop_sendspin_output()
        self.assertTrue(self.media.audio.capturing)
        self.assertFalse(self.media.audio.queued_output)
        self.assertFalse(self.player._sendspin_playback_started)

    def test_stop_without_robot_is_safe(self):
        self.player.reachy_mini = None
        self.player.stop()
        self.assertFalse(self.player.is_playing)

    def test_failed_flush_does_not_fall_back_to_stopping_microphone(self):
        with patch.object(self.media.audio, "clear_player", side_effect=RuntimeError("backend unavailable")):
            self.player.stop()
        self.assertTrue(self.media.audio.capturing)


if __name__ == "__main__":
    unittest.main()

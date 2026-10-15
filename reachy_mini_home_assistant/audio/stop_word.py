"""Playback interruption without cancelling microphone capture."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    import numpy as np

    from ..models import ServerState

_LOGGER = logging.getLogger(__name__)


class StopWordDetector:
    """Keep stop-model state within one explicitly armed playback interval."""

    def __init__(self) -> None:
        self._armed = False

    def process(self, state: ServerState, features: Iterable[np.ndarray]) -> None:
        model = state.stop_word
        satellite = state.satellite
        armed = bool(
            model
            and satellite
            and model.id in state.active_wake_words
            and not state.is_muted
            and not satellite.is_streaming_audio
            and satellite._pending_voice_request is None
            and (state.tts_player.is_playing or satellite._timer_finished)
        )
        if not armed:
            self._armed = False
            return

        if not self._armed:
            # Reset on the inference thread: stale scores must not stop a new reply.
            model.reset()
            self._armed = True

        for feature in features:
            if model.process_streaming(feature):
                _LOGGER.info("Stop word detected during playback - stopping playback")
                self._armed = False
                satellite.stop()
                return

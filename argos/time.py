import asyncio
import contextlib
from datetime import datetime
import logging
from typing import Optional, TYPE_CHECKING

from gi.repository import GObject

if TYPE_CHECKING:
    from .app import Application
from .http import MopidyHTTPClient
from .model import Model, PlaybackState

LOGGER = logging.getLogger(__name__)

DELAY = 10  # s


class TimePositionTracker(GObject.GObject):
    """Track time position.

    Periodic synchronization with Mopidy server happens every
    ``DELAY`` seconds.

    """

    _last_sync: Optional[datetime] = None

    def __init__(
        self,
        application: "Application",
    ):
        super().__init__()

        self._model: Model = application.props.model
        self._http: MopidyHTTPClient = application.props.http

        self._time_position_changed_handler_id = self._model.playback.connect(
            "notify::time-position",
            self._on_time_position_changed,
        )

    def _on_time_position_changed(
        self,
        _1: GObject.GObject,
        _2: GObject.ParamSpec,
    ) -> None:
        LOGGER.debug("Storing timestamp of last time position synchronization")
        self._last_sync = datetime.now()

    async def track(self) -> None:
        LOGGER.debug("Tracking time position...")
        while True:
            if (
                self._model.network_available
                and self._model.connected
                and self._model.playback.state == PlaybackState.PLAYING
            ):
                time_position: Optional[int] = -1
                if self._model.playback.time_position != -1 and self._last_sync:
                    time_position = self._model.playback.time_position + 1000
                    delta = (datetime.now() - self._last_sync).total_seconds()
                    needs_sync = delta >= DELAY
                else:
                    needs_sync = True

                synced = False
                if needs_sync:
                    LOGGER.debug("Trying to synchronize time position")
                    try:
                        time_position = await asyncio.wait_for(
                            self._http.get_time_position(),
                            1,
                        )
                        synced = True
                    except asyncio.exceptions.TimeoutError:
                        time_position = None
                else:
                    LOGGER.debug("No need to synchronize time position")

                if time_position is None:
                    time_position = -1

                if not synced:
                    LOGGER.debug(
                        f"Won't signal time position change to {self._time_position_changed_handler_id}"
                    )
                    args = {"block_handler": self._time_position_changed_handler_id}
                else:
                    args = {}

                self._model.playback.set_time_position(time_position, **args)

            await asyncio.sleep(1)

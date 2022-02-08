import asyncio
import logging
from functools import partial
from threading import Thread
from typing import List

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk

from .widgets.preferences import PreferencesWindow

from .accessor import ModelAccessor
from .download import ImageDownloader
from .http import MopidyHTTPClient
from .message import Message, MessageType
from .model import Model, PlaybackState
from .utils import configure_logger
from .window import ArgosWindow
from .ws import MopidyWSListener

LOGGER = logging.getLogger(__name__)


class Application(Gtk.Application):
    def __init__(self, *args, **kwargs):
        Gtk.Application.__init__(
            self,
            *args,
            application_id="app.argos.Argos",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
            **kwargs,
        )
        self._loop = asyncio.get_event_loop()
        self._messages = asyncio.Queue()
        self._model = Model()

        self._http = MopidyHTTPClient()
        self._ws = MopidyWSListener(message_queue=self._messages)
        self._download = ImageDownloader(message_queue=self._messages)

        self.window = None
        self.prefs_window = None

        self._start_fullscreen = None
        self._disable_tooltips = None

        self.add_main_option(
            "debug",
            ord("d"),
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Enable debug logs",
            None,
        )
        self.add_main_option(
            "fullscreen",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Start with fullscreen window",
            None,
        )
        self.add_main_option(
            "no-tooltips",
            0,
            GLib.OptionFlags.NONE,
            GLib.OptionArg.NONE,
            "Disable tooltips",
            None,
        )

    def do_command_line(self, command_line):
        options = command_line.get_options_dict()
        options = options.end().unpack()

        configure_logger(options)
        self._start_fullscreen = "fullscreen" in options
        self._disable_tooltips = "no-tooltips" in options

        self.activate()
        return 0

    def do_activate(self):
        if not self.window:
            self.window = ArgosWindow(
                application=self,
                message_queue=self._messages,
                loop=self._loop,
                disable_tooltips=self._disable_tooltips,
            )
        if self._start_fullscreen:
            self.window.fullscreen()

        self.window.present()

    def do_startup(self):
        Gtk.Application.do_startup(self)

        show_prefs_action = Gio.SimpleAction.new("show_preferences", None)
        show_prefs_action.connect("activate", self.show_prefs_activate_cb)
        self.add_action(show_prefs_action)

        play_random_album_action = Gio.SimpleAction.new("play_random_album", None)
        play_random_album_action.connect("activate", self.play_random_album_activate_cb)
        self.add_action(play_random_album_action)

        play_favorite_playlist_action = Gio.SimpleAction.new(
            "play_favorite_playlist", None
        )
        play_favorite_playlist_action.connect(
            "activate", self.play_favorite_playlist_activate_cb
        )
        self.add_action(play_favorite_playlist_action)

        # Run an event loop in a dedicated thread and reserve main
        # thread to Gtk processing loop
        t = Thread(target=self._start_event_loop, daemon=True)
        t.start()

    def _start_event_loop(self):
        LOGGER.debug("Attaching event loop to calling thread")
        asyncio.set_event_loop(self._loop)

        LOGGER.debug("Starting event loop")
        self._loop.run_until_complete(
            asyncio.gather(
                self._reset_model(),
                self._process_messages(),
                self._track_time_position(),
                self._ws.listen(),
            )
        )
        LOGGER.debug("Event loop stopped")

    async def _track_time_position(self) -> None:
        LOGGER.debug("Tracking time position...")
        while True:
            if self._model.state == PlaybackState.PLAYING and self._model.track_length:
                await self._update_time_position()
            await asyncio.sleep(1)

    async def _update_time_position(self) -> None:
        time_position = await self._http.get_time_position()
        async with self.model_accessor as model:
            model.update_from(time_position=time_position)

    async def _process_messages(self) -> None:
        LOGGER.debug("Waiting for new messages...")
        while True:
            message = await self._messages.get()
            type = message.type

            LOGGER.debug(f"Processing {type!r} message")

            # Commands
            if type == MessageType.TOGGLE_PLAYBACK_STATE:
                current_state = self._model.state
                if current_state == PlaybackState.PLAYING:
                    await self._http.pause()
                elif current_state == PlaybackState.PAUSED:
                    await self._http.resume()
                elif current_state == PlaybackState.STOPPED:
                    await self._http.play()

            elif type == MessageType.PLAY_PREV_TRACK:
                await self._http.previous()

            elif type == MessageType.PLAY_NEXT_TRACK:
                await self._http.next()

            elif type == MessageType.PLAY_RANDOM_ALBUM:
                await self._http.play_random_album()

            elif type == MessageType.PLAY_FAVORITE_PLAYLIST:
                await self._http.play_favorite_playlist()

            elif type == MessageType.SEEK:
                time_position = round(message.data.get("time_position"))
                await self._http.seek(time_position)

            elif type == MessageType.SET_VOLUME:
                volume = round(message.data * 100)
                await self._http.set_volume(volume)

            elif type == MessageType.LIST_PLAYLISTS:
                playlists = await self._http.list_playlists()
                if self.prefs_window and playlists:
                    GLib.idle_add(
                        partial(
                            self.prefs_window.update_favorite_playlist_completion,
                            playlists=playlists,
                        )
                    )

            # Events (from websocket)
            elif type == MessageType.TRACK_PLAYBACK_STARTED:
                tl_track = message.data.get("tl_track", {})
                async with self.model_accessor as model:
                    model.update_from(tl_track=tl_track)

            elif type == MessageType.TRACK_PLAYBACK_PAUSED:
                async with self.model_accessor as model:
                    model.update_from(raw_state="paused")

            elif type == MessageType.TRACK_PLAYBACK_RESUMED:
                async with self.model_accessor as model:
                    model.update_from(raw_state="playing")

            elif type == MessageType.TRACK_PLAYBACK_ENDED:
                async with self.model_accessor as model:
                    model.clear_tl()

            elif type == MessageType.PLAYBACK_STATE_CHANGED:
                raw_state = message.data.get("new_state")
                async with self.model_accessor as model:
                    model.update_from(raw_state=raw_state)

            elif type == MessageType.MUTE_CHANGED:
                mute = message.data.get("mute")
                async with self.model_accessor as model:
                    model.update_from(mute=mute)

            elif type == MessageType.VOLUME_CHANGED:
                volume = message.data.get("volume")
                async with self.model_accessor as model:
                    model.update_from(volume=volume)

            elif type == MessageType.TRACKLIST_CHANGED:
                async with self.model_accessor as model:
                    model.clear_tl()

            elif type == MessageType.SEEKED:
                time_position = message.data.get("time_position")
                async with self.model_accessor as model:
                    model.update_from(time_position=time_position)

            # Events (internal)
            elif type == MessageType.IMAGE_AVAILABLE:
                track_uri = message.data.get("track_uri")
                image_path = message.data.get("image_path")
                if self._model.track_uri == track_uri:
                    async with self.model_accessor as model:
                        model.update_from(image_path=image_path)

            elif type == MessageType.MODEL_CHANGED:
                changed = message.data.get("changed", [])
                await self._handle_model_changed(changed)

            else:
                LOGGER.warning(
                    f"Unhandled message type {type!r} " f"with data {message.data!r}"
                )

    @property
    def model_accessor(self) -> ModelAccessor:
        return ModelAccessor(model=self._model, message_queue=self._messages)

    async def _handle_model_changed(self, changed: List[str]) -> None:
        """Propage model changes to UI."""
        if not self.window:
            return

        if "image_path" in changed:
            GLib.idle_add(self.window.update_image, self._model.image_path)

        if (
            "track_name" in changed
            or "artist_name" in changed
            or "track_length" in changed
        ):
            GLib.idle_add(
                partial(
                    self.window.update_labels,
                    track_name=self._model.track_name,
                    artist_name=self._model.artist_name,
                    track_length=self._model.track_length,
                )
            )

            track_uri = self._model.track_uri
            if not track_uri:
                return

            track_images = await self._http.get_images(track_uri)
            await self._download.fetch_first_image(
                track_uri=track_uri, track_images=track_images
            )

        if "volume" in changed or "mute" in changed:
            GLib.idle_add(
                partial(
                    self.window.update_volume,
                    mute=self._model.mute,
                    volume=self._model.volume,
                )
            )

        if "state" in changed:
            GLib.idle_add(
                partial(self.window.update_play_button, state=self._model.state)
            )

        if "time_position" in changed:
            GLib.idle_add(
                partial(
                    self.window.update_time_position_scale,
                    time_position=self._model.time_position,
                )
            )

    async def _reset_model(self) -> None:
        raw_state = await self._http.get_state()
        mute = await self._http.get_mute()
        volume = await self._http.get_volume()
        tl_track = await self._http.get_current_tl_track()
        time_position = await self._http.get_time_position()

        async with self.model_accessor as model:
            model.update_from(
                raw_state=raw_state,
                mute=mute,
                volume=volume,
                time_position=time_position,
                tl_track=tl_track,
            )

    def show_prefs_activate_cb(self, action, parameter) -> None:
        if self.window is None:
            return

        self.prefs_window = PreferencesWindow(
            message_queue=self._messages,
            loop=self._loop,
        )
        self.prefs_window.set_transient_for(self.window)
        self.prefs_window.connect("destroy", self.prefs_window_destroy_cb)

        self.prefs_window.present()

    def prefs_window_destroy_cb(self, window: Gtk.Window) -> None:
        self.prefs_window = None

    def play_random_album_activate_cb(self, action, parameter) -> None:
        self._loop.call_soon_threadsafe(
            self._messages.put_nowait, Message(MessageType.PLAY_RANDOM_ALBUM)
        )

    def play_favorite_playlist_activate_cb(self, action, parameter) -> None:
        self._loop.call_soon_threadsafe(
            self._messages.put_nowait, Message(MessageType.PLAY_FAVORITE_PLAYLIST)
        )

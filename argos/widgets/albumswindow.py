import logging
import re
import threading
from enum import IntEnum
from pathlib import Path
from typing import List

from gi.repository import GLib, GObject, Gtk
from gi.repository.GdkPixbuf import Pixbuf

from argos.message import MessageType
from argos.utils import elide_maybe
from argos.widgets.albumsbrowsingprogressbox import AlbumsBrowsingProgressBox
from argos.widgets.utils import default_image_pixbuf, scale_album_image

LOGGER = logging.getLogger(__name__)

ALBUM_IMAGE_SIZE = 100


class AlbumStoreColumns(IntEnum):
    MARKUP = 0
    TOOLTIP = 1
    URI = 2
    IMAGE_FILE_PATH = 3
    PIXBUF = 4
    FILTER_TEXT = 5
    FILTER_TEXT_SECONDARY = 6


@Gtk.Template(resource_path="/io/github/orontee/Argos/ui/albums_window.ui")
class AlbumsWindow(Gtk.Overlay):
    __gtype_name__ = "AlbumsWindow"

    __gsignals__ = {"album-selected": (GObject.SIGNAL_RUN_FIRST, None, (str,))}

    default_album_image = default_image_pixbuf(
        "media-optical-cd-audio-symbolic",
        target_width=ALBUM_IMAGE_SIZE,
    )

    albums_view: Gtk.IconView = Gtk.Template.Child()

    filtered_albums_store = GObject.Property(type=Gtk.TreeModelFilter)
    filtering_text = GObject.Property(type=str)

    def __init__(self, application: Gtk.Application):
        super().__init__()

        self._app = application
        self._model = application.model

        albums_store = Gtk.ListStore(str, str, str, str, Pixbuf, str, str)
        self.props.filtered_albums_store = albums_store.filter_new()
        self.props.filtered_albums_store.set_visible_func(self._filter_album_row, None)
        self.albums_view.set_model(self.props.filtered_albums_store)

        self.albums_view.set_markup_column(AlbumStoreColumns.MARKUP)
        self.albums_view.set_tooltip_column(AlbumStoreColumns.TOOLTIP)
        self.albums_view.set_pixbuf_column(AlbumStoreColumns.PIXBUF)
        self.albums_view.set_item_width(ALBUM_IMAGE_SIZE)

        if application.props.disable_tooltips:
            self.albums_view.props.has_tooltip = False

        self._progress_box = AlbumsBrowsingProgressBox()
        self.add_overlay(self._progress_box)
        self._progress_box.show_all()
        self.show_all()

        self._model.connect("notify::albums-loaded", self._update_store)
        application.props.download.connect(
            "albums-images-downloaded", self._update_store_pixbufs
        )
        # Don't make expectations on the order both signals are emitted!!

        self._ongoing_store_update = threading.Lock()
        self._abort_pixbufs_update = False

    def set_filtering_text(self, text: str) -> None:
        stripped = text.strip()
        if stripped != self.props.filtering_text:
            LOGGER.debug(f"Filtering albums store according to {stripped!r}")

            self.props.filtering_text = stripped
            self.props.filtered_albums_store.refilter()

    def _filter_album_row(
        self,
        model: Gtk.ListStore,
        iter: Gtk.TreeIter,
        data: None,
    ) -> bool:
        if not self.props.filtering_text:
            return True

        pattern = re.escape(self.props.filtering_text)
        text = model.get_value(iter, AlbumStoreColumns.FILTER_TEXT)
        if re.search(pattern, text, re.IGNORECASE) is not None:
            return True

        secondary_text = model.get_value(iter, AlbumStoreColumns.FILTER_TEXT_SECONDARY)
        return re.search(pattern, secondary_text, re.IGNORECASE) is not None

    def _update_store(
        self,
        _1: GObject.GObject,
        _2: GObject.GParamSpec,
    ) -> None:
        LOGGER.debug("Updating album store...")

        self._progress_box.show()

        if self._ongoing_store_update.locked():
            self._abort_pixbufs_update = True
            LOGGER.info("Pixbufs update thread has been requested to abort...")

        image_uris: List[Path] = []
        with self._ongoing_store_update:
            self._abort_pixbufs_update = False
            store = self.props.filtered_albums_store.get_model()
            store.clear()

            for album in self._model.albums:
                escaped_album_name = GLib.markup_escape_text(album.name)
                elided_escaped_album_name = GLib.markup_escape_text(
                    elide_maybe(album.name)
                )
                escaped_artist_name = GLib.markup_escape_text(album.artist_name)
                elided_escaped_artist_name = GLib.markup_escape_text(
                    elide_maybe(album.artist_name)
                )
                store.append(
                    [
                        f"<b>{elided_escaped_album_name}</b>\n{elided_escaped_artist_name}",
                        f"<b>{escaped_album_name}</b>\n{escaped_artist_name}",
                        album.uri,
                        str(album.image_path) if album.image_path else "",
                        self.default_album_image,
                        album.artist_name,
                        album.name,
                    ]
                )
                if album.image_uri:
                    image_uris.append(album.image_uri)

        LOGGER.debug("Will fetch album images since albums were just loaded")
        self._app.send_message(
            MessageType.FETCH_ALBUM_IMAGES, data={"image_uris": image_uris}
        )

        self._progress_box.hide()

    def _update_store_pixbufs(
        self,
        _1: GObject.GObject,
    ) -> None:
        thread = threading.Thread(
            target=self._start_store_pixbufs_update_task, name="ImagesThread"
        )
        thread.daemon = True
        thread.start()

    def _start_store_pixbufs_update_task(self) -> None:
        # wait for model.albums_loaded
        with self._ongoing_store_update:
            # Will wait for ongoing store update to finish
            LOGGER.debug("Updating album store pixbufs...")

            store = self.props.filtered_albums_store.get_model()

            def update_pixbuf_at(path: Gtk.TreePath, pixbuf: Pixbuf) -> None:
                store_iter = store.get_iter(path)
                store.set_value(store_iter, AlbumStoreColumns.PIXBUF, pixbuf)

            store_iter = store.get_iter_first()
            while store_iter is not None and not self._abort_pixbufs_update:
                image_path, current_pixbuf = store.get(
                    store_iter,
                    AlbumStoreColumns.IMAGE_FILE_PATH,
                    AlbumStoreColumns.PIXBUF,
                )
                if image_path:
                    if current_pixbuf == self.default_album_image:
                        scaled_pixbuf = scale_album_image(
                            image_path,
                            target_width=ALBUM_IMAGE_SIZE,
                        )
                        path = store.get_path(store_iter)
                        GLib.idle_add(update_pixbuf_at, path, scaled_pixbuf)
                else:
                    uri = store.get_value(store_iter, AlbumStoreColumns.URI)
                    LOGGER.debug(f"No image path for {uri}")
                store_iter = store.iter_next(store_iter)

    @Gtk.Template.Callback()
    def albums_view_item_activated_cb(
        self, icon_view: Gtk.IconView, path: Gtk.TreePath
    ) -> None:
        sensitive = self._model.network_available and self._model.connected
        if not sensitive:
            return

        filtered_store = icon_view.get_model()
        store_iter = filtered_store.get_iter(path)
        uri = filtered_store.get_value(store_iter, AlbumStoreColumns.URI)
        self.emit("album-selected", uri)

import gettext
import logging
from enum import IntEnum
from typing import TYPE_CHECKING, Optional

from gi.repository import Gio, GObject, Gtk

if TYPE_CHECKING:
    from argos.app import Application

LOGGER = logging.getLogger(__name__)

_ = gettext.gettext

SECONDS_PER_DAY = 3600 * 24


class AlbumSortStoreColumns(IntEnum):
    TEXT = 0
    ID = 1


@Gtk.Template(resource_path="/io/github/orontee/Argos/ui/preferences.ui")
class PreferencesWindow(Gtk.Window):
    __gtype_name__ = "PreferencesWindow"

    connection_warning_label: Gtk.Label = Gtk.Template.Child()
    mopidy_base_url_entry: Gtk.Entry = Gtk.Template.Child()
    mopidy_local_switch: Gtk.Switch = Gtk.Template.Child()
    mopidy_local_label: Gtk.Label = Gtk.Template.Child()
    mopidy_bandcamp_switch: Gtk.Switch = Gtk.Template.Child()
    mopidy_bandcamp_label: Gtk.Label = Gtk.Template.Child()
    mopidy_jellyfin_switch: Gtk.Switch = Gtk.Template.Child()
    mopidy_jellyfin_label: Gtk.Label = Gtk.Template.Child()
    mopidy_podcast_switch: Gtk.Switch = Gtk.Template.Child()
    mopidy_podcast_label: Gtk.Label = Gtk.Template.Child()
    album_sort_view: Gtk.TreeView = Gtk.Template.Child()
    history_playlist_check_button: Gtk.CheckButton = Gtk.Template.Child()
    history_playlist_max_length_label: Gtk.Label = Gtk.Template.Child()
    history_playlist_max_length_button: Gtk.SpinButton = Gtk.Template.Child()
    recent_additions_playlist_check_button: Gtk.CheckButton = Gtk.Template.Child()
    recent_additions_playlist_max_age_label: Gtk.Label = Gtk.Template.Child()
    recent_additions_playlist_max_age_button: Gtk.SpinButton = Gtk.Template.Child()

    def __init__(
        self,
        application: "Application",
    ):
        super().__init__(application=application)
        self.set_wmclass("Argos", "preferences")
        self._model = application.model

        store = Gtk.ListStore(str, str)
        self.album_sort_view.set_model(store)
        self.album_sort_view.set_activate_on_single_click(True)
        self.album_sort_view.set_headers_visible(False)
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn(
            cell_renderer=renderer, text=AlbumSortStoreColumns.TEXT
        )
        self.album_sort_view.append_column(column)
        self.album_sort_view.set_enable_search(False)

        self.connection_warning_label.set_visible(
            self._model.network_available and not self._model.connected
        )

        self._settings: Gio.Settings = application.props.settings
        base_url = self._settings.get_string("mopidy-base-url")
        if base_url:
            self.mopidy_base_url_entry.set_text(base_url)

        mopidy_local = self._settings.get_boolean("mopidy-local")
        self.mopidy_local_switch.set_active(mopidy_local)

        mopidy_bandcamp = self._settings.get_boolean("mopidy-bandcamp")
        self.mopidy_bandcamp_switch.set_active(mopidy_bandcamp)

        mopidy_jellyfin = self._settings.get_boolean("mopidy-jellyfin")
        self.mopidy_jellyfin_switch.set_active(mopidy_jellyfin)

        mopidy_podcast = self._settings.get_boolean("mopidy-podcast")
        self.mopidy_podcast_switch.set_active(mopidy_podcast)

        album_sort_id = self._settings.get_string("album-sort")
        to_select: Optional[Gtk.TreeIter] = None
        for name, id in (
            (_("Album name"), "by_album_name"),
            (_("Artist name"), "by_artist_name"),
            (_("Publication date"), "by_publication_date"),
        ):
            store_iter = store.append([name, id])
            if id == album_sort_id:
                to_select = store_iter

        if to_select is not None:
            selection = self.album_sort_view.get_selection()
            selection.select_iter(to_select)

        history_playlist = self._settings.get_boolean("history-playlist")
        self.history_playlist_check_button.set_active(history_playlist)

        history_max_length = self._settings.get_int("history-max-length")
        self.history_playlist_max_length_button.set_value(history_max_length)

        recent_additions_playlist = self._settings.get_boolean(
            "recent-additions-playlist"
        )
        self.recent_additions_playlist_check_button.set_active(
            recent_additions_playlist
        )

        recent_additions_max_age = self._settings.get_int("recent-additions-max-age")
        self.recent_additions_playlist_max_age_button.set_value(
            recent_additions_max_age // SECONDS_PER_DAY
        )

        sensitive = self._model.network_available and self._model.connected
        for widget in (
            self.mopidy_local_switch,
            self.mopidy_local_label,
            self.mopidy_bandcamp_switch,
            self.mopidy_bandcamp_label,
            self.mopidy_jellyfin_switch,
            self.mopidy_jellyfin_label,
            self.mopidy_podcast_switch,
            self.mopidy_podcast_label,
            self.history_playlist_check_button,
            self.history_playlist_max_length_label,
            self.history_playlist_max_length_button,
            self.recent_additions_playlist_check_button,
            self.recent_additions_playlist_max_age_label,
            self.recent_additions_playlist_max_age_button,
        ):
            widget.set_sensitive(sensitive)

        self.history_playlist_max_length_label.set_sensitive(
            sensitive and history_playlist
        )
        self.history_playlist_max_length_button.set_sensitive(
            sensitive and history_playlist
        )
        self.recent_additions_playlist_max_age_label.set_sensitive(
            sensitive and recent_additions_playlist
        )
        self.recent_additions_playlist_max_age_button.set_sensitive(
            sensitive and recent_additions_playlist
        )

        self._model.connect("notify::network-available", self.on_connection_changed)
        self._model.connect("notify::connected", self.on_connection_changed)

        # ⚠️ Don't connect signals to handlers automatically through
        # Gtk.Template since otherwise handlers will be called during
        # initialization from settings

        self.mopidy_base_url_entry.connect(
            "changed", self.on_mopidy_base_url_entry_changed
        )
        self.mopidy_local_switch.connect(
            "notify::active", self.on_mopidy_local_switch_activated
        )
        self.mopidy_bandcamp_switch.connect(
            "notify::active", self.on_mopidy_bandcamp_switch_activated
        )
        self.mopidy_jellyfin_switch.connect(
            "notify::active", self.on_mopidy_jellyfin_switch_activated
        )
        self.mopidy_podcast_switch.connect(
            "notify::active", self.on_mopidy_podcast_switch_activated
        )
        self.album_sort_view.connect(
            "row-activated", self.on_album_sort_view_row_activated
        )
        self.history_playlist_check_button.connect(
            "toggled", self.on_history_playlist_check_button_toggled
        )
        self.history_playlist_max_length_button.connect(
            "value-changed", self.on_history_playlist_max_length_button_value_changed
        )
        self.recent_additions_playlist_check_button.connect(
            "toggled", self.on_recent_additions_playlist_check_button_toggled
        )
        self.recent_additions_playlist_max_age_button.connect(
            "value-changed",
            self.on_recent_additions_playlist_max_age_button_value_changed,
        )

    def on_connection_changed(
        self,
        _1: GObject.GObject,
        _2: GObject.GParamSpec,
    ) -> None:
        self.connection_warning_label.set_visible(
            self._model.network_available and not self._model.connected
        )

        sensitive = self._model.network_available and self._model.connected
        widgets = (
            self.mopidy_local_switch,
            self.mopidy_local_label,
            self.mopidy_bandcamp_switch,
            self.mopidy_bandcamp_label,
            self.mopidy_jellyfin_switch,
            self.mopidy_jellyfin_label,
            self.mopidy_podcast_switch,
            self.mopidy_podcast_label,
            self.history_playlist_check_button,
            self.recent_additions_playlist_check_button,
        )
        for widget in widgets:
            widget.set_sensitive(sensitive)

        history_playlist = self._settings.get_boolean("history-playlist")
        self.history_playlist_max_length_label.set_sensitive(
            sensitive and history_playlist
        )
        self.history_playlist_max_length_button.set_sensitive(
            sensitive and history_playlist
        )

        recent_additions_playlist = self._settings.get_boolean(
            "recent-additions-playlist"
        )
        self.recent_additions_playlist_max_age_label.set_sensitive(
            sensitive and recent_additions_playlist
        )
        self.recent_additions_playlist_max_age_button.set_sensitive(
            sensitive and recent_additions_playlist
        )

    def on_mopidy_base_url_entry_changed(self, entry: Gtk.Entry) -> None:
        base_url = entry.get_text()
        self._settings.set_string("mopidy-base-url", base_url)

    def on_mopidy_local_switch_activated(
        self,
        switch: Gtk.Switch,
        _1: GObject.ParamSpec,
    ) -> None:
        mopidy_local = switch.get_active()
        self._settings.set_boolean("mopidy-local", mopidy_local)

    def on_mopidy_bandcamp_switch_activated(
        self,
        switch: Gtk.Switch,
        _1: GObject.ParamSpec,
    ) -> None:
        mopidy_bandcamp = switch.get_active()
        self._settings.set_boolean("mopidy-bandcamp", mopidy_bandcamp)

    def on_mopidy_jellyfin_switch_activated(
        self,
        switch: Gtk.Switch,
        _1: GObject.ParamSpec,
    ) -> None:
        mopidy_jellyfin = switch.get_active()
        self._settings.set_boolean("mopidy-jellyfin", mopidy_jellyfin)

    def on_mopidy_podcast_switch_activated(
        self,
        switch: Gtk.Switch,
        _1: GObject.ParamSpec,
    ) -> None:
        mopidy_podcast = switch.get_active()
        self._settings.set_boolean("mopidy-podcast", mopidy_podcast)

    def on_album_sort_view_row_activated(
        self, _1: Gtk.TreeView, _2: Gtk.TreePath, _3: Gtk.TreeViewColumn
    ) -> None:
        selection = self.album_sort_view.get_selection()
        store, store_iter = selection.get_selected()
        album_sort_id = store.get_value(store_iter, AlbumSortStoreColumns.ID)
        self._settings.set_string("album-sort", album_sort_id)

    def on_history_playlist_check_button_toggled(self, button: Gtk.CheckButton) -> None:
        history_playlist = button.get_active()
        self._settings.set_boolean("history-playlist", history_playlist)
        self.history_playlist_max_length_label.set_sensitive(history_playlist)
        self.history_playlist_max_length_button.set_sensitive(history_playlist)

    def on_history_playlist_max_length_button_value_changed(
        self, button: Gtk.CheckButton
    ) -> None:
        history_max_length = button.get_value()
        self._settings.set_int("history-max-length", history_max_length)

    def on_recent_additions_playlist_check_button_toggled(
        self, button: Gtk.CheckButton
    ) -> None:
        recent_additions_playlist = button.get_active()
        self._settings.set_boolean(
            "recent-additions-playlist", recent_additions_playlist
        )
        self.recent_additions_playlist_max_age_label.set_sensitive(
            recent_additions_playlist
        )
        self.recent_additions_playlist_max_age_button.set_sensitive(
            recent_additions_playlist
        )

    def on_recent_additions_playlist_max_age_button_value_changed(
        self, button: Gtk.CheckButton
    ) -> None:
        recent_additions_max_age = button.get_value() * SECONDS_PER_DAY
        self._settings.set_int("recent-additions-max-age", recent_additions_max_age)

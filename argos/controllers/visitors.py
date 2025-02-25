import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, cast

LOGGER = logging.getLogger(__name__)


class LengthAcc:
    """Visitor accumulating track length by uri.

    See ``argos.utils.parse_tracks()``.

    """

    def __init__(self):
        self.length: Dict[str, int] = defaultdict(int)

    def __call__(self, uri: str, track: Dict[str, Any]) -> None:
        if self.length[uri] != -1 and "length" in track:
            self.length[uri] += int(track["length"])
        else:
            self.length[uri] = -1


class AlbumMetadataCollector:
    """Visitor identifying album metadatas.

    The identified metadata are: The album artist name, the number of
    tracks, the number of discs and the publication date.

    The album artist name is defined to be the name of the first
    artist in the ``artists`` property of an album; If not defined,
    the names of the artists of the album tracks are collected and the
    most common name is returned.

    See ``argos.utils.parse_tracks()``."""

    def __init__(self):
        self._name: Dict[str, str] = {}
        self._track_names: Dict[str, List[str]] = defaultdict(list)
        self._num_tracks: Dict[str, int] = {}
        self._num_discs: Dict[str, int] = {}
        self._date: Dict[str, str] = {}

    def __call__(self, uri: str, track: Dict[str, Any]) -> None:
        album: Optional[Dict[str, Dict[str, Any]]] = track.get("album")
        if album is None:
            return

        if uri not in self._name:
            album_artists = cast(List[Dict[str, str]], album.get("artists", []))
            if len(album_artists) > 0:
                self._name[uri] = album_artists[0].get("name", "")
            else:
                artists = cast(List[Dict[str, str]], track.get("artists", []))
                self._track_names[uri] += [
                    a.get("name", "") for a in artists if "name" in a
                ]

        if uri not in self._num_tracks:
            num_tracks = cast(int, album.get("num_tracks"))
            if num_tracks is not None:
                self._num_tracks[uri] = num_tracks

        if uri not in self._num_discs:
            num_discs = cast(int, album.get("num_discs"))
            if num_discs is not None:
                self._num_discs[uri] = num_discs

        if uri not in self._date:
            date = cast(str, album.get("date"))
            if date is not None:
                self._date[uri] = date

    def artist_name(self, album_uri: str) -> str:
        if album_uri in self._name:
            return self._name.get(album_uri, "")

        count = Counter(self._track_names[album_uri])
        ranking = count.most_common(1)
        return ranking[0][0] if len(ranking) > 0 else ""

    def num_tracks(self, album_uri: str) -> Optional[int]:
        return self._num_tracks.get(album_uri)

    def num_discs(self, album_uri: str) -> Optional[int]:
        return self._num_discs.get(album_uri)

    def date(self, album_uri: str) -> Optional[str]:
        return self._date.get(album_uri)

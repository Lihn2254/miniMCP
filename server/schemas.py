from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

TRACK_URI_PREFIX = "spotify:track:"
ALBUM_URI_PREFIX = "spotify:album:"

# Reusable constrained types. Validation lives here, in the models, so every
# tool (and the albums file loader) gets the same rules.
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TrackUri = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=rf"^{TRACK_URI_PREFIX}\S+$"),
]
AlbumUri = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=rf"^{ALBUM_URI_PREFIX}\S+$"),
]


class Track(BaseModel):
    name: NonEmptyStr = Field(
        description="Common name of the track for internal use. It is not mandatory to match the official name of the track"
    )
    uri: TrackUri = Field(
        description=f"Spotify's URI for the track. Must always start with '{TRACK_URI_PREFIX}' prefix"
    )


class Album(BaseModel):
    name: NonEmptyStr = Field(description="Name of the album")
    artist: NonEmptyStr = Field(description="Name of the album's artist")
    uri: AlbumUri = Field(
        description=f"Spotify's URI for the album. Must always start with '{ALBUM_URI_PREFIX}' prefix"
    )
    tracks: list[Track] = Field(
        default_factory=list, description="Tracks that belong to the album"
    )

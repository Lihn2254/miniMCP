from pydantic import BaseModel, Field


class Track(BaseModel):
    name: str = Field(
        description="Common name of the track for internal use. It is not mandatory to match the official name of the track"
    )
    uri: str = Field(
        description="Spotify's URI for the track. Must always start with 'spotify:track:' prefix"
    )


class Album(BaseModel):
    name: str
    artist: str
    uri: str
    tracks: list[Track]

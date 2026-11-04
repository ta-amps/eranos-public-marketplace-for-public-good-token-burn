"""Load public-good build tracks (`tracks/<id>/track.json`)."""

from __future__ import annotations

from pathlib import Path

from eranos.jsonfile import load_json
from eranos.schemas import TrackPack

TRACKS_DIR = Path(__file__).resolve().parent.parent / "tracks"


def load_tracks(root: Path | None = None) -> dict[str, TrackPack]:
    folder = root or TRACKS_DIR
    packs: dict[str, TrackPack] = {}
    for path in sorted(folder.glob("*/track.json")):
        pack = TrackPack.model_validate(load_json(path))
        if pack.id != path.parent.name:
            raise ValueError(f"track id {pack.id!r} must match folder name {path.parent.name!r}")
        if pack.id in packs:
            raise ValueError(f"duplicate track id {pack.id!r}")
        packs[pack.id] = pack
    return packs


def get_track(track_id: str, root: Path | None = None) -> TrackPack:
    packs = load_tracks(root)
    if track_id not in packs:
        raise KeyError(f"unknown track {track_id!r}; known: {sorted(packs)}")
    return packs[track_id]

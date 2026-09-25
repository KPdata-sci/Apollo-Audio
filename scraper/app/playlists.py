from .models import PlaylistEntry

# Empty by default — this project ships generic, with no third-party or
# personal SoundCloud accounts baked in. Add your own entries here to
# populate the front end's genre -> playlist dropdowns; no migration or
# restart needed, GET /api/playlists reads this fresh on every request.
#
# Example shape (uncomment and edit, or add your own genres/entries):
#
# CATALOG: dict[str, list[PlaylistEntry]] = {
#     "Some Genre": [
#         PlaylistEntry(name="A playlist I like", url="https://soundcloud.com/<user>/sets/<slug>"),
#     ],
# }
CATALOG: dict[str, list[PlaylistEntry]] = {}


def list_playlists() -> dict[str, list[PlaylistEntry]]:
    return CATALOG

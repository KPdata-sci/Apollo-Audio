from .models import PlaylistEntry

# Curated genre -> playlist catalog shown in the front end's one-click
# "pick a genre, pick a playlist" picker. GET /api/playlists reads this fresh
# on every request — no migration or restart needed after editing it.
#
# Populated and verified 2026-09-25. Every entry below is a PUBLIC
# soundcloud.com playlist (or, where noted, a profile) that was scraped
# end-to-end with this app's own scraper (app.scraping.fetch_html +
# parse_html, i.e. exactly what POST /scrape runs) and returned >= 10 tracks
# whose genres fit the heading it's filed under. Most sets come from
# SoundCloud's own editorial curator accounts (soundcloud-uk, -hustle,
# -circuits, -the-peak, -shine, -scenes, -amped, -auras, -vibrations,
# -la-onda, -vs, -stories, trending-music-us), which are maintained by
# SoundCloud itself and so are the least likely to vanish or go private.
#
# Things that can still change underneath this list:
#   * Editorial/chart sets are re-curated over time; entries noted as a
#     "weekly chart" swap their whole track list every week.
#   * Track counts drift as uploaders delete or privatize tracks.
#   * Profile entries only yield what the profile page lazy-loads while
#     scrolling, and SoundCloud exposes no per-track genre there.
#
# Re-verifying: scrape each URL with the real scraper and check the track
# count (>= 10) and genres. With the built API image, from the repo root:
#
#   docker run --rm -e PYTHONPATH=/app -v "$PWD/scraper:/app" -w /app \
#     apollo-api:latest python -c "
#   import asyncio
#   from app.playlists import CATALOG
#   from app.scraping import fetch_html, parse_html
#   async def main():
#       for genre, entries in CATALOG.items():
#           for e in entries:
#               html, hyd = await fetch_html(e.url)
#               n = len(parse_html(html, hyd, source_url=e.url))
#               print('OK ' if n >= 10 else 'BAD', n, genre, '|', e.name, e.url, flush=True)
#               await asyncio.sleep(4)  # be courteous: sequential, paced
#   asyncio.run(main())"
#
# (~20-40s per page.) Static integrity checks (https, soundcloud.com host, no
# duplicates, valid PlaylistEntry) live in tests/test_playlists.py.

_WEEKLY_CHART = "SoundCloud's weekly trending chart for this genre — the track list changes every week."


def _p(name: str, url: str, note: str | None = None) -> PlaylistEntry:
    return PlaylistEntry(name=name, url=url, note=note)


CATALOG: dict[str, list[PlaylistEntry]] = {
    "Drum & Bass": [
        _p("Fresh Drum & Bass: Bassbin", "https://soundcloud.com/soundcloud-uk/sets/bassbin-fresh-drum-and-bass"),
        _p("Essential Drum & Bass: Sub-Bass", "https://soundcloud.com/soundcloud-the-peak/sets/sub-bass-essential-drum-bass"),
        _p("Jump-Up D&B", "https://soundcloud.com/soundcloud-stories/sets/jump-up-dnb"),
        _p("Jungle & D&B's New Era", "https://soundcloud.com/soundcloud-stories/sets/jungle"),
        _p(
            "DnB Allstars",
            "https://soundcloud.com/dnballstars",
            note="A profile, not a playlist: scrapes the channel's latest uploads (no per-track genre tags); "
            "how many load depends on how far the page scrolls.",
        ),
    ],
    "House": [
        _p("Deep House: Deep", "https://soundcloud.com/soundcloud-circuits/sets/deep-deep-house"),
        _p("Trending House", "https://soundcloud.com/trending-music-us/sets/house", note=_WEEKLY_CHART),
        _p("Piano House", "https://soundcloud.com/soundcloud-stories/sets/piano-house"),
        _p("Disco & Nu Disco: Glitter", "https://soundcloud.com/soundcloud-circuits/sets/glitter-disco-nu-disco"),
        _p("Minimal Tech House", "https://soundcloud.com/soundcloud-stories/sets/minimal-tech-house"),
        _p("Bass House: Basslines", "https://soundcloud.com/soundcloud-the-peak/sets/basslines-bass-house"),
    ],
    "Techno": [
        _p("Techno for Cardio: Tempo", "https://soundcloud.com/soundcloud-circuits/sets/tempo-techno-for-cardio"),
        _p("Trending Techno", "https://soundcloud.com/trending-music-us/sets/techno", note=_WEEKLY_CHART),
        _p("Schranz & Hard Techno", "https://soundcloud.com/soundcloud-stories/sets/schranz"),
        _p("Tekno & Beyond", "https://soundcloud.com/sc-scenes-playlists/sets/tekno-and-beyond"),
    ],
    "Hip-Hop & Rap": [
        _p("Best Rap Right Now: Drippin'", "https://soundcloud.com/soundcloud-hustle/sets/drippin-best-rap-right-now"),
        _p("Tomorrow's Rap Hits: The Lookout", "https://soundcloud.com/soundcloud-hustle/sets/the-lookout-tomorrows-rap-hits"),
        _p("Best Female Rappers Now: Femcees", "https://soundcloud.com/soundcloud-hustle/sets/femcees-best-female-rappers-right-now"),
        _p("Best UK Rap: Bars", "https://soundcloud.com/soundcloud-uk/sets/bars-best-uk-rap"),
        _p("Headphone Hip-Hop: Boom Bap", "https://soundcloud.com/soundcloud-vs/sets/boom-bap-headphone-hip-hop"),
        _p("Hip-Hop Essentials", "https://soundcloud.com/soundcloud-stories/sets/hip-hop-essentials"),
    ],
    "R&B & Soul": [
        _p("Best New R&B: Vibes", "https://soundcloud.com/soundcloud-auras/sets/vibes-best-new-r-b"),
        _p("Warm Soothing Soul: Warm", "https://soundcloud.com/soundcloud-auras/sets/warm-soothing-soul"),
        _p("Best UK R&B: Jamz", "https://soundcloud.com/soundcloud-uk/sets/jamz-best-uk-r-b"),
        _p("New Era R&B", "https://soundcloud.com/soundcloud-stories/sets/new-era-r-b"),
        _p("Buzzing R&B", "https://soundcloud.com/buzzing-playlists/sets/buzzing-r-b"),
        _p("Trending Soul", "https://soundcloud.com/trending-music-us/sets/soul", note=_WEEKLY_CHART),
    ],
    "Lo-fi & Chill": [
        _p("Lofi Girl: Beats to Relax/Study To", "https://soundcloud.com/lofi_girl/sets/lofi-girl-beats-to-relax-study"),
        _p("Chillhop: Lofi Hip Hop", "https://soundcloud.com/chillhopdotcom/sets/lofihiphop"),
        _p("Chillhop: Chill Study Beats", "https://soundcloud.com/chillhopdotcom/sets/chill-study-beats-2025"),
        _p("Lo-Fi Beats: Focus", "https://soundcloud.com/soundcloud-vs/sets/focus-lo-fi-beats"),
        _p("Work From Home Chill: WFH", "https://soundcloud.com/soundcloud-circuits/sets/wfh-work-from-home-chill"),
    ],
    "Ambient": [
        _p("New Era Ambient", "https://soundcloud.com/soundcloud-stories/sets/new-era-ambient"),
        _p("Airy Ambient for Sleep: Night Sounds", "https://soundcloud.com/soundcloud-circuits/sets/night-sounds-airy-ambient-for-sleep"),
        _p("Anti-Anxiety Ambient: Calm", "https://soundcloud.com/soundcloud-circuits/sets/calm-anti-anxiety-ambient"),
        _p("Ambient for Yoga: Downward", "https://soundcloud.com/soundcloud-circuits/sets/downward-ambient-for-yoga"),
        _p("Dark Ambient: Unchill", "https://soundcloud.com/soundcloud-circuits/sets/unchill-dark-ambient"),
    ],
    "Pop": [
        _p("Tomorrow's Hits Today: Fizz", "https://soundcloud.com/soundcloud-shine/sets/fizz-tomorrows-hits-today"),
        _p("Fresh Pop Picks: Ear Candy", "https://soundcloud.com/soundcloud-shine/sets/ear-candy-fresh-pop-picks"),
        _p("Pop Hits: Dialed In", "https://soundcloud.com/soundcloud-shine/sets/dialed-in-pop-party-hits"),
        _p("Hot Pop UK: Sizzle", "https://soundcloud.com/soundcloud-uk/sets/sizzle-hot-uk-pop"),
        _p("Chill Pop: Easy", "https://soundcloud.com/soundcloud-shine/sets/easy-chill-pop"),
        _p("K-Pop and More", "https://soundcloud.com/soundcloud-shine/sets/k-pop-and-more"),
    ],
    "Indie & Alternative": [
        _p("Indie New Arrivals: Stitches", "https://soundcloud.com/soundcloud-scenes/sets/stitches-indie-new-arrivals"),
        _p("Emerging Indie: Dreams", "https://soundcloud.com/soundcloud-scenes/sets/dreams-emerging-indie"),
        _p("Indie Rock: Riffs", "https://soundcloud.com/soundcloud-scenes/sets/riffs-indie-rock"),
        _p("Fresh UK Indie: Texture", "https://soundcloud.com/soundcloud-uk/sets/texture-fresh-uk-indie"),
        _p("Chill Bedroom Pop: Cozy", "https://soundcloud.com/soundcloud-scenes/sets/cozy-chill-bedroom-pop"),
    ],
    "Rock & Metal": [
        _p("New Rock Now: The Dive", "https://soundcloud.com/soundcloud-amped/sets/the-dive-new-rock-now"),
        _p("Road Trip Rock: Dashboard", "https://soundcloud.com/soundcloud-amped/sets/dashboard-road-trip-rock"),
        _p("Punk & Hardcore: Rage", "https://soundcloud.com/soundcloud-amped/sets/rage-punk-and-hardcore"),
        _p("Essential Metal: Shred", "https://soundcloud.com/soundcloud-amped/sets/shred-essential-metal"),
        _p("Trending Rock, Metal & Punk", "https://soundcloud.com/trending-music-us/sets/rock-metal-punk", note=_WEEKLY_CHART),
    ],
    "Jazz": [
        _p("A Jazz Thing", "https://soundcloud.com/soundcloud-stories/sets/a-jazz-thing"),
        _p("Indie Jazz: Blow Up", "https://soundcloud.com/soundcloud-scenes/sets/blow-up-indie-jazz"),
        _p("Jazz Rap Journeys: Excursions", "https://soundcloud.com/soundcloud-vs/sets/excursions-jazz-rap-journeys"),
        _p("Lofi Girl: Jazz Lofi", "https://soundcloud.com/lofi_girl/sets/jazz-lofi"),
        _p("Trending Jazz", "https://soundcloud.com/trending-music-us/sets/jazz", note=_WEEKLY_CHART),
    ],
    "Classical & Piano": [
        _p("50 Classical Music Hits (Solo Piano)", "https://soundcloud.com/solopianoclassics/sets/50-classical-music-hits-the"),
        _p("Chopin: The Essential Collection", "https://soundcloud.com/chopin-official/sets/chopin-the-essential"),
        _p("Lofi Girl: Peaceful Piano", "https://soundcloud.com/lofi_girl/sets/peaceful-piano-music-to-focus"),
        _p("Hip-Hop & R&B Piano/Violin Covers", "https://soundcloud.com/marques-benderbierria/sets/copy-of-hip-hop-and-r-b-piano"),
    ],
    "Afrobeats & Amapiano": [
        _p("New Afrobeats: Afro Bops", "https://soundcloud.com/soundcloud-vibrations/sets/afro-bops-new-afrobeats"),
        _p("New African Pop: Giants", "https://soundcloud.com/soundcloud-vibrations/sets/giants-new-african-pop"),
        _p("Afro Summer Jams", "https://soundcloud.com/soundcloud-stories/sets/afro-summer-jams"),
        _p("UK Afrobeats & Fusion: Afroswing", "https://soundcloud.com/soundcloud-uk/sets/uk-afrobeats-fusion-afroswing"),
        _p("Dark Amapiano: Spookasem", "https://soundcloud.com/soundcloud-vibrations/sets/spookasem-dark-amapiano"),
    ],
    "Reggae & Dancehall": [
        _p("Dancehall Party: Forwards", "https://soundcloud.com/soundcloud-vibrations/sets/forwards-dancehall-party"),
        _p("Women of Dancehall: Dancehall Queens", "https://soundcloud.com/soundcloud-vibrations/sets/queens-women-of-dancehall"),
        _p("Women of Reggae: Empress", "https://soundcloud.com/soundcloud-vibrations/sets/empress-women-of-reggae"),
        _p("Heady Reggae & Dub: Medicinal Reverb", "https://soundcloud.com/soundcloud-vibrations/sets/medicinal-reverb-heady-reggae-dub"),
    ],
    "Dubstep & Bass": [
        _p("New Bass Heat: Bass Flex", "https://soundcloud.com/soundcloud-the-peak/sets/bass-flex-new-dubstep-heat"),
        _p("New Era Dubstep", "https://soundcloud.com/soundcloud-stories/sets/new-era-dubstep"),
        _p("New Era Bass", "https://soundcloud.com/soundcloud-stories/sets/new-era-bass"),
        _p("Dark Electro & Heavy Bass: Midnight", "https://soundcloud.com/soundcloud-the-peak/sets/midnight-dark-electro-heavy-bass"),
    ],
    "UK Garage & Bassline": [
        _p("UK Garage", "https://soundcloud.com/soundcloud-stories/sets/uk-garage"),
        _p("UK Bassline, Grime & Garage: Step", "https://soundcloud.com/soundcloud-uk/sets/uk-bassline-grime-garage-step"),
        _p("New UK Garage (uBazz)", "https://soundcloud.com/ubazz/sets/uk-garage-soundcloud-playlist"),
    ],
    "Latin": [
        _p("Reggaeton Bangers: Baile", "https://soundcloud.com/soundcloud-la-onda/sets/baile-reggaeton-bangers"),
        _p("Next Wave Reggaeton", "https://soundcloud.com/soundcloud-stories/sets/reggaeton"),
        _p("Fresh Latin Music: Fresco", "https://soundcloud.com/soundcloud-la-onda/sets/fresco-emerging-latin-music"),
        _p("Top-Down Latin Trap: Fuego", "https://soundcloud.com/soundcloud-la-onda/sets/fuego-top-down-latin-trap"),
        _p("Nueva Música Mexicana: ¡Arriba!", "https://soundcloud.com/soundcloud-la-onda/sets/arriba-regional-mexican-music"),
    ],
    "Electronic & EDM": [
        _p("Best Electronic Now: Tunnel", "https://soundcloud.com/soundcloud-circuits/sets/tunnel-best-electronic-now"),
        _p("New EDM Hits: On The Up", "https://soundcloud.com/soundcloud-the-peak/sets/on-the-up-new-edm-hits"),
        _p("EDM Next: Level Up", "https://soundcloud.com/soundcloud-the-peak/sets/level-up-edm-next"),
        _p("New Era Trance", "https://soundcloud.com/soundcloud-stories/sets/new-era-trance"),
        _p("Hard Dance & Hardstyle: Hard", "https://soundcloud.com/soundcloud-the-peak/sets/hard-dance-and-hardstyle"),
        _p("Chill Electronics: Drifting", "https://soundcloud.com/soundcloud-circuits/sets/drifting-chill-electronics"),
    ],
    "Country & Folk": [
        _p("Best Country Now: Backroads", "https://soundcloud.com/soundcloud-shine/sets/backroads-best-country-now"),
        _p("Emerging Country: Porch Swing", "https://soundcloud.com/soundcloud-scenes/sets/porch-swing-emerging-country"),
        _p("New Era Folk", "https://soundcloud.com/soundcloud-stories/sets/new-era-folk"),
        _p("Trending Folk", "https://soundcloud.com/trending-music-us/sets/folk", note=_WEEKLY_CHART),
    ],
}


def list_playlists() -> dict[str, list[PlaylistEntry]]:
    return CATALOG

# API Coverage — osxphotos 0.77.x (Photos library read and export)

> Full coverage by default. Opt-outs are explicit, reasoned decisions.

Phase 4 adopts osxphotos as the one Photos surface (D-01). The library is read at rest under
Full Disk Access; nothing in the adapter drives Photos.app, PhotoKit or AppleScript. The rows
cover the osxphotos capability surface a caller could expect from a Photos adapter. Device
tests import throwaway photos through Photos' own AppleScript `import` verb; that is test
scaffolding, not an adapter capability.

| capability | decision | reason |
|---|---|---|
| library-open (`PhotosDB()` on the system library, at rest) | INTEGRATE | |
| albums-list (`album_info`: uuid, title, folder path, photo count) | INTEGRATE | |
| photo-search (`photos()` + one folded predicate over eight text fields) | INTEGRATE | |
| photo-by-id (`get_photo(uuid)`, old AppleScript id form reduced to the uuid) | INTEGRATE | |
| photo-metadata-dates (taken, added, modified) | INTEGRATE | |
| photo-metadata-location (latitude, longitude, place name) | INTEGRATE | |
| photo-metadata-persons (person names) | INTEGRATE | |
| photo-metadata-exif-subset (camera, lens, focal, aperture, shutter, ISO, size) | INTEGRATE | |
| photo-kind-flags (video, Live Photo, edited, in trash, file on disk) | INTEGRATE | exposed in photo_info: video and Live Photo (kind), edited; used internally only: in trash (the id is refused), file on disk (the export absent check) |
| export-edited-still (`PhotoInfo.export`, no overwrite, no increment) | INTEGRATE | |
| album-create, folder-create, album-delete | OPT-OUT | explicitly out of scope: no Photos write other than the export in this phase (CONTEXT) |
| photo-import | OPT-OUT | explicitly out of scope (CONTEXT); device tests import through Photos AppleScript as test scaffolding only |
| photo-delete | OPT-OUT | explicitly out of scope; Photos AppleScript cannot delete media items, and no requirement asks for it |
| keyword-title-description-person-edits (photoscript writes) | OPT-OUT | explicitly out of scope: no keyword or person edit (CONTEXT) |
| shared-albums (`album_info_shared`) | OPT-OUT | explicitly out of scope: osxphotos #2003 on macOS 26 |
| export-original-of-an-edited-photo, RAW, video, Live Photo motion | OPT-OUT | explicitly out of scope (D-08, Deferred Ideas) |
| export-icloud-download (download-on-export options) | OPT-OUT | explicitly out of scope: no silent network work (D-09) |
| thumbnails, previews, inline image bytes | OPT-OUT | explicitly out of scope (D-05; REQUIREMENTS: no inline binary) |
| library-wide dump (all photos as payload, JSON or sidecar export of the library) | OPT-OUT | explicitly out of scope (D-05: no library-wide dump) |
| export-sidecars (XMP, JSON, exiftool) and format conversion | OPT-OUT | not needed: the export writes the still as Photos shows it |
| folders-list as its own tool (`folder_info`) | OPT-OUT | not needed: the folder path rides on each album Pointer's `folder` |
| persons-list as its own tool (`person_info`) | OPT-OUT | not needed yet: person names ride on `photo_info` |
| face regions, AI scores, captions, detected text | OPT-OUT | not needed; more personal data than the bounded read requires |
| moments, memories, burst, hidden and favorite filters | OPT-OUT | not needed yet — no requirement in this milestone |
| adjustment details (`adjustmentinfo`) | OPT-OUT | not needed: `edited` true or false is what the export decision uses |
| non-system libraries (`PhotosDB(dbfile=…)`) | OPT-OUT | not needed: the daemon serves the owner's system library |
| the osxphotos CLI | OPT-OUT | not integrated; the owner uses it by hand (CONTEXT specifics), and the build drops its thin CLI dylibs |

Field detail for the shortened rows: the search predicate covers original filename,
filename, title, description, keywords, place name, person names and labels (D-04); the EXIF
subset is camera make and model, lens, focal length, aperture, shutter speed, ISO and pixel
size (D-05); the export writes the edited still when the photo has adjustments, the original
when it has none (D-08).

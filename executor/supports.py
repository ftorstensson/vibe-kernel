"""
Grounding supports: which sentence of the model's answer came from which cited pages.

Gemini's grounding metadata (groundingMetadata) lists the pages the search used
(`groundingChunks`) and, for each supported piece of the answer, a `groundingSupports`
entry: the piece's text, where it is, and the indices of the chunks behind it.
litellm already hands the executor the raw metadata on the response
(`vertex_ai_grounding_metadata`, one dict per candidate); this module reads the first
candidate's. No network, no model call, no state.

Two output fields come from here (docs/m0 C1 section 4.1): `grounding_chunks`, every chunk the
provider returned in the provider's order, and `grounding_supports`, whose `source_indices` index
into `grounding_chunks`. (litellm's own `message.annotations`, behind `grounding_sources`, keeps
only the FIRST chunk of each support, so it cannot carry the sentence-to-page links.)

Offsets (docs/m0 C1 section 4.1):
  - The provider measures `startIndex` / `endIndex` in UTF-8 BYTES of the text part, not in
    characters (verified 2026-10-29 on real non-ASCII output: the segment text matched as byte
    offsets 8 of 8 and as character offsets 0 of 8). They are converted to Python code-point
    offsets into `output.text`, so `output.text[start:end]` is the segment.
  - Never wrong offsets: after conversion the slice must equal the segment text; if it does not,
    or the offsets are unusable (not integers, not on a character boundary, out of range, end
    missing), `start` and `end` are null and the segment is still kept.
  - The provider omits `startIndex` when it is 0 (seen in a real response): missing start = 0.
"""
from executor import links


def raw_metadata(response):
    """The first candidate's raw groundingMetadata dict, or None."""
    candidates = getattr(response, "vertex_ai_grounding_metadata", None)
    if candidates is None:
        hidden = getattr(response, "_hidden_params", None)
        candidates = hidden.get("vertex_ai_grounding_metadata") if isinstance(hidden, dict) else None
    if isinstance(candidates, dict):
        return candidates
    if isinstance(candidates, (list, tuple)) and candidates and isinstance(candidates[0], dict):
        return candidates[0]
    return None


def _is_index(value):
    return type(value) is int and value >= 0


def _byte_to_codepoint_map(text):
    """{byte offset: code-point offset} for every offset that falls on a character boundary."""
    boundaries = {0: 0}
    position = 0
    for i, ch in enumerate(text):
        position += len(ch.encode("utf-8"))
        boundaries[position] = i + 1
    return boundaries


def convert_offsets(text, start_byte, end_byte, segment_text, boundaries=None):
    """(start, end) as code-point offsets into `text` when they are provably right, else
    (None, None). `start_byte` None means the provider omitted it (= 0)."""
    if start_byte is None:
        start_byte = 0
    if not _is_index(start_byte) or not _is_index(end_byte) or end_byte < start_byte:
        return None, None
    try:
        boundaries = boundaries if boundaries is not None else _byte_to_codepoint_map(text)
    except UnicodeEncodeError:        # a lone surrogate in the text cannot be measured in UTF-8
        return None, None
    start, end = boundaries.get(start_byte), boundaries.get(end_byte)
    if start is None or end is None:  # beyond the text, or inside a multi-byte character
        return None, None
    if text[start:end] != segment_text:
        return None, None
    return start, end


def extract_chunks(metadata):
    """Every chunk the provider returned, in the provider's order, as the same
    {title, url, redirect_url, resolved} a grounding source has (nothing resolved yet), so
    that an index into the provider's chunk list is an index into this list. A chunk that is
    not a web page (or is malformed) keeps its place as {"title": "Source", "url": null,
    "redirect_url": null, "resolved": false}. Never raises; [] when there is nothing."""
    chunks = metadata.get("groundingChunks") if isinstance(metadata, dict) else None
    if not isinstance(chunks, list):
        return []
    result = []
    for chunk in chunks:
        web = chunk.get("web") if isinstance(chunk, dict) else None
        web = web if isinstance(web, dict) else {}
        uri = web.get("uri")
        title = web.get("title")
        result.append(links.source(title if isinstance(title, str) and title else "Source", uri if isinstance(uri, str) and uri else None))
    return result


def extract_supports(text, metadata):
    """The supports in the order the provider gives them, as
    [{"text", "start", "end", "source_indices"}] where start/end are code-point offsets into
    `text` (or null, see above) and source_indices are the provider's own chunk indices, i.e.
    indices into `extract_chunks(metadata)`: integers within the provider's chunk list,
    duplicates within a support removed (first occurrence kept), the provider's order kept.
    Never raises; [] when there is nothing."""
    if not isinstance(metadata, dict):
        return []
    supports = metadata.get("groundingSupports")
    if not isinstance(supports, list):
        return []
    chunks = metadata.get("groundingChunks")
    n_chunks = len(chunks) if isinstance(chunks, list) else 0
    try:
        boundaries = _byte_to_codepoint_map(text)
    except UnicodeEncodeError:
        boundaries = {}
    result = []
    for support in supports:
        if not isinstance(support, dict):
            continue
        segment = support.get("segment")
        segment = segment if isinstance(segment, dict) else {}
        segment_text = segment.get("text")
        segment_text = segment_text if isinstance(segment_text, str) else ""
        start, end = convert_offsets(text, segment.get("startIndex"), segment.get("endIndex"), segment_text, boundaries or None) if boundaries else (None, None)
        indices, seen = [], set()
        raw_indices = support.get("groundingChunkIndices")
        for index in (raw_indices if isinstance(raw_indices, list) else []):
            if _is_index(index) and index < n_chunks and index not in seen:
                seen.add(index)
                indices.append(index)
        result.append({"text": segment_text, "start": start, "end": end, "source_indices": indices})
    return result


def referenced_indices(grounding_supports):
    """The chunk indices some support points at, ascending and without duplicates."""
    return sorted({i for s in grounding_supports for i in s["source_indices"]})

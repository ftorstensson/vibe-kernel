import os

from core.capture import utf16_len


class AssembledPrompt(str):
    """The exact text PromptBuilder.assemble() has always returned, plus the
    pieces it was built from, so a capture can label block content without
    parsing the text back apart. Behaves as a plain str everywhere; segments
    are computed lazily (nothing runs unless a capture asks). See
    core/capture.py for the segment rules."""

    def __new__(cls, text, parts):
        obj = super().__new__(cls, text)
        obj._parts = parts
        return obj

    def __getnewargs__(self):
        return (str(self), self._parts)

    @property
    def segments(self):
        if "".join(piece for _, _, piece in self._parts) != str(self):
            return []
        segments = []
        offset = 0
        for layer, label, piece in self._parts:
            length = utf16_len(piece)
            if layer and length:
                segments.append({"layer": layer, "label": label, "start": offset, "end": offset + length, "bytes": len(piece.encode("utf-8"))})
            offset += length
        return segments


class PromptBuilder:
    @staticmethod
    def assemble(mandate: str, lens: str = "", truth: str = "", signal: str = ""):
        """
        Assembles the Functional Blocks of the AI Brain.
        Industrial Layering: Mandate (Law), Lens (Way of Thinking), Truth (Data),
        Signal (this turn's situational input from upstream functions).

        signal is the one slot where an upstream function's own output (e.g.
        Gatekeeper's whisper, Chat Manager's whisper) may enter a downstream
        call -- never into mandate/lens/truth. It is optional and empty by
        default; when empty, no SIGNAL block is rendered at all, so every
        existing three-block caller produces byte-identical output.
        """
        signal_block = (
            f"\n### BLOCK 4: THE SIGNAL (SITUATIONAL -- THIS TURN ONLY)\n{signal}\n"
            if signal else ""
        )
        text = f"""
### BLOCK 1: THE MANDATE (UNBREAKABLE LAW)
{mandate}

### BLOCK 2: THE LENS (STRATEGIC PERSPECTIVE)
{lens}

### BLOCK 3: THE TRUTH (PROJECT KNOWLEDGE & DATA)
{truth}
{signal_block}
[EXECUTION_START: Apply the LENS to the TRUTH while obeying the MANDATE.]
"""
        parts = [
            (None, None, "\n### BLOCK 1: THE MANDATE (UNBREAKABLE LAW)\n"),
            ("mandate", "THE MANDATE", f"{mandate}"),
            (None, None, "\n\n### BLOCK 2: THE LENS (STRATEGIC PERSPECTIVE)\n"),
            ("lens", "THE LENS", f"{lens}"),
            (None, None, "\n\n### BLOCK 3: THE TRUTH (PROJECT KNOWLEDGE & DATA)\n"),
            ("truth", "THE TRUTH", f"{truth}"),
            (None, None, "\n"),
        ]
        if signal:
            parts += [
                (None, None, "\n### BLOCK 4: THE SIGNAL (SITUATIONAL -- THIS TURN ONLY)\n"),
                ("signal", "THE SIGNAL", f"{signal}"),
                (None, None, "\n"),
            ]
        parts.append((None, None, "\n[EXECUTION_START: Apply the LENS to the TRUTH while obeying the MANDATE.]\n"))
        return AssembledPrompt(text, parts)

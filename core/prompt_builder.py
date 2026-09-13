import os

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
        return f"""
### BLOCK 1: THE MANDATE (UNBREAKABLE LAW)
{mandate}

### BLOCK 2: THE LENS (STRATEGIC PERSPECTIVE)
{lens}

### BLOCK 3: THE TRUTH (PROJECT KNOWLEDGE & DATA)
{truth}
{signal_block}
[EXECUTION_START: Apply the LENS to the TRUTH while obeying the MANDATE.]
"""

import os

class PromptBuilder:
    @staticmethod
    def assemble(mandate: str, lens: str = "", truth: str = ""):
        """
        Assembles the 3 Functional Blocks of the AI Brain.
        Industrial Layering: Mandate (Law), Lens (Way of Thinking), Truth (Data).
        """
        return f"""
### BLOCK 1: THE MANDATE (UNBREAKABLE LAW)
{mandate}

### BLOCK 2: THE LENS (STRATEGIC PERSPECTIVE)
{lens}

### BLOCK 3: THE TRUTH (PROJECT KNOWLEDGE & DATA)
{truth}

[EXECUTION_START: Apply the LENS to the TRUTH while obeying the MANDATE.]
"""

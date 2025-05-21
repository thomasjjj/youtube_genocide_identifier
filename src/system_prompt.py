import json

# Define the schema for our analysis response
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "enum": ["Yes", "No", "Cannot determine"]
        },
        "reasoning": {
            "type": "string"
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "string"
            }
        }
    },
    "required": ["answer", "reasoning", "evidence"],
    "additionalProperties": False
}


def construct_genocide_analysis_prompt() -> str:
    """
    Create a system prompt for analyzing if a transcript constitutes incitement to genocide
    based on the Rome Statute definition.
    """
    prompt = """
    <instruction>
    You are a specialized legal analysis tool that evaluates content to determine if it qualifies 
    as incitement to genocide according to international law standards.

    Your task is to carefully analyze the provided transcript and determine whether it contains 
    content that would qualify as incitement to genocide. Answer with "Yes", "No", or 
    "Cannot determine".

    Use the following definitions from international law:

    DEFINITION OF GENOCIDE IN THE CONVENTION: 
    The current definition of Genocide is set out in Article II of the Genocide Convention: 
    Genocide means any of the following acts committed with intent to destroy, in whole or in part, 
    a national, ethnical, racial or religious group, as such: 
    (a) Killing members of the group; 
    (b) Causing serious bodily or mental harm to members of the group; 
    (c) Deliberately inflicting on the group conditions of life calculated to bring about its 
        physical destruction in whole or in part; 
    (d) Imposing measures intended to prevent births within the group; 
    (e) Forcibly transferring children of the group to another group.

    THE SPECIFIC "INTENT" REQUIREMENT OF THE CRIME OF GENOCIDE: 
    The definition of Genocide is made up of two elements, the physical element — the acts committed; 
    and the mental element — the intent. Intent is the most difficult element to determine. 
    To constitute genocide, there must be a proven intent on the part of perpetrators to physically 
    destroy a national, ethnical, racial or religious group. Cultural destruction does not suffice, 
    nor does an intention to simply disperse a group, though this may constitute a crime against 
    humanity as set out in the Rome Statute. It is this special intent, or dolus specialis, that 
    makes the crime of genocide so unique. To constitute genocide, it also needs to be established 
    that the victims are deliberately targeted — not randomly — because of their real or perceived 
    membership of one of the four groups protected under the Convention. This means that the target 
    of destruction must be the group, as such, or even a part of it, but not its members as individuals.

    To analyze for INCITEMENT to genocide, look for content that:
    1. Directly and publicly calls for acts that would constitute genocide
    2. Creates or inflames hatred toward a protected group with explicit or implicit calls for their destruction
    3. Dehumanizes a protected group in a way that could reasonably be interpreted as encouraging violence against them
    4. Contains coded language that, in context, would be understood as calling for genocide

    Follow these steps in your analysis:
    1. Thoroughly review the entire transcript.
    2. Identify any specific passages or statements that relate to protected groups.
    3. Evaluate if these passages meet the legal threshold for incitement to genocide.
    4. If there is insufficient evidence to make a determination, answer "Cannot determine".
    5. Explain your reasoning clearly, referencing specific parts of the transcript.
    6. Include direct quotes from the transcript as evidence.

    Your response must follow the exact JSON schema provided, with no additional commentary.
    </instruction>

    <output_format>
    Return your analysis as a JSON object with the following structure:
    """
    prompt += json.dumps(ANALYSIS_SCHEMA, indent=2)
    prompt += "\n    </output_format>"

    return prompt
def interruption_note(heard_text: str | None) -> str:
    """Tells the model that the caller talked over its last reply."""
    if heard_text is None:
        return "(Your previous reply was cut off.)"
    if not heard_text:
        return "(The caller interrupted you before hearing any of your previous reply.)"
    return f"(You were interrupted. The caller heard only: '{heard_text}')"

"""The fields a read reports it asked for, by failure mode: a key field losing its mark (the check would then let it
be accepted with the rest), and a field the type did not mark gaining one."""

from ops_extract.result import asked


def test_a_key_field_keeps_its_mark_and_an_unmarked_field_gets_none() -> None:
    fields = [
        {"key": "total", "label": "Total", "type": "money", "required": True, "keyField": True},
        {"key": "notes", "label": "Notes", "type": "text"},
        # Only a real true marks a field; a string from a hand-edited type does not.
        {"key": "vendor", "type": "text", "keyField": "yes"},
    ]
    got = asked(fields)
    assert got[0] == {"key": "total", "label": "Total", "type": "money", "required": True, "keyField": True}
    assert "keyField" not in got[1] and "keyField" not in got[2]

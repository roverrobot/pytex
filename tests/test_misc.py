def test_interaction_mode_commands_are_distinct_from_relax(collector):
    collector.parse("\\ifx\\scrollmode\\relax a\\else b\\fi")
    assert collector.getString() == "b"


def test_interaction_mode_commands_update_global_mode(parser):
    parser.parse("\\batchmode")
    assert parser.globals["interactionmode"] == 0
    parser.parse("\\nonstopmode")
    assert parser.globals["interactionmode"] == 1
    parser.parse("\\scrollmode")
    assert parser.globals["interactionmode"] == 2
    parser.parse("\\errorstopmode")
    assert parser.globals["interactionmode"] == 3

from app.dsh_runtime.plugin_management.compatibility import classify_conversation_tools


def test_bundle_without_conversation_tools_is_explicitly_unsupported():
    assert classify_conversation_tools(set(), set()) == ("unsupported", "no_global_tool_detected")


def test_all_tools_must_be_exposed_to_the_session():
    assert classify_conversation_tools({"a", "b"}, {"a"}) == ("not_exposed", "tools_missing_from_session")
    assert classify_conversation_tools({"a", "b"}, {"a", "b"}) == ("session_exposed", "invocation_not_verified")

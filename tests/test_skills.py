from app.agent.skills import get_skill, render_skills, select_auto_skill


def test_get_skill():
    assert get_skill("research") is not None
    assert get_skill("RESEARCH") is not None
    assert get_skill("missing") is None


def test_render_skills_mentions_usage():
    rendered = render_skills()

    assert "research" in rendered
    assert "/skill <name>" in rendered


def test_select_auto_skill():
    assert select_auto_skill("what did I work on emotions?") == "research"
    assert select_auto_skill("brainstorm ideas for this project") == "brainstorm"
    assert select_auto_skill("give me next steps") == "planner"
    assert select_auto_skill("hello") is None

from app.agent.skills import build_skill_router_prompt, get_skill, parse_skill_router_output, render_skills, select_auto_skill


def test_get_skill():
    assert get_skill("research") is not None
    assert get_skill("RESEARCH") is not None
    assert get_skill("missing") is None


def test_skill_prompt_includes_contract():
    skill = get_skill("debug")

    assert skill is not None
    rendered = skill.prompt()
    assert "Memory scope:" in rendered
    assert "Tool policy:" in rendered
    assert "Output format:" in rendered
    assert skill.max_memory_items == 2


def test_render_skills_mentions_usage():
    rendered = render_skills()

    assert "research" in rendered
    assert "/skill <name>" in rendered


def test_select_auto_skill():
    assert select_auto_skill("what did I work on emotions?") == "research"
    assert select_auto_skill("brainstorm ideas for this project") == "brainstorm"
    assert select_auto_skill("give me next steps") == "planner"
    assert select_auto_skill("what should I focus now") == "planner"
    assert select_auto_skill("what are my priorities this week?") == "planner"
    assert select_auto_skill("hello") is None


def test_skill_router_prompt_and_parser():
    prompt = build_skill_router_prompt("what should I docus now")

    assert "planner" in prompt
    assert parse_skill_router_output("planner") == "planner"
    assert parse_skill_router_output("`memory`") == "memory"
    assert parse_skill_router_output("none") is None

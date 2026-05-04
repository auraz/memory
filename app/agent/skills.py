from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerSkill:
    name: str
    summary: str
    instructions: str


SKILLS: dict[str, AnswerSkill] = {
    "research": AnswerSkill(
        name="research",
        summary="Ground answers in recalled memory, separate facts from inference.",
        instructions=(
            "Skill: research.\n"
            "Ground the answer in recalled memory. Separate what the memory says from your inference. "
            "Mention gaps or uncertainty briefly. Prefer concise synthesis over long lists."
        ),
    ),
    "coach": AnswerSkill(
        name="coach",
        summary="Reflect patterns, tradeoffs, and next actions.",
        instructions=(
            "Skill: coach.\n"
            "Reflect patterns in the user's history, name tradeoffs clearly, and end with one or two concrete next actions. "
            "Do not be motivational or fluffy."
        ),
    ),
    "brainstorm": AnswerSkill(
        name="brainstorm",
        summary="Generate options, clusters, and angles.",
        instructions=(
            "Skill: brainstorm.\n"
            "Generate several distinct options or angles. Cluster related ideas. Include one pragmatic recommendation."
        ),
    ),
    "planner": AnswerSkill(
        name="planner",
        summary="Turn context into a short plan.",
        instructions=(
            "Skill: planner.\n"
            "Turn recalled context into a sequenced plan with clear priorities, dependencies, and a near-term next step."
        ),
    ),
    "journal": AnswerSkill(
        name="journal",
        summary="Summarize personal themes in a reflective but direct style.",
        instructions=(
            "Skill: journal.\n"
            "Summarize personal themes and emotional patterns from memory. Keep the tone reflective, grounded, and direct."
        ),
    ),
}


def get_skill(name: str | None) -> AnswerSkill | None:
    if not name or name == "auto":
        return None
    return SKILLS.get(name.lower())


def select_auto_skill(message: str) -> str | None:
    text = message.lower()
    if "what did" in text or "what have i" in text:
        return "research"
    research_terms = ["what did", "what have i", "summarize", "research", "source", "evidence", "compare"]
    coach_terms = ["why do i", "pattern", "stuck", "feel", "avoid", "struggle", "motivation"]
    brainstorm_terms = ["brainstorm", "ideas", "options", "alternatives", "possibilities"]
    planner_terms = ["plan", "next steps", "roadmap", "schedule", "prioritize", "todo"]
    journal_terms = ["journal", "reflect", "emotion", "emotions", "mood", "meaning"]

    scored = {
        "research": sum(term in text for term in research_terms),
        "coach": sum(term in text for term in coach_terms),
        "brainstorm": sum(term in text for term in brainstorm_terms),
        "planner": sum(term in text for term in planner_terms),
        "journal": sum(term in text for term in journal_terms),
    }
    best_name, best_score = max(scored.items(), key=lambda item: item[1])
    return best_name if best_score > 0 else None


def render_skills() -> str:
    lines = ["Available skills:"]
    lines.append("- auto: choose a skill from each message")
    for skill in SKILLS.values():
        lines.append(f"- {skill.name}: {skill.summary}")
    lines.append("Use /skill <name>, /skill auto, or /skill off.")
    return "\n".join(lines)

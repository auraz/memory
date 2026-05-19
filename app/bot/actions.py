from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SheetCell: TypeAlias = str | int | float | bool | None
SheetRows: TypeAlias = list[list[SheetCell]]


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RecallArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic: str = ""


class ContextPreviewArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = ""


class SetSkillArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skill: str = ""

    @field_validator("skill")
    @classmethod
    def normalize_skill(cls, value: str) -> str:
        return value.strip().lower()


class RememberArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = ""


class OpenClawDelegateArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task: str = ""


class GwsSheetsCreateArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = ""
    rows: SheetRows = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return " ".join(value.split())


class GwsSheetsReadArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spreadsheet_id: str = ""
    range: str = ""


class GwsSheetsUpdateArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spreadsheet_id: str = ""
    range: str = ""
    values: SheetRows = Field(default_factory=list)


class GwsSheetsAppendArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spreadsheet_id: str = ""
    worksheet: str = "Sheet1"
    rows: SheetRows = Field(default_factory=list)


class GwsSheetsReplaceArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spreadsheet_id: str = ""
    worksheet: str = ""
    rows: SheetRows = Field(default_factory=list)


class GwsSheetsFillColumnArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    spreadsheet_id: str = ""
    worksheet: str = ""
    header: str = ""
    value: SheetCell = ""

    @field_validator("header")
    @classmethod
    def normalize_header(cls, value: str) -> str:
        return " ".join(value.split())


class GoalArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    operation: Literal["show", "set", "status", "clear"] = "show"
    text: str = ""

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())


ActionArgs: TypeAlias = (
    EmptyArgs
    | RecallArgs
    | ContextPreviewArgs
    | SetSkillArgs
    | RememberArgs
    | OpenClawDelegateArgs
    | GwsSheetsCreateArgs
    | GwsSheetsReadArgs
    | GwsSheetsUpdateArgs
    | GwsSheetsAppendArgs
    | GwsSheetsReplaceArgs
    | GwsSheetsFillColumnArgs
    | GoalArgs
)


@dataclass(frozen=True)
class ActionSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    args_hint: str = "{}"
    allowed_during_memory_job: bool = False

    def prompt_line(self) -> str:
        suffix = f" args: {self.args_hint}." if self.args_hint else ""
        return f"- {self.name}: {self.description}{suffix}"

    def input_schema(self) -> dict[str, Any]:
        schema = self.args_schema.model_json_schema()
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema.setdefault("additionalProperties", False)
        return schema

    def openai_tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema(),
            },
        }

    def mcp_tool_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema(),
        }


ACTION_SPECS: dict[str, ActionSpec] = {
    "recall": ActionSpec(
        name="recall",
        description="Direct memory search/debug.",
        args_schema=RecallArgs,
        args_hint='{"topic":"..."}',
    ),
    "context_preview": ActionSpec(
        name="context_preview",
        description="Inspect what context would be used before answering.",
        args_schema=ContextPreviewArgs,
        args_hint='{"message":"..."}',
    ),
    "show_core_memory": ActionSpec(
        name="show_core_memory",
        description="Show Letta/core memory blocks.",
        args_schema=EmptyArgs,
        allowed_during_memory_job=True,
    ),
    "memory_status": ActionSpec(
        name="memory_status",
        description="Show memory backend/status.",
        args_schema=EmptyArgs,
        allowed_during_memory_job=True,
    ),
    "memory_jobs": ActionSpec(
        name="memory_jobs",
        description="Show active/background memory jobs.",
        args_schema=EmptyArgs,
        allowed_during_memory_job=True,
    ),
    "cancel_memory_job": ActionSpec(
        name="cancel_memory_job",
        description="Cancel active memory job.",
        args_schema=EmptyArgs,
        allowed_during_memory_job=True,
    ),
    "list_skills": ActionSpec(
        name="list_skills",
        description="List answer skills.",
        args_schema=EmptyArgs,
        allowed_during_memory_job=True,
    ),
    "set_skill": ActionSpec(
        name="set_skill",
        description="Set answer skill.",
        args_schema=SetSkillArgs,
        args_hint='{"skill":"auto|off|research|coach|brainstorm|planner|journal|debug|build|decision|memory"}',
        allowed_during_memory_job=True,
    ),
    "refresh_memory": ActionSpec(
        name="refresh_memory",
        description="Start non-destructive background memory refresh.",
        args_schema=EmptyArgs,
    ),
    "remember": ActionSpec(
        name="remember",
        description="Store a user-provided memory.",
        args_schema=RememberArgs,
        args_hint='{"text":"..."}',
    ),
    "openclaw_delegate": ActionSpec(
        name="openclaw_delegate",
        description="Delegate a task to OpenClaw.",
        args_schema=OpenClawDelegateArgs,
        args_hint='{"task":"..."}',
    ),
    "gws_sheets_create": ActionSpec(
        name="gws_sheets_create",
        description="Create a Google Sheets spreadsheet, optionally seeded with rows.",
        args_schema=GwsSheetsCreateArgs,
        args_hint='{"title":"...","rows":[["header"],["value"]]}',
    ),
    "gws_sheets_read": ActionSpec(
        name="gws_sheets_read",
        description="Read values from a Google Sheets range.",
        args_schema=GwsSheetsReadArgs,
        args_hint='{"spreadsheet_id":"...","range":"Sheet1!A1:B10"}',
    ),
    "gws_sheets_update": ActionSpec(
        name="gws_sheets_update",
        description="Replace values in a Google Sheets range.",
        args_schema=GwsSheetsUpdateArgs,
        args_hint='{"spreadsheet_id":"...","range":"Sheet1!A1:B2","values":[["A","B"]]}',
    ),
    "gws_sheets_append": ActionSpec(
        name="gws_sheets_append",
        description="Append rows to a Google Sheets worksheet.",
        args_schema=GwsSheetsAppendArgs,
        args_hint='{"spreadsheet_id":"...","worksheet":"Sheet1","rows":[["value"]]}',
    ),
    "gws_sheets_replace": ActionSpec(
        name="gws_sheets_replace",
        description="Clear a Google Sheets worksheet and write a full replacement table.",
        args_schema=GwsSheetsReplaceArgs,
        args_hint='{"spreadsheet_id":"...","worksheet":"Sheet1 or empty for first tab","rows":[["header"],["value"]]}',
    ),
    "gws_sheets_fill_column": ActionSpec(
        name="gws_sheets_fill_column",
        description="Add or reuse a Google Sheets column and fill existing data rows with one value.",
        args_schema=GwsSheetsFillColumnArgs,
        args_hint='{"spreadsheet_id":"...","worksheet":"Sheet1 or empty for first tab","header":"timezone","value":"Europe/Kyiv"}',
    ),
    "goal": ActionSpec(
        name="goal",
        description="Show, set, clear, or summarize status for the active Frakir goal.",
        args_schema=GoalArgs,
        args_hint='{"operation":"show|set|status|clear","text":"..."}',
        allowed_during_memory_job=True,
    ),
}

ACTION_NAMES = frozenset({"chat", *ACTION_SPECS})
ToolSchemaFormat: TypeAlias = Literal["openai", "mcp"]


def render_action_catalog() -> str:
    lines = ["- chat: normal assistant conversation or task answer."]
    lines.extend(spec.prompt_line() for spec in ACTION_SPECS.values())
    return "\n".join(lines)


def export_action_tool_schemas(format: ToolSchemaFormat = "mcp") -> list[dict[str, Any]]:
    if format == "openai":
        return [spec.openai_tool_schema() for spec in ACTION_SPECS.values()]
    if format == "mcp":
        return [spec.mcp_tool_schema() for spec in ACTION_SPECS.values()]
    raise ValueError(f"Unsupported tool schema format: {format}")


def is_allowed_during_memory_job(action_name: str) -> bool:
    spec = ACTION_SPECS.get(action_name)
    return bool(spec and spec.allowed_during_memory_job)


def validate_action_args(action_name: str, args: object) -> dict:
    spec = ACTION_SPECS.get(action_name)
    if spec is None:
        return {}
    try:
        parsed = spec.args_schema.model_validate(args or {})
    except ValidationError:
        return {}
    return parsed.model_dump()

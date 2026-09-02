"""Phase A quickstart verification: Strands SDK import + API surface check."""
from strands import Agent, tool
print("STRANDS_OK")

try:
    from strands.models import BedrockModel
    print("BEDROCK_IMPORT_OK: strands.models.BedrockModel")
except ImportError as e:
    print("BEDROCK_IMPORT_FAIL:", e)
    import strands
    import pkgutil
    for m in pkgutil.iter_modules(strands.__path__):
        print("  submodule:", m.name)

# hooks / steering / conversation manager surface check
try:
    from strands.hooks import BeforeToolCallEvent, AfterToolCallEvent
    print("HOOKS_OK")
except ImportError as e:
    print("HOOKS_FAIL:", e)

try:
    from strands.agent import SlidingWindowConversationManager, SummarizingConversationManager
    print("CONV_MGR_OK")
except ImportError as e:
    print("CONV_MGR_FAIL:", e)

# tool decorator smoke test (no model call, no network)
@tool
def echo(x: str) -> str:
    """Echo input back."""
    return f"echo:{x}"

print("TOOL_DECORATOR_OK:", echo.__name__ if hasattr(echo, "__name__") else type(echo))

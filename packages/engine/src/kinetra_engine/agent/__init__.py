"""Agent tools (G-02): what an LLM or the MCP server may call to change a project (`edit_tools.py`, G-02a; `guard.py`, G-04) or to
read it in numbers (`query_tools.py`, G-02b); proposals and retries `proposal.py` (G-03a); run and verdict requests `run_tools.py` (G-02c);
failure explanations that quote only the run's and the checks' numbers `explain.py` (G-05)."""

from .edit_tools import TOOL_NAMES, EditTools, HubEditTools, ToolResult, load_library, specs
from .explain import DISCARDED_NOTICE, EVIDENCE_TOOLS, Citation, Explainer, FailureExplanation, check_numbers, evidence_of
from .guard import OutOfCatalog, guard_arguments, guard_tool, introduced, out_of_catalog
from .proposal import DEFAULT_MAX_ATTEMPTS, EXPLANATION_LABEL, VERDICT_NOTICE, Attempt, Explanation, Proposal, ProposalResult, ProposedCall, Proposer
from .query_tools import QUERY_TOOL_NAMES, ROLLOUT_NOTICE, STATICS_LABEL, HubQueryTools, QueryResult, QueryTools, query_specs, summarize_rollout
from .run_tools import RUN_LABEL, RUN_TOOL_NAMES, Judge, RunTools, RunToolResult, Verdict, VerdictRequest, run_specs

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DISCARDED_NOTICE",
    "EVIDENCE_TOOLS",
    "EXPLANATION_LABEL",
    "QUERY_TOOL_NAMES",
    "ROLLOUT_NOTICE",
    "RUN_LABEL",
    "RUN_TOOL_NAMES",
    "STATICS_LABEL",
    "TOOL_NAMES",
    "VERDICT_NOTICE",
    "Attempt",
    "Citation",
    "EditTools",
    "Explainer",
    "Explanation",
    "FailureExplanation",
    "HubEditTools",
    "HubQueryTools",
    "Judge",
    "OutOfCatalog",
    "Proposal",
    "ProposalResult",
    "ProposedCall",
    "Proposer",
    "QueryResult",
    "QueryTools",
    "RunToolResult",
    "RunTools",
    "ToolResult",
    "Verdict",
    "VerdictRequest",
    "check_numbers",
    "evidence_of",
    "guard_arguments",
    "guard_tool",
    "introduced",
    "load_library",
    "out_of_catalog",
    "query_specs",
    "run_specs",
    "specs",
    "summarize_rollout",
]

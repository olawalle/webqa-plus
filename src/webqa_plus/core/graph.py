"""LangGraph state definitions and graph orchestration."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Awaitable, Callable, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field


class AgentState(str, Enum):
    """Agent execution states."""

    IDLE = "idle"
    EXPLORING = "exploring"
    TESTING = "testing"
    VALIDATING = "validating"
    REPORTING = "reporting"
    COMPLETED = "completed"
    ERROR = "error"


class TestStep(BaseModel):
    """A single test step execution."""

    step_number: int
    agent: str
    action: str
    target: Optional[str] = None
    status: str = "pending"  # pending, success, failed, skipped
    screenshot_path: Optional[str] = None
    console_logs: List[Dict[str, Any]] = Field(default_factory=list)
    network_logs: List[Dict[str, Any]] = Field(default_factory=list)
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    duration_ms: Optional[int] = None


class UserFlow(BaseModel):
    """A discovered user flow through the application."""

    flow_id: str
    name: str
    description: str
    steps: List[TestStep] = Field(default_factory=list)
    status: str = "discovered"  # discovered, testing, completed, failed
    coverage: float = 0.0
    start_url: str
    end_url: Optional[str] = None


class GraphState(TypedDict):
    """LangGraph state schema."""

    # Current execution state
    current_state: AgentState
    current_step: int
    max_steps: int

    # Browser context
    browser: Any  # Playwright page object (not serializable)
    mcp_client: Any  # MCP client instance
    current_url: str
    page_title: str

    # Testing data
    visited_urls: Annotated[List[str], "visited_urls"]  # Accumulated
    discovered_flows: List[UserFlow]
    current_flow: Optional[UserFlow]
    test_results: List[TestStep]

    # Metrics and tracking
    coverage_metrics: Dict[str, float]
    llm_calls: int
    total_tokens: int
    estimated_cost: float

    # Configuration
    config: Dict[str, Any]
    auth_completed: bool
    artifacts: Dict[str, Any]

    # Error handling
    errors: List[str]
    should_stop: bool


class LangGraphOrchestrator:
    """LangGraph orchestrator for the 4-agent system."""

    def __init__(self, explorer_agent, tester_agent, validator_agent, reporter_agent):
        """Initialize the orchestrator with agent instances."""
        self.explorer = explorer_agent
        self.tester = tester_agent
        self.validator = validator_agent
        self.reporter = reporter_agent

        # Build the graph
        self.graph = self._build_graph()

    def _build_graph(self):
        """Build the LangGraph state machine."""
        # Create the graph
        workflow = StateGraph(GraphState)

        # Add nodes
        workflow.add_node("explorer", self._explorer_node)
        workflow.add_node("tester", self._tester_node)
        workflow.add_node("validator", self._validator_node)
        workflow.add_node("reporter", self._reporter_node)

        # Define edges
        workflow.set_entry_point("explorer")

        workflow.add_conditional_edges(
            "explorer",
            self._should_continue,
            {
                "continue": "tester",
                "report": "reporter",
            },
        )

        workflow.add_conditional_edges(
            "tester",
            self._should_validate,
            {
                "validate": "validator",
                "explore": "explorer",
            },
        )

        workflow.add_conditional_edges(
            "validator",
            self._after_validation,
            {
                "continue": "tester",
                "explore": "explorer",
                "report": "reporter",
            },
        )

        workflow.add_edge("reporter", END)

        return workflow.compile()

    def _build_run_config(self, state: GraphState) -> Dict[str, Any]:
        """Build LangGraph runtime config with safe recursion budget."""
        max_steps = int(state.get("max_steps", 200))
        recursion_limit = max(200, max_steps * 6)
        return {"recursion_limit": recursion_limit}

    async def _explorer_node(self, state: GraphState) -> GraphState:
        """Explorer agent node - discovers new flows and elements."""
        state["current_state"] = AgentState.EXPLORING
        return await self.explorer.run(state)

    async def _tester_node(self, state: GraphState) -> GraphState:
        """Tester agent node - executes actions and generates inputs."""
        state["current_state"] = AgentState.TESTING
        return await self.tester.run(state)

    async def _validator_node(self, state: GraphState) -> GraphState:
        """Validator agent node - checks for errors and validates state."""
        state["current_state"] = AgentState.VALIDATING
        return await self.validator.run(state)

    async def _reporter_node(self, state: GraphState) -> GraphState:
        """Reporter agent node - generates final report."""
        state["current_state"] = AgentState.REPORTING
        return await self.reporter.run(state)

    def _should_continue(self, state: GraphState) -> str:
        """Decide whether to continue testing or report."""
        if state["should_stop"]:
            return "report"
        if state["current_step"] >= state["max_steps"]:
            return "report"
        if len(state["errors"]) > 10:  # Too many errors
            return "report"
        return "continue"

    def _should_validate(self, state: GraphState) -> str:
        """Decide whether to validate or explore."""
        if state["current_flow"] is None:
            return "explore"
        return "validate"

    def _after_validation(self, state: GraphState) -> str:
        """Decide next step after validation."""
        if state["should_stop"]:
            return "report"
        if state["current_step"] % 10 == 0:  # Explore periodically
            return "explore"
        return "continue"

    async def run(self, initial_state: GraphState) -> GraphState:
        """Execute the graph with initial state."""
        return await self.graph.ainvoke(initial_state, config=self._build_run_config(initial_state))

    async def run_with_updates(
        self,
        initial_state: GraphState,
        on_update: Callable[[GraphState], Awaitable[None]],
    ) -> GraphState:
        """Execute the graph and emit intermediate state updates."""
        final_state = initial_state
        run_config = self._build_run_config(initial_state)
        async for state in self.graph.astream(initial_state, stream_mode="values", config=run_config):
            final_state = state
            await on_update(state)
        return final_state

"""The interviewer as a LangGraph state machine. One `ainvoke` == one interview turn.

    START --(event=start)--> plan_interview --> ask_question --> END
    START --(event=answer)-> evaluate_answer --> decide_next --+--> ask_follow_up --> END
                                                               +--> ask_question  --> END
                                                               +--> finish        --> END

Every path ends at END after a single question is asked (or the interview finishes), so each HTTP
request advances the interview by exactly one turn. The state is loaded from and saved to the
`interview_state` table around the run (see app/services/interview.py); there is no checkpointer
and no memory between requests.
"""

from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.interviewer import nodes
from app.agents.interviewer.state import InterviewContext, InterviewState


def build_graph() -> Any:
    g = StateGraph(InterviewState, context_schema=InterviewContext)
    g.add_node("plan_interview", nodes.plan_interview)
    g.add_node("ask_question", nodes.ask_question)
    g.add_node("evaluate_answer", nodes.evaluate_answer)
    g.add_node("decide_next", nodes.decide_next)
    g.add_node("ask_follow_up", nodes.ask_follow_up)
    g.add_node("finish", nodes.finish)

    g.add_conditional_edges(START, nodes.route_entry, ["plan_interview", "evaluate_answer"])
    g.add_edge("plan_interview", "ask_question")
    g.add_edge("evaluate_answer", "decide_next")
    g.add_conditional_edges(
        "decide_next", nodes.route_after_decide, ["ask_follow_up", "ask_question", "finish"]
    )
    g.add_edge("ask_question", END)
    g.add_edge("ask_follow_up", END)
    g.add_edge("finish", END)
    return g.compile()


@lru_cache(maxsize=1)
def get_graph() -> Any:
    """Compiled once per process (compiling is pure CPU; the graph holds no session data)."""
    return build_graph()


async def run_turn(state: InterviewState, ctx: InterviewContext) -> InterviewState:
    result = await get_graph().ainvoke(state, context=ctx)
    return InterviewState.model_validate(result)

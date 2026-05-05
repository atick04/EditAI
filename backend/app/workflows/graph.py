from langgraph.graph import StateGraph, START, END
from app.workflows.state import VideoEditingState
from app.workflows.nodes import prepare_context_node, director_agent_node, graphics_agent_node

builder = StateGraph(VideoEditingState)

builder.add_node("prepare_context", prepare_context_node)
builder.add_node("director_agent", director_agent_node)
builder.add_node("graphics_agent", graphics_agent_node)

builder.add_edge(START, "prepare_context")
builder.add_edge("prepare_context", "director_agent")
builder.add_edge("director_agent", "graphics_agent")
builder.add_edge("graphics_agent", END)

editor_graph = builder.compile()

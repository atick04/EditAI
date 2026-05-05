from typing import TypedDict, List, Dict, Any, Annotated, Optional
import operator
from langchain_core.messages import BaseMessage

class VideoEditingState(TypedDict, total=False):
    file_id: str
    user_message: str
    is_evaluation: bool
    transcript_text: str
    visual_context: str
    auto_cuts: List[Dict[str, Any]]
    template_id: Optional[str]
    template_config: Optional[Dict[str, Any]]
    active_edits: Optional[List[Dict[str, Any]]]
    
    # Langchain message stream for generating response
    messages: Annotated[List[BaseMessage], operator.add]
    
    # Resulting parse output
    ai_response_json: str
    edits: List[Dict[str, Any]]
    variants: List[Dict[str, Any]]
    ready_to_render: bool

from pydantic import BaseModel
from typing import List, Optional

class SubtitleConfig(BaseModel):
    font: str
    fontSize: int
    position: str
    colorMap: List[str]
    animation: str
    useOutline: bool
    wordsPerScreen: int

class EditingConfig(BaseModel):
    autoCutSilences: bool
    zoomFrequency: str  # 'high', 'medium', 'low', 'none'
    brollFrequency: str # 'high', 'medium', 'low', 'none'
    speedRamp: bool

class GraphicsConfig(BaseModel):
    theme: str  # e.g., 'vibrant', 'minimal', 'cinematic'
    useSoundEffects: bool

class TemplateConfig(BaseModel):
    id: str
    name: str
    description: str
    preview_url: str
    subtitles: SubtitleConfig
    editing: EditingConfig
    graphics: GraphicsConfig

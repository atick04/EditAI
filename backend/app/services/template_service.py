import json
import os
import glob
from app.schemas.template import TemplateConfig

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates", "library")

def load_templates():
    templates = []
    if not os.path.exists(TEMPLATE_DIR):
        return templates
        
    for filepath in glob.glob(os.path.join(TEMPLATE_DIR, "*.json")):
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                template = TemplateConfig(**data)
                templates.append(template)
            except Exception as e:
                print(f"Error loading template {filepath}: {e}")
    return templates

def get_template(template_id: str):
    templates = load_templates()
    for t in templates:
        if t.id == template_id:
            return t
    return None

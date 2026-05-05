from fastapi import APIRouter
from app.services.template_service import load_templates

router = APIRouter(prefix="/api/templates", tags=["Templates"])

@router.get("")
async def get_all_templates():
    templates = load_templates()
    return templates

from fastapi import APIRouter, File, UploadFile, HTTPException, BackgroundTasks
import os
import uuid
import shutil
import json
from app.services.video_service import extract_audio
from app.services.ai_service import transcribe_audio
from app.services.vlm_service import analyze_video_scenes, format_visual_context

router = APIRouter(prefix="/api/video", tags=["Video"])

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def log_progress(file_id: str, message: str):
    log_path = os.path.join(UPLOAD_DIR, f"{file_id}.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(message + "\n")

async def process_video_pipeline(video_path: str, audio_path: str, file_id: str):
    """Фоновая задача: достать аудио, распознать текст и сделать визуальный анализ"""
    log_progress(file_id, "⚙️ Извлекаем аудио дорожку (FFmpeg)...")
    extract_audio(video_path, audio_path)
    
    log_progress(file_id, "🧠 ИИ расшифровывает речь (Whisper via Groq)...")
    transcript = await transcribe_audio(audio_path)
    
    if transcript:
        transcript_path = os.path.join(UPLOAD_DIR, f"{file_id}_transcript.json")
        with open(transcript_path, "w", encoding="utf-8") as f:
            json.dump(transcript, f, ensure_ascii=False, indent=2)
        log_progress(file_id, "✅ Транскрипция успешно сохранена! Вы можете общаться с ИИ агентом.")
    else:
        log_progress(file_id, "❌ Ошибка при транскрипции Whisper.")
    
    # VLM Visual Analysis with Gemini
    log_progress(file_id, "👁️ Gemini Vision анализирует кадры видео...")
    scenes = await analyze_video_scenes(video_path, fps=0.5)
    if scenes:
        visual_path = os.path.join(UPLOAD_DIR, f"{file_id}_visual.json")
        with open(visual_path, "w", encoding="utf-8") as f:
            json.dump(scenes, f, ensure_ascii=False, indent=2)
        log_progress(file_id, f"🎬 Визуальный анализ готов! Обнаружено {len(scenes)} сцен.")
    else:
        log_progress(file_id, "⚠️ Визуальный анализ пропущен (нет кадров или ошибка Gemini).")

@router.post("/upload")
async def upload_video(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video")
    
    file_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename)[1]
    filename = f"{file_id}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    log_progress(file_id, "📥 Файл загружен на сервер.")
    
    audio_path = os.path.join(UPLOAD_DIR, f"{file_id}.mp3")
    background_tasks.add_task(process_video_pipeline, file_path, audio_path, file_id)
    
    return {
        "message": "Video uploaded successfully", 
        "file_id": file_id, 
        "filename": filename,
        "path": file_path
    }

@router.get("/{file_id}/status")
async def get_video_status(file_id: str):
    rendered_path = os.path.join(UPLOAD_DIR, f"{file_id}_rendered.mp4")
    log_path = os.path.join(UPLOAD_DIR, f"{file_id}.log")
    render_lock_path = os.path.join(UPLOAD_DIR, f"{file_id}.rendering")
    
    logs = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            logs = f.read().strip().split("\n")
    
    # If a render lock file exists, render is actively in progress
    is_rendering = os.path.exists(render_lock_path)
    is_ready = os.path.exists(rendered_path) and not is_rendering
    updated_at = os.stat(rendered_path).st_mtime if os.path.exists(rendered_path) else 0
    
    if is_rendering:
        status = "processing"
    elif is_ready:
        status = "ready"
    else:
        status = "editing"

    return {
        "status": status,
        "filename": f"{file_id}_rendered.mp4" if is_ready else None,
        "updated_at": updated_at,
        "logs": [l for l in logs if l]
    }

@router.get("/{file_id}/transcript")
async def get_transcript(file_id: str):
    transcript_path = os.path.join(UPLOAD_DIR, f"{file_id}_transcript.json")
    if os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            return {"status": "error", "detail": str(e)}
    return {"status": "processing"}

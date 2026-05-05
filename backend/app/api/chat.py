from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import os
import json
import glob
import asyncio
from typing import Optional
from app.services.ai_service import client
from app.services.video_service import render_video
from app.services.vlm_service import format_visual_context
from app.services.template_service import get_template

router = APIRouter(prefix="/api/chat", tags=["Chat"])

class ChatRequest(BaseModel):
    file_id: str
    message: str
    font: str = "Arial"
    font_size: int = 100
    use_outline: bool = True
    font_color: str = "White"
    force_edits: Optional[list] = None
    position: str = "center"
    edl: Optional[dict] = None
    template_id: Optional[str] = None
    active_edits: Optional[list] = None

class RenderStyleRequest(BaseModel):
    file_id: str
    font: str = "Arial"
    font_size: int = 100
    use_outline: bool = True
    font_color: str = "White"
    position: str = "center"
    edits: Optional[list] = None
    edl: Optional[dict] = None
    template_id: Optional[str] = None

def log_progress(file_id: str, message: str):
    log_path = os.path.join("uploads", f"{file_id}.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def process_render_task(file_id: str, edits: list, edl: dict = None, font: str = "Arial", font_size: int = 100, use_outline: bool = True, font_color: str = "White", template_id: str = None, is_pure_addition: bool = False):
    """Background task to trigger actual FFmpeg rendering from Agent instructions"""
    lock_path = os.path.join("uploads", f"{file_id}.rendering")
    
    # Create lock file to signal that rendering is in progress
    with open(lock_path, "w") as f:
        f.write("rendering")
    
    log_progress(file_id, f"🎬 Подготовка к рендеру... (Получено мультитрековое состояние)")
    files = glob.glob(f"uploads/{file_id}.*")
    print(f"[RenderTask] Found files: {files}")
    # Case-insensitive match: handle .MP4 .MOV .WEBM from iPhones and cameras
    video_exts = ('.mp4', '.mov', '.webm', '.avi', '.mkv')
    video_file = next(
        (f for f in files
         if f.lower().endswith(video_exts)
         and not f.lower().endswith('_rendered.mp4')
         and '_rendered' not in f),
        None
    )
    print(f"[RenderTask] Video file selected: {video_file}")
    if not video_file: 
        log_progress(file_id, "❌ Файл исходного видео не найден.")
        if os.path.exists(lock_path):
            os.remove(lock_path)
        return
        
    previously_rendered = os.path.join("uploads", f"{file_id}_rendered.mp4")
    cache_video = os.path.join("uploads", f"{file_id}_cache.mp4")
    
    if is_pure_addition and os.path.exists(previously_rendered):
        log_progress(file_id, "⚡ Инкрементальный Рендер: наложение новых эффектов поверх уже готового видео...")
        import shutil
        shutil.copy2(previously_rendered, cache_video)
        video_file = cache_video
    else:
        log_progress(file_id, "🔄 Полный Рендер: пересборка всех эффектов с исходника...")
    
    transcript_path = os.path.join("uploads", f"{file_id}_transcript.json")
    transcript_data = {}
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript_data = json.load(f)
            
    print(f"[RenderTask] Transcript loaded: {bool(transcript_data)}")
    
    if template_id:
        tpl = get_template(template_id)
        if tpl:
            sub = tpl.subtitles
            font = sub.font
            font_size = sub.fontSize
            use_outline = sub.useOutline
            font_color = sub.colorMap[0] if sub.colorMap else "White"
            log_progress(file_id, f"🎨 Применён ПРЕМИУМ-ШАБЛОН: {tpl.name}. Переопределение стилей на {font} ({font_size}pt).")

    output_path = os.path.join("uploads", f"{file_id}_rendered.mp4")
    log_progress(file_id, f"🔥 Запущен процесс рендеринга видео со шрифтом {font} (FFmpeg)...")
    print(f"[RenderTask] Calling render_video: input={video_file}, output={output_path}, edits={len(edits)}")
    success = render_video(video_file, output_path, transcript_data, edits, edl, font, font_size, use_outline, font_color)
    print(f"[RenderTask] render_video returned: success={success}")
    
    # Remove lock file regardless of success/failure
    if os.path.exists(lock_path):
        os.remove(lock_path)
    
    if success:
        log_progress(file_id, "✅ Видео успешно смонтировано и сохранено!")
    else:
        log_progress(file_id, "❌ Произошла ошибка FFmpeg во время рендеринга.")
        
    # Clean up incremental cache track
    if is_pure_addition and os.path.exists(cache_video):
        try:
            os.remove(cache_video)
        except Exception:
            pass

@router.post("")
async def chat_with_director(request: ChatRequest, background_tasks: BackgroundTasks):
    import asyncio
    async def stream_response():
        transcript_path = os.path.join("uploads", f"{request.file_id}_transcript.json")
        # --- PHASE 0: Bypass LLM if force_edits is provided ---
        if request.force_edits is not None or request.edl is not None:
            yield json.dumps({"type": "log", "message": "Render Engine: Финализация выбранного варианта..."}) + "\n"
            yield json.dumps({"type": "log", "message": "Render Engine: Запуск FFmpeg пайплайна (EDL Engine)..."}) + "\n"
            background_tasks.add_task(process_render_task, request.file_id, request.force_edits or [], request.edl, request.font, request.font_size, request.use_outline, request.font_color, request.template_id)
            yield json.dumps({"type": "result", "role": "ai", "content": "Принято! Я запустил многослойный рендер (EDL). Через несколько минут результат будет готов.", "variants": []}) + "\n"
            return
            
        yield json.dumps({"type": "log", "message": "Manager Agent: Адаптация запроса и распределение задач..."}) + "\n"
        await asyncio.sleep(0.5)

        is_evaluation = request.message.startsWith("SYSTEM_EVALUATION") if hasattr(request.message, "startsWith") else request.message.startswith("SYSTEM_EVALUATION")

        auto_cuts = []
        
        if is_evaluation:
            yield json.dumps({"type": "log", "message": "Evaluation Module: Загружаю свежий рендер в зрительную кору..."}) + "\n"
            await asyncio.sleep(0.5)
            yield json.dumps({"type": "log", "message": "Evaluation Module: Анализирую итоговый результат на предмет ошибок..."}) + "\n"
        else:
            yield json.dumps({"type": "log", "message": "Editor Agent: Подготовка контекста и транскрипта..."}) + "\n"
            await asyncio.sleep(0.5)
            yield json.dumps({"type": "log", "message": "Motion Agent: Читаю визуальный контекст и планирую графику..."}) + "\n"
            await asyncio.sleep(0.5)

        try:
            from app.workflows.graph import editor_graph
            initial_state = {
                "file_id": request.file_id,
                "user_message": request.message,
                "is_evaluation": is_evaluation,
                "template_id": request.template_id,
                "active_edits": request.active_edits or []
            }

            buffer = ""
            is_thinking = False
            found_think_start = False
            json_buffer = ""

            async for event in editor_graph.astream_events(initial_state, version="v2"):
                if event["event"] == "on_chain_end" and event["name"] == "prepare_context":
                    auto_cuts = event["data"]["output"].get("auto_cuts", [])
                    if auto_cuts:
                        yield json.dumps({"type": "log", "message": f"Editor Agent: Найдено {len(auto_cuts)} затянутых пауз. Добавлены в очередь удаления."}) + "\n"
                        await asyncio.sleep(0.3)
                
                elif event["event"] == "on_chat_model_stream":
                    content = event["data"]["chunk"].content
                    if not isinstance(content, str):
                        continue
                    buffer += content
                    
                    if not found_think_start:
                        if "<think>" in buffer:
                            found_think_start = True
                            is_thinking = True
                            buffer = buffer.split("<think>", 1)[1]
                        elif len(buffer) > 30 and "<" not in buffer:
                            # Fallback
                            found_think_start = True
                            is_thinking = False
                            json_buffer += buffer
                            buffer = ""
                    
                    if found_think_start:
                        if is_thinking:
                            if "</think>" in buffer:
                                is_thinking = False
                                parts = buffer.split("</think>", 1)
                                thought_line = parts[0]
                                if thought_line.strip():
                                    for line in thought_line.split('\n'):
                                        if line.strip():
                                            yield json.dumps({"type": "reasoning", "step": line.strip(), "status": "done"}) + "\n"
                                
                                json_buffer += parts[1]
                                buffer = ""
                            else:
                                # Stream out closed lines
                                while "\n" in buffer:
                                    line, buffer = buffer.split("\n", 1)
                                    if line.strip():
                                        yield json.dumps({"type": "reasoning", "step": line.strip(), "status": "done"}) + "\n"
                        else:
                            json_buffer += buffer
                            buffer = ""
                        
            # Out of stream loop
            if is_thinking and buffer.strip():
                for line in buffer.split('\n'):
                    if line.strip():
                        yield json.dumps({"type": "reasoning", "step": line.strip(), "status": "done"}) + "\n"
            else:
                json_buffer += buffer

            # Extract JSON from json_buffer
            import re
            json_matches = re.findall(r'```json\s*(.*?)\s*```', json_buffer, re.DOTALL)
            
            # Start with existing edits but filter out old auto-cuts to freshen them
            active = request.active_edits or []
            all_edits = [e for e in active if e.get("action") not in ("cut_out")]
            all_edits.extend(auto_cuts)
            
            reply_texts = []
            variants = []
            is_ready = False

            def apply_ai_data(ai_data):
                nonlocal is_ready, all_edits, reply_texts, variants
                if ai_data.get("ready_to_render"):
                    is_ready = True
                if ai_data.get("reply"):
                    reply_texts.append(ai_data.get("reply"))
                if ai_data.get("variants"):
                    variants.extend(ai_data.get("variants"))
                    
                # Backward compatibility for INIT_PLAN or fallback models
                if ai_data.get("edits"):
                    all_edits.extend(ai_data.get("edits"))
                    
                # Handle new architectural patch schema
                if ai_data.get("edits_patch"):
                    patch = ai_data.get("edits_patch")
                    to_remove = patch.get("remove_action_types", [])
                    if to_remove:
                       all_edits = [e for e in all_edits if e.get("action") not in to_remove]
                    all_edits.extend(patch.get("append_edits", []))
            
            if json_matches:
                for json_str in json_matches:
                    try:
                        ai_data = json.loads(json_str)
                        apply_ai_data(ai_data)
                    except Exception as e:
                        print(f"JSON Parse Error: {e} block={json_str}")
            else:
                s_idx = json_buffer.find("{")
                e_idx = json_buffer.rfind("}")
                json_str = json_buffer[s_idx : e_idx+1] if s_idx != -1 and e_idx != -1 else "{}"
                try:
                    ai_data = json.loads(json_str)
                    apply_ai_data(ai_data)
                except Exception as e:
                    pass
            
            if is_ready:
                yield json.dumps({"type": "log", "message": "Правки применены. Нажмите 'SYNC SETTINGS' для финального рендера."}) + "\n"
            elif not is_evaluation:
                yield json.dumps({"type": "log", "message": "Ожидаю решения пользователя..."}) + "\n"
                
            # --- LIVE PREVIEW UPDATE ---
            try:
                hf_edits = [e for e in all_edits if e.get("action") == "add_hyperframes_graphics"]
                if hf_edits:
                    combined_html = "\n".join([e.get("html_content", "") for e in hf_edits])
                    html_doc = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: 100%; height: 100%; overflow: hidden; background: transparent; display: flex; align-items: center; justify-content: center; }}
      .clip {{ position: absolute; }}
      #preview-container {{ width: 1080px; height: 1920px; position: relative; transform-origin: center center; background: transparent; overflow: hidden; }}
    </style>
  </head>
  <body>
    <div id="preview-container">
      {combined_html}
    </div>
    <script>
      function resize() {{
        const container = document.getElementById('preview-container');
        const scale = Math.min(window.innerWidth / 1080, window.innerHeight / 1920);
        container.style.transform = `scale(${{scale}})`;
      }}
      window.addEventListener('resize', resize);
      resize();
      
      let isSynced = false;
      window.addEventListener('message', (event) => {{
          if (event.data && event.data.type === 'sync_time') {{
              isSynced = true;
              if (window.__timelines && window.__timelines["main"]) {{
                  window.__timelines["main"].pause();
                  window.__timelines["main"].seek(event.data.time);
              }}
          }}
      }});

      // Automatically play all animations for isolated preview pane!
      setTimeout(() => {{
        if (!isSynced && window.__timelines && window.__timelines["main"]) {{
           const tl = window.__timelines["main"];
           const clips = Array.from(document.querySelectorAll('.clip'));
           if (clips.length > 0) {{
               let minStart = Math.min(...clips.map(c => parseFloat(c.getAttribute('data-start') || 0)));
               let maxEnd = Math.max(...clips.map(c => parseFloat(c.getAttribute('data-start') || 0) + parseFloat(c.getAttribute('data-duration') || 0)));
               
               tl.seek(minStart).play();
               setInterval(() => {{
                   if (tl.time() > maxEnd + 0.5) {{
                       tl.seek(minStart).play();
                   }}
               }}, 100);
           }}
        }}
      }}, 500);
    </script>
  </body>
</html>"""
                    idx_file = os.path.join(os.path.dirname(__file__), "..", "..", "..", "hyperframes_studio", "index.html")
                    with open(idx_file, "w", encoding="utf-8") as f:
                        f.write(html_doc)
            except Exception as e:
                print(f"Failed to update Live Preview: {e}")
                
            yield json.dumps({
                "type": "result", 
                "role": "ai", 
                "content": "\n\n".join([r for r in reply_texts if r.strip()]) or "Готово.", 
                "variants": variants,
                "edits": all_edits
            }) + "\n"

        except BaseException as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[Chat Stream] FATAL: {e}\n{tb}")
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(stream_response(), media_type="application/x-ndjson")

@router.post("/render")
async def direct_render_from_ui(request: RenderStyleRequest, background_tasks: BackgroundTasks):
    """Directly re-render via UI without LLM stream"""
    background_tasks.add_task(process_render_task, request.file_id, request.edits or [], request.edl, request.font, request.font_size, request.use_outline, request.font_color, request.template_id)
    return {"status": "rendering started"}

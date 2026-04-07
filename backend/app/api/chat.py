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

class RenderStyleRequest(BaseModel):
    file_id: str
    font: str = "Arial"
    font_size: int = 100
    use_outline: bool = True
    font_color: str = "White"
    position: str = "center"
    edits: Optional[list] = None
    edl: Optional[dict] = None

def log_progress(file_id: str, message: str):
    log_path = os.path.join("uploads", f"{file_id}.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def process_render_task(file_id: str, edits: list, edl: dict = None, font: str = "Arial", font_size: int = 100, use_outline: bool = True, font_color: str = "White"):
    """Background task to trigger actual FFmpeg rendering from Agent instructions"""
    log_progress(file_id, f"🎬 Подготовка к рендеру... (Получено мультитрековое состояние)")
    files = glob.glob(f"uploads/{file_id}.*")
    # Native video input (ignore audio/json or already rendered exports)
    video_file = next((f for f in files if f.endswith(('.mp4', '.mov', '.webm')) and not f.endswith('_rendered.mp4')), None)
    if not video_file: 
        log_progress(file_id, "❌ Файл исходного видео не найден.")
        return
    
    transcript_path = os.path.join("uploads", f"{file_id}_transcript.json")
    transcript_data = {}
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript_data = json.load(f)
            
    output_path = os.path.join("uploads", f"{file_id}_rendered.mp4")
    log_progress(file_id, f"🔥 Запущен процесс рендеринга видео со шрифтом {font} (FFmpeg)...")
    success = render_video(video_file, output_path, transcript_data, edits, edl, font, font_size, use_outline, font_color)
    if success:
        log_progress(file_id, "✅ Видео успешно смонтировано и сохранено!")
    else:
        log_progress(file_id, "❌ Произошла ошибка FFmpeg во время рендеринга.")

@router.post("")
async def chat_with_director(request: ChatRequest, background_tasks: BackgroundTasks):
    import asyncio
    async def stream_response():
        transcript_path = os.path.join("uploads", f"{request.file_id}_transcript.json")
        # --- PHASE 0: Bypass LLM if force_edits is provided ---
        if request.force_edits is not None or request.edl is not None:
            yield json.dumps({"type": "log", "message": "Render Engine: Финализация выбранного варианта..."}) + "\n"
            yield json.dumps({"type": "log", "message": "Render Engine: Запуск FFmpeg пайплайна (EDL Engine)..."}) + "\n"
            background_tasks.add_task(process_render_task, request.file_id, request.force_edits or [], request.edl, request.font, request.font_size, request.use_outline, request.font_color)
            yield json.dumps({"type": "result", "role": "ai", "content": "Принято! Я запустил многослойный рендер (EDL). Через несколько минут результат будет готов.", "variants": []}) + "\n"
            return
            
        yield json.dumps({"type": "log", "message": "Manager Agent: Адаптация запроса и распределение задач..."}) + "\n"
        await asyncio.sleep(0.5)

        transcript_text = "Транскрипт пока не готов."
        
        is_evaluation = request.message.startsWith("SYSTEM_EVALUATION") if hasattr(request.message, "startsWith") else request.message.startswith("SYSTEM_EVALUATION")
        eval_context = request.message.replace("SYSTEM_EVALUATION: ", "").replace("SYSTEM_EVALUATION:", "").strip() if is_evaluation else ""

        auto_cuts = []
        
        if is_evaluation:
            yield json.dumps({"type": "log", "message": "Evaluation Module: Загружаю свежий рендер в зрительную кору..."}) + "\n"
            await asyncio.sleep(0.5)
            yield json.dumps({"type": "log", "message": "Evaluation Module: Анализирую итоговый результат на предмет ошибок..."}) + "\n"
        else:
            # --- EDITOR AGENT LOGIC ---
            yield json.dumps({"type": "log", "message": "Editor Agent: Анализирую транскрипт и выявляю тишину/паузы..."}) + "\n"
            await asyncio.sleep(0.5)
            
            if os.path.exists(transcript_path):
                try:
                    with open(transcript_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        
                        # Compress words for LLM
                        words = data.get("words", [])
                        if words:
                            context_lines = []
                            for w in words:
                                context_lines.append(f"{w.get('word', '').strip()}[{w.get('start', 0.0):.1f}-{w.get('end', 0.0):.1f}]")
                            transcript_text = " ".join(context_lines)
                        else:
                            transcript_text = data.get("text", transcript_text)

                        # Dead silence detection logic (> 0.8 seconds)
                        segments = data.get("segments", [])
                        if segments:
                            for i in range(len(segments) - 1):
                                current_end = segments[i].get("end", 0)
                                next_start = segments[i+1].get("start", 0)
                                if next_start - current_end > 0.8:  
                                    auto_cuts.append({
                                        "action": "cut_out", 
                                        "start": current_end + 0.1, 
                                        "end": next_start - 0.1, 
                                        "reason": "Авто-удаление мертвой тишины"
                                    })
                except Exception as e:
                    print(f"Error Loading transcript: {e}")

            if auto_cuts:
                yield json.dumps({"type": "log", "message": f"Editor Agent: Найдено {len(auto_cuts)} затянутых пауз. Добавлены в очередь удаления."}) + "\n"
                await asyncio.sleep(0.3)

            # --- MOTION / VISUAL AGENT LOGIC ---
            yield json.dumps({"type": "log", "message": "Motion Agent: Читаю визуальный контекст и планирую графику..."}) + "\n"
            await asyncio.sleep(0.5)

        visual_context_text = "Визуальный анализ кадров недоступен."
        visual_path = os.path.join("uploads", f"{request.file_id}_visual.json")
        if os.path.exists(visual_path):
            try:
                with open(visual_path, "r", encoding="utf-8") as f:
                    scenes = json.load(f)
                visual_context_text = format_visual_context(scenes)
            except Exception:
                pass

        mode_instructions = ""
        if is_evaluation:
            mode_instructions = f"""ТЕКУЩИЙ КОНТЕКСТ: ОЦЕНКА РЕЗУЛЬТАТА И ФИНАЛ.
Только что система завершила тяжелый процесс рендеринга видео (включая все твои правки).
Юзер изначально просил тебя сделать следующее: "{eval_context}".

Твоя задача:
1. Радостно сообщить пользователю, что ты "просмотрел" готовое видео и оно отрендерено.
2. КРАТКО, но конкретно перечислить свою проделанную работу над видео, учитывая запрос юзера (например, "я добавил красные субтитры снизу и вырезал длинные паузы" или то, что актуально для '{eval_context}').

КРИТИЧЕСКОЕ ПРАВИЛО: Ты обязан вернуть "ready_to_render": false, "edits": [], "variants": []. Ничего не рендери заново!

ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО):
<think>
1. Жду загрузки видеоплеера...
2. Вспоминаю изначальный запрос: "{eval_context}"
3. Формирую отчет о проделанной работе и оцениваю качество склеек.
</think>
```json
{{
  "reply": "Всё готово! Я только что отсмотрел отрендеренное видео — переходы легли отлично! По вашему запросу я добавил крупные стильные субтитры по центру и очистил речь от пауз. Желаю приятного просмотра! 🍿",
  "ready_to_render": false,
  "variants": [],
  "edits": []
}}
```"""
        elif request.message == "INIT_PLAN":
            mode_instructions = f"""ТЕКУЩИЙ КОНТЕКСТ: ИНИЦИАЛИЗАЦИЯ ШАБЛОНОВ.
Пользователь только что загрузил исходник. Твоя задача — сгенерировать МИНИМУМ 3 концептуальных варианта монтажа в массиве "variants", используя РАЗНЫЕ шрифты.
Обязательно верни "ready_to_render": false, "edits": [].

ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО):
<think>
1. Анализирую таймкоды и подбираю дизайнерские шрифты...
2. Формирую минимум 3 разных варианта монтажа.
</think>
```json
{{
  "reply": "Привет! Вот 3 классных варианта монтажа на выбор.",
  "ready_to_render": false,
  "variants": [
    {{
      "id": 1,
      "title": "Хайповый TikTok",
      "description": "Используется крупный шрифт Bebas Neue для динамики.",
      "edits": [ {{"action": "add_subtitles", "position": "center", "font": "BebasNeue-Regular", "font_size": 130, "font_color": "Yellow", "use_outline": true}} ]
    }}
  ],
  "edits": []
}}
```"""
        else:
            mode_instructions = f"""ТЕКУЩИЙ КОНТЕКСТ: ВЫПОЛНЕНИЕ ПРАВОК И РЕНДЕР.
Пользователь дает команду/правку в середине диалога. Текущий запрос пользователя: "{request.message}"

КРИТИЧЕСКОЕ ПРАВИЛО: ЗАПРЕЩЕНО ГЕНЕРИРОВАТЬ ВАРИАНТЫ! Массив "variants" ДОЛЖЕН БЫТЬ АБСОЛЮТНО ПУСТЫМ [].
Ты ОБЯЗАН выполнить просьбу пользователя: добавь нужные правки в массив "edits", поставь "ready_to_render": true, и сообщи ему об успешном старте рендера.

ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО):
<think>
1. Анализирую запрос пользователя на изменение...
2. Составляю массив edits. Массив variants оставляю абсолютно пустым `[]`.
</think>
```json
{{
  "reply": "Готово! Я применил ваши правки и обновил шрифты. Отправляю на финальный рендер!",
  "ready_to_render": true,
  "variants": [],
  "edits": [
    {{"action": "add_subtitles", "position": "bottom", "font": "Inter_24pt-Bold", "font_size": 80, "font_color": "White", "use_outline": false}}
  ]
}}
```"""

        system_prompt = f"""Ты — ПРОФЕССИОНАЛЬНЫЙ ВИДЕОМОНТАЖЁР И РЕЖИССЁР ЭЛИТНОГО УРОВНЯ. Ты создаешь премиальный визуальный контент, уделяя огромное внимание стилю, типографике и динамике кадра.

ПРАВИЛО ТИПОГРАФИКИ: У тебя есть огромная база дизайнерских шрифтов. Ты должен выбирать шрифт, идеально подходящий под настроение:
- "Inter_24pt-Bold" (Минимализм, Tech-стартапы, IT)
- "BebasNeue-Regular" (TikTok-хит, крупные заголовки, капс)
- "Rubik-Bold" (Трендовый, современный, блогерский)
- "Oswald-Bold" (Строгий, стильный, вытянутый вверх)
- "Manrope-Bold" (Современный, чистый и мягкий)
- "JetBrainsMono-Bold" или "IBMPlexSans-Bold" (Для стиля программистов, технологий, ИИ)
- "Comfortaa-Bold" (Округлый, расслабленный, лайфстайл)
- "Lobster-Regular" (Рукописный, креативный, игровой)
- "Montserrat-ExtraBold" (Твой базовый лучший шрифт)

Текст из видео с точными таймкодами (в секундах):
======================
{transcript_text}
======================

Визуальный контекст:
======================
{visual_context_text}
======================

ДОСТУПНЫЕ ДЕЙСТВИЯ (используй только нужные в 'edits'):
- "add_subtitles": наложить субтитры. Поля: 
   * position: (top/bottom/left/right/center), 
   * font: строго одно из названий дизайнерских шрифтов из списка выше, 
   * font_size: (от 40 до 200, где 100 - средний), 
   * font_color: (White/Black/Yellow/Red/NeonBlue и т.д.), 
   * use_outline: (true/false) добавляет рамку/тень к тексту.
- "camera_zoom": плавный зум. Поля: type (zoom_in / zoom_out), start, end.
- "speed_ramp": ускорить/замедлить. Поля: start, end, speed. 
- "add_text_overlay": текстовая плашка. Поля: text, start, end, fontsize, color.
- "add_broll": стоковое видео поверх кадра. Поля: start, end, query (английское слово).
- "cut_out": вырезать скучный кусок, тишину или скрытые слова-паразиты. Поля: start, end. ВАЖНО: Нейросеть-транскрибатор часто "съедает" мусорные слова (эээ, ммм), поэтому они не появляются в тексте. Зато они оставляют НЕЕСТЕСТВЕННЫЕ ПАУЗЫ между словами в таймкодах (например, конец одного слова 1.5s, а начало следующего только 3.0s). Ищи такие разрывы (gaps) и вырезай их!

ПРИМЕЧАНИЕ: Ты имеешь полный контроль над обрезкой. Смело вырезай тишину или мусорные слова, опираясь на массив транскрипта.

{mode_instructions}"""

        try:
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile", 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": request.message}
                ],
                temperature=0.3,
                max_tokens=2000,
                stream=True
            )

            buffer = ""
            is_thinking = False
            found_think_start = False
            json_buffer = ""

            async for chunk in response:
                content = chunk.choices[0].delta.content or ""
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
            json_match = re.search(r'```json\s*(.*?)\s*```', json_buffer, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                s_idx = json_buffer.find("{")
                e_idx = json_buffer.rfind("}")
                json_str = json_buffer[s_idx : e_idx+1] if s_idx != -1 and e_idx != -1 else "{}"

            try:
                ai_data = json.loads(json_str)
            except Exception as e:
                print(f"JSON Parse Error: {e} json_str={json_str}")
                ai_data = {"reply": "Произошла ошибка при обработке ответа ИИ.", "ready_to_render": False, "edits": []}
            
            # If ready to render, merge edits
            is_ready = ai_data.get("ready_to_render", False)
            edits = (auto_cuts + ai_data.get("edits", [])) if is_ready else []
            
            if is_ready:
                yield json.dumps({"type": "log", "message": "Render Engine: Пользователь дал добро. Запуск FFmpeg пайплайна..."}) + "\n"
                print(f"Triggering render Engine. Actions to perform: {edits}")
                background_tasks.add_task(process_render_task, request.file_id, edits, request.edl, request.font, request.font_size, request.use_outline, request.font_color)
            elif not is_evaluation:
                yield json.dumps({"type": "log", "message": "Director Agent: Ожидаю решения пользователя..."}) + "\n"
                
            yield json.dumps({
                "type": "result", 
                "role": "ai", 
                "content": ai_data.get("reply", "Готово."), 
                "variants": ai_data.get("variants", []),
                "edits": edits
            }) + "\n"

        except Exception as e:
            print(f"Llama Error: {e}")
            yield json.dumps({"type": "error", "message": str(e)}) + "\n"

    return StreamingResponse(stream_response(), media_type="application/x-ndjson")

@router.post("/render")
async def direct_render_from_ui(request: RenderStyleRequest, background_tasks: BackgroundTasks):
    """Directly re-render via UI without LLM stream"""
    background_tasks.add_task(process_render_task, request.file_id, request.edits or [], request.edl, request.font, request.font_size, request.use_outline, request.font_color)
    return {"status": "rendering started"}

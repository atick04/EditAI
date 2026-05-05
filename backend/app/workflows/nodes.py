import os
import json
import asyncio
import re
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from app.services.vlm_service import format_visual_context
from app.workflows.state import VideoEditingState
from app.services.template_service import get_template

FILLER_WORDS = {"аааааа", "ээ", "мм", "эм", "ну", "типа", "короче", "в общем", "значит", "как бы", "аа", "э-э", "м-м", "эээ", "ммм", "ну типа"}

# Initialize LLM with streaming enabled
llm = ChatGroq(model="llama-3.3-70b-versatile", temperature=0.3, max_tokens=6000, streaming=True)

async def prepare_context_node(state: VideoEditingState) -> VideoEditingState:
    file_id = state.get("file_id")
    is_evaluation = state.get("is_evaluation", False)
    user_message = state.get("user_message", "")
    
    transcript_path = os.path.join("uploads", f"{file_id}_transcript.json")
    visual_path = os.path.join("uploads", f"{file_id}_visual.json")
    
    transcript_text = "Транскрипт пока не готов."
    visual_context_text = "Визуальный анализ кадров недоступен."
    auto_cuts = []
    
    template_id = state.get("template_id")
    template_config = None
    if template_id:
        tpl = get_template(template_id)
        if tpl:
            template_config = tpl.dict()

    # 1. Transcript and Auto Cuts
    if not is_evaluation and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                words = data.get("words", [])
                if words:
                    context_lines = []
                    for i, w in enumerate(words):
                        text_word = w.get('word', '').strip()
                        start_w = w.get('start', 0.0)
                        end_w = w.get('end', 0.0)
                        
                        clean_word = re.sub(r'[^\w\s-]', '', text_word).lower()
                        
                        if clean_word in FILLER_WORDS:
                            # Точечный динамический отступ: не залезая на чужие слова
                            prev_end = words[i-1].get('end', 0.0) if i > 0 else 0.0
                            next_start = words[i+1].get('start', end_w + 0.5) if i < len(words) - 1 else end_w + 0.5
                            
                            safe_start = max(start_w - 0.03, prev_end + 0.01)
                            safe_end = min(end_w + 0.03, next_start - 0.01)
                            
                            auto_cuts.append({
                                "action": "cut_out", 
                                "start": round(safe_start, 2), 
                                "end": round(safe_end, 2), 
                                "reason": f"Слово-паразит: {text_word}"
                            })
                        else:
                            context_lines.append(f"{text_word}[{start_w:.1f}-{end_w:.1f}]")
                            
                        # ПРОФЕССИОНАЛЬНАЯ ОБРЕЗКА (J-cuts, L-cuts, сохранение ритма)
                        if i < len(words) - 1:
                            next_word_start = words[i+1].get('start', 0.0)
                            pause_duration = next_word_start - end_w
                            # Не режем "драматические" и естественные паузы. Режем только затянутые куски (> 0.8 сек)
                            if pause_duration > 0.8:
                                # Оставляем "воздух" (0.15 сек после слова, 0.15 сек перед новым), чтобы избежать "эффекта робота"
                                safe_cut_start = end_w + 0.15
                                safe_cut_end = next_word_start - 0.15
                                if safe_cut_end > safe_cut_start:
                                    auto_cuts.append({
                                        "action": "cut_out",
                                        "start": round(safe_cut_start, 2),
                                        "end": round(safe_cut_end, 2),
                                        "reason": "Затянутая пауза"
                                    })

                    transcript_text = " ".join(context_lines)
                else:
                    transcript_text = data.get("text", transcript_text)
        except Exception as e:
            print(f"Error Loading transcript: {e}")

    # 2. Visual Context
    if os.path.exists(visual_path):
        try:
            with open(visual_path, "r", encoding="utf-8") as f:
                scenes = json.load(f)
            visual_context_text = format_visual_context(scenes)
        except Exception:
            pass

    return {
        "transcript_text": transcript_text,
        "visual_context": visual_context_text,
        "auto_cuts": auto_cuts,
        "template_config": template_config
    }

async def director_agent_node(state: VideoEditingState) -> VideoEditingState:
    is_evaluation = state.get("is_evaluation", False)
    user_message = state.get("user_message", "")
    transcript_text = state.get("transcript_text", "")
    visual_context_text = state.get("visual_context", "")
    eval_context = user_message.replace("SYSTEM_EVALUATION: ", "").replace("SYSTEM_EVALUATION:", "").strip() if is_evaluation else ""
    template_config = state.get("template_config")

    template_instructions = ""
    if template_config:
        template_instructions = f"""
==== НАСТРОЙКИ ВЫБРАННОГО ШАБЛОНА ====
ПОЛЬЗОВАТЕЛЬ ВЫБРАЛ СТИЛЬ: "{template_config.get('name')}"

ТЫ ОБЯЗАН ИСПОЛЬЗОВАТЬ СТРОГО ЭТИ ПАРАМЕТРЫ ПРИ ФОРМИРОВАНИИ EDITS:
{json.dumps(template_config, ensure_ascii=False, indent=2)}

УКАЗАНИЯ ДЛЯ ТЕБЯ:
- Субтитры (`add_subtitles`): используй точный `font` из шаблона, точный `fontSize`, `position` (top/center/bottom), цвета из `colorMap`, параметры `animation` и `useOutline`.
- Темп (Pacing): проанализируй "editing" конфиг. Если `zoomFrequency` = "high" — генерируй много экшенов `camera_zoom`. Если `brollFrequency` = "high" — добавь много `add_broll` вставок.
========================================
"""

    mode_instructions = ""
    if is_evaluation:
        mode_instructions = f"""ТЕКУЩИЙ КОНТЕКСТ: РЕЖИМ ОЦЕНКИ (ШАГ 7 — ПРОВЕРИТЬ РЕЗУЛЬТАТ).

Рендеринг завершён. Запрос юзера был: "{eval_context}".

Твой отчёт должен:
1. Сообщить что ты просмотрел итоговое видео
2. Кратко и конкретно описать что именно было сделано:
   - Какой стиль и шрифты были применены?
   - Были ли вырезаны паузы?
   - Были ли добавлены бироллы, зум, ускорение?
3. Сказать соответствует ли результат запросу юзера
4. Пригласить юзера к диалогу если он хочет что-то изменить

КРИТИЧЕСКОЕ ПРАВИЛО: Верни "ready_to_render": false, "edits": [], "variants": []. НЕ запускай рендер повторно!

ФОРМАТ ОТВЕТА:
<think>
1. Вспоминаю запрос юзера: "{eval_context}"
2. Перечисляю шаги которые были выполнены из пайплайна
3. Формирую живое и конкретное сообщение о проделанной работе
</think>
```json
{{
  "reply": "[живой отчёт о проделанной работе]",
  "ready_to_render": false,
  "variants": [],
  "edits": []
}}
```"""
    elif user_message == "INIT_PLAN":
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
        mode_instructions = f"""ТЕКУЩИЙ КОНТЕКСТ: ВЫПОЛНЕНИЕ ПРАВОК И ДИАЛОГ.
Пользователь обращается к тебе (ИИ-режиссеру) прямо сейчас. Текущий запрос: "{user_message}"

ИНСТРУКЦИЯ К ДЕЙСТВИЮ:
1. Если запрос пользователя ТРЕБУЕТ применения инструментов монтажа (добавления правок):
   - Добавь нужные блоки в массив `edits_patch`.
   - КРИТИЧЕСКОЕ ПРАВИЛО ПО РЕНДЕРУ: Поставь "ready_to_render": false (если только пользователь прямо не попросил "срендери", "собери видео", "покажи результат"). По умолчанию ты должен просто накапливать правки!
   - Верни `"reply": ""` (пустую строку) если ты запустил рендер. Но если рендер `false`, дай короткий текстовый ответ (например "Правка добавлена, собираем?").

2. Если запрос пользователя — это просто вопрос, беседа, просьба дать совет или просто болтовня:
   - Поставь "ready_to_render": false.
   - Напиши развернутый и живой ответ в `"reply"`.

КРИТИЧЕСКОЕ ПРАВИЛО: Массив "variants" ДОЛЖЕН БЫТЬ АБСОЛЮТНО ПУСТЫМ [] всегда в этом режиме.

ФОРМАТ ОТВЕТА (ОБЯЗАТЕЛЬНО):
<think>
1. Анализирую запрос... Это команда на монтаж или вопрос? Просил ли юзер запуск рендера?
2. Составляю список команд на добавление или удаление слоев (patch).
3. Ставлю ready_to_render.
</think>
```json
{{
  "reply": "",
  "ready_to_render": true,
  "variants": [],
  "edits_patch": {{
    "remove_action_types": [], 
    "append_edits": [
      {{"action": "add_broll", "start": 0, "end": 3, "query": "business"}}
    ]
  }}
}}
```"""

    active_edits = state.get("active_edits", [])
    persistence_instructions = ""
    if active_edits:
        persistence_instructions = f"""
==== ТЕКУЩЕЕ СОСТОЯНИЕ (ACTIVE EDITS) ====
В видео уже применены следующие инструменты:
{json.dumps(active_edits, ensure_ascii=False, indent=2)}

📌 КАК РАБОТАТЬ С ПАТЧАМИ (edits_patch):
Если юзер просит ПРОСТО добавить что-то (например, "добавь бироллы"), не трогай старые слои. Просто вложи новые бироллы в `append_edits`. Бэкенд склеит их сам!
Если юзер просит "изменить", "сдвинуть" или "переделать" существующие элементы (например, субтитры), ты должен НАПИСАТЬ `"add_subtitles"` в массив `"remove_action_types"`, чтобы старые сабы удалились, а в `"append_edits"` сгенерировать новые субтитры.
========================================
"""

    system_prompt = f"""Ты — ПРОФЕССИОНАЛЬНЫЙ ИИ-РЕЖИССЁР ЭЛИТНОГО УРОВНЯ. Твой монтаж должен быть кинематографичным, с чувством ритма, а не роботизированным!

🔥 ПРОФЕССИОНАЛЬНЫЕ ПРАВИЛА МОНТАЖА (СТРОГО СОБЛЮДАТЬ!):
1. Метафоричность, а не буквальность (B-roll): Не ищи B-roll "горящий мост" на фразу "сжег мосты". Ищи концептуальные кадры (например "explosion", "dramatic cinematic", "change").
2. Правило J-Cut (Внахлест): Видео B-roll ДОЛЖНО начинаться за 0.5 сек ДО того, как спикер произнесет ключевое слово. Это создает эффект предвосхищения!
3. Визуальный воздух (Графика G1): Не перегружай кадр! Если идет список из 5 пунктов, не выводи их все за секунду. Делай плавные графические акценты. Поручай агенту по графике (через hyperframes_html) оставлять место на экране.
4. Разнообразие: Чередуй графику и B-roll, чтобы не было 10 секунд одного и того же приема.

Твои задачи:
1. Инициализация (когда юзер просит план) — создать 3 варианта шрифтов (в массиве variants).
2. Обработка команд (добавить бироллы, удалить музыку и т.д.) — генерировать патчи (edits_patch) для изменения JSON-чертежа.
3. Общение — давать короткие, экспертные советы по режиссуре.

{persistence_instructions}

ПАЙПЛАЙН МОНТАЖА (следуй ему в мышлении):
1. ПОНЯТЬ ЦЕЛЬ — что хочет юзер? Какой формат (Shorts/Reels/YouTube)?
2. РАЗБИТЬ НА СЦЕНЫ — читаю транскрипт, делю на смысловые блоки по 5-15 секунд
3. ОПРЕДЕЛИТЬ СТИЛЬ — выбираю шрифт, цвет, энергетику под тон видео
4. СПЛАНИРОВАТЬ РИТМ — чередую: крупный план → зум → B-roll → крупный план
5. ПРИМЕНИТЬ МОНТАЖ — формирую массив edits с ТОЧНЫМИ таймкодами из транскрипта
6. ПРОВЕРИТЬ — всё ли синхронизировано? Нет ли наложений друг на друга?

====== ЗОЛОТЫЕ ПРАВИЛА МОНТАЖА ======

📌 B-ROLL (стоковое видео):
- КОГДА ИСПОЛЬЗОВАТЬ: ТОЛЬКО когда спикер говорит о чём-то АБСТРАКТНОМ (технологии, природа, бизнес, город), и в кадре нет важного действия
- КОГДА НЕ ИСПОЛЬЗОВАТЬ: когда спикер показывает что-то руками, демонстрирует продукт, или когда его эмоции важны
- ДЛИТЕЛЬНОСТЬ: строго 2-4 секунды! Стоковое видео дольше 4 сек выглядит дёшево
- QUERY: пиши КОНКРЕТНЫЕ английские запросы. НЕ "background", а "city skyline night", "laptop coding", "team meeting office"
- МАКСИМУМ 2-3 B-roll вставки на минуту видео. Не больше!
- B-roll НИКОГДА не ставится в начало видео (0-3 сек) — зритель должен сначала увидеть спикера

📌 CAMERA ZOOM:
- zoom_in на КЛЮЧЕВЫХ словах — когда спикер делает важное утверждение
- Длительность зума: 1-2 секунды максимум
- Не более 3-4 зумов на минуту видео

📌 СУБТИТРЫ:
- ВСЕГДА указывай animation_style! Статичные субтитры запрещены
- pop/bounce — для энергичных, slide_up — для Shorts, glow — для кино, karaoke — для музыки

📌 ГРАФИКА vs B-ROLL (НИКОГДА НЕ ПУТАЙ!):
- B-roll (add_broll) = ЖИВОЕ стоковое видео с Pexels. Для ИЛЛЮСТРАЦИИ абстрактных концепций
- Графика (hyperframes_html) = АНИМИРОВАННЫЕ плашки, инфографика. Для ДАННЫХ, цифр, списков
- НЕЛЬЗЯ ставить B-roll и графику на одинаковый таймкод!

========================================

ПРАВИЛО ТИПОГРАФИКИ — выбирай шрифт под настроение:
- "Inter_24pt-Bold" (Минимализм, Tech, IT)
- "BebasNeue-Regular" (TikTok, крупные заголовки)
- "Rubik-Bold" (Трендовый, блогерский)
- "Oswald-Bold" (Строгий, стильный)
- "Manrope-Bold" (Современный, мягкий)
- "JetBrainsMono-Bold" (Код, технологии, ИИ)
- "Comfortaa-Bold" (Лайфстайл, расслабленный)
- "Montserrat-ExtraBold" (Универсальный)

Транскрипт с таймкодами:
======================
{transcript_text}
======================

Визуальный контекст:
======================
{visual_context_text}
======================
{persistence_instructions}
{template_instructions}

ДОСТУПНЫЕ ИНСТРУМЕНТЫ (edits):
- "add_subtitles": субтитры. Поля: position, font, font_size, font_color, use_outline, animation_style
- "camera_zoom": зум. Поля: type (zoom_in/zoom_out), start, end
- "speed_ramp": скорость. Поля: start, end, speed
- "add_text_overlay": текстовая плашка. Поля: text, start, end, fontsize, color
- "add_broll": стоковое видео. Поля: start, end, query (КОНКРЕТНЫЙ английский запрос для Pexels)
*(Удаление пауз и слов-паразитов выполняется автоматически. НЕ генерируй cut_out)*

{mode_instructions}"""

    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message)
    ])
    
    return {"messages": [response]}


async def graphics_agent_node(state: VideoEditingState) -> VideoEditingState:
    is_evaluation = state.get("is_evaluation", False)
    user_message = state.get("user_message", "")
    transcript_text = state.get("transcript_text", "")
    visual_context_text = state.get("visual_context", "")
    template_config = state.get("template_config")
    
    template_instructions = ""
    if template_config:
        graphics_conf = template_config.get("graphics", {})
        template_instructions = f"""
АДАПТИРУЙ ЦВЕТА ПОД ТЕМУ '{graphics_conf.get('theme', 'vibrant')}'.
(cinematic = белый, серый, полупрозрачный. vibrant = сочные неоновые цвета).
"""
    
    if is_evaluation or user_message == "INIT_PLAN":
        return {"messages": []}

    # Читаем шаблоны из библиотеки
    templates_text = ""
    try:
        lib_path = os.path.join(os.path.dirname(__file__), "..", "templates", "graphics_library.json")
        if os.path.exists(lib_path):
            with open(lib_path, "r", encoding="utf-8") as f:
                lib_data = json.load(f)
                templates_text = "\n====== ДОСТУПНЫЕ ПРЕМИУМ ШАБЛОНЫ (ИСПОЛЬЗУЙ ИХ!) ======\n"
                for t in lib_data.get("templates", []):
                    templates_text += f"\n👉 Шаблон: {t['name']} (ID: {t['id']})\n"
                    templates_text += f"Когда использовать: {t['use_when']}\n"
                    templates_text += f"HTML: {t['html_template']}\n"
                    templates_text += f"Анимация (GSAP): {t['animation']}\n"
                    templates_text += "---"
    except Exception as e:
        print(f"Failed to load graphics library: {e}")

    system_prompt = f"""Ты — ЭЛИТНЫЙ MOTION-ДИЗАЙНЕР. Ты создаёшь графику через Hyperframes (HTML + CSS + GSAP).

⚠️ ТВОЯ РОЛЬ: Ты делаешь ТОЛЬКО графику (плашки, инфографику, карточки). НЕ B-roll!

🔥 ПРОФЕССИОНАЛЬНЫЕ ПРАВИЛА ДИЗАЙНА:
1. Иерархия и Композиция: Оставляй "воздух". Не перекрывай лицо спикера. Распределяй графику по углам или по золотому сечению.
2. Motion Blur: Анимация не должна быть "деревянной" как в PowerPoint. Используй легкий blur при движении в GSAP: `filter: "blur(10px)"` на старте, переходящий в `filter: "blur(0px)"`. 
3. Цветовой баланс: Не используй вырвиглазные цвета наугад. Строй палитру от белого, серого, мягкого неонового (#06b6d4, #8b5cf6, #10b981) с использованием Glassmorphism (blur фона).

КОГДА СОЗДАВАТЬ ГРАФИКУ:
✅ Спикер называет ЦИФРУ или СТАТИСТИКУ → покажи число в стильной плашке
✅ Спикер перечисляет СПИСОК → покажи пункты с галочками
✅ Спикер говорит ТЕРМИН → покажи текстовую карточку с неоновой обводкой
✅ Спикер делает ВЫВОД → покажи ключевую мысль в большой glassmorphism-карточке
✅ Спикер говорит про ЦЕЛИ, СТРАТЕГИИ, ИНСАЙТЫ → используй премиум-шаблоны из библиотеки ниже!

КОГДА НЕ СОЗДАВАТЬ:
❌ Спикер просто разговаривает без конкретных данных
❌ Юзер не просил добавлять графику

ХОЛСТ: 1080x1920 (вертикальный).
ДИЗАЙН-ПРАВИЛА:
1. НЕ используй <img src> — рисуй SVG, CSS-градиенты, box-shadow
2. Шрифты: font-family:'Inter',sans-serif. Размер: 48-120px
3. Glassmorphism: backdrop-filter:blur(24px); background:rgba(255,255,255,0.08)
4. НИКОГДА не закрывай лицо! Безопасные зоны: низ (bottom: 200-400px), верхние углы (top: 150-300px)
5. Каждая графика: 3-5 секунд максимум
{templates_text}

====== АРХИТЕКТУРА HYPERFRAMES (СТРОГО СОБЛЮДАЙ!) ======

Каждая композиция — это ОДИН корневой `<div>` с `data-composition-id="main"`.
Внутри него лежат элементы-клипы с `class="clip"`, `data-start`, `data-duration`, `data-track-index`.
ОДИН `<script>` в конце создаёт timeline и регистрирует его под тем же ID "main".

ОБЯЗАТЕЛЬНАЯ СТРУКТУРА html_content:
```
<div id="root" data-composition-id="main" data-start="0" data-duration="{{ОБЩАЯ_ДЛИТЕЛЬНОСТЬ}}" data-width="1080" data-height="1920">

  <div id="el1" class="clip" data-start="2" data-duration="4" data-track-index="1"
       style="position:absolute; ...">
    СОДЕРЖИМОЕ
  </div>

  <div id="el2" class="clip" data-start="8" data-duration="3" data-track-index="2"
       style="position:absolute; ...">
    СОДЕРЖИМОЕ
  </div>

  <script>
    const tl = gsap.timeline({{ paused: true }});
    tl.to("#el1", {{opacity:1, y:-40, duration:0.6, ease:"power3.out"}}, 2);
    tl.to("#el1", {{opacity:0, duration:0.4, ease:"power2.in"}}, 5.5);
    tl.to("#el2", {{opacity:1, duration:0.5, ease:"back.out(1.4)"}}, 8);
    tl.to("#el2", {{opacity:0, duration:0.4, ease:"power2.in"}}, 10.5);
    window.__timelines = window.__timelines || {{}};
    window.__timelines["main"] = tl;
  </script>
</div>
```

КРИТИЧЕСКИЕ ПРАВИЛА:
- data-composition-id ТОЛЬКО на корневом div, СОВПАДАЕТ с ключом в window.__timelines
- data-duration на корневом div = максимальное время всех анимаций
- Каждый видимый элемент: class="clip" + data-start + data-duration + data-track-index
- Все элементы начинают с opacity:0, GSAP анимирует появление
- НЕ ставь data-composition-id на дочерние элементы!
- Второй параметр в tl.to() — это АБСОЛЮТНОЕ время на таймлайне (не относительное!)

{template_instructions}

Транскрипт: {transcript_text}
Визуальный контекст: {visual_context_text}

ФОРМАТ ОТВЕТА:
<think>Есть ли цифры, списки, термины? На каких таймкодах?</think>
```json
{{
  "reply": "",
  "ready_to_render": true,
  "edits_patch": {{
    "remove_action_types": ["hyperframes_html"],
    "append_edits": [
      {{
        "action": "hyperframes_html",
        "html_content": "... ВАЛИДНЫЙ HTML ..."
      }}
    ]
  }}
}}
```

⚠️ ВАЖНО ПРО ФОРМАТ JSON: Значение поля "html_content" должно быть обернуто в ОБЫЧНЫЕ двойные кавычки ("), а НЕ в обратные кавычки (`). Использование обратных кавычек приведет к фатальной ошибке JSON Parse Error! Все двойные кавычки ВНУТРИ HTML кода должны быть строго экранированы (\\") либо заменены на одинарные кавычки (').

Если графика не нужна — верни `append_edits: []`.
"""


    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message)
    ])
    
    return {"messages": [response]}


"use client";

import { use, useState, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import TimelineEditor from "@/components/TimelineEditor";
import VideoTimeline from "@/components/VideoTimeline";

export default function EditorPage({ params }: { params: Promise<{ id: string }> }) {
    const resolvedParams = use(params);
    const { id } = resolvedParams;
    const searchParams = useSearchParams();
    const filename = searchParams.get('filename');
    const router = useRouter();

    const [message, setMessage] = useState("");
    const [fontStyle, setFontStyle] = useState("Arial");
    const [fontSize, setFontSize] = useState(100);
    const [fontColor, setFontColor] = useState("White");
    const [useOutline, setUseOutline] = useState(true);
    const [chat, setChat] = useState<{ role: string, text?: string, steps?: any[], variants?: any[] }[]>([
        { role: "ai", text: "Привет! Исходник видео загружен. Как только Whisper распознает речь, внизу появятся ваши субтитры. 🎉 Попросите меня наложить их на видео!" }
    ]);
    const [transcript, setTranscript] = useState<any>(null);
    const [renderedUrl, setRenderedUrl] = useState<string | null>(null);
    const [logs, setLogs] = useState<string[]>([]);
    const [hasInitialized, setHasInitialized] = useState(false);
    const [activeEdits, setActiveEdits] = useState<any[]>([]);
    const [multiTrackEdl, setMultiTrackEdl] = useState<{v1: {start: number, end: number}[], a1: {start: number, end: number}[]} | null>(null);
    const [audioPeaks, setAudioPeaks] = useState<number[]>([]);
    const [activeTab, setActiveTab] = useState<'text' | 'video'>('text');
    const chatEndRef = useRef<HTMLDivElement>(null);
    const chatContainerRef = useRef<HTMLDivElement>(null);
    
    const hyperframesEdits = activeEdits.filter(e => e.action === 'add_hyperframes_graphics');
    const graphicsHtml = hyperframesEdits.length > 0 ? `
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 100%; height: 100%; overflow: hidden; background: transparent; display: flex; align-items: center; justify-content: center; }
      .clip { position: absolute; }
      #preview-container { width: 1080px; height: 1920px; position: relative; transform-origin: center center; background: transparent; overflow: hidden; }
    </style>
  </head>
  <body>
    <div id="preview-container">
      ${hyperframesEdits.map(e => e.html_content).join('\\n')}
    </div>
    <script>
      function resize() {
        const container = document.getElementById('preview-container');
        const scale = Math.min(window.innerWidth / 1080, window.innerHeight / 1920);
        container.style.transform = \`scale(\${scale})\`;
      }
      window.addEventListener('resize', resize);
      resize();
      
      let isSynced = false;
      window.addEventListener('message', (event) => {
          if (event.data && event.data.type === 'sync_time') {
              isSynced = true;
              if (window.__timelines && window.__timelines["main"]) {
                  window.__timelines["main"].pause();
                  window.__timelines["main"].seek(event.data.time);
              }
          }
      });

      // Automatically play all animations for isolated preview pane!
      setTimeout(() => {
        if (!isSynced && window.__timelines && window.__timelines["main"]) {
           const tl = window.__timelines["main"];
           const clips = Array.from(document.querySelectorAll('.clip'));
           if (clips.length > 0) {
               let minStart = Math.min(...clips.map(c => parseFloat(c.getAttribute('data-start') || 0)));
               let maxEnd = Math.max(...clips.map(c => parseFloat(c.getAttribute('data-start') || 0) + parseFloat(c.getAttribute('data-duration') || 0)));
               
               tl.seek(minStart).play();
               setInterval(() => {
                   if (tl.time() > maxEnd + 0.5) {
                       tl.seek(minStart).play();
                   }
               }, 100);
           }
        }
      }, 500);
    </script>
  </body>
</html>
` : undefined;

    // Template states
    const [templates, setTemplates] = useState<any[]>([]);
    const [selectedTemplate, setSelectedTemplate] = useState<string>("");
    const [showTemplatesDrawer, setShowTemplatesDrawer] = useState<boolean>(false);
    
    // Process States
    const [isAgentTyping, setIsAgentTyping] = useState(false);
    const [isRendering, setIsRendering] = useState(false);
    const isProcessing = isAgentTyping; // Only block input while AI is thinking, NOT during render
    const isRenderingBackground = isRendering; // Render runs in background - user can still chat
    // Guard against duplicate SYSTEM_EVALUATION calls (React StrictMode runs updaters twice)
    const renderInProgressRef = useRef(false);
    const evaluationSentRef = useRef(false);
    const lastUserMessageRef = useRef('');

    // Resizable Timeline State
    const [timelineHeight, setTimelineHeight] = useState(250);
    const [isResizing, setIsResizing] = useState(false);
    
    // Derived Video URLs (must be initialized before useEffects)
    const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    const videoUrl = filename ? `${API_URL}/uploads/${filename}` : null;
    const currentVideo = renderedUrl || videoUrl;

    const videoRef = useRef<HTMLVideoElement>(null);
    const audioRef = useRef<HTMLAudioElement>(null);
    const iframeOverlayRef = useRef<HTMLIFrameElement>(null);
    const [isPlaying, setIsPlaying] = useState(false);
    
    // NLE Real-Time Playback Engine
    const playbackRAF = useRef<number | null>(null);

    // --- CONTINUOUS IFRAME SYNC ---
    useEffect(() => {
        let raf: number;
        const syncIframe = () => {
            if (videoRef.current && iframeOverlayRef.current?.contentWindow) {
                iframeOverlayRef.current.contentWindow.postMessage(
                    { type: 'sync_time', time: videoRef.current.currentTime },
                    '*'
                );
            }
            raf = requestAnimationFrame(syncIframe);
        };
        raf = requestAnimationFrame(syncIframe);
        return () => cancelAnimationFrame(raf);
    }, []);

    // Audio Waveform Peak Generator
    useEffect(() => {
        fetch(`${API_URL}/api/templates`)
            .then(res => res.json())
            .then(data => {
                setTemplates(data || []);
            })
            .catch(err => console.error("Failed to load templates", err));
    }, []);

    useEffect(() => {
        if (!currentVideo) return;
        const generatePeaks = async () => {
            try {
                const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
                const audioCtx = new AudioContextClass();
                const response = await fetch(currentVideo);
                const arrayBuffer = await response.arrayBuffer();
                const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
                const channelData = audioBuffer.getChannelData(0);
                
                const peaks = [];
                const samples = 1000; // Generate 1000 data points for smooth UI
                const blockSize = Math.floor(channelData.length / samples);
                for (let i = 0; i < samples; i++) {
                    let blockStart = blockSize * i;
                    let sum = 0;
                    for (let j = 0; j < blockSize; j++) {
                        sum += Math.abs(channelData[blockStart + j]);
                    }
                    peaks.push(sum / blockSize);
                }
                
                // Normalize peaks
                const maxPeak = Math.max(...peaks);
                const normalizedPeaks = peaks.map(p => (p / maxPeak) * 100);
                
                setAudioPeaks(normalizedPeaks);
            } catch (error) {
                console.error("Failed to generate audio peaks:", error);
                setAudioPeaks(Array(100).fill(20)); // Fake flat fallback
            }
        };
        generatePeaks();
    }, [currentVideo]);

    useEffect(() => {
        if (!isPlaying || !multiTrackEdl) return;
        
        const loop = () => {
            const vRef = videoRef.current;
            const aRef = audioRef.current;
            if (!vRef || !aRef) return;

            const vTime = vRef.currentTime;
            
            // Check V1 track validation
            const validV1 = multiTrackEdl.v1.find(k => vTime >= k.start && vTime < k.end);
            if (!validV1) {
                // We hit a gap! Jump to next valid V1!
                const nextV1 = multiTrackEdl.v1.find(k => k.start >= vTime);
                if (nextV1) {
                    vRef.currentTime = nextV1.start;
                } else {
                    // Video ended
                    vRef.pause();
                    aRef.pause();
                    setIsPlaying(false);
                    return;
                }
            }

            // Sync A1 track independently (Mute audio if it hits an audio gap)
            // Wait, since playhead is driven by Video time currently, we check if A1 should be playing:
            const validA1 = multiTrackEdl.a1.find(k => vTime >= k.start && vTime < k.end);
            if (!validA1) {
                aRef.muted = true;
            } else {
                aRef.muted = false;
                // Keep audio synced to video time if they drift significantly
                if (Math.abs(aRef.currentTime - vRef.currentTime) > 0.15) {
                    aRef.currentTime = vRef.currentTime;
                }
            }

            playbackRAF.current = requestAnimationFrame(loop);
        };

        // Start
        playbackRAF.current = requestAnimationFrame(loop);

        return () => {
            if (playbackRAF.current) cancelAnimationFrame(playbackRAF.current);
        };
    }, [isPlaying, multiTrackEdl]);

    // Resizing Handler
    useEffect(() => {
        if (!isResizing) return;
        const handlePointerMove = (e: PointerEvent) => {
            const windowHeight = window.innerHeight;
            // padding-bottom is 24px (p-6)
            let newHeight = windowHeight - e.clientY - 24; 
            newHeight = Math.max(150, Math.min(windowHeight * 0.7, newHeight));
            setTimelineHeight(newHeight);
        };
        const handlePointerUp = () => setIsResizing(false);
        
        window.addEventListener('pointermove', handlePointerMove);
        window.addEventListener('pointerup', handlePointerUp);
        return () => {
            window.removeEventListener('pointermove', handlePointerMove);
            window.removeEventListener('pointerup', handlePointerUp);
        };
    }, [isResizing]);

    const duration = transcript?.words?.length ? transcript.words[transcript.words.length - 1].end + 0.5 : 0;

    const scrollToBottom = () => {
        chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    // No auto-scroll on logs or AI messages — user controls the scroll
    // Scroll only happens explicitly when user sends a message

    // 1: Poll for logs & rendered status
    useEffect(() => {
        if (!id) return;
        const fetchStatus = async () => {
            try {
                const res = await fetch(`${API_URL}/api/video/${id}/status`);
                const data = await res.json();

                if (data.logs) {
                    setLogs(data.logs);
                }

                if (data.status === "processing" || data.status === "transcribing") {
                    renderInProgressRef.current = true;
                    setIsRendering(true);
                }

                if (data.status === "ready" && data.filename && renderInProgressRef.current) {
                    renderInProgressRef.current = false;
                    setIsRendering(false);
                    setRenderedUrl(`${API_URL}/uploads/${data.filename}?v=${data.updated_at}`);
                    // Trigger evaluation exactly once — NOT inside a state updater to avoid StrictMode double-invoke
                    if (!evaluationSentRef.current) {
                        evaluationSentRef.current = true;
                        const context = lastUserMessageRef.current;
                        setTimeout(() => {
                            handleSend(`SYSTEM_EVALUATION: ${context}`, true);
                            // Reset after 10s to allow future renders
                            setTimeout(() => { evaluationSentRef.current = false; }, 10000);
                        }, 300);
                    }
                }
            } catch (e) { }
        };
        fetchStatus();
        const interval = setInterval(fetchStatus, 2000);
        return () => clearInterval(interval);
    }, [id]);

    // 2: Poll for transcript data (to show subtitles)
    useEffect(() => {
        if (!id || transcript) return;
        const fetchTranscript = async () => {
            try {
                const res = await fetch(`${API_URL}/api/video/${id}/transcript`);
                const data = await res.json();
                if (data.status !== "processing") {
                    setTranscript(data);
                }
            } catch (e) { }
        };
        fetchTranscript();
        const interval = setInterval(fetchTranscript, 3000);
        return () => clearInterval(interval);
    }, [id, transcript]);
    // 3: Trigger initial AI greeting
    useEffect(() => {
        if (!id || chat.length > 0 || hasInitialized || !transcript) return;
        setHasInitialized(true);
        handleSend("INIT_PLAN", true);
    }, [id, chat.length, hasInitialized, transcript]);

    const handleSend = async (customMessage?: string, isInitial: boolean = false, forceEdits?: any[]) => {
        const textToSend = customMessage || message;
        if (!textToSend.trim() && !forceEdits) return;

        if (!isInitial && textToSend !== "INIT_PLAN" && !textToSend.startsWith("SYSTEM_EVALUATION")) {
            setChat(prev => [...prev, { role: "user", text: textToSend }]);
            lastUserMessageRef.current = textToSend; // Track for post-render evaluation
            if (!customMessage) setMessage("");
        }
        
        // Only scroll when user sends — gives them control while viewing video
        setTimeout(() => scrollToBottom(), 50);

        setIsAgentTyping(true);
        // Track if this request will trigger a render
        let willRender = false;

        try {
            const response = await fetch(`${API_URL}/api/chat`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ 
                    file_id: id, 
                    message: textToSend, 
                    font: fontStyle,
                    font_size: fontSize,
                    font_color: fontColor,
                    use_outline: useOutline,
                    force_edits: forceEdits || null,
                    active_edits: activeEdits,
                    template_id: selectedTemplate || null
                })
            });

            const reader = response.body?.getReader();
            const decoder = new TextDecoder("utf-8");

            if (reader) {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    
                    const chunk = decoder.decode(value, { stream: true });
                    const lines = chunk.split("\n").filter(line => line.trim() !== "");
                    
                    for (const line of lines) {
                        try {
                            const data = JSON.parse(line);
                            if (data.type === "log") {
                                setLogs(prev => [...prev, data.message]);
                                setTimeout(() => scrollToBottom(), 50);
                            } else if (data.type === "reasoning") {
                                setChat(prev => {
                                    const copy = [...prev];
                                    const last = copy[copy.length - 1];
                                    if (last?.role === "reasoning") {
                                        const newSteps = [...(last.steps || [])];
                                        const existing = newSteps.find(s => s.step === data.step);
                                        if (existing) {
                                            existing.status = data.status;
                                        } else {
                                            newSteps.push({ step: data.step, status: data.status });
                                        }
                                        copy[copy.length - 1] = { ...last, steps: newSteps };
                                        return copy;
                                    } else {
                                        return [...copy, { role: "reasoning", steps: [{ step: data.step, status: data.status }] }];
                                    }
                                });
                                setTimeout(() => scrollToBottom(), 50);
                            } else if (data.type === "result") {
                                // If agent is triggering a render - lock UI immediately, don't wait for polling
                                if (data.ready_to_render === true || (data.edits && data.edits.length > 0 && !data.variants?.length)) {
                                    willRender = true;
                                    renderInProgressRef.current = true; // Guard against stale 'ready' from polling
                                    setIsRendering(true);
                                }
                                // Only show ai message if content is non-empty (agent silences itself when rendering)
                                if (data.content && data.content.trim() !== "") {
                                    setChat(prev => [...prev, { role: "ai", text: data.content, variants: data.variants || [] }]);
                                }
                                if (data.edits && data.edits.length > 0 && !data.variants?.length) {
                                    // Smart merge: new edits from agent replace old edits of the same action type,
                                    // but KEEP any existing edits for action types the agent didn't touch.
                                    setActiveEdits((prev: any[]) => {
                                        const newActionTypes = new Set(data.edits.map((e: any) => e.action));
                                        // Remove old edits of the same types that are being replaced
                                        const kept = prev.filter((e: any) => !newActionTypes.has(e.action));
                                        return [...kept, ...data.edits];
                                    });
                                    
                                    // Generate synchronized base EDL from AI text cut_outs
                                    const dur = duration || 10000;
                                    const cuts = data.edits.filter((e: any) => e.action === "cut_out").sort((a: any, b: any) => a.start - b.start);
                                    if (cuts.length > 0) {
                                        let current = 0;
                                        const keeps = [];
                                        for (const cut of cuts) {
                                            if (cut.start > current) keeps.push({start: current, end: cut.start});
                                            current = Math.max(current, cut.end);
                                        }
                                        if (current < dur) keeps.push({start: current, end: dur});
                                        setMultiTrackEdl({ v1: keeps, a1: keeps });
                                    }
                                }
                                setTimeout(() => scrollToBottom(), 50);
                            } else if (data.type === "error") {
                                setChat(prev => [...prev, { role: "ai", text: "Ошибка: " + data.message }]);
                            }
                        } catch (e) {
                            console.error("Failed to parse chunk:", line);
                        }
                    }
                }
            }
        } catch (error) {
            setChat(prev => [...prev, { role: "ai", text: "Ошибка связи с ИИ-сервером." }]);
        } finally {
            setIsAgentTyping(false);
            // If render was triggered, keep isRendering=true — it will be cleared by the polling
            // when the file is actually ready. Do NOT clear it here.
        }
    };

    const handleDirectRender = async () => {
        try {
            setIsRendering(true);
            setChat((prev: any) => [...prev, {
                role: "system",
                text: `🎬 Запуск прямого рендера с новыми стилями и таймлайном...`
            }]);
            await fetch(`${API_URL}/api/chat/render`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ 
                    file_id: id, 
                    font: fontStyle, 
                    font_size: fontSize, 
                    font_color: fontColor, 
                    use_outline: useOutline,
                    position: "center",
                    edits: activeEdits.length > 0 ? activeEdits : null,
                    edl: multiTrackEdl, // Expose independent tracks to backend
                    template_id: selectedTemplate || null
                })
            });
        } catch (error) {
            setChat(prev => [...prev, { role: "system", text: "❌ Ошибка запуска прямого рендера." }]);
        }
    };

    return (
        <div className="h-screen bg-[#09090b] text-zinc-100 flex flex-col font-sans overflow-hidden">
            <header className="h-[60px] border-b border-zinc-800/60 flex items-center px-8 justify-between bg-[#09090b] z-20">
                <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-fuchsia-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                        <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <h1 className="text-[17px] font-semibold text-zinc-100 tracking-tight">Montage AI</h1>
                </div>
                <div className="flex items-center gap-4">
                    <span className="text-[11px] font-mono text-indigo-400 bg-indigo-500/10 px-3 py-1.5 rounded-full border border-indigo-500/20 flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse"></span>
                        СЕССИЯ АКТИВНА
                    </span>
                    <button onClick={() => router.push('/')} className="text-sm font-medium text-zinc-400 hover:text-white transition-colors">
                        На главную
                    </button>
                </div>
            </header>

            <div className="flex flex-col flex-1 overflow-hidden p-6 gap-4">
                
                {/* Top Section */}
                <div className="flex flex-1 gap-6 min-h-0 overflow-hidden">
                    
                    {/* Left Pane: Video Player */}
                    <div className="flex-1 flex flex-col min-w-0 min-h-0">
                        <div
                            className="flex-1 rounded-[24px] overflow-hidden border border-zinc-800/80 relative flex flex-col shadow-2xl group w-full min-h-0"
                            style={{
                                background: currentVideo?.endsWith('.webm')
                                    // Checkered pattern for WebM alpha preview
                                    ? `repeating-conic-gradient(#1a1a1a 0% 25%, #232323 0% 50%) 0 0 / 24px 24px`
                                    : '#000000',
                            }}
                        >
                            {!currentVideo?.endsWith('.webm') && (
                                <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[60%] h-[60%] bg-indigo-600/20 blur-[120px] pointer-events-none rounded-full" />
                            )}

                            {/* Alpha badge for WebM */}
                            {currentVideo?.endsWith('.webm') && (
                                <div className="absolute top-3 right-3 z-20 bg-black/60 backdrop-blur-sm border border-white/10 rounded-full px-3 py-1 text-[11px] text-white/60 font-mono flex items-center gap-1.5">
                                    <span className="w-2 h-2 rounded-full bg-violet-400 inline-block" />
                                    ALPHA CHANNEL
                                </div>
                            )}

                            {/* Native NLE Player */}
                            <div className="flex-1 relative flex items-center justify-center p-4 overflow-hidden min-h-0">
                                {currentVideo ? (
                                    <>
                                        <div className="relative w-full h-full flex items-center justify-center">
                                            <video
                                                key={currentVideo + "_video"}
                                                ref={videoRef}
                                                src={currentVideo}
                                                controls={false}
                                                loop={false}
                                                muted={true}
                                                className="w-auto h-auto max-w-full max-h-full object-contain rounded-xl relative z-10 shadow-lg"
                                                style={{
                                                    // Ensure browser respects alpha channel for WebM
                                                    background: 'transparent',
                                                }}
                                            />
                                            {/* MOTION GRAPHICS FULL-SCREEN OVERLAY */}
                                            {graphicsHtml && (
                                                <div className="absolute inset-0 z-20 pointer-events-none flex items-center justify-center">
                                                    <iframe 
                                                        ref={iframeOverlayRef}
                                                        srcDoc={graphicsHtml}
                                                        className="w-full h-full object-contain pointer-events-none"
                                                        title="Graphics Overlay"
                                                        style={{ border: 'none', backgroundColor: 'transparent' }}
                                                    />
                                                </div>
                                            )}
                                        </div>
                                        <audio
                                            key={currentVideo + "_audio"}
                                            ref={audioRef}
                                            src={currentVideo}
                                            className="hidden"
                                        />
                                    </>
                                ) : (
                                    <p className="text-zinc-500 text-sm font-medium">Ожидание медиа...</p>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Right Pane: Premium AI Studio Chat & Graphics Preview */}
                    <div className="w-[400px] flex flex-col flex-shrink-0 bg-[#121214] border border-zinc-800/60 rounded-[24px] overflow-hidden relative shadow-2xl">
                    
                        {/* 🌟 Live Motion Graphics Preview 🌟 */}
                        <div className="h-[250px] w-full border-b border-zinc-800/60 bg-[#0a0a0c] relative flex flex-col items-center justify-center overflow-hidden shrink-0">
                            <div className="absolute top-2 left-3 z-10 flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></div>
                                <span className="text-[10px] text-zinc-400 font-mono tracking-widest uppercase">Motion Design Preview</span>
                            </div>
                            {/* Iframe pointing to Hyperframes Vite Server */}
                            <iframe 
                                src="http://localhost:3002" 
                                className="w-full h-full pointer-events-none"
                                title="Motion Preview"
                                style={{ border: 'none', backgroundColor: 'transparent' }}
                            />
                        </div>
                    
                    <div ref={chatContainerRef} className="flex-1 overflow-y-auto p-5 pb-[200px] flex flex-col gap-5 scroll-smooth">
                        {chat.map((msg, i) => (
                            <div key={i} className={`flex w-full ${msg.role === 'user' ? 'justify-end' : (msg.role === 'system' ? 'justify-center' : 'justify-start')}`}>
                                {msg.role === 'system' ? (
                                    <div className="bg-zinc-900/50 border border-zinc-800 text-zinc-400 text-[11px] py-1.5 px-3 rounded-full font-mono mt-1 mb-1 flex items-center gap-2">
                                        <div className="w-1.5 h-1.5 rounded-full bg-emerald-500"></div>
                                        {msg.text}
                                    </div>
                                ) : msg.role === 'reasoning' ? (
                                    <div className="w-full relative pl-3 border-l-2 border-indigo-500/30 ml-2 mt-1 mb-1">
                                        <div className="text-[10px] text-indigo-400/60 font-mono mb-1.5 uppercase tracking-widest">Цепочка рассуждений</div>
                                        {msg.steps?.filter((st: any) => {
                                            // Filter out steps that are clearly the final reply content (>100 chars or quoted)
                                            const s = st.step?.trim() || '';
                                            return s.length < 120 && !s.startsWith('"') && !s.startsWith('```');
                                        }).map((st: any, idx: number) => (
                                            <div 
                                                key={idx} 
                                                className="flex items-start gap-2.5 text-[11.5px] font-mono mb-1 last:mb-0 opacity-0 animate-[fadeIn_0.3s_ease_forwards]"
                                                style={{ animationDelay: `${idx * 60}ms` }}
                                            >
                                                <svg className="h-3 w-3 text-emerald-500 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                                </svg>
                                                <span className="text-zinc-500 leading-snug">{st.step}</span>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className={`max-w-[85%] flex flex-col gap-1 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                                        <div className={`rounded-[20px] p-4 text-[14px] leading-relaxed relative ${
                                            msg.role === 'user' 
                                            ? 'bg-gradient-to-br from-indigo-600 to-violet-600 text-white rounded-tr-sm shadow-md' 
                                            : 'bg-zinc-900 border border-zinc-800/80 rounded-tl-sm shadow-sm'
                                        }`}>
                                            <div className="text-zinc-200">{msg.text}</div>
                                            
                                            {/* Variant Cards Component */}
                                            {msg.variants && msg.variants.length > 0 && (
                                                <div className="flex flex-col gap-3 mt-4 w-[300px]">
                                                    {msg.variants.map((v: any, vIdx: number) => (
                                                        <div key={vIdx} className="bg-[#18181b] border border-zinc-700/60 rounded-xl p-4 hover:border-indigo-500/80 transition-all cursor-pointer shadow-lg group">
                                                            <div className="flex items-center justify-between mb-2">
                                                                <span className="text-[14px] font-bold text-zinc-100 group-hover:text-indigo-400 transition-colors drop-shadow-sm">{v.title}</span>
                                                            </div>
                                                            <p className="text-[12px] text-zinc-400 mb-4 leading-relaxed">{v.description}</p>
                                                            <button 
                                                                onClick={() => handleSend(`Я выбираю вариант: ${v.title}`, false, v.edits)}
                                                                className="w-full py-2 bg-indigo-600/10 hover:bg-indigo-600 text-indigo-400 hover:text-white rounded-lg text-[12px] font-semibold transition-all border border-indigo-600/20 active:scale-[0.98]"
                                                            >
                                                                Выбрать этот вариант
                                                            </button>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>
                        ))}

                        {/* Live Render Logs as AI Reasoning */}
                        {(isRenderingBackground && logs.length > 0) && (
                            <div className="flex w-full justify-start">
                                <div className="w-[90%] relative pl-3 border-l-2 border-fuchsia-500/40 ml-2 mt-1 mb-6 py-2 bg-zinc-900/40 rounded-r-xl border-y border-r border-zinc-800/40 shadow-sm backdrop-blur-md">
                                    <div className="text-[10px] text-fuchsia-400 font-mono mb-3 uppercase tracking-widest flex items-center gap-2 px-2">
                                        <div className="w-1.5 h-1.5 bg-fuchsia-500 rounded-full animate-pulse shadow-[0_0_8px_rgba(217,70,239,0.8)]"></div>
                                        Прямой Эфир: Монтаж Видео
                                    </div>
                                    <div className="flex flex-col gap-2 relative px-2">
                                        {logs.slice(-6).map((logLine, idx, arr) => (
                                            <div 
                                                key={idx} 
                                                className={`flex items-start gap-2.5 text-[11px] font-mono leading-relaxed transition-all duration-300 ${idx === arr.length - 1 ? 'text-zinc-200 font-semibold' : 'text-zinc-500/70'}`}
                                            >
                                                <svg className={`h-3 w-3 mt-0.5 shrink-0 transition-colors ${idx === arr.length - 1 ? 'text-fuchsia-400' : 'text-zinc-600/50'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={idx === arr.length - 1 ? 3 : 2} d={idx === arr.length - 1 ? "M13 10V3L4 14h7v7l9-11h-7z" : "M5 13l4 4L19 7"} />
                                                </svg>
                                                <span className="line-clamp-3">{logLine}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        )}

                        <div ref={chatEndRef} />
                    </div>

                    {/* Floating Input Area (Glassmorphic) */}
                    <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-[#09090b] via-[#09090b] to-transparent pt-12 pb-5 z-20">
                        {/* Compact Settings Bar */}
                        <div className="flex gap-2 mb-3 items-center justify-between px-1">
                            <div className="flex gap-2 bg-zinc-900/90 backdrop-blur-md border border-zinc-800 rounded-xl p-1.5 shadow-lg">
                                <select 
                                    value={fontStyle}
                                    onChange={(e) => setFontStyle(e.target.value)}
                                    className="bg-transparent text-[11px] text-zinc-400 outline-none cursor-pointer font-medium hover:text-zinc-200 transition-colors"
                                >
                                    <option value="Montserrat-ExtraBold">Montserrat Bold</option>
                                    <option value="Inter_24pt-Bold">Inter Bold</option>
                                    <option value="BebasNeue-Regular">Bebas Neue</option>
                                    <option value="Rubik-Bold">Rubik</option>
                                    <option value="Oswald-Bold">Oswald</option>
                                    <option value="Manrope-Bold">Manrope</option>
                                    <option value="JetBrainsMono-Bold">JetBrains Mono</option>
                                    <option value="Comfortaa-Bold">Comfortaa</option>
                                    <option value="Lobster-Regular">Lobster</option>
                                </select>
                                <div className="w-[1px] h-3 bg-zinc-800 my-auto"></div>
                                <select 
                                    value={fontColor}
                                    onChange={(e) => setFontColor(e.target.value)}
                                    className="bg-transparent text-[11px] text-zinc-400 outline-none cursor-pointer font-medium hover:text-zinc-200 transition-colors"
                                >
                                    <option value="White">White</option>
                                    <option value="Yellow">Yellow</option>
                                    <option value="Red">Red</option>
                                </select>
                                <div className="w-[1px] h-3 bg-zinc-800 my-auto"></div>
                                <button
                                    onClick={() => setShowTemplatesDrawer(!showTemplatesDrawer)}
                                    className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-bold transition-all ${showTemplatesDrawer ? 'bg-indigo-500/20 text-indigo-300' : 'hover:bg-zinc-800 text-fuchsia-400'}`}
                                >
                                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                                    </svg>
                                    {selectedTemplate ? `Шаблон Выбран` : `Выбрать Стиль`}
                                </button>
                            </div>
                            <button onClick={handleDirectRender} className="text-[9px] bg-zinc-900/80 border border-zinc-800 text-zinc-500 font-semibold px-2 py-1 rounded-lg hover:text-indigo-400 hover:border-indigo-500/30 transition-all uppercase tracking-wider">
                                Sync Settings
                            </button>
                        </div>

                        {/* Template Carousel Drawer */}
                        {showTemplatesDrawer && (
                            <div className="mb-4 bg-[#0c0c0e]/95 backdrop-blur-xl border border-zinc-800/80 rounded-2xl p-4 shadow-2xl relative overflow-hidden animate-in slide-in-from-bottom-2 fade-in duration-200">
                                <div className="flex items-center justify-between mb-3">
                                    <h3 className="text-[13px] font-bold text-zinc-100 flex items-center gap-2">
                                        <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" /></svg>
                                        Featured Templates
                                    </h3>
                                    <button onClick={() => setShowTemplatesDrawer(false)} className="text-zinc-500 hover:text-zinc-300">
                                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                                    </button>
                                </div>
                                
                                <div className="flex gap-4 overflow-x-auto pb-2 custom-scrollbar snap-x">
                                    {/* Default Custom Option */}
                                    <div 
                                        onClick={() => setSelectedTemplate("")} 
                                        className={`snap-start min-w-[200px] max-w-[200px] h-[140px] flex-shrink-0 cursor-pointer rounded-xl border flex flex-col items-center justify-center transition-all ${selectedTemplate === "" ? "border-indigo-500 bg-indigo-500/10 ring-2 ring-indigo-500/30" : "border-zinc-800 bg-zinc-900/50 hover:border-zinc-600 hover:bg-zinc-800/50"}`}
                                    >
                                        <span className="text-2xl mb-2">✨</span>
                                        <span className={`text-[12px] font-semibold ${selectedTemplate === "" ? "text-indigo-400" : "text-zinc-400"}`}>ИИ Директор (Без шаблона)</span>
                                        <span className="text-[10px] text-zinc-500 text-center mt-1 px-4">ИИ сам решает какие плашки использовать.</span>
                                    </div>

                                    {/* Dynamic Templates from API */}
                                    {templates.map(t => (
                                        <div 
                                            key={t.id} 
                                            onClick={() => setSelectedTemplate(t.id)}
                                            className={`relative snap-start min-w-[220px] max-w-[220px] h-[140px] flex-shrink-0 cursor-pointer rounded-xl border overflow-hidden transition-all group ${selectedTemplate === t.id ? "border-indigo-500 ring-2 ring-indigo-500/50" : "border-zinc-800 hover:border-zinc-600"}`}
                                        >
                                            <div className="absolute inset-0 bg-zinc-900">
                                                {t.preview_url ? (
                                                    <img src={t.preview_url} alt={t.name} className="w-full h-full object-cover opacity-60 group-hover:opacity-80 transition-opacity duration-300" />
                                                ) : (
                                                    <div className="w-full h-full flex flex-col items-center justify-center opacity-30 text-indigo-400">
                                                        <svg className="w-8 h-8 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                                                    </div>
                                                )}
                                                <div className="absolute inset-0 bg-gradient-to-t from-black/95 via-black/40 to-transparent"></div>
                                            </div>
                                            
                                            <div className="absolute inset-0 p-3 flex flex-col justify-end">
                                                <span className={`text-[13px] font-bold drop-shadow-md mb-1 leading-tight ${selectedTemplate === t.id ? "text-indigo-300" : "text-zinc-100 group-hover:text-white"}`}>{t.name}</span>
                                                <span className="text-[10px] text-zinc-400 line-clamp-2 leading-tight drop-shadow-sm">{t.description || "Готовый дизайнерский стиль монтажа"}</span>
                                            </div>

                                            {selectedTemplate === t.id && (
                                                <div className="absolute top-2 right-2 w-5 h-5 bg-indigo-500 rounded-full flex items-center justify-center shadow-lg">
                                                    <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                                <div className="mt-4 pt-3 border-t border-zinc-800/80 flex items-center justify-between animate-in fade-in slide-in-from-bottom-2">
                                    <div className="flex flex-col">
                                        <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-bold">Текущий выбор</span>
                                        <span className="text-[13px] text-zinc-200 font-bold">{selectedTemplate === "" ? "✨ ИИ Директор (Без шаблона)" : templates.find(t => t.id === selectedTemplate)?.name || "Не выбран"}</span>
                                    </div>
                                    <button 
                                        onClick={() => {
                                            setShowTemplatesDrawer(false);
                                            const tName = selectedTemplate === "" ? "ИИ Директор (Автовыбор плашек)" : templates.find(t => t.id === selectedTemplate)?.name || "";
                                            handleSend(`[Система] Пользователь переключил визуальный стиль видео на: ${tName}. Пожалуйста, используй этот визуальный стиль, шрифты и плашки в своих будущих отчетах.`);
                                        }}
                                        className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-[12px] font-bold rounded-xl shadow-lg shadow-indigo-600/20 transition-all active:scale-95 flex items-center gap-2"
                                    >
                                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" /></svg>
                                        Применить Стиль
                                    </button>
                                </div>
                            </div>
                        )}

                        {/* Text Input */}
                        <div className="relative group shadow-2xl">
                            <input
                                type="text"
                                value={message}
                                onChange={(e) => setMessage(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && !isProcessing && handleSend()}
                                disabled={isProcessing}
                                placeholder={isAgentTyping ? "Агент обдумывает..." : isRenderingBackground ? "Рендер идёт в фоне — можете писать..." : "Напишите агенту о правках..."}
                                className="w-full bg-[#121214]/90 backdrop-blur-xl border border-zinc-800/80 rounded-2xl pl-5 pr-14 py-4 text-[13px] text-zinc-200 focus:outline-none focus:border-indigo-500/50 focus:ring-1 focus:ring-indigo-500/50 shadow-inner placeholder:text-zinc-600 transition-all font-medium disabled:opacity-50"
                            />
                            <button
                                onClick={() => handleSend()}
                                disabled={!message.trim() || isProcessing}
                                className={`absolute right-2 top-2 bottom-2 w-10 min-h-[30px] rounded-xl flex items-center justify-center transition-all shadow-lg text-white ${isProcessing ? 'bg-indigo-600/50 cursor-wait' : isRenderingBackground ? 'bg-indigo-600 hover:bg-indigo-500 ring-1 ring-indigo-400/40 animate-pulse active:scale-[0.95]' : 'bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-800/50 disabled:text-zinc-700 disabled:pointer-events-none active:scale-[0.95]'}`}
                            >
                                {isProcessing ? (
                                    <svg className="animate-spin h-5 w-5 opacity-80" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle>
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                    </svg>
                                ) : (
                                    <svg className="w-4 h-4 ml-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 19V5m0 0l-6 6m6-6l6 6" />
                                    </svg>
                                )}
                            </button>
                        </div>
                    </div>
                </div>
                {/* ☝️ Closes Right Pane */}
            </div>
            {/* ☝️ Closes Top Section */}

            {/* Resizer Handle */}
            <div 
                className="h-2 w-full cursor-row-resize flex items-center justify-center group -my-2 relative z-50 rounded"
                onPointerDown={(e) => {
                    e.preventDefault();
                    setIsResizing(true);
                }}
            >
                <div className="w-16 h-1 bg-zinc-700/50 group-hover:bg-indigo-500 rounded-full transition-colors"></div>
                {isResizing && <div className="fixed inset-0 cursor-row-resize z-[100]" />}
            </div>

            {/* Bottom Section: Timelines */}
            <div 
                className="flex-shrink-0 bg-[#121214] border border-zinc-800/60 rounded-[20px] flex flex-col shadow-inner overflow-hidden relative transition-[opacity,transform] duration-75"
                style={{ height: timelineHeight }}
            >
                <div className="h-10 bg-[#0e0e10] border-b border-zinc-800 flex items-center px-4 justify-between shrink-0">
                    <div className="flex gap-4 h-full">
                        <button 
                            onClick={() => setActiveTab('text')}
                            className={`h-full px-2 text-[12px] font-semibold border-b-2 transition-colors flex items-center gap-2 ${activeTab === 'text' ? 'border-indigo-500 text-indigo-400' : 'border-transparent text-zinc-500 hover:text-zinc-300'}`}
                        >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16m-7 6h7" /></svg>
                            Текст Таймлайн
                        </button>
                            <button 
                                onClick={() => setActiveTab('video')}
                                className={`h-full px-2 text-[12px] font-semibold border-b-2 transition-colors flex items-center gap-2 ${activeTab === 'video' ? 'border-indigo-500 text-indigo-400' : 'border-transparent text-zinc-500 hover:text-zinc-300'}`}
                            >
                                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                                Видео Таймлайн
                            </button>
                        </div>
                        {activeTab === 'text' && (
                            <button 
                                onClick={handleDirectRender} 
                                className="h-7 px-4 bg-indigo-600 hover:bg-indigo-500 text-white text-[11px] font-bold rounded-md shadow-lg shadow-indigo-900/40 transition-transform active:scale-95 flex items-center gap-2"
                            >
                                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758a3 3 0 10-4.243 4.243 3 3 0 004.243-4.243zm0-5.758a3 3 0 10-4.243-4.243 3 3 0 004.243 4.243z" /></svg>
                                ВЫРЕЗАТЬ И ОТРЕНДЕРИТЬ
                            </button>
                        )}
                    </div>
                    
                    <div className="flex-1 p-2 overflow-hidden bg-[#0a0a0c]">
                        {activeTab === 'text' ? (
                            <TimelineEditor 
                                transcript={transcript} 
                                activeEdits={activeEdits} 
                                onEditsChange={setActiveEdits} 
                            />
                        ) : (
                            <VideoTimeline 
                                duration={duration}
                                activeEdits={activeEdits}
                                multiTrackEdl={multiTrackEdl || { v1: [{start: 0, end: duration}], a1: [{start: 0, end: duration}] }}
                                audioPeaks={audioPeaks}
                                videoRef={videoRef}
                                audioRef={audioRef}
                                isPlaying={isPlaying}
                                onTogglePlay={() => {
                                    if (!videoRef.current) return;
                                    if (isPlaying) {
                                        videoRef.current.pause();
                                        audioRef.current?.pause();
                                        setIsPlaying(false);
                                    } else {
                                        videoRef.current.play();
                                        audioRef.current?.play();
                                        setIsPlaying(true);
                                    }
                                }}
                                onEdlChange={(newEdl: {v1: {start: number, end: number}[], a1: {start: number, end: number}[]}) => setMultiTrackEdl(newEdl)}
                                onActiveEditsChange={(newEdits) => setActiveEdits(newEdits)}
                            />
                        )}
                    </div>
                </div>

            </div>
        </div>
    );
}

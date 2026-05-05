import React, { useState, useEffect, useRef } from "react";

type KeepSegment = { start: number; end: number };

export default function VideoTimeline({ 
  duration,
  activeEdits,
  multiTrackEdl,
  audioPeaks,
  videoRef,
  audioRef,
  isPlaying,
  onTogglePlay,
  onEdlChange,
  onActiveEditsChange
}: { 
  duration: number;
  activeEdits: any[];
  multiTrackEdl: { v1: KeepSegment[], a1: KeepSegment[] };
  audioPeaks?: number[];
  videoRef: React.RefObject<HTMLVideoElement | null>;
  audioRef?: React.RefObject<HTMLAudioElement | null>;
  isPlaying: boolean;
  onTogglePlay: () => void;
  onEdlChange: (edl: { v1: KeepSegment[], a1: KeepSegment[] }) => void;
  onActiveEditsChange?: (edits: any[]) => void;
}) {
    const [timelineTime, setTimelineTime] = useState(0);
    const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
    const [activeTool, setActiveTool] = useState<'pointer' | 'razor'>('pointer');
    // Inline text editing for T1 subtitle track
    const [editingChunk, setEditingChunk] = useState<{index: number; text: string} | null>(null);
    const editInputRef = useRef<HTMLInputElement>(null);
    // Animation style selector — synced from activeEdits prop
    const [animStyle, setAnimStyle] = useState<string>(
        () => activeEdits.find(e => e.action === 'add_subtitles')?.animation_style || 'fade'
    );
    // Keep animStyle in sync when activeEdits changes externally (e.g. agent returns new edits)
    useEffect(() => {
        const subEdit = activeEdits.find(e => e.action === 'add_subtitles');
        if (subEdit?.animation_style && subEdit.animation_style !== animStyle) {
            setAnimStyle(subEdit.animation_style);
        }
    }, [activeEdits]);

    const setAndSaveAnimStyle = (style: string) => {
        setAnimStyle(style);
        if (onActiveEditsChange) {
            const updated = activeEdits.map(e =>
                e.action === 'add_subtitles' ? { ...e, animation_style: style } : e
            );
            onActiveEditsChange(updated);
        }
    };
    
    // Trim State — supports v1, a1, t1 (subtitles), v2 (broll)
    const [trimState, setTrimState] = useState<{ 
        track: 'v1' | 'a1' | 't1' | 'v2',
        clipIndex: number, 
        type: 'left' | 'right', 
        startX: number, 
        initialTime: number,
        pointerId: number
    } | null>(null);
    const [previewTrim, setPreviewTrim] = useState<{time: number} | null>(null);
    
    const containerRef = useRef<HTMLDivElement>(null);

    // Timeline length estimation (max end time from v1 and a1)
    const v1End = multiTrackEdl.v1.length > 0 ? multiTrackEdl.v1[multiTrackEdl.v1.length - 1].end : duration;
    // For rendering we map source time to position because this visually matches the transcript right now.
    // True EDL contiguous timeline is complex, so we will keep spatial layout proportional to original duration.
    
    // Playback loop Sync
    useEffect(() => {
        let rafId: number;
        const loop = () => {
            if (videoRef?.current) {
                // During playback, we track the video player's source time
                setTimelineTime(videoRef.current.currentTime);
            }
            rafId = requestAnimationFrame(loop);
        }
        loop();
        return () => cancelAnimationFrame(rafId);
    }, [videoRef]);

    // Handle Delete for all tracks
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if ((e.key === 'Backspace' || e.key === 'Delete') && selectedClipId && !trimState) {
                if (selectedClipId.startsWith('V2-Broll-')) {
                    // Delete a B-roll clip from activeEdits
                    const idx = parseInt(selectedClipId.replace('V2-Broll-', ''), 10);
                    if (onActiveEditsChange) {
                        const brolls = activeEdits.filter(ae => ae.action === 'add_broll');
                        const others = activeEdits.filter(ae => ae.action !== 'add_broll');
                        onActiveEditsChange([...others, ...brolls.filter((_, i) => i !== idx)]);
                    }
                } else if (selectedClipId.startsWith('T1-Sub-')) {
                    // Delete a subtitle segment — remove corresponding V1 segment
                    const idx = parseInt(selectedClipId.replace('T1-Sub-', ''), 10);
                    const newEdl = { ...multiTrackEdl, v1: multiTrackEdl.v1.filter((_, i) => i !== idx) };
                    onEdlChange(newEdl);
                } else if (selectedClipId.startsWith('G1-Graphic-')) {
                    // We don't support deleting individual graphics easily yet because they are bundled in html_content
                    // Just unselect
                } else {
                    const [, track, indexStr] = selectedClipId.split('-');
                    const index = parseInt(indexStr, 10);
                    const newEdl = { ...multiTrackEdl };
                    if (track === 'Video') newEdl.v1 = newEdl.v1.filter((_, idx) => idx !== index);
                    else if (track === 'Audio') newEdl.a1 = newEdl.a1.filter((_, idx) => idx !== index);
                    onEdlChange(newEdl);
                }
                setSelectedClipId(null);
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [selectedClipId, multiTrackEdl, activeEdits, onEdlChange, onActiveEditsChange, trimState]);

    if (!duration || duration <= 0) return <div className="p-4 text-zinc-500">Загрузка таймлайна...</div>;

    const hasSubtitles = activeEdits.some(e => e.action === "add_subtitles");
    const hasBroll = activeEdits.some(e => e.action === "add_broll");

    const graphicClips: {start: number, end: number, id: string, label: string}[] = [];
    activeEdits.forEach(e => {
        if (e.action === "hyperframes_html" && e.html_content) {
            const divRegex = /<div[^>]*class=['"][^'"]*clip[^'"]*['"][^>]*>/g;
            let divMatch;
            while ((divMatch = divRegex.exec(e.html_content)) !== null) {
                const tag = divMatch[0];
                if (tag.includes('id="root"') || tag.includes("id='root'")) continue;
                
                const idMatch = tag.match(/id=['"]([^'"]+)['"]/);
                const startMatch = tag.match(/data-start=['"]([\d.]+)['"]/);
                const durMatch = tag.match(/data-duration=['"]([\d.]+)['"]/);
                
                if (startMatch && durMatch) {
                    const start = parseFloat(startMatch[1]);
                    const duration = parseFloat(durMatch[1]);
                    graphicClips.push({ 
                        start, 
                        end: start + duration, 
                        id: idMatch ? idMatch[1] : "Graphic", 
                        label: idMatch ? idMatch[1] : "Graphic" 
                    });
                }
            }
        }
    });
    const hasGraphics = graphicClips.length > 0;

    const handleScrub = (e: React.MouseEvent<HTMLDivElement>) => {
        if (!duration || !videoRef?.current) return;
        const rect = e.currentTarget.getBoundingClientRect();
        const percent = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        const newTime = percent * duration;
        
        videoRef.current.currentTime = newTime;
        if (audioRef?.current) audioRef.current.currentTime = newTime;
        setTimelineTime(newTime);
    };

    const handleClipClick = (e: React.MouseEvent, id: string, clip: KeepSegment, clipIndex: number, track: 'v1' | 'a1') => {
        e.stopPropagation();
        
        if (activeTool === 'pointer') {
            setSelectedClipId(id);
        } else if (activeTool === 'razor') {
            const rect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
            const percentInClip = (e.clientX - rect.left) / rect.width;
            const clickTime = clip.start + percentInClip * (clip.end - clip.start);
            
            const newEdl = { ...multiTrackEdl };
            const targetArray = newEdl[track];
            targetArray.splice(clipIndex, 1, 
                {start: clip.start, end: clickTime - 0.01},
                {start: clickTime + 0.01, end: clip.end}
            );
            
            onEdlChange(newEdl);
            setActiveTool('pointer');
        }
    };

    // Trim Handlers — support v1, a1, t1, v2
    const handleTrimStart = (e: React.PointerEvent, track: 'v1'|'a1'|'t1'|'v2', clipIndex: number, type: 'left' | 'right', initialTime: number) => {
        if (activeTool !== 'pointer') return;
        e.stopPropagation();
        e.currentTarget.setPointerCapture(e.pointerId);
        setTrimState({ track, clipIndex, type, startX: e.clientX, initialTime, pointerId: e.pointerId });
        setPreviewTrim({ time: initialTime });
    };

    const handleTrimMove = (e: React.PointerEvent) => {
        if (!trimState || e.pointerId !== trimState.pointerId || !containerRef.current) return;
        const trackWidth = containerRef.current.getBoundingClientRect().width || 1;
        const deltaSec = ((e.clientX - trimState.startX) / trackWidth) * duration;
        let newTime = trimState.initialTime + deltaSec;
        newTime = Math.max(0, Math.min(newTime, duration));
        setPreviewTrim({ time: newTime });
    };

    const handleTrimEnd = (e: React.PointerEvent) => {
        if (!trimState || !previewTrim) return;
        e.currentTarget.releasePointerCapture(e.pointerId);

        if (trimState.track === 'v2') {
            // Broll clip trim — update activeEdits
            if (onActiveEditsChange) {
                const brolls = activeEdits.filter(ae => ae.action === 'add_broll');
                const others = activeEdits.filter(ae => ae.action !== 'add_broll');
                const updated = brolls.map((b, i) => {
                    if (i !== trimState.clipIndex) return b;
                    return trimState.type === 'left'
                        ? { ...b, start: previewTrim.time }
                        : { ...b, end: previewTrim.time };
                });
                onActiveEditsChange([...others, ...updated]);
            }
        } else {
            // v1, a1, t1 all live in multiTrackEdl (t1 mirrors v1)
            const edlKey = trimState.track === 't1' ? 'v1' : trimState.track;
            const newEdl = { ...multiTrackEdl, [edlKey]: multiTrackEdl[edlKey as 'v1'|'a1'].map((clip, i) => {
                if (i !== trimState.clipIndex) return clip;
                return trimState.type === 'left'
                    ? { ...clip, start: previewTrim.time }
                    : { ...clip, end: previewTrim.time };
            })};
            onEdlChange(newEdl);
        }
        setTrimState(null);
        setPreviewTrim(null);
    };

    const formatTime = (secs: number) => {
        const m = Math.floor(secs / 60).toString().padStart(2, '0');
        const s = Math.floor(secs % 60).toString().padStart(2, '0');
        return `${m}:${s}`;
    };

    const rulerTicks = Array.from({length: 11}, (_, i) => (duration / 10) * i);

    return (
        <div className="flex flex-col h-full bg-[#1e1e1e] rounded-xl overflow-hidden border border-zinc-800 select-none" onClick={() => setSelectedClipId(null)}>
            
            {/* Toolbar Area */}
            <div className="bg-[#121212] border-b border-zinc-900 h-12 flex items-center px-4 justify-between shrink-0 z-30 relative shadow-md">
                
                <div className="flex items-center gap-4">
                    {/* Playback Controls */}
                    <button 
                        onClick={onTogglePlay}
                        className={`w-9 h-9 rounded-full flex items-center justify-center transition-all shadow-sm ${isPlaying ? 'bg-zinc-800 text-indigo-400 hover:bg-zinc-700' : 'bg-indigo-600 text-white hover:bg-indigo-500 hover:scale-105'}`}
                        title="Play/Pause (Space)"
                    >
                        {isPlaying ? (
                            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M6 4h4v16H6zm8 0h4v16h-4z"/></svg>
                        ) : (
                            <svg className="w-5 h-5 translate-x-0.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
                        )}
                    </button>
                    
                    <div className="w-px h-6 bg-zinc-800 mx-1"></div>

                    <div className="flex items-center gap-1 bg-[#0a0a0a] p-1 rounded-lg border border-zinc-800" onClick={e => e.stopPropagation()}>
                        <button 
                            onClick={() => setActiveTool('pointer')}
                            className={`p-1.5 rounded-md flex items-center justify-center transition-colors ${activeTool === 'pointer' ? 'bg-indigo-600/20 text-indigo-400' : 'text-zinc-500 hover:bg-zinc-800'}`}
                            title="Выделение (V)"
                        >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122" /></svg>
                        </button>
                        <button 
                            onClick={() => setActiveTool('razor')}
                            className={`p-1.5 rounded-md flex items-center justify-center transition-colors ${activeTool === 'razor' ? 'bg-red-500/20 text-red-500' : 'text-zinc-500 hover:bg-zinc-800'}`}
                            title="Лезвие (C) - Разрезать клип"
                        >
                            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" /></svg>
                        </button>
                    </div>
                </div>

                {/* Animation Picker — shown when subtitles exist */}
                {hasSubtitles && (
                    <div className="flex items-center gap-1.5" onClick={e => e.stopPropagation()}>
                        <div className="w-px h-5 bg-zinc-800 mx-1" />
                        <span className="text-[9px] font-bold text-zinc-500 uppercase tracking-wider">Анимация:</span>
                        {([
                            { key: 'fade',       label: '✦ Fade',   title: 'Fade — плавное появление' },
                            { key: 'pop',        label: '🔺 Pop',   title: 'Pop — TikTok вспрыгивание' },
                            { key: 'slide_up',   label: '↑ Slide',  title: 'Slide Up — снизу вверх' },
                            { key: 'bounce',     label: '🔵 Bounce',title: 'Bounce — пружинистое' },
                            { key: 'glow',       label: '✨ Glow',  title: 'Glow — размытый свет' },
                            { key: 'typewriter', label: '⌨ Type',  title: 'Typewriter — побуквенно' },
                            { key: 'karaoke',    label: '🎤 Kara',  title: 'Karaoke — подсветка слов' },
                        ] as const).map(({ key, label, title }) => (
                            <button
                                key={key}
                                onClick={() => setAndSaveAnimStyle(key)}
                                title={title}
                                className={`px-2 py-0.5 rounded text-[9px] font-bold transition-all border ${
                                    animStyle === key
                                        ? 'bg-fuchsia-600 border-fuchsia-400 text-white shadow-sm shadow-fuchsia-900'
                                        : 'bg-zinc-900 border-zinc-700 text-zinc-400 hover:border-fuchsia-600/50 hover:text-fuchsia-300'
                                }`}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                )}
                <div className="flex items-center gap-4">
                    {selectedClipId && <span className="text-[10px] font-mono text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20 animate-pulse">Press DEL to Remove</span>}
                    <span className="text-[11px] font-mono font-medium text-zinc-400 bg-[#0a0a0c] px-3 py-1 rounded-md border border-zinc-800/80">
                        {formatTime(timelineTime)} / {formatTime(duration)}
                    </span>
                </div>
            </div>

            {/* Tracks Container */}
            <div className="flex flex-1 relative overflow-y-auto overflow-x-hidden bg-[#151515] scrollbar-thin scrollbar-thumb-zinc-700 scrollbar-track-transparent">
                <div className="w-16 bg-[#0f0f11] border-r border-zinc-900 flex flex-col pt-6 z-20 flex-shrink-0 shadow-lg">
                    {hasSubtitles && <div className="h-12 border-b border-zinc-800 flex items-center justify-center text-[10px] font-bold text-zinc-500 uppercase">T1</div>}
                    {hasGraphics && <div className="h-12 border-b border-zinc-800 flex items-center justify-center text-[10px] font-bold text-zinc-500 uppercase">G1</div>}
                    {hasBroll && <div className="h-12 border-b border-zinc-800 flex items-center justify-center text-[10px] font-bold text-zinc-500 uppercase">V2</div>}
                    <div className="h-12 border-b border-zinc-800 flex items-center justify-center text-[10px] font-bold text-zinc-500 uppercase">V1</div>
                    <div className="h-12 border-b border-zinc-800 flex items-center justify-center text-[10px] font-bold text-zinc-500 uppercase">A1</div>
                </div>

                <div ref={containerRef} className={`flex-1 relative overflow-x-auto overflow-y-hidden ${activeTool === 'razor' ? 'cursor-[crosshair]' : 'cursor-default'}`}>
                    <div className="min-w-full h-full relative group" style={{ minWidth: '100%' }}>
                        
                        <div className="absolute top-0 left-0 w-full h-6 border-b border-zinc-800/50 flex items-end cursor-text z-30 bg-[#0a0a0a]/80 backdrop-blur-sm hover:bg-zinc-900 transition-colors" onClick={handleScrub}>
                            {rulerTicks.map((tick, i) => (
                                <div key={i} className="absolute flex flex-col items-center -translate-x-1/2 pointer-events-none" style={{ left: `${(tick / duration) * 100}%` }}>
                                    <span className="text-[9px] text-zinc-500 font-mono mb-0.5">{formatTime(tick)}</span>
                                    <div className="w-px h-1.5 bg-zinc-700"></div>
                                </div>
                            ))}
                        </div>

                        <div className="absolute top-6 left-0 w-full bottom-0 flex flex-col">
                            {/* T1 Track — Subtitles with inline text editing + trim + delete */}
                            {hasSubtitles && (
                                <div className="h-12 border-b border-zinc-800/60 bg-transparent relative flex items-center px-1">
                                    {multiTrackEdl.v1.map((clip, i) => {
                                        const clipId = `T1-Sub-${i}`;
                                        const isSelected = selectedClipId === clipId;
                                        const isEditing = editingChunk?.index === i;
                                        const overrideEdits = activeEdits.filter(e => e.action === 'subtitle_override');
                                        const overrideForChunk = overrideEdits.find(e => e.chunk_index === i);
                                        const label = overrideForChunk?.text || 'SUBTITLES';
                                        const clipStart = trimState?.clipIndex === i && trimState.track === 't1' && trimState.type === 'left' && previewTrim ? previewTrim.time : clip.start;
                                        const clipEnd = trimState?.clipIndex === i && trimState.track === 't1' && trimState.type === 'right' && previewTrim ? previewTrim.time : clip.end;
                                        return (
                                            <div
                                                key={clipId}
                                                title="Клик — выбрать | Двойной клик — редактировать | DEL — удалить"
                                                onClick={(e) => { e.stopPropagation(); setSelectedClipId(clipId); }}
                                                onDoubleClick={(e) => {
                                                    e.stopPropagation();
                                                    setEditingChunk({ index: i, text: label });
                                                    setTimeout(() => editInputRef.current?.focus(), 50);
                                                }}
                                                className={`absolute h-8 bg-fuchsia-600/80 hover:bg-fuchsia-500/90 rounded border shadow-inner overflow-hidden flex items-center cursor-pointer transition-colors group/t1 ${
                                                    isSelected ? 'border-white ring-2 ring-white/50 z-10' : 'border-fuchsia-400/50'
                                                }`}
                                                style={{ left: `${(clipStart / duration) * 100}%`, width: `${((clipEnd - clipStart) / duration) * 100}%` }}
                                            >
                                                <div className="w-full h-full opacity-20 bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(0,0,0,0.3)_4px,rgba(0,0,0,0.3)_8px)] pointer-events-none absolute inset-0" />
                                                {isEditing ? (
                                                    <input
                                                        ref={editInputRef}
                                                        value={editingChunk!.text}
                                                        onChange={ev => setEditingChunk({ index: i, text: ev.target.value })}
                                                        onClick={e => e.stopPropagation()}
                                                        onDoubleClick={e => e.stopPropagation()}
                                                        onKeyDown={e => {
                                                            if (e.key === 'Enter' || e.key === 'Escape') {
                                                                if (e.key === 'Enter' && onActiveEditsChange) {
                                                                    const others = activeEdits.filter(ae => !(ae.action === 'subtitle_override' && ae.chunk_index === i));
                                                                    onActiveEditsChange([...others, { action: 'subtitle_override', chunk_index: i, text: editingChunk!.text, start: clip.start, end: clip.end }]);
                                                                }
                                                                setEditingChunk(null);
                                                            }
                                                        }}
                                                        onBlur={() => {
                                                            if (onActiveEditsChange) {
                                                                const others = activeEdits.filter(ae => !(ae.action === 'subtitle_override' && ae.chunk_index === i));
                                                                onActiveEditsChange([...others, { action: 'subtitle_override', chunk_index: i, text: editingChunk!.text, start: clip.start, end: clip.end }]);
                                                            }
                                                            setEditingChunk(null);
                                                        }}
                                                        className="absolute inset-0 w-full h-full bg-[#1a0033] text-fuchsia-200 text-[10px] font-mono font-bold px-2 outline-none border-2 border-fuchsia-300 rounded z-30"
                                                    />
                                                ) : (
                                                    <span className="absolute text-[10px] text-white/90 font-bold ml-2 drop-shadow-md pointer-events-none truncate right-5 left-5">
                                                        ✏️ {label}
                                                    </span>
                                                )}
                                                {/* Trim handles */}
                                                {activeTool === 'pointer' && !isEditing && (
                                                    <>
                                                        <div className="absolute left-0 top-0 bottom-0 w-3 cursor-ew-resize bg-white/0 hover:bg-white/40 z-20" onPointerDown={(e) => handleTrimStart(e, 't1', i, 'left', clip.start)} onPointerMove={handleTrimMove} onPointerUp={handleTrimEnd} />
                                                        <div className="absolute right-0 top-0 bottom-0 w-3 cursor-ew-resize bg-white/0 hover:bg-white/40 z-20" onPointerDown={(e) => handleTrimStart(e, 't1', i, 'right', clip.end)} onPointerMove={handleTrimMove} onPointerUp={handleTrimEnd} />
                                                    </>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}

                            {/* V2 (B-ROLL) Track — selectable, trimmable, deletable */}
                            {hasBroll && (
                                <div className="h-12 border-b border-zinc-800/60 bg-transparent relative flex items-center px-1">
                                    {activeEdits.filter(e => e.action === 'add_broll').map((broll, i) => {
                                        const clipId = `V2-Broll-${i}`;
                                        const isSelected = selectedClipId === clipId;
                                        const rawStart = broll.start;
                                        const rawEnd = broll.end;
                                        const clipStart = trimState?.clipIndex === i && trimState.track === 'v2' && trimState.type === 'left' && previewTrim ? previewTrim.time : rawStart;
                                        const clipEnd = trimState?.clipIndex === i && trimState.track === 'v2' && trimState.type === 'right' && previewTrim ? previewTrim.time : rawEnd;
                                        const query = broll.query || 'Stock';
                                        return (
                                            <div
                                                key={clipId}
                                                onClick={(e) => { e.stopPropagation(); setSelectedClipId(clipId); }}
                                                title="Клик — выбрать | DEL — удалить | Тянуть края — обрезать"
                                                className={`absolute h-9 bg-cyan-600/80 rounded-sm border hover:brightness-110 shadow-inner overflow-hidden flex items-center cursor-pointer group/v2 ${
                                                    isSelected ? 'border-white ring-2 ring-white/50 z-10' : 'border-cyan-400/50'
                                                }`}
                                                style={{ left: `${(clipStart / duration) * 100}%`, width: `${((clipEnd - clipStart) / duration) * 100}%` }}
                                            >
                                                <div className="w-full h-full opacity-30 bg-[repeating-linear-gradient(-45deg,transparent,transparent_4px,rgba(0,0,0,0.2)_4px,rgba(0,0,0,0.2)_8px)] pointer-events-none" />
                                                <span className="text-[9px] text-white/90 absolute left-4 font-mono font-bold pointer-events-none tracking-tight overflow-hidden text-ellipsis whitespace-nowrap right-4">🎥 {query.toUpperCase()}</span>
                                                {/* Trim handles */}
                                                {activeTool === 'pointer' && (
                                                    <>
                                                        <div className="absolute left-0 top-0 bottom-0 w-3 cursor-ew-resize bg-white/0 hover:bg-white/40 z-20" onPointerDown={(e) => handleTrimStart(e, 'v2', i, 'left', rawStart)} onPointerMove={handleTrimMove} onPointerUp={handleTrimEnd} />
                                                        <div className="absolute right-0 top-0 bottom-0 w-3 cursor-ew-resize bg-white/0 hover:bg-white/40 z-20" onPointerDown={(e) => handleTrimStart(e, 'v2', i, 'right', rawEnd)} onPointerMove={handleTrimMove} onPointerUp={handleTrimEnd} />
                                                    </>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}

                            {/* G1 (Graphics) Track */}
                            {hasGraphics && (
                                <div className="h-12 border-b border-zinc-800/60 bg-transparent relative flex items-center px-1">
                                    {graphicClips.map((clip, i) => {
                                        const clipId = `G1-Graphic-${clip.id}-${i}`;
                                        const isSelected = selectedClipId === clipId;
                                        const rawStart = clip.start;
                                        const rawEnd = clip.end;
                                        // We don't support trimming graphics from UI yet as it requires regenerating HTML, but we show them
                                        const clipStart = rawStart;
                                        const clipEnd = rawEnd;
                                        return (
                                            <div
                                                key={clipId}
                                                onClick={(e) => { e.stopPropagation(); setSelectedClipId(clipId); }}
                                                title="Графический элемент"
                                                className={`absolute h-9 bg-fuchsia-600/80 rounded-sm border hover:brightness-110 shadow-inner overflow-hidden flex items-center cursor-pointer group/g1 ${
                                                    isSelected ? 'border-white ring-2 ring-white/50 z-10' : 'border-fuchsia-400/50'
                                                }`}
                                                style={{ left: `${(clipStart / duration) * 100}%`, width: `${((clipEnd - clipStart) / duration) * 100}%` }}
                                            >
                                                <div className="w-full h-full opacity-30 bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(0,0,0,0.2)_4px,rgba(0,0,0,0.2)_8px)] pointer-events-none" />
                                                <span className="text-[9px] text-white/90 absolute left-4 font-mono font-bold pointer-events-none tracking-tight overflow-hidden text-ellipsis whitespace-nowrap right-4">✨ {clip.label.toUpperCase()}</span>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}

                            {/* V1 Track */}
                            <div className="h-12 border-b border-zinc-800/60 bg-transparent relative flex items-center px-1">
                                {multiTrackEdl.v1.map((clip, i) => {
                                    const clipId = `V1-Video-${i}`;
                                    const isSelected = selectedClipId === clipId;
                                    const clipStart = trimState?.clipIndex === i && trimState.track === 'v1' && trimState.type === 'left' && previewTrim ? previewTrim.time : clip.start;
                                    const clipEnd = trimState?.clipIndex === i && trimState.track === 'v1' && trimState.type === 'right' && previewTrim ? previewTrim.time : clip.end;

                                    return (
                                        <div key={clipId} onClick={(e) => handleClipClick(e, clipId, clip, i, 'v1')} className={`absolute h-9 bg-indigo-600/80 rounded-sm border hover:brightness-110 shadow-inner overflow-hidden flex items-center group/clip ${activeTool === 'pointer' ? 'cursor-pointer' : 'cursor-crosshair'} ${isSelected ? 'border-white ring-2 ring-white/50 z-10' : 'border-indigo-400/50'}`} style={{ left: `${(clipStart / duration) * 100}%`, width: `${((clipEnd - clipStart) / duration) * 100}%` }}>
                                            <div className="w-full h-full opacity-30 bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,rgba(0,0,0,0.2)_4px,rgba(0,0,0,0.2)_8px)] pointer-events-none" />
                                            <span className="text-[9px] text-white/70 absolute left-3 font-mono font-medium pointer-events-none tracking-tight">V1 MEDIA</span>
                                            {activeTool === 'pointer' && (
                                                <>
                                                    <div className={`absolute left-0 top-0 bottom-0 w-3 cursor-ew-resize bg-white/0 hover:bg-white/40 flex items-center justify-center z-20 ${trimState?.pointerId ? 'pointer-events-auto bg-white/40' : ''}`} onPointerDown={(e) => handleTrimStart(e, 'v1', i, 'left', clip.start)} onPointerMove={handleTrimMove} onPointerUp={handleTrimEnd} />
                                                    <div className={`absolute right-0 top-0 bottom-0 w-3 cursor-ew-resize bg-white/0 hover:bg-white/40 flex items-center justify-center z-20 ${trimState?.pointerId ? 'pointer-events-auto bg-white/40' : ''}`} onPointerDown={(e) => handleTrimStart(e, 'v1', i, 'right', clip.end)} onPointerMove={handleTrimMove} onPointerUp={handleTrimEnd} />
                                                </>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                            
                            {/* A1 Track */}
                            <div className="h-12 border-b border-zinc-800/60 bg-transparent relative flex items-center px-1">
                                {multiTrackEdl.a1.map((clip, i) => {
                                    const clipId = `A1-Audio-${i}`;
                                    const isSelected = selectedClipId === clipId;
                                    const clipStart = trimState?.clipIndex === i && trimState.track === 'a1' && trimState.type === 'left' && previewTrim ? previewTrim.time : clip.start;
                                    const clipEnd = trimState?.clipIndex === i && trimState.track === 'a1' && trimState.type === 'right' && previewTrim ? previewTrim.time : clip.end;

                                    // Determine slice of audioPeaks for this specific clip
                                    // The audioPeaks array represents the entire `duration`
                                    const peaks = audioPeaks && audioPeaks.length > 0 ? audioPeaks : Array(100).fill(20);
                                    const startIdx = Math.floor((clipStart / duration) * peaks.length);
                                    const endIdx = Math.ceil((clipEnd / duration) * peaks.length);
                                    const clipPeaks = peaks.slice(startIdx, endIdx);

                                    return (
                                        <div key={clipId} onClick={(e) => handleClipClick(e, clipId, clip, i, 'a1')} className={`absolute h-9 bg-emerald-600/80 rounded-sm border hover:brightness-110 shadow-inner overflow-hidden flex items-center group/clip ${activeTool === 'pointer' ? 'cursor-pointer' : 'cursor-crosshair'} ${isSelected ? 'border-white ring-2 ring-white/50 z-10' : 'border-emerald-400/40'}`} style={{ left: `${(clipStart / duration) * 100}%`, width: `${((clipEnd - clipStart) / duration) * 100}%` }}>
                                            
                                            <div className="w-full h-full flex items-center justify-between px-0.5 opacity-70 pointer-events-none">
                                                {clipPeaks.map((peak, idx) => (
                                                    <div 
                                                        key={idx} 
                                                        className="bg-emerald-200/90 rounded-full" 
                                                        style={{ 
                                                            height: `${Math.max(10, peak)}%`, 
                                                            width: `${100 / clipPeaks.length}%`,
                                                            margin: '0 0.5px'
                                                        }} 
                                                    />
                                                ))}
                                            </div>
                                            
                                            {activeTool === 'pointer' && (
                                                <>
                                                    <div className={`absolute left-0 top-0 bottom-0 w-3 cursor-ew-resize bg-white/0 hover:bg-white/40 flex items-center justify-center z-20 ${trimState?.pointerId ? 'pointer-events-auto bg-white/40' : ''}`} onPointerDown={(e) => handleTrimStart(e, 'a1', i, 'left', clip.start)} onPointerMove={handleTrimMove} onPointerUp={handleTrimEnd} />
                                                    <div className={`absolute right-0 top-0 bottom-0 w-3 cursor-ew-resize bg-white/0 hover:bg-white/40 flex items-center justify-center z-20 ${trimState?.pointerId ? 'pointer-events-auto bg-white/40' : ''}`} onPointerDown={(e) => handleTrimStart(e, 'a1', i, 'right', clip.end)} onPointerMove={handleTrimMove} onPointerUp={handleTrimEnd} />
                                                </>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        </div>

                        <div className="absolute top-0 bottom-0 w-px bg-red-500 z-40 pointer-events-none shadow-[0_0_12px_rgba(239,68,68,1)]" style={{ left: `${(timelineTime / duration) * 100}%` }}>
                            <div className="w-2.5 h-2.5 bg-red-500 rounded-sm absolute -top-1 -left-1 shadow-md"></div>
                        </div>

                    </div>
                </div>
            </div>
        </div>
    );
}

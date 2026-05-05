"use client";

import React from "react";

export default function TimelineEditor({ 
  transcript,
  activeEdits,
  onEditsChange
}: { 
  transcript: any;
  activeEdits: any[];
  onEditsChange: (edits: any[]) => void;
}) {
    if (!transcript || !transcript.words) return <div className="p-4 text-zinc-500 text-sm">Загрузка таймлайна...</div>;

    const words = transcript.words;
    if (words.length === 0) return <div className="p-4 text-zinc-500 text-sm">Слова не найдены...</div>;

    // Helper to toggle cut on a word
    const handleWordClick = (word: any) => {
        let cutIndex = -1;
        const isCut = activeEdits.some((edit, idx) => {
            if (edit.action === "cut_out") {
                // Check if word overlaps with the cut
                if ((word.start >= edit.start && word.start < edit.end) || 
                    (word.end > edit.start && word.end <= edit.end) ||
                    (word.start <= edit.start && word.end >= edit.end) // word envelopes cut
                   ) {
                    cutIndex = idx;
                    return true;
                }
            }
            return false;
        });

        if (isCut) {
            // Remove the cut block completely
            const newEdits = [...activeEdits];
            newEdits.splice(cutIndex, 1);
            onEditsChange(newEdits);
        } else {
            // Add a cut block for this exact word duration
            onEditsChange([...activeEdits, { action: "cut_out", start: word.start, end: word.end }]);
        }
    };

    return (
        <div className="flex flex-col gap-2 h-full">
            <div className="flex justify-between items-center mb-1 sticky top-0 bg-[#121214] z-10 py-1">
                <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider flex items-center gap-2">
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 10l-2 1m0 0l-2-1m2 1v2.5M20 7l-2 1m2-1l-2-1m2 1v2.5M14 4l-2-1-2 1M4 7l2-1M4 7l2 1M4 7v2.5M12 21l-2-1m2 1l2-1m-2 1v-2.5M6 18l-2-1v-2.5M18 18l2-1v-2.5" />
                    </svg>
                    Smart Timeline
                </h3>
                <span className="text-[10px] text-zinc-500 bg-zinc-900 px-2 py-0.5 rounded-full border border-zinc-800 flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block animate-pulse"></span>
                    Клик для вырезки / отмены
                </span>
            </div>
            
            {/* Minimalist wrap-block timeline (Descript-style) */}
            <div className="flex-1 overflow-y-auto px-1 group">
                <div className="flex flex-wrap leading-loose gap-y-2 gap-x-0.5">
                    {words.map((w: any, idx: number) => {
                        // Check if word is effectively inside a cut_out
                        const isCut = activeEdits.some(edit => edit.action === "cut_out" && (w.start >= edit.start - 0.1 && w.end <= edit.end + 0.1));
                        
                        return (
                            <span 
                                key={idx}
                                onClick={() => handleWordClick(w)}
                                className={`
                                    relative cursor-pointer transition-all px-1 rounded-sm text-[13px] font-sans user-select-none
                                    ${isCut 
                                        ? 'text-red-400/80 bg-red-900/10 line-through decoration-red-500/60 hover:opacity-100 hover:bg-red-900/30 font-medium' 
                                        : 'text-zinc-300 hover:bg-indigo-500/20 hover:text-white font-normal'
                                    }
                                `}
                                title={`Start: ${w.start.toFixed(2)}s | End: ${w.end.toFixed(2)}s`}
                            >
                                {w.word}
                            </span>
                        )
                    })}
                </div>
            </div>
        </div>
    );
}

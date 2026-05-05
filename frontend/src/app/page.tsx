"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const router = useRouter();

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setUploading(true);

    const formData = new FormData();
    formData.append("file", file);

    const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

    try {
      const response = await fetch(`${API_URL}/api/video/upload`, {
        method: "POST",
        body: formData,
      });
      const data = await response.json();

      // Navigate to the editor directly with exactly generated ID and URL!
      router.push(`/editor/${data.file_id}?filename=${data.filename}`);
    } catch (error) {
      console.error("Upload failed", error);
      alert("Ошибка загрузки. Проверьте, включен ли бэкенд на порту 8000.");
      setUploading(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#09090b] text-zinc-100 flex flex-col items-center justify-center p-6 font-sans relative overflow-hidden">
      {/* Ambient background glows */}
      <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-indigo-600/10 blur-[150px] pointer-events-none rounded-full" />
      <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] bg-fuchsia-600/10 blur-[150px] pointer-events-none rounded-full" />

      <div className="max-w-xl w-full bg-[#121214]/80 backdrop-blur-2xl border border-zinc-800/60 rounded-[32px] shadow-2xl p-10 z-10 relative">
        <div className="relative z-10">
          <div className="flex justify-center mb-8">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-fuchsia-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
          </div>

          <h1 className="text-4xl font-extrabold tracking-tight mb-3 text-center text-zinc-100">
            Montage AI Studio
          </h1>
          <p className="text-zinc-500 mb-10 text-center text-[15px] max-w-sm mx-auto">
            Ваш личный ИИ-режиссер. Загрузите видео, и алгоритм сам подготовит его для Shorts или Reels.
          </p>

          <div className="flex flex-col gap-6">
            <div className="relative group cursor-pointer transition-all">
              <input
                type="file"
                accept="video/*"
                onChange={handleFileChange}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
              />
              <div className={`border-2 border-dashed rounded-[24px] p-10 flex flex-col items-center justify-center transition-all duration-300 ${file ? 'border-indigo-500 bg-indigo-500/10 shadow-[0_0_30px_rgba(99,102,241,0.15)]' : 'border-zinc-800 hover:border-indigo-500/50 hover:bg-zinc-900/50'}`}>
                <svg className={`w-12 h-12 mb-4 transition-colors ${file ? 'text-indigo-500' : 'text-zinc-600'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                </svg>
                <p className="text-[15px] font-semibold text-zinc-300 tracking-wide">
                  {file ? file.name : "Нажмите или перетащите видео"}
                </p>
                <p className="text-[12px] text-zinc-500 mt-2 font-mono bg-zinc-900 px-3 py-1 rounded-full border border-zinc-800">MP4, MOV до 500MB</p>
              </div>
            </div>

            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="w-full bg-zinc-100 hover:bg-white disabled:bg-zinc-800 disabled:text-zinc-600 text-zinc-900 font-bold py-4 px-4 rounded-[20px] transition-all shadow-xl active:scale-[0.98] flex items-center justify-center text-[15px]"
            >
              {uploading ? (
                <span className="flex items-center justify-center gap-3">
                  <svg className="animate-spin h-5 w-5 text-indigo-500" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Загрузка медиа...
                </span>
              ) : "Начать магию"}
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}

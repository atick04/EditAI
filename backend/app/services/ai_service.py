import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv(override=True)

groq_api_key = os.getenv("GROQ_API_KEY")
# Используем OpenAI SDK, но направляем запросы на сверхбыстрые серверы Groq
client = AsyncOpenAI(
    api_key=groq_api_key,
    base_url="https://api.groq.com/openai/v1"
)

async def transcribe_audio(audio_path: str):
    """Transcribes an audio file and returns text with timestamps using Groq Whisper."""
    if not os.path.exists(audio_path):
        print(f"Audio file not found for transcription: {audio_path}")
        return None
        
    try:
        print(f"Starting Whisper transcription for {audio_path} via Groq...")
        with open(audio_path, "rb") as audio_file:
            try:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-large-v3",
                    file=audio_file,
                    prompt="Ум, эээ, ааа, ммм, ну, короче, значит, типа, вот, как бы.",
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"]
                )
            except Exception as e:
                print(f"Word-level timestamps failed natively, retrying without: {e}")
                audio_file.seek(0)
                transcript = await client.audio.transcriptions.create(
                    model="whisper-large-v3",
                    file=audio_file,
                    prompt="Ум, эээ, ааа, ммм, ну, короче, значит, типа, вот, как бы.",
                    response_format="verbose_json"
                )
        print("Transcription complete!")
        return transcript.model_dump()
    except Exception as e:
        print(f"OpenAI Transcription error: {str(e)}")
        return None

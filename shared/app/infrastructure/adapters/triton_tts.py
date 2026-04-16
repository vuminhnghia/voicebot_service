import asyncio
import io

import numpy as np
import soundfile as sf
import tritonclient.http as httpclient

from app.domain.ports.tts import TTSPort


class TritonTTSAdapter(TTSPort):
    """TTS adapter — calls mms_tts model on Triton."""

    def __init__(self, triton_url: str) -> None:
        self._client = httpclient.InferenceServerClient(url=triton_url)

    def _infer(self, text: str) -> bytes:
        text_np = np.array([[text.encode("utf-8")]], dtype=object)
        text_input = httpclient.InferInput("text_input", [1, 1], "BYTES")
        text_input.set_data_from_numpy(text_np)

        result = self._client.infer(
            "mms_tts",
            inputs=[text_input],
            outputs=[
                httpclient.InferRequestedOutput("audio_output"),
                httpclient.InferRequestedOutput("sample_rate"),
            ],
        )
        audio = result.as_numpy("audio_output").flatten().astype(np.float32)
        sr = int(result.as_numpy("sample_rate").flatten()[0])

        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return buf.read()

    async def synthesize(self, text: str) -> bytes:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._infer, text)

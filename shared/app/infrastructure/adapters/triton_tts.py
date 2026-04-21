import io
import time

import numpy as np
import soundfile as sf
import structlog
import tritonclient.http as httpclient
import tritonclient.http.aio as httpclient_aio

from app.domain.ports.tts import TTSPort

logger = structlog.get_logger(__name__)


class TritonTTSAdapter(TTSPort):
    """TTS adapter — calls mms_tts model on Triton."""

    def __init__(self, triton_url: str) -> None:
        self._client = httpclient_aio.InferenceServerClient(url=triton_url)

    async def synthesize(self, text: str) -> bytes:
        log = logger.bind(text_len=len(text))
        log.debug("tts_start")
        t0 = time.monotonic()
        try:
            text_np = np.array([[text.encode("utf-8")]], dtype=object)
            text_input = httpclient.InferInput("text_input", [1, 1], "BYTES")
            text_input.set_data_from_numpy(text_np)

            result = await self._client.infer(
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
            audio_bytes = buf.read()
        except Exception as exc:
            log.error("tts_error", duration_s=round(time.monotonic() - t0, 3), error=str(exc))
            raise

        log.info("tts_complete", duration_s=round(time.monotonic() - t0, 3), audio_bytes=len(audio_bytes))
        return audio_bytes

    async def aclose(self) -> None:
        await self._client.close()

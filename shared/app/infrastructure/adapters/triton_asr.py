import asyncio
import io
import time

import librosa
import numpy as np
import structlog
import tritonclient.http as httpclient
import tritonclient.http.aio as httpclient_aio

from app.domain.ports.asr import ASRPort

logger = structlog.get_logger(__name__)


class TritonASRAdapter(ASRPort):
    """ASR adapter — calls parakeet_asr model on Triton."""

    def __init__(self, triton_url: str) -> None:
        self._client = httpclient_aio.InferenceServerClient(url=triton_url)

    def _prepare_inputs(self, audio_bytes: bytes) -> list:
        buf = io.BytesIO(audio_bytes)
        audio, sr = librosa.load(buf, sr=None, mono=True)
        audio = audio.astype(np.float32)

        audio_input = httpclient.InferInput("audio_input", [1, audio.shape[0]], "FP32")
        audio_input.set_data_from_numpy(audio[np.newaxis, :])

        sr_input = httpclient.InferInput("sample_rate", [1, 1], "INT32")
        sr_input.set_data_from_numpy(np.array([[sr]], dtype=np.int32))

        return [audio_input, sr_input]

    async def transcribe(self, audio_bytes: bytes) -> str:
        log = logger.bind(audio_bytes=len(audio_bytes))
        log.debug("asr_start")
        t0 = time.monotonic()
        try:
            loop = asyncio.get_running_loop()
            inputs = await loop.run_in_executor(None, self._prepare_inputs, audio_bytes)

            result = await self._client.infer(
                "parakeet_asr",
                inputs=inputs,
                outputs=[httpclient.InferRequestedOutput("transcription")],
            )
            raw = result.as_numpy("transcription").flatten()[0]
            transcript = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        except Exception as exc:
            log.error("asr_error", duration_s=round(time.monotonic() - t0, 3), error=str(exc))
            raise

        log.info("asr_complete", duration_s=round(time.monotonic() - t0, 3), transcript_len=len(transcript))
        return transcript

    async def aclose(self) -> None:
        await self._client.close()

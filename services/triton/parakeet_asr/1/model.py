import json
import os
import numpy as np
import librosa
import onnxruntime as ort
import triton_python_backend_utils as pb_utils


MODEL_DIR = "/opt/models/parakeet_asr"
TARGET_SAMPLE_RATE = 16000

# Mel spectrogram params từ preprocessor_cfg.yaml
WIN_LENGTH  = int(0.025 * TARGET_SAMPLE_RATE)  # 400
HOP_LENGTH  = int(0.01  * TARGET_SAMPLE_RATE)  # 160
N_FFT       = 512
N_MELS      = 80
DITHER      = 1.0e-5


class TritonPythonModel:
    def initialize(self, args):
        model_config = json.loads(args["model_config"])
        # Triton parameters là dict, không phải list
        params = {k: v["string_value"] for k, v in model_config.get("parameters", {}).items()}
        model_dir = params.get("model_dir", MODEL_DIR)

        with open(os.path.join(model_dir, "vocab.json"), encoding="utf-8") as f:
            self.vocabulary = json.load(f)
        self.blank_id = len(self.vocabulary)

        providers = ["CPUExecutionProvider"]

        onnx_path = os.path.join(model_dir, "model.onnx")
        self.session = ort.InferenceSession(onnx_path, providers=providers)
        self.input_names  = [inp.name for inp in self.session.get_inputs()]
        self.output_names = [out.name for out in self.session.get_outputs()]

    def _preprocess(self, audio: np.ndarray, sample_rate: int):
        """Raw audio → log mel spectrogram với librosa (thay NeMo)."""
        if sample_rate != TARGET_SAMPLE_RATE:
            audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=TARGET_SAMPLE_RATE)

        # Dithering (per NeMo config)
        audio = audio + np.random.randn(len(audio)) * DITHER

        mel = librosa.feature.melspectrogram(
            y=audio,
            sr=TARGET_SAMPLE_RATE,
            n_fft=N_FFT,
            hop_length=HOP_LENGTH,
            win_length=WIN_LENGTH,
            n_mels=N_MELS,
            window="hann",
            power=2.0,
        )

        # Log scale
        log_mel = np.log(mel + 1e-14)  # [80, T]

        # Per-feature normalization (normalize=per_feature trong NeMo)
        mean = log_mel.mean(axis=1, keepdims=True)
        std  = log_mel.std(axis=1,  keepdims=True)
        log_mel = (log_mel - mean) / (std + 1e-5)

        # Batch dim: [1, 80, T]
        log_mel = log_mel[np.newaxis].astype(np.float32)
        length  = np.array([log_mel.shape[2]], dtype=np.int64)
        return log_mel, length

    def _ctc_greedy_decode(self, logprobs: np.ndarray) -> str:
        indices = np.argmax(logprobs, axis=-1)
        deduped = [indices[0]]
        for idx in indices[1:]:
            if idx != deduped[-1]:
                deduped.append(idx)
        tokens = [self.vocabulary[i] for i in deduped if i != self.blank_id]
        return "".join(tokens).replace("▁", " ").strip()

    def execute(self, requests):
        responses = []
        for request in requests:
            audio_tensor = pb_utils.get_input_tensor_by_name(request, "audio_input")
            audio = audio_tensor.as_numpy().flatten().astype(np.float32)

            sr_tensor = pb_utils.get_input_tensor_by_name(request, "sample_rate")
            sample_rate = int(sr_tensor.as_numpy()[0]) if sr_tensor is not None else TARGET_SAMPLE_RATE

            processed, processed_length = self._preprocess(audio, sample_rate)

            onnx_inputs = {}
            for name in self.input_names:
                if "length" in name or "len" in name:
                    onnx_inputs[name] = processed_length
                else:
                    onnx_inputs[name] = processed

            outputs  = self.session.run(self.output_names, onnx_inputs)
            logprobs = outputs[0][0]  # [T, vocab_size]

            text = self._ctc_greedy_decode(logprobs)
            out_tensor = pb_utils.Tensor("transcription", np.array([[text]], dtype=object))
            responses.append(pb_utils.InferenceResponse(output_tensors=[out_tensor]))

        return responses

    def finalize(self):
        del self.session

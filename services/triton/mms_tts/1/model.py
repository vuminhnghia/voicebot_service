import json
import os
import numpy as np
import onnxruntime as ort
import triton_python_backend_utils as pb_utils
from transformers import AutoTokenizer


SAMPLE_RATE = 16000  # MMS-TTS output: 16kHz


class TritonPythonModel:
    def initialize(self, args):
        model_config = json.loads(args["model_config"])
        params = {k: v["string_value"] for k, v in model_config.get("parameters", {}).items()}
        model_dir = params.get("model_dir", "/opt/models/mms_tts_vie")

        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)

        onnx_path = os.path.join(model_dir, "model.onnx")
        providers = ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(onnx_path, providers=providers)
        self.output_names = [o.name for o in self.session.get_outputs()]

    def execute(self, requests):
        responses = []
        for request in requests:
            text_tensor = pb_utils.get_input_tensor_by_name(request, "text_input")
            text = text_tensor.as_numpy()[0][0].decode("utf-8")

            inputs = self.tokenizer(text, return_tensors="np")
            ort_inputs = {
                "input_ids": inputs["input_ids"].astype(np.int64),
                "attention_mask": inputs["attention_mask"].astype(np.int64),
            }

            outputs = self.session.run(self.output_names, ort_inputs)
            # waveform là output đầu tiên, shape: [1, num_samples] hoặc [1, 1, num_samples]
            waveform = outputs[0].squeeze().astype(np.float32)

            audio_out = pb_utils.Tensor("audio_output", waveform)
            sr_out = pb_utils.Tensor("sample_rate", np.array([SAMPLE_RATE], dtype=np.int32))
            responses.append(pb_utils.InferenceResponse(output_tensors=[audio_out, sr_out]))

        return responses

    def finalize(self):
        del self.session

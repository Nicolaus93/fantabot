"""
Text-to-speech service based on the xtts model.

The following code is based on the [XTTS-v2 model](https://huggingface.co/coqui/XTTS-v2)
and Coqui's [TTS package](https://github.com/coqui-ai/TTS) repository.

The TTS package is licensed under the Mozilla Public License 2.0,
which you may find at https://github.com/coqui-ai/TTS/blob/dev/LICENSE.txt

The model itself is licensed under the Coqui Public Model License,
which you may find at https://coqui.ai/cpml

"""

import io
import modal
import time

tts_image = (
    modal.Image.debian_slim(python_version="3.11.9")
    .apt_install(
        "git",
        "ffmpeg"
    )
    .pip_install(
        "git+https://github.com/coqui-ai/TTS@8c20a599d8d4eac32db2f7b8cd9f9b3d1190b73a",
        "deepspeed==0.10.3",
        "pydub",
    )
    .env(
        {"COQUI_TOS_AGREED": "1"}
    )  # Coqui requires you to agree to the terms of service before downloading the model
)

with tts_image.imports():
    from TTS.api import TTS
    import torch

app = modal.App(
    name="xtts-to-voice",
    image=tts_image,
)

@app.cls(
    image=tts_image,
    gpu="A10G",
    container_idle_timeout=600,
    timeout=600,  # slow load so make sure timeout is long enough to support model load
    concurrency_limit=1,
)
class XTTS:
    def __init__(self):
        pass

    # We can stack the build and enter methods to download the model during build and load it during entry
    @modal.build()
    @modal.enter()
    def load_model(self):
        # """
        # Load the model weights into GPU memory when the container starts.
        # """
        print("Loading XTTS model")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(
            self.device
        )
        print("XTTS model loaded")
        speakers = self.model.synthesizer.tts_model.speaker_manager.speakers.keys()
        print(f"Supported speakers: {speakers}")

    @modal.method()
    def prewarm(self):
        # no-op to prewarm XTTS model instance
        pass

    @modal.method()
    def speak(self, text, speaker="Kazuhiko Atallah", language="en"):
        """
        Runs xtts-v2 on a given text.
        """
        t0 = time.time()
        # Save into an in-memory wav file
        wav_file = io.BytesIO()
        self.model.tts_to_file(
            text=text,
            file_path=wav_file,
            speaker=speaker,
            language=language,
        )
        print(f"TTS completed in {time.time() - t0:.2f}s")

        # return wav as a file object
        return text, wav_file


# For local testing, run `modal run -q src.xtts --text "Hello, how are you doing on this fine day?"`
@app.function(image=tts_image, secrets=[modal.Secret.from_name('fantabot-secrets')])
async def tts_entrypoint(text):
    print("Doing something..")
    tts = XTTS()

    # run multiple times to ensure cache is warmed up
    wav_file = "/tmp/output_xtts.wav"
    for i in range(3):
        text, wav = tts.speak.remote(text)
        print(text)
        with open(wav_file, "wb") as f:
            f.write(wav.getvalue())

    from pydub import AudioSegment
    import requests
    import os

    # Load the WAV file
    audio = AudioSegment.from_wav(wav_file)

    # Export as OGG
    ogg_file = "/tmp/output.ogg"
    audio.export(ogg_file, format="ogg")

    TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
    #TELEGRAM_CHAT_ID = 268217449
    TELEGRAM_CHAT_ID = 258851952

    with open(ogg_file, 'rb') as audio:
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'title': 'something to listen to',
            'parse_mode': 'HTML'
        }
        files = {
            'audio': audio.read(),
        }
        resp = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendAudio",
            data=payload,
            files=files
        ).json()
        print(resp)


@app.local_entrypoint()
def main(text: str = "Hello, how are you doing on this fine day?"):
    tts_entrypoint.remote(text=text)

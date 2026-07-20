FROM python:3.10-slim

WORKDIR /app

# ffmpeg: wandelt MP3-Uploads der Voice-Recording-Seite nach WAV (siehe
# voice_recording_controller.py) - Wiedergabe (ROS + "Play WAV"-Blockly-
# Block) liest ausschliesslich WAV.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY ./pib_api/flask/requirements.txt /app

COPY ./pib_blockly/pib_blockly_client /tmp/pib_blockly_client
RUN pip install /tmp/pib_blockly_client

RUN pip install -r requirements.txt

COPY ./pib_api/flask/ .

RUN flask --app run db upgrade
RUN flask --app run seed_db


CMD ["flask", "--app", "run", "run"]

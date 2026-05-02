from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any

from rocky_relay.config import Config, load_config
from rocky_relay.pipeline import run_typed_turn


class RockyRelayHandler(BaseHTTPRequestHandler):
    config: Config

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": "rocky-relay",
                    "llm_backend": self.config.llm_backend,
                    "tts_backend": self.config.tts_backend,
                    "persona": self.config.persona,
                }
            )
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/chat":
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return

        try:
            body = self._read_json()
            text = str(body.get("text", "")).strip()
            result = run_typed_turn(
                text,
                self.config,
                llm_backend=_optional_str(body.get("llm_backend")),
                tts_backend=_optional_str(body.get("tts_backend")),
                persona=_optional_str(body.get("persona")),
            )
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._send_json(result.as_dict(include_audio=True))

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def serve(config: Config) -> None:
    RockyRelayHandler.config = config
    server = ThreadingHTTPServer((config.host, config.port), RockyRelayHandler)
    print(f"Rocky Relay server listening on http://{config.host}:{config.port}")
    print("Endpoints: GET /health, POST /chat")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nRocky Relay server stopped.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the Rocky Relay local server.")
    parser.add_argument("--config", help="Path to config.json.")
    parser.add_argument("--host", help="Override host.")
    parser.add_argument("--port", type=int, help="Override port.")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.host or args.port:
        config = Config(
            root_dir=config.root_dir,
            host=args.host or config.host,
            port=args.port or config.port,
            log_dir=config.log_dir,
            output_dir=config.output_dir,
            capture_dir=config.capture_dir,
            ffmpeg_bin=config.ffmpeg_bin,
            mac_audio_device=config.mac_audio_device,
            mac_record_sample_rate=config.mac_record_sample_rate,
            mac_record_channels=config.mac_record_channels,
            mac_record_duration_s=config.mac_record_duration_s,
            stt_backend=config.stt_backend,
            whisper_cpp_bin=config.whisper_cpp_bin,
            whisper_cpp_model=config.whisper_cpp_model,
            whisper_cpp_language=config.whisper_cpp_language,
            whisper_cpp_no_gpu=config.whisper_cpp_no_gpu,
            llm_backend=config.llm_backend,
            ollama_url=config.ollama_url,
            ollama_model=config.ollama_model,
            tts_backend=config.tts_backend,
            piper_bin=config.piper_bin,
            piper_model=config.piper_model,
            rocky_tts_path=config.rocky_tts_path,
            rocky_tts_server_url=config.rocky_tts_server_url,
            rocky_tts_speed=config.rocky_tts_speed,
            rocky_tts_agree_cpml=config.rocky_tts_agree_cpml,
            smallest_api_key_env=config.smallest_api_key_env,
            smallest_tts_url=config.smallest_tts_url,
            smallest_voice_id=config.smallest_voice_id,
            smallest_sample_rate=config.smallest_sample_rate,
            smallest_speed=config.smallest_speed,
            smallest_language=config.smallest_language,
            smallest_output_format=config.smallest_output_format,
            smallest_stt_url=config.smallest_stt_url,
            smallest_stt_language=config.smallest_stt_language,
            smallest_stt_word_timestamps=config.smallest_stt_word_timestamps,
            smallest_stt_diarize=config.smallest_stt_diarize,
            persona=config.persona,
            rocky_say_path=config.rocky_say_path,
            max_reply_sentences=config.max_reply_sentences,
        )
    serve(config)


if __name__ == "__main__":
    main()

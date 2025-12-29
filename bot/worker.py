import asyncio
import argparse
import os
import sys
import signal
import inspect
import time
import aiohttp
from dotenv import load_dotenv
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import EndFrame, TextFrame
from pipecat.services.tavus.video import TavusVideoService
from pipecat import frames as pipecat_frames
try:
    from pipecat.transports.daily.transport import DailyParams, DailyTransport
except ImportError:
    from pipecat.transports.services.daily import DailyParams, DailyTransport

try:
    from pipecat.services.cartesia.tts import CartesiaTTSService
    CARTESIA_MODE = "streaming"
except ImportError:
    from pipecat.services.cartesia.http_tts import CartesiaHttpTTSService as CartesiaTTSService
    CARTESIA_MODE = "http"

load_dotenv()


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


class MediaDebugTap(FrameProcessor):
    """Counts Tavus -> Daily frames and prints heartbeats when DEBUG_MEDIA=1."""

    AUDIO_FRAME_TYPES = tuple(
        cls for cls in (
            getattr(pipecat_frames, "SpeechOutputAudioRawFrame", None),
            getattr(pipecat_frames, "OutputAudioRawFrame", None),
            getattr(pipecat_frames, "AudioRawFrame", None),
        )
        if cls is not None
    )
    VIDEO_FRAME_TYPES = tuple(
        cls for cls in (
            getattr(pipecat_frames, "OutputImageRawFrame", None),
            getattr(pipecat_frames, "OutputVideoRawFrame", None),
            getattr(pipecat_frames, "ImageRawFrame", None),
            getattr(pipecat_frames, "VideoRawFrame", None),
        )
        if cls is not None
    )

    def __init__(self, label: str, enabled: bool, heartbeat_seconds: float = 2.0):
        super().__init__(name=f"MediaDebugTap[{label}]")
        self._label = label
        self._enabled = enabled
        self._heartbeat_seconds = heartbeat_seconds
        self._video_frames = 0
        self._audio_frames = 0
        self._first_video_logged = False
        self._first_audio_logged = False
        self._last_heartbeat = time.monotonic()
        if self._enabled and not (self.VIDEO_FRAME_TYPES or self.AUDIO_FRAME_TYPES):
            print(f"[MEDIA] {self._label}: debug tap active but no frame types were detected; update Pipecat SDK.")

    async def process_frame(self, frame, source=None):  # type: ignore[override]
        if self._enabled:
            self._log_if_media(frame)
        await self.push_frame(frame)

    def _log_if_media(self, frame) -> None:
        now = time.monotonic()
        if self.VIDEO_FRAME_TYPES and isinstance(frame, self.VIDEO_FRAME_TYPES):
            self._video_frames += 1
            if not self._first_video_logged:
                width = getattr(frame, "width", "?")
                height = getattr(frame, "height", "?")
                fmt = getattr(frame, "format", getattr(frame, "fmt", "?"))
                print(f"[MEDIA] {self._label}: first video frame width={width} height={height} format={fmt}")
                self._first_video_logged = True
        if self.AUDIO_FRAME_TYPES and isinstance(frame, self.AUDIO_FRAME_TYPES):
            self._audio_frames += 1
            if not self._first_audio_logged:
                sample_rate = getattr(frame, "sample_rate", getattr(frame, "rate", "?"))
                channels = getattr(frame, "channels", getattr(frame, "num_channels", "?"))
                byte_length = len(getattr(frame, "audio", getattr(frame, "data", b"")))
                print(
                    f"[MEDIA] {self._label}: first audio frame sample_rate={sample_rate} "
                    f"channels={channels} bytes={byte_length}"
                )
                self._first_audio_logged = True
        if now - self._last_heartbeat >= self._heartbeat_seconds:
            self._last_heartbeat = now
            print(
                f"[MEDIA] {self._label}: forwarded_video_frames={self._video_frames} "
                f"forwarded_audio_frames={self._audio_frames}"
            )


class CartesiaDebugTap(FrameProcessor):
    """Counts Cartesia -> Tavus audio frames when DEBUG_MEDIA=1."""

    AUDIO_FRAME_TYPES = tuple(
        cls
        for cls in (
            getattr(pipecat_frames, "SpeechOutputAudioRawFrame", None),
            getattr(pipecat_frames, "OutputAudioRawFrame", None),
            getattr(pipecat_frames, "AudioRawFrame", None),
        )
        if cls is not None
    )

    def __init__(self, label: str, enabled: bool, heartbeat_seconds: float = 2.0):
        super().__init__(name=f"CartesiaDebugTap[{label}]")
        self._label = label
        self._enabled = enabled
        self._heartbeat_seconds = heartbeat_seconds
        self._audio_frames = 0
        self._first_audio_logged = False
        self._last_heartbeat = time.monotonic()
        if self._enabled and not self.AUDIO_FRAME_TYPES:
            print(f"[MEDIA] {self._label}: debug tap active but no audio frame types detected; update Pipecat SDK.")

    async def process_frame(self, frame, source=None):  # type: ignore[override]
        if self._enabled:
            self._log_if_audio(frame)
        await self.push_frame(frame)

    def _log_if_audio(self, frame) -> None:
        now = time.monotonic()
        if self.AUDIO_FRAME_TYPES and isinstance(frame, self.AUDIO_FRAME_TYPES):
            self._audio_frames += 1
            if not self._first_audio_logged:
                sample_rate = getattr(frame, "sample_rate", getattr(frame, "rate", "?"))
                channels = getattr(frame, "channels", getattr(frame, "num_channels", "?"))
                byte_length = len(getattr(frame, "audio", getattr(frame, "data", b"")))
                print(
                    f"[MEDIA] {self._label}: first audio frame sample_rate={sample_rate} "
                    f"channels={channels} bytes={byte_length}"
                )
                self._first_audio_logged = True
        if now - self._last_heartbeat >= self._heartbeat_seconds:
            self._last_heartbeat = now
            print(f"[MEDIA] {self._label}: forwarded_audio_frames={self._audio_frames}")


async def main():
    parser = argparse.ArgumentParser(description="Tavus Replica Bot (Cartesia -> Tavus)")
    parser.add_argument("--room_url", required=True, help="Daily room URL")
    parser.add_argument("--token", required=True, help="Daily meeting token")
    parser.add_argument("--bot_name", default="Replica", help="Name of the bot in the room")
    parser.add_argument("--mode", default="interactive", help="Mode: interactive or script")
    cli_args = parser.parse_args()

    print(f"Initializing bot: {cli_args.bot_name} for room: {cli_args.room_url}")

    # Environment configuration
    tavus_api_key = os.getenv("TAVUS_API_KEY") or ""
    tavus_replica_id = os.getenv("TAVUS_REPLICA_ID") or ""
    cartesia_api_key = os.getenv("CARTESIA_API_KEY") or ""
    cartesia_voice_id = os.getenv("CARTESIA_VOICE_ID") or ""
    cartesia_model = os.getenv("CARTESIA_MODEL") or "sonic-3"

    sample_rate_raw = os.getenv("CARTESIA_SAMPLE_RATE", "24000") or "24000"
    try:
        cartesia_sample_rate = int(sample_rate_raw)
    except ValueError:
        print(f"WARN: Invalid CARTESIA_SAMPLE_RATE='{sample_rate_raw}', falling back to 24000")
        cartesia_sample_rate = 24000

    missing = []
    if not cartesia_api_key:
        missing.append("CARTESIA_API_KEY")
    if not cartesia_voice_id:
        missing.append("CARTESIA_VOICE_ID")
    if not tavus_api_key:
        missing.append("TAVUS_API_KEY")
    if not tavus_replica_id:
        missing.append("TAVUS_REPLICA_ID")
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        sys.exit(2)

    media_debug_enabled = _truthy(os.getenv("DEBUG_MEDIA"))

    print(f"Cartesia mode: {CARTESIA_MODE}")
    print(f"Cartesia voice: {cartesia_voice_id}")
    print(f"Cartesia model: {cartesia_model}")
    print(f"Sample rate: {cartesia_sample_rate} Hz")
    print(f"Tavus replica id: {tavus_replica_id}")

    # Daily transport configuration with feature detection for available params
    desired_params: dict[str, object] = {
        "audio_in_enabled": True,
        "vad_enabled": False,
        "video_out_enabled": True,
        "video_out_is_live": True,
        "video_out_width": 1280,
        "video_out_height": 720,
        "video_out_framerate": 30,
        "video_out_destinations": ["camera"],
        "camera_out_enabled": True,
        "audio_out_enabled": True,
        "audio_out_destinations": ["microphone"],
        "microphone_out_enabled": True,
        "audio_out_sample_rate": None,
        "audio_out_channels": 1,
    }

    applied_params: dict[str, object] = {}
    ignored_params: dict[str, object] = {}

    try:
        params_probe = DailyParams()
    except TypeError:
        params_probe = None

    for key, value in desired_params.items():
        if params_probe is not None and hasattr(params_probe, key):
            applied_params[key] = value
        else:
            try:
                DailyParams(**{key: value})
            except TypeError:
                ignored_params[key] = value
            else:
                applied_params[key] = value

    print(f"DailyParams applied keys: {applied_params}")
    if ignored_params:
        print(f"DailyParams ignored (unsupported) keys: {ignored_params}")

    daily_params = DailyParams(**applied_params)

    transport = DailyTransport(
        room_url=cli_args.room_url,
        token=cli_args.token,
        bot_name=cli_args.bot_name,
        params=daily_params,
    )

    resolved_params = {
        key: getattr(daily_params, key)
        for key in applied_params.keys()
        if hasattr(daily_params, key)
    }
    print(f"DailyParams resolved values: {resolved_params}")

    # Services
    cartesia_kwargs = {
        "api_key": cartesia_api_key,
        "voice_id": cartesia_voice_id,
        "model": cartesia_model,
        "sample_rate": cartesia_sample_rate,
    }

    try:
        tts = CartesiaTTSService(**cartesia_kwargs)
    except TypeError as err:
        print(f"Error: CartesiaTTSService could not be initialized with provided configuration: {err}")
        sys.exit(2)

    aiohttp_session = aiohttp.ClientSession()

    tavus_kwargs = {
        "api_key": tavus_api_key,
        "replica_id": tavus_replica_id,
        "session": aiohttp_session,
    }

    try:
        tavus = TavusVideoService(
            **tavus_kwargs,
            sample_rate=cartesia_sample_rate,
        )
    except TypeError as err:
        print(f"WARN: TavusVideoService sample_rate override failed ({err}); continuing with provider defaults")
        try:
            tavus = TavusVideoService(**tavus_kwargs)
        except TypeError as err2:
            print(f"Error: TavusVideoService could not be initialized: {err2}")
            await aiohttp_session.close()
            sys.exit(2)

    # Pipeline construction
    media_tap = MediaDebugTap("tavus->daily", media_debug_enabled)
    cartesia_tap = CartesiaDebugTap("cartesia->tavus", media_debug_enabled)

    pipeline = Pipeline([
        transport.input(),
        tts,
        cartesia_tap,
        tavus,
        media_tap,
        transport.output(),
    ])

    task = PipelineTask(pipeline)

    # Runner setup
    runner = PipelineRunner()
    stop_event = asyncio.Event()

    async def _await_if_needed(result):
        if inspect.isawaitable(result):
            await result

    joined_logged = False
    welcome_sent = False

    participant_id_keys = ("id", "session_id", "user_id", "participant_id", "daily_id")
    participant_name_keys = ("user_name", "userName", "display_name", "displayName", "name", "username")
    participant_local_keys = ("local", "is_local", "isLocal")

    def _flatten_candidates(value):
        if isinstance(value, (list, tuple)):
            for item in value:
                yield from _flatten_candidates(item)
        elif value is not None:
            yield value

    def _looks_like_participant(candidate):
        if candidate is None:
            return False
        if isinstance(candidate, dict):
            return any(key in candidate for key in (*participant_id_keys, *participant_name_keys))
        return any(hasattr(candidate, key) for key in (*participant_id_keys, *participant_name_keys))

    def _unwrap_participant(candidate):
        extras: list[object] = []
        obj = candidate
        if isinstance(obj, (list, tuple)):
            elements = list(obj)
            obj = None
            for element in elements:
                if obj is None and _looks_like_participant(element):
                    obj = element
                else:
                    extras.append(element)
            if obj is None and elements:
                obj = elements[0]
                extras.extend(elements[1:])
        return obj, extras

    def _extract_field(source, *keys):
        if source is None:
            return None
        if isinstance(source, dict):
            for key in keys:
                value = source.get(key)
                if value not in (None, ""):
                    return value
        for key in keys:
            if hasattr(source, key):
                value = getattr(source, key)
                if value not in (None, ""):
                    return value
        return None

    def _extract_settings(candidates):
        for candidate in _flatten_candidates(candidates):
            if isinstance(candidate, dict):
                if any(key in candidate for key in ("bot_name", "botName", "name")):
                    return candidate
            elif hasattr(candidate, "bot_name") or hasattr(candidate, "botName"):
                return candidate
        return None

    def _extract_bot_name(settings):
        bot_name = _extract_field(settings, "bot_name", "botName", "name")
        return str(bot_name) if bot_name else None

    def _participant_summary(candidate):
        participant_obj, extras = _unwrap_participant(candidate)
        if participant_obj is None:
            return "unknown", "", False, extras
        participant_id = _extract_field(participant_obj, *participant_id_keys)
        name = _extract_field(participant_obj, *participant_name_keys)
        local_flag = _extract_field(participant_obj, *participant_local_keys)
        participant_id_str = str(participant_id) if participant_id not in (None, "") else "unknown"
        name_str = str(name) if name not in (None, "") else ""
        is_local = bool(local_flag)
        return participant_id_str, name_str, is_local, extras

    def _normalize_event_payload(handler_args, handler_kwargs):
        positional = list(handler_args)
        transport_obj = handler_kwargs.get("transport")
        if transport_obj is None and positional:
            transport_obj = positional.pop(0)

        participant_candidate = handler_kwargs.get("participant")
        if participant_candidate is None and positional:
            participant_candidate = positional.pop(0)

        participant_id_str, name_str, is_local_flag, participant_extras = _participant_summary(participant_candidate)

        extras: list[object] = []
        extras.extend(participant_extras)
        extras.extend(positional)
        if "settings" in handler_kwargs:
            extras.append(handler_kwargs["settings"])
        if "args" in handler_kwargs:
            extras.append(handler_kwargs["args"])
        if "kwargs" in handler_kwargs:
            extras.append(handler_kwargs["kwargs"])

        if participant_candidate is None:
            for candidate in _flatten_candidates(extras):
                if _looks_like_participant(candidate):
                    participant_candidate = candidate
                    participant_id_str, name_str, is_local_flag, _ = _participant_summary(participant_candidate)
                    break

        settings_obj = _extract_settings(extras)

        return transport_obj, participant_candidate, participant_id_str, name_str, is_local_flag, settings_obj

    async def on_first_participant_joined(*handler_args, **handler_kwargs):
        nonlocal welcome_sent
        try:
            _, _, participant_id, name, _, _ = _normalize_event_payload(handler_args, handler_kwargs)
            print(f"First participant joined: {participant_id} name='{name}'")
            print("Sending greeting via Cartesia -> Tavus pipeline")
            if not welcome_sent:
                welcome_sent = True
                try:
                    await task.queue_frames([
                        TextFrame("Hello, can you hear and see me?"),
                    ])
                except Exception as exc:
                    print(f"WARN: Failed to enqueue welcome message via Cartesia: {exc}")
        except Exception as exc:
            print(f"WARN: on_first_participant_joined handler error: {exc!r}; args={handler_args}; kwargs={handler_kwargs}")

    async def on_participant_joined(*handler_args, **handler_kwargs):
        nonlocal joined_logged
        try:
            transport_obj, participant_obj, participant_id, name, is_local, settings_obj = _normalize_event_payload(handler_args, handler_kwargs)
            display_name = name or "(no name)"
            print(f"Participant joined: {participant_id} name='{display_name}' local={is_local}")
            if is_local and not joined_logged:
                joined_logged = True
                print(f"✅ Joined Daily room: {cli_args.room_url} as {cli_args.bot_name} (participant {participant_id})")
            if not is_local:
                remote_display = name or participant_id
                print(f"Remote participant active: {remote_display} ({participant_id})")
                bot_targets = {cli_args.bot_name.lower()}
                settings_bot_name = _extract_bot_name(settings_obj)
                if settings_bot_name:
                    bot_targets.add(settings_bot_name.strip().lower())
                if str(remote_display).strip().lower() in bot_targets:
                    print("[MEDIA] Tavus avatar publishing tracks (audio/video) through Daily.")
        except Exception as exc:
            print(f"WARN: on_participant_joined handler error: {exc!r}; args={handler_args}; kwargs={handler_kwargs}")

    async def on_participant_left(*handler_args, **handler_kwargs):
        try:
            _, _, participant_id, name, _, _ = _normalize_event_payload(handler_args, handler_kwargs)
            print(f"Participant left: {participant_id} name='{name or '(no name)'}'")
        except Exception as exc:
            print(f"WARN: on_participant_left handler error: {exc!r}; args={handler_args}; kwargs={handler_kwargs}")

    async def on_joined_event(transport, *handler_args, **handler_kwargs):
        nonlocal joined_logged
        if not joined_logged:
            joined_logged = True
            print(f"✅ Joined Daily room: {cli_args.room_url} as {cli_args.bot_name}")
        if media_debug_enabled:
            print("[MEDIA] Daily transport joined; Tavus frames will be forwarded when available.")

    transport.add_event_handler("on_first_participant_joined", on_first_participant_joined)
    transport.add_event_handler("on_participant_joined", on_participant_joined)
    transport.add_event_handler("on_participant_left", on_participant_left)
    try:
        transport.add_event_handler("on_joined", on_joined_event)
    except Exception as exc:
        print(f"WARN: Could not attach on_joined handler: {exc}")

    # Graceful Shutdown
    async def shutdown(sig=None):
        print(f"Shutting down (Signal: {sig})")
        if not stop_event.is_set():
            stop_event.set()
        try:
            await task.queue_frames([EndFrame()])
        except Exception as exc:
            print(f"Failed to enqueue EndFrame during shutdown: {exc}")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s)))
        except NotImplementedError:
            # Windows event loops cannot register signal handlers directly.
            signal.signal(sig, lambda *_: asyncio.create_task(shutdown(sig)))

    print(f"Starting bot {cli_args.bot_name} in {cli_args.room_url}")
    runner_task = asyncio.create_task(runner.run(task))
    stop_waiter = asyncio.create_task(stop_event.wait())

    try:
        done, pending = await asyncio.wait(
            {runner_task, stop_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if runner_task in done:
            try:
                await runner_task
            except Exception as exc:
                print(f"Pipeline runner exited with error: {exc}")
            stop_event.set()
        else:
            # stop_event triggered; ensure pipeline finishes
            await runner_task
    finally:
        for task_handle in (stop_waiter, runner_task):
            if not task_handle.done():
                task_handle.cancel()
        await asyncio.gather(stop_waiter, runner_task, return_exceptions=True)

        try:
            for method_name in ("leave", "close", "disconnect"):
                method = getattr(transport, method_name, None)
                if callable(method):
                    try:
                        await _await_if_needed(method())
                    except Exception as exc:
                        print(f"WARN: Failed to {method_name} Daily transport cleanly: {exc}")
                    break
        except Exception as exc:
            print(f"WARN: Transport cleanup encountered an unexpected error: {exc}")

        for service, label in ((tts, "Cartesia TTS"), (tavus, "Tavus service")):
            for method_name in ("close", "stop", "shutdown"):
                method = getattr(service, method_name, None)
                if callable(method):
                    try:
                        signature = inspect.signature(method)
                        required = [
                            param
                            for param in signature.parameters.values()
                            if param.default is param.empty
                            and param.kind in (
                                param.POSITIONAL_ONLY,
                                param.POSITIONAL_OR_KEYWORD,
                            )
                        ]
                        if required:
                            continue
                        await _await_if_needed(method())
                    except Exception as exc:
                        print(f"WARN: Failed to {method_name} {label}: {exc}")
                    break

        try:
            await aiohttp_session.close()
        except Exception as exc:
            print(f"WARN: Failed to close aiohttp session cleanly: {exc}")

if __name__ == "__main__":
    asyncio.run(main())

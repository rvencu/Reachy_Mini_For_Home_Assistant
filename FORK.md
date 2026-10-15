# Smarty maintenance branch

This is the robot-side **Reachy Mini for Home Assistant** app. It supplies local
wake-word detection, audio capture/playback and an ESPHome voice endpoint. It is
separate from the Reachy control integration in HA, the ESPHome integration in HA,
and Smarty's HA/aibox services. HA remains responsible for the selected assistant
and each satellite's permissions.

## Baseline and fix

- Baseline: upstream `main`, commit `819af765637f68cf36357ff5e5e4cbcbf06ec8e4`, version 1.0.7.
- Maintained branch: `smarty`; fork version: `1.0.7+smarty.1`.
- Runtime checked: Reachy Mini Wireless, SDK **1.11.0**, Python 3.12.
- Symptom: the first wake word is recognized, the robot raises its head and keeps
  animating, but HA receives no usable command audio; later wake words stop working.

In SDK 1.11.0, `media.stop_playing()` sets the shared microphone/playback pipeline
to NULL. The app called it before playing the wake sound. The sound uses a separate
playbin, so its completion can start an HA request while capture remains stopped.
The fork uses `media.audio.clear_player()` to flush queued output while retaining
capture. It covers stop/pause, local-file cancellation/timeouts and Sendspin stop.
No model, sensitivity, permissions, motion configuration or speech service changes
are included.

The playback/local-file correction is a backport of the approach in
[upstream develop at 4407b7e](https://github.com/ha-china/Reachy_Mini_For_Home_Assistant/blob/4407b7ee1673f6436f9161b923a8f8688cf4a992/reachy_mini_home_assistant/audio/audio_player_playback.py).
The fork also applies it to Sendspin and adds regression coverage. The relevant
[SDK implementation](https://github.com/pollen-robotics/reachy_mini/blob/v1.11.0/src/reachy_mini/media/audio_gstreamer.py)
shares capture and streamed playback. `clear_player()` flushes streamed output;
it does not provide a separate public API to cancel the SDK's local-file playbin.
Local-file interruption therefore needs a future SDK improvement for immediate
speaker cancellation without stopping capture.

## Tests

Use Python 3.12 or newer, with NumPy and requests installed:

```sh
python -m unittest discover -s tests -p test_playback_capture.py -v
python -m unittest discover -s tests -p test_install_wheel.py -v
```

The eight tests exercise consecutive wake-sound callbacks, stop, pause, local-file
timeout/cancellation, Sendspin, missing robot and flush errors. The fake audio
backend models the SDK's shared-pipeline semantics; seven tests fail on upstream
1.0.7 and all pass with the correction. They do not replace a physical microphone,
HA transcription and speaker test. The fork's GitHub workflow runs this suite.
Four installer tests check offline restoration, rejection of an unvalidated SDK
or unresolved Git LFS models, and refusal to stop a different active robot app.

## Install on the robot

Keep the existing app and its ESPHome device; do not uninstall/re-add it in HA.
Use SSH to the robot's documented `pollen` account. From a checkout of this fork,
review and select a **full commit hash** on `smarty`, then run on the robot:

```sh
git checkout --detach <reviewed-commit>
git lfs pull
/venvs/apps_venv/bin/python -m unittest discover -s tests -p test_playback_capture.py -v
/venvs/apps_venv/bin/python -m pip wheel --no-deps --no-build-isolation --no-index --wheel-dir dist .
/venvs/apps_venv/bin/python scripts/install_wheel.py \
  --wheel dist/reachy_mini_home_assistant-1.0.7+smarty.1-py3-none-any.whl \
  --revision "$(git rev-parse HEAD)"
```

The checkout needs Git LFS for wake-word models and audio assets. The installer
rejects wheels containing LFS pointer text instead of these files. The installed
app environment supplies the build tools; no SDK or runtime
dependency upgrades are requested. If build tooling is missing, stop and prepare
a wheel separately rather than upgrading the robot's shared environment. The
installer accepts only SDK 1.11.0 and app 1.0.7 or this fork version. It backs up the
old package and metadata under `~/.local/share/reachy-smarty/backups/`, stops only
this voice app, installs the wheel without fetching dependencies, verifies every
Python source file against the wheel, and starts the app. An installation failure
restores the backup. Startup acceptance still needs to be checked in HA and by
speaking two consecutive requests.

The wheel hash, full Git revision and backup path are recorded in
`~/.local/share/reachy-smarty/current.json`. Keep the printed backup path. To roll
back, run the copy of the installer saved inside that backup:

```sh
/venvs/apps_venv/bin/python <backup-path>/install_wheel.py --restore <backup-path>
```

This restores only the app package and metadata, then restarts that app. HA,
the robot SDK, user settings outside the package and other robot apps are retained.

## Updates

Fetch upstream into the `upstream` remote, review changes, and merge or backport
onto `smarty`. Keep `main` and `develop` as upstream references. Bump the fork's
local version and installer expectations for each reviewed release; retain test
coverage and recheck compatibility when the SDK changes. Deploy a full commit,
not a moving branch name.

The robot's catalog still knows the original Hugging Face application. Its
**Update/Reinstall** action can replace this fork with upstream. Update this fork
through the documented wheel workflow instead. Upstream Hugging Face publishing
workflows are restricted to the upstream GitHub owner in this branch; this fork
does not publish to the original author's spaces.

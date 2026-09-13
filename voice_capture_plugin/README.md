# Peace Walker voice capture probe

This temporary research plugin captures decoded XAudio2 source buffers while armed.

1. Build `PeaceWalkerVoiceCapture.asi` with `build_plugin.bat`.
2. Put the ASI in the game's `scripts` folder alongside the existing ASI loader.
3. Start the game. The plugin remains idle by default.
4. Create `scripts/PWVoiceCapture.arm` immediately before triggering a test voice line.
5. Delete the marker immediately afterward.
6. Inspect the timestamped folder under `voice_captures`. It contains WAV files and `manifest.csv`.

Remove the ASI when voice mapping is complete.

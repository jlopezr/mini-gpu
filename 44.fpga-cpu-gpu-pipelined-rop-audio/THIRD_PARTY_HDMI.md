# HDMI transmitter attribution

The `hdmi*.v` files in this directory are imported from
[`danodus/ecp5_hdmi_audio_video`](https://github.com/danodus/ecp5_hdmi_audio_video),
commit cloned on 2026-11-17.  They provide the HDMI 1.4b packet path, including
data islands, TERC4, infoframes, ACR, LPCM packets and the ECP5 serializer.

They are MIT licensed; the complete notice is kept verbatim in
[`LICENSE.third_party_hdmi`](LICENSE.third_party_hdmi).  The imported project
attributes portions of its stack to `hdl-util/hdmi` under MIT OR Apache-2.0
and to BrunoLevy's ULX3S HDMI examples under MIT; that attribution is retained
in the source headers and the imported LICENSE.

MiniGPU-owned integration lives in `top.v`: it supplies the existing RGB
scanout and initially supplies zero-valued signed 16-bit stereo samples at
48 kHz.  The future PCM ring/DMA is deliberately not part of this import.

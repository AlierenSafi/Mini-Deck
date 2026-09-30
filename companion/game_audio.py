"""Discord render sessions only; never touches system or PUBG audio."""

import psutil


def discord_sessions():
    import comtypes
    from pycaw.utils import AudioSession
    from pycaw.api.audiopolicy import IAudioSessionControl2
    from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
    from pycaw.constants import CLSID_MMDeviceEnumerator

    enumerator = comtypes.CoCreateInstance(
        CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER
    )
    devices = enumerator.EnumAudioEndpoints(0, 1)  # all active render devices
    from pycaw.utils import AudioUtilities

    result = []
    for i in range(devices.GetCount()):
        device = AudioUtilities.CreateDevice(devices.Item(i))
        sessions = device.AudioSessionManager.GetSessionEnumerator()
        for j in range(sessions.GetCount()):
            session = AudioSession(sessions.GetSession(j).QueryInterface(IAudioSessionControl2))
            try:
                if (
                    session.State != 2
                    and session.Process
                    and session.Process.name().lower()
                    in ("discord.exe", "discordptb.exe", "discordcanary.exe")
                ):
                    result.append(session)
            except psutil.Error:
                continue
    return result


class DiscordAudio:
    def __init__(self, source=discord_sessions):
        self.source = source
        self.original = {}  # session identity -> original volume, never COM objects
        self.focus = False

    def sample(self):
        sessions = self.source()
        if self.focus:
            for session in sessions:
                key = session.InstanceIdentifier
                if key not in self.original:
                    volume = session.SimpleAudioVolume
                    self.original[key] = volume.GetMasterVolume()
                    volume.SetMasterVolume(min(self.original[key], 0.20), None)
        if not sessions:
            return None, None
        values = [s.SimpleAudioVolume for s in sessions]
        return round(max(v.GetMasterVolume() for v in values) * 100), all(
            v.GetMute() for v in values
        )

    def restore(self):
        for session in self.source():
            key = session.InstanceIdentifier
            if key in self.original:
                session.SimpleAudioVolume.SetMasterVolume(self.original[key], None)
        self.original.clear()
        self.focus = False

    def command(self, action):
        sessions = self.source()
        if action == 4 and self.focus:
            self.restore()
            return "Ayak sesi modu kapalı; Discord ses seviyesi geri yüklendi."
        if not sessions:
            raise ValueError("Discord ses oturumu yok. Discord’da bir ses kanalına bağlanın.")
        if action == 4:
            self.focus = True
            self.sample()
            return "Ayak sesi modu açık; yalnızca Discord sesi en fazla %20."
        if action == 1:
            muted = not all(s.SimpleAudioVolume.GetMute() for s in sessions)
            for session in sessions:
                session.SimpleAudioVolume.SetMute(muted, None)
            return "Discord sesi kapalı" if muted else "Discord sesi açık"
        if action in (2, 3):
            if self.focus:
                self.restore()
            delta = -0.1 if action == 2 else 0.1
            for session in sessions:
                volume = session.SimpleAudioVolume
                volume.SetMasterVolume(max(0.0, min(1.0, volume.GetMasterVolume() + delta)), None)
            return "Discord ses seviyesi değiştirildi."
        raise ValueError("Geçersiz ses komutu")

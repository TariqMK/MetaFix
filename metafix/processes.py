"""Run external metadata tools without opening a Windows console window."""
import os
import subprocess


def run_hidden(command, **kwargs):
    if os.name == 'nt':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = startup
    return subprocess.run(command, **kwargs)

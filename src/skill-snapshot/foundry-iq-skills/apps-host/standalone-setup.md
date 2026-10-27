# Prerequisites and runtime setup

The launcher implements Windows, macOS and Linux process ownership. **macOS
acceptance is blocked until a Mac is available**; implementation is not execution
proof. Windows requires Windows 10 / Server 2016 or later.
Use an explicit Node 22.13+ executable (development verification: 22.19.0)
and an existing Python 3.12 executable. Configure `python` as an absolute path;
the same executable runs the runtime bootstrap and, by default, the process
supervisor. An optional absolute `supervisorPython` overrides the latter.
The supervisor's standard-library Windows Job Object or POSIX process-group
integration installs nothing.

Complete runtime setup explicitly using your configured Python package sources.
From an operator directory outside the installed plugin, run these commands for
each configured domain (all three are shown):

```powershell
& 'C:\operator\python312\python.exe' -I 'C:\installed plugin\runtime\bootstrap.py' setup ontology
& 'C:\operator\python312\python.exe' -I 'C:\installed plugin\runtime\bootstrap.py' setup ekg
& 'C:\operator\python312\python.exe' -I 'C:\installed plugin\runtime\bootstrap.py' setup grz
& 'C:\operator\python312\python.exe' -I 'C:\installed plugin\runtime\bootstrap.py' status ontology
& 'C:\operator\python312\python.exe' -I 'C:\installed plugin\runtime\bootstrap.py' status ekg
& 'C:\operator\python312\python.exe' -I 'C:\installed plugin\runtime\bootstrap.py' status grz
```

Bootstrap setup prepares an environment keyed to the Python version and platform
and verifies the artifact and complete hashed dependency lock. It uses configured
pip sources; do not alter global package settings. Normal launch uses only
`python -I <plugin>\runtime\bootstrap.py run <domain> <console-entry-point> [args...]`.
Isolated mode is required before bootstrap imports: it ignores inherited
`PYTHONPATH` and user site packages rather than relying on later environment cleanup.
Warm runs never install dependencies. Missing or invalid setup fails explicitly;
the host does not install packages or silently choose another runtime. Do not
use a development checkout or an unrelated console script.

[Prerequisites and setup](standalone-setup.md) | [Launch](standalone-launch.md)

# Operator configuration example

Keep operator JSON outside the installed plugin and source control. Configure
only the domains needed; this example enables all three:

```json
{
  "python": "C:\\operator\\python312\\python.exe",
  "cwd": "C:\\operator",
  "port": 0,
  "domains": {
    "ontology": {
      "scope": {
        "state_dir": "C:\\operator\\ontology-state",
        "version": 1
      },
      "env": {
        "SystemRoot": "C:\\Windows",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    },
    "ekg": {
      "scope": {
        "descriptor_path": "C:\\operator\\published-ekg.json"
      },
      "env": {
        "SystemRoot": "C:\\Windows",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      },
      "timeoutMs": 120000
    },
    "grz": {
      "scope": {
        "descriptor_path": "C:\\operator\\published-grz.json",
        "endpoint": "https://approved-service.search.windows.net",
        "auth": "entra"
      },
      "env": {
        "SystemRoot": "C:\\Windows",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1"
      }
    }
  }
}
```

[Prerequisites and setup](standalone-setup.md) | [Launch](standalone-launch.md)

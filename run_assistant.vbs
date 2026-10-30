Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "python C:\Users\VINAYAK\pc_agent.py", 0
WScript.Sleep 1000
WshShell.Run "chrome.exe --app=http://localhost:5000", 1
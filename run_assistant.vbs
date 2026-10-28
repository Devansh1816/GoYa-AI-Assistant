Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\VINAYAK"
WshShell.Run "python pc_agent.py", 0, False
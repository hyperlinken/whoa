Set oFSO = CreateObject("Scripting.FileSystemObject")
sDir = oFSO.GetParentFolderName(WScript.ScriptFullName)
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run Chr(34) & sDir & "\run_agent.bat" & Chr(34), 0, False
Set WshShell = Nothing

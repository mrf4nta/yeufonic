; Yeufonic.exe: what the shortcuts start.  It runs launcher.py with pythonw, so there is
; no console window, and waits while it runs, so Task Manager lists Yeufonic, with its
; icon, and the engine and the app beneath it.  It shows nothing of its own.
;
; Built by build.sh beside the installer:
;   makensis -DVERSION=0.0.1 -DICON=yeufonic.ico -DOUTFILE=Yeufonic.exe yeufonic-exe.nsi

Unicode true
Name "Yeufonic"
OutFile "${OUTFILE}"
Icon "${ICON}"
RequestExecutionLevel user
SilentInstall silent
ShowInstDetails nevershow

; Task Manager names a program by its file description.
VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Yeufonic"
VIAddVersionKey "FileDescription" "Yeufonic"
VIAddVersionKey "CompanyName" "Yeufonic"
VIAddVersionKey "LegalCopyright" "Copyright (c) 2026 Paul Shields. All rights reserved."
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

Section
  IfFileExists "$EXEDIR\venv\Scripts\pythonw.exe" +3
    MessageBox MB_ICONSTOP "Yeufonic is not fully installed. Run its installer again, or Repair Yeufonic from the Start menu."
    Quit
  SetOutPath "$EXEDIR"
  ExecWait '"$EXEDIR\venv\Scripts\pythonw.exe" "$EXEDIR\launcher.py"' $0
  SetErrorLevel $0
SectionEnd

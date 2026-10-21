from pathlib import Path
import sys
root=Path(SPECPATH)
library='depth_codec.dll' if sys.platform=='win32' else 'libdepth_codec.so'
a=Analysis([str(root/'main.py')],pathex=[str(root)],
    binaries=[(str(root/'assets'/library),'assets')],
    datas=[(str(root/'assets/map_studio.ico'),'assets'),(str(root/'assets/map_studio.png'),'assets'),(str(root/'assets/THIRD_PARTY_NOTICES.txt'),'assets')],
    hiddenimports=['scipy.stats','matplotlib.backends.backend_svg','PIL._tkinter_finder','PIL._imagingtk'],
    hookspath=[],hooksconfig={'matplotlib':{'backends':['Agg','svg','pdf']}},runtime_hooks=[],
    excludes=['torch','tensorflow','IPython','notebook','jupyter','pytest','PyQt5','PyQt6','PySide2','PySide6'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,a.binaries,a.datas,[],name='RPBotMapStudio',console=False,debug=False,
        strip=False,upx=False,icon=str(root/'assets/map_studio.ico'))

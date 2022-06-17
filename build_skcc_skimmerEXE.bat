::
:: Requires PyInstaller.  Install using command:
::   pip install PyInstaller
::

python3 -m PyInstaller --onefile --distpath=. --workpath=tempdir skcc_skimmer.py

del skcc_skimmer.spec
rmdir /S /Q tempdir

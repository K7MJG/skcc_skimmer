import subprocess
import sys

ArgV = sys.argv[1:]

if len(ArgV) != 1:
	print('Requires a version number argument.')
	sys.exit()

version = ArgV[0]

try:
	gitSha = subprocess.check_output(['git', 'rev-list', '-n', '1', version]).strip().decode('utf-8')
except:
	sys.exit()

versionStamp = subprocess.check_output(['git', 'show', '-s', '--oneline', '--format=%as (%h)', gitSha]).strip().decode('utf-8')

with open(rf'cVersion.py', 'w', encoding='utf-8') as file:
	file.write(f"VERSION = '{version} / {versionStamp}'\n")

sys.exit(0)
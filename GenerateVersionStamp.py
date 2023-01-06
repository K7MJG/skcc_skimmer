import subprocess
import sys

def Main() -> None:
	ArgV = sys.argv[1:]

	if len(ArgV) != 1:
		print('Requires a version number argument.')
		sys.exit()

	version = ArgV[0]

	try:
		gitSha = subprocess.check_output(['git', 'rev-list', '-n', '1', version]).strip().decode('utf-8')
	except:
		sys.exit()

	versionDetail = subprocess.check_output(['git', 'show', '-s', '--oneline', '--format=%as (%h)', gitSha]).strip().decode('utf-8')
	versionStamp = f'{version} / {versionDetail}'

	with open(rf'Lib/cVersion.py', 'w', encoding='utf-8') as file:
		file.write(f"VERSION = '{versionStamp}'\n")

if __name__ == '__main__':
	Main()
import re

class cCommon:
	@staticmethod
	def Split(text: str) -> list[str]:
		return re.split('[, ][ ]*', text.strip())
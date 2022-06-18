from __future__ import annotations

import re

class cCommon:
	@staticmethod
	def Split(text: str) -> list[str]:
		strippedText = text.strip()

		if strippedText == '':
			return []

		return re.split('[, ][ ]*', strippedText)
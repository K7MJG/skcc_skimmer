#!/usr/bin/python3
'''

	 The MIT License (MIT)

	 Copyright (c) 2015-2022 Mark J Glenn

	 Permission is hereby granted, free of charge, to any person obtaining a copy
	 of this software and associated documentation files (the "Software"), to deal
	 in the Software without restriction, including without limitation the rights
	 to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
	 copies of the Software, and to permit persons to whom the Software is
	 furnished to do so, subject to the following conditions:

	 The above copyright notice and this permission notice shall be included in all
	 copies or substantial portions of the Software.

	 THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
	 IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
	 FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
	 AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
	 LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
	 OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
	 SOFTWARE.

	 Mark Glenn, February 2015
	 mglenn@cox.net

'''

from __future__ import annotations

import time

from typing import Any, Callable

class cStateMachine:
	StateMachines: dict[Any, bool] = {}
	EventFunctions: dict[str, Any]

	def __init__(self, InitialState: Any, Debug: bool = False):
		cStateMachine.StateMachines[self] = True

		self.Debug          = Debug
		self.Timeout        = None
		self.State: Any     = None
		self.EventFunctions = {}
		self.InitialState   = InitialState

	def __CacheEventFunctions(self):
		if self.State not in self.EventFunctions:
			self.EventFunctions = self.State()

			if self.EventFunctions is None:
				print(f'Must return locals in {self.State.__name__}')

		return

	def SendEvent(self, Event: str):
		self.__CacheEventFunctions()

		if Event in self.EventFunctions:
			self.EventFunctions[Event]()

	def SendEventArg(self, Event: str, Arg: Any):
		self.__CacheEventFunctions()

		if Event in self.EventFunctions:
			self.EventFunctions[Event](Arg)

	def Transition(self, To: Callable[..., Any]):
		if self.State is not None:
			if self.Debug:
				print(f'<<< {self.__class__.__name__}.{self.State.__name__}...')

			self.Timeout = None
			self.SendEvent('EXIT')

		self.State = To

		if self.Debug:
			print(f'>>> {self.__class__.__name__}.{self.State.__name__}...')

		self.SendEvent('ENTER')

	def TimeoutInSeconds(self, Seconds: float):
		self.Timeout = time.time() + Seconds

	def Terminate(self):
		cStateMachine.StateMachines.pop(self)

	def Run(self):
		if self.State is None:
			self.Transition(self.InitialState)
		elif self.Timeout is not None:
			if time.time() > self.Timeout:
				self.SendEvent('TIMEOUT')

		return

	@staticmethod
	def RunAll():
		for StateMachine in cStateMachine.StateMachines:
			StateMachine.Run()

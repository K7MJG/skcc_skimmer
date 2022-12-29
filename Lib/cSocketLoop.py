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
import errno
import socket
import select

from typing         import Any
from .cStateMachine import cStateMachine

class cSocketLoop:
	ReaderSockets:    dict[Any, cStateMachine]
	WriterSockets:    dict[Any, cStateMachine]
	ConnectorSockets: dict[Any, cStateMachine]

	def __init__(self, Timeout: float = 0.1, Debug: bool = False):
		self.Timeout          = Timeout
		self.Debug            = Debug
		self.ReaderSockets    = {}
		self.WriterSockets    = {}
		self.ConnectorSockets = {}

	def AddReader(self, Socket: Any, NotificationObject: cStateMachine):
		self.ReaderSockets[Socket] = NotificationObject

	def RemoveReader(self, Socket: Any):
		self.ReaderSockets.pop(Socket)

	def AddWriter(self, Socket: Any, NotificationObject: cStateMachine):
		self.WriterSockets[Socket] = NotificationObject

	def RemoveWriter(self, Socket: Any):
		self.WriterSockets.pop(Socket)

	def AddConnector(self, Socket: Any, NotificationObject: cStateMachine):
		self.ConnectorSockets[Socket] = NotificationObject

	def RemoveConnector(self, Socket: Any):
		self.ConnectorSockets.pop(Socket)

	def RunCount(self, Count: int):
		for _ in range(0, Count):
			self.RunOne()

	def Run(self):
		while True:
			self.RunOne()

	def RunOne(self):
		cStateMachine.RunAll()

		AllWriters = list(self.WriterSockets) + list(self.ConnectorSockets)

		if len(self.ReaderSockets) + len(AllWriters) == 0:
			time.sleep(self.Timeout)
			return

		if self.Debug:
			if self.ReaderSockets:
				for ReaderSocket in self.ReaderSockets:
					print('WAITING TO READ: ', ReaderSocket)

			if self.WriterSockets:
				for WriterSocket in self.WriterSockets:
					print('WAITING TO WRITE:', WriterSocket)

			print('ReaderSockets: ', self.ReaderSockets)
			print('WriterSockets: ', AllWriters)

		ReadableSockets, WriteableSockets, _ = select.select(self.ReaderSockets, AllWriters, [], self.Timeout)

		for Socket in ReadableSockets:
			if self.Debug:
				print('READ READY:', Socket)

			self.ReaderSockets[Socket].SendEvent('READY_TO_READ')

		for Socket in WriteableSockets:
			if self.Debug:
				print('WRITE READY:', Socket)

			if Socket in self.WriterSockets:
				self.WriterSockets[Socket].SendEvent('READY_TO_WRITE')
			elif Socket in self.ConnectorSockets:
				Return = Socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)

				if Return == 0:
					self.ConnectorSockets[Socket].SendEvent('CONNECTED')
				elif Return == errno.ECONNREFUSED:
					self.ConnectorSockets[Socket].SendEvent('REFUSED')

		return

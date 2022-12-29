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

	 Mark Glenn, March 2015
	 mglenn@cox.net

'''

from __future__ import annotations

import socket
import random

from typing         import Any
from .cSocketLoop   import cSocketLoop
from .cStateMachine import cStateMachine

MasterClusterList = {
	'SKCC': [
		('skimmer.skccgroup.com', 7000),
	],

	'RBN': [
		('telnet.reversebeacon.net',    7000)
	],
}

class cRBN:
	def __init__(self):
		self.Incoming = ''
		self.bOutgoing = b''
		self.Socket: socket.SocketType

		self.InactivityTimeoutSeconds = 60

	def Receive(self):
		try:
			bData: bytes = self.Socket.recv(4 * 1024)
		except socket.error:
			return False
		else:
			if not bData:
				return False

			self.Incoming += bData.decode('utf-8')
			return True

	def SentAll(self):
		try:
			BytesSent = self.Socket.send(self.bOutgoing)
			self.bOutgoing = self.bOutgoing[BytesSent:]
		except socket.error:
			pass
		else:
			return len(self.bOutgoing) == 0

class cRBN_Client(cRBN, cStateMachine):
	AddressTuple: tuple[str, int]

	def __init__(self, SocketLoop: cSocketLoop, CallSign: str, Clusters: str):
		cRBN.__init__(self)
		cStateMachine.__init__(self, self.STATE_ConnectingToRBN, Debug = False)

		self.SocketLoop        = SocketLoop
		self.CallSign          = CallSign
		self.MasterClusterList = MasterClusterList
		self.Iter: Any         = None
		self.AddressTuple      = ('', 0)
		self.Cluster           = None

		if ',' in Clusters:
			self.Clusters = Clusters.upper().split(',')
		else:
			self.Clusters = Clusters.upper().split()

	@staticmethod
	def FindEnd(What: str, text: str):
		index = text.find(What)

		if index == -1:
			return None

		return index + len(text)

	def STATE_ConnectingToRBN(self):
		def ENTER():
			AddressTupleList: list[tuple[str, tuple[str, int]]] = []

			for ClusterKey in self.Clusters:
				ServerList = self.MasterClusterList[ClusterKey]
				random.shuffle(ServerList)

				for AddressTuple in ServerList:
					AddressTupleList.append((ClusterKey, AddressTuple))

			self.Iter = iter(AddressTupleList)
			__Initiate()

		def CONNECTED():
			Address, Port = self.AddressTuple
			print(f'\nCONNECTED to {self.Cluster} ({Address}:{Port})... ')

			self.SocketLoop.RemoveConnector(self.Socket)
			self.Transition(self.STATE_WaitingForPrompt)

		def REFUSED():
			#print('Attempt to Connect to {} REFUSED... '.format(self.AddressTuple))
			self.SocketLoop.RemoveConnector(self.Socket)
			self.Socket.close()
			__Initiate()

		def TIMEOUT():
			#print('Attempt to Connect to {} TIMED OUT... '.format(self.AddressTuple))
			self.SocketLoop.RemoveConnector(self.Socket)
			self.Socket.close()
			__Initiate()

		def __Initiate():
			self.Cluster, self.AddressTuple = next(self.Iter)

			if self.AddressTuple:
				self.Socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
				self.Socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 0)
				self.Socket.setblocking(False)
				self.SocketLoop.AddConnector(self.Socket, self)

				try:
					self.Socket.connect_ex(self.AddressTuple)
				except socket.error:
					print('\nNo apparent network connection.  Retrying...')
					self.Transition(self.STATE_PauseAndReconnect)
			else:
				print('Failed to connect to any server.')
				self.Transition(self.STATE_PauseAndReconnect)

		_ = ENTER, CONNECTED, REFUSED, TIMEOUT
		return locals()

	def STATE_PauseAndReconnect(self):
		def ENTER():
			self.TimeoutInSeconds(5)

		def TIMEOUT():
			self.Transition(self.STATE_ConnectingToRBN)

		_ = ENTER, TIMEOUT
		return locals()

	def STATE_WaitingForPrompt(self):
		def ENTER():
			self.SocketLoop.AddReader(self.Socket, self)
			self.TimeoutInSeconds(15)

		def EXIT():
			self.SocketLoop.RemoveReader(self.Socket)

		def READY_TO_READ():
			if not self.Receive():
				self.Transition(self.STATE_Closing)
			else:
				if self.Incoming == '\xff\xfc\x22':
					# Special, strange prompt sequence from relay2
					self.Incoming = ''
					self.Transition(self.STATE_SendingCallSign)
				else:
					# Normal prompt
					End = cRBN_Client.FindEnd('call: ', self.Incoming)

					if End:
						self.Incoming = self.Incoming[End:]
						self.Transition(self.STATE_SendingCallSign)


		def TIMEOUT():
			print('Timed out')
			self.Transition(self.STATE_Closing)

		_ = ENTER, EXIT, READY_TO_READ, TIMEOUT
		return locals()

	def STATE_SendingCallSign(self):
		def ENTER():
			CallSign = self.CallSign + '\r\n'
			bCallSign = CallSign.encode('ascii')

			self.bOutgoing += bCallSign
			self.SocketLoop.AddWriter(self.Socket, self)

		def EXIT():
			self.SocketLoop.RemoveWriter(self.Socket)

		def READY_TO_WRITE():
			if self.SentAll():
				self.Transition(self.STATE_WaitingForHeader)

		_ = ENTER, EXIT, READY_TO_WRITE
		return locals()

	def STATE_WaitingForHeader(self):
		def ENTER():
			self.SocketLoop.AddReader(self.Socket, self)
			self.TimeoutInSeconds(.75)

		def EXIT():
			self.SocketLoop.RemoveReader(self.Socket)

		def READY_TO_READ():
			if not self.Receive():
				self.Transition(self.STATE_Closing)
			else:
				End = cRBN_Client.FindEnd('>\r\n\r\n', self.Incoming)

				if End:
					# Normal header.

					self.Incoming = self.Incoming[End:]
					self.Transition(self.STATE_ConnectedToRBN)
				else:
					# For some reason, relay2 is special.

					End = cRBN_Client.FindEnd("Welcome to RBN's bulk spots telnet server.\r\n", self.Incoming)

					if End:
						self.Incoming = self.Incoming[End:]
						self.Transition(self.STATE_ConnectedToRBN)

		def TIMEOUT():
			self.Transition(self.STATE_Closing)

		_ = ENTER, EXIT, READY_TO_READ, TIMEOUT
		return locals()

	def STATE_ConnectedToRBN(self):
		def ENTER():
			self.SocketLoop.AddReader(self.Socket, self)
			self.TimeoutInSeconds(self.InactivityTimeoutSeconds)

		def EXIT():
			self.SocketLoop.RemoveReader(self.Socket)

		def READY_TO_READ():
			self.TimeoutInSeconds(self.InactivityTimeoutSeconds)

			if not self.Receive():
				print('\nLost connection.  Attempting to reconnect...')
				self.Transition(self.STATE_PauseAndReconnect)
			else:
				self.RawData(self.Incoming)
				self.Incoming = ''

		def TIMEOUT():
			print(f'\nNo activity for {self.InactivityTimeoutSeconds} seconds.  Attempting to reconnect.')
			self.Socket.shutdown(socket.SHUT_RDWR)
			self.Socket.close()
			self.Transition(self.STATE_PauseAndReconnect)

		_ = ENTER, EXIT, READY_TO_READ, TIMEOUT
		return locals()

	def STATE_Closing(self):
		def ENTER():
			self.Socket.shutdown(socket.SHUT_RDWR)
			self.Socket.close()
			self.Transition(self.STATE_Closed)

		_ = ENTER
		return locals()

	def STATE_Closed(self):
		def ENTER():
			pass

		_ = ENTER
		return locals()

	def RawData(self, Data: str):
		pass
